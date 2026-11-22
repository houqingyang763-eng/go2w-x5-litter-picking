"""Download only the GO RGB chunks and official label pairs needed by Issue #3."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shutil
import threading
import time
import zipfile

from PIL import Image

from go_source import (
    FORWARD_LEFT, NS, RangeFile, SOURCES, bag_index, rgb_frames, write_text_manifest, zip_member,
)


RECORD_DELAY_NS = 36_000_000
SAMPLE_TOLERANCE_NS = 120_000_000
LABEL_TOLERANCE_NS = 1_000_000_000


@dataclass(frozen=True)
class Chunk:
    offset: int
    stop: int
    start_ns: int
    end_ns: int
    count: int

    @property
    def midpoint(self):
        return (self.start_ns + self.end_ns) // 2


class CameraChunks:
    def __init__(self, data, index, conn):
        self.chunks = sorted(
            [
                Chunk(offset, data[i + 1][0] if i + 1 < len(data) else index["index_pos"], low, high, counts[conn])
                for i, (offset, low, high, counts) in enumerate(data)
                if conn in counts
            ],
            key=lambda chunk: chunk.midpoint,
        )
        self.midpoints = [chunk.midpoint for chunk in self.chunks]

    def nearest(self, target, count):
        wanted = target + RECORD_DELAY_NS
        center = bisect_left(self.midpoints, wanted)
        candidates = self.chunks[max(0, center - 12):center + 12]
        return sorted(
            candidates,
            key=lambda chunk: (
                max(chunk.start_ns - wanted, wanted - chunk.end_ns, 0),
                abs(chunk.midpoint - wanted),
            ),
        )[:count]

    def around_label(self, stamp):
        pos = bisect_left(self.midpoints, stamp)
        return [
            chunk for chunk in self.chunks[max(pos - 100, 0):pos + 100]
            if chunk.end_ns >= stamp - LABEL_TOLERANCE_NS
            and chunk.start_ns <= stamp + LABEL_TOLERANCE_NS
        ]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_bytes(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def get_index(root, source, proxy):
    path = root / "source-index.json"
    chunks_path = root / "chunks.json"
    if path.is_file() and chunks_path.is_file():
        index, chunks = read_json(path), read_json(chunks_path)
    else:
        index, chunks = bag_index(source, proxy)
        write_text_manifest(path, index)
        write_text_manifest(chunks_path, chunks)
    if (index["name"], index["bytes"]) != (source.name, source.size):
        raise ValueError("Cached index disagrees with the official file")
    return index, chunks


def annotation_catalog(index, source, proxy, output):
    kind_pattern = re.compile(r"rgb_segmentation/(images|masks|masks_color)/(train|val|test)/(\d+)\.(jpg|png)")
    names_by_stamp = defaultdict(dict)
    with RangeFile(SOURCES["labels"], proxy) as remote, zipfile.ZipFile(remote) as archive:
        ordered = sorted(archive.infolist(), key=lambda entry: entry.header_offset)
        next_offsets = {
            info.filename: ordered[i + 1].header_offset if i + 1 < len(ordered) else archive.start_dir
            for i, info in enumerate(ordered)
        }
        infos = {info.filename: info for info in ordered}
        report = json.loads(archive.read("rgb_segmentation/bag_split_report.json"))
        class_bytes = archive.read("rgb_segmentation/classes.json")
        atomic_bytes(output / "classes.json", class_bytes)
        atomic_bytes(output / "class_id_mapping.json", archive.read("rgb_segmentation/class_id_mapping.json"))
        expected = {}
        for split, info in report["segmentation"].items():
            count = info["bags"].get(source.split_key, 0)
            if count:
                expected[split] = count
        for name in infos:
            match = kind_pattern.fullmatch(name)
            if match is None:
                continue
            kind, split, raw_stamp, _ = match.groups()
            stamp = int(raw_stamp)
            if index["start_ns"] - 2 * NS <= stamp <= index["end_ns"] + 2 * NS:
                names_by_stamp[stamp][kind] = name
                names_by_stamp[stamp]["split"] = split
    all_kinds = {"split", "images", "masks", "masks_color"}
    observed = dict(Counter(entry["split"] for entry in names_by_stamp.values()))
    if observed != expected or any(set(entry) != all_kinds for entry in names_by_stamp.values()):
        raise ValueError(f"ZIP entries disagree with the GO split report for {source.name}: {observed}, {expected}")
    return dict(names_by_stamp), infos, next_offsets, json.loads(class_bytes), expected


class DownloadPool:
    def __init__(self, source, proxy, cache, conn, workers):
        self.source = source
        self.proxy = proxy
        self.cache = cache
        self.conn = conn
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.local = threading.local()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.executor.shutdown()

    def remote(self):
        if not hasattr(self.local, "remote"):
            self.local.remote = RangeFile(self.source, self.proxy)
        return self.local.remote

    def fetch_chunk(self, chunk):
        manifest = self.cache / f"{chunk.offset}.json"
        if manifest.is_file():
            rows = read_json(manifest)
            if len(rows) == chunk.count and all((self.cache / row["file"]).is_file() for row in rows):
                return rows, 0

        data = self.remote().fetch(chunk.offset, chunk.stop - chunk.offset)
        rows = []
        for row, image in rgb_frames(data, self.conn):
            row["file"] = f"{chunk.offset}_{row['stamp_ns']}_{row['seq']}.jpg"
            atomic_bytes(self.cache / row["file"], image)
            rows.append(row)
        if len(rows) != chunk.count:
            raise ValueError(f"RGB message count mismatch at bag offset {chunk.offset}")
        write_text_manifest(manifest, rows)
        return rows, len(data)

    def chunks(self, by_target, title):
        needed = set(chunk for choices in by_target.values() for chunk in choices)
        predicted = sum(chunk.stop - chunk.offset for chunk in needed)
        free = shutil.disk_usage(self.cache).free
        if free < predicted + 2 * 1024 ** 3:
            raise OSError(f"Only {free} bytes free, range plan requires up to {predicted} bytes plus 2 GiB")
        print(f"{title}: {len(needed)} chunks, up to {predicted:,} bytes; {free:,} bytes free", flush=True)

        rows = {}
        errors = {}
        pending = {
            self.executor.submit(self.fetch_chunk, chunk): chunk
            for chunk in sorted(needed, key=lambda chunk: chunk.offset)
        }
        transferred = 0
        last = time.monotonic()
        for count, job in enumerate(as_completed(pending), 1):
            chunk = pending[job]
            try:
                rows[chunk], size = job.result()
                transferred += size
            except (OSError, ValueError) as error:
                errors[chunk.offset] = str(error)
            if count == len(pending) or time.monotonic() - last > 15:
                print(
                    f"{title}: {count}/{len(pending)} chunks, {transferred:,} bytes fetched, {len(errors)} failed",
                    flush=True,
                )
                last = time.monotonic()
        write_text_manifest(self.cache.parent / f"{title}-transfer.json", {
            "estimated_range_bytes": predicted,
            "transferred_bytes": transferred,
            "chunks": len(needed),
            "failed_ranges": errors,
        })
        return {
            target: [row for chunk in choices for row in rows.get(chunk, [])]
            for target, choices in by_target.items()
        }

    def label_member(self, info, end, path):
        if not path.is_file():
            atomic_bytes(path, zip_member(self.remote(), info, end))


def link_frame(row, cache, output):
    path = output / f"{row['stamp_ns']}_{row['seq']}.jpg"
    if not path.exists():
        try:
            os.link(cache / row["file"], path)
        except OSError:
            shutil.copyfile(cache / row["file"], path)
    return path


def to_row(row, target, path, offset_ns, root):
    return {
        "target_ns": target,
        "stamp_ns": row["stamp_ns"],
        "bag_ns": row["bag_ns"],
        "seq": row["seq"],
        "frame_id": row["frame_id"],
        "elapsed_s": f"{(row['stamp_ns'] - offset_ns) / NS:.9f}",
        "rgb": path.relative_to(root).as_posix(),
    }


def write_csv(path, rows, columns):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


FRAME_COLUMNS = ["target_ns", "stamp_ns", "bag_ns", "seq", "frame_id", "elapsed_s", "rgb"]


def sample_targets(pool, camera, targets, label):
    requested = {stamp: camera.nearest(stamp, 1) for stamp in targets}
    result = pool.chunks(requested, label)
    missing = {
        stamp: camera.nearest(stamp, 4)
        for stamp, rows in result.items()
        if not any(abs(row["stamp_ns"] - stamp) <= SAMPLE_TOLERANCE_NS for row in rows)
    }
    if missing:
        result.update(pool.chunks(missing, f"{label}-retry"))
    taken = set()
    for target in targets:
        options = [
            row for row in result[target]
            if abs(row["stamp_ns"] - target) <= SAMPLE_TOLERANCE_NS and row["stamp_ns"] not in taken
        ]
        if options:
            row = min(options, key=lambda row: abs(row["stamp_ns"] - target))
            taken.add(row["stamp_ns"])
            yield target, row


def matched_targets(pool, camera, stamps):
    result = pool.chunks({stamp: camera.nearest(stamp, 4) for stamp in stamps}, "label-chunks")
    missing = {
        stamp: camera.around_label(stamp)
        for stamp, rows in result.items()
        if not any(row["stamp_ns"] == stamp for row in rows)
    }
    if missing:
        result.update(pool.chunks(missing, "label-chunks-retry"))

    matches = {}
    for stamp, rows in result.items():
        exact = {row["file"]: row for row in rows if row["stamp_ns"] == stamp}
        if len(exact) == 1:
            matches[stamp] = next(iter(exact.values()))
    return matches


def prepare_labels(root, proxy, workers, matches, catalog, infos, next_offsets, classes, offset_ns):
    paths_by_stamp = {}
    with DownloadPool(SOURCES["labels"], proxy, root, None, workers) as pool:
        pending = []
        for stamp, row in matches.items():
            members = catalog[stamp]
            pair = {"source_rgb": link_frame(row, root / ".chunk-cache", root / "label-bag-rgb")}
            for kind, folder in {
                "images": "label-official-rgb", "masks": "label-mask", "masks_color": "label-mask-color",
            }.items():
                name = members[kind]
                path = root / folder / Path(name).name
                pair[kind] = path
                pending.append(pool.executor.submit(pool.label_member, infos[name], next_offsets[name], path))
            paths_by_stamp[stamp] = pair
        for count, job in enumerate(as_completed(pending), 1):
            job.result()
            if count % 100 == 0 or count == len(pending):
                print(f"Official ZIP members complete: {count}/{len(pending)}", flush=True)

    rows = []
    valid_ids = set(classes.values())
    for stamp, pair in sorted(paths_by_stamp.items()):
        with (
            Image.open(pair["source_rgb"]) as source,
            Image.open(pair["images"]) as official,
            Image.open(pair["masks"]) as mask,
            Image.open(pair["masks_color"]) as color,
        ):
            if source.size != official.size or source.size != mask.size or source.size != color.size:
                raise ValueError(f"Mismatched dimensions at {stamp}")
            if mask.mode not in ("L", "P"):
                raise ValueError(f"Unexpected label encoding {mask.mode} at {stamp}")
            hist = mask.histogram()
            present = {idx for idx, pixels in enumerate(hist) if pixels}
            if not present <= valid_ids:
                raise ValueError(f"Unknown class IDs at {stamp}: {sorted(present - valid_ids)}")
        entry = to_row(matches[stamp], stamp, pair["source_rgb"], offset_ns, root)
        entry.update(
            split=catalog[stamp]["split"],
            official_rgb=pair["images"].relative_to(root).as_posix(),
            mask=pair["masks"].relative_to(root).as_posix(),
            color_mask=pair["masks_color"].relative_to(root).as_posix(),
            official_rgb_member=catalog[stamp]["images"],
            mask_member=catalog[stamp]["masks"],
            ids=" ".join(map(str, sorted(present))),
            grass_pixels=hist[classes["grass"]],
            dirt_pixels=hist[classes["dirt"]],
            trees_pixels=hist[classes["trees"]],
            sky_pixels=hist[classes["sky"]],
        )
        rows.append(entry)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", choices=["spring", "winter"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=["preview", "benchmark"], required=True)
    parser.add_argument("--proxy", help="Optional existing HTTP proxy, with ordinary TLS verification")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    source = SOURCES[args.season]
    root = args.output / args.season
    cache = root / ".chunk-cache"
    cache.mkdir(parents=True, exist_ok=True)
    index, chunks = get_index(root, source, args.proxy)
    conn, = [
        key for key, value in index["connections"].items()
        if value["topic"] == FORWARD_LEFT and value["type"] == "sensor_msgs/CompressedImage"
    ]
    camera = CameraChunks(chunks, index, conn)
    start = max(index["start_ns"], camera.chunks[0].midpoint)
    print(f"{args.season}: {source.name}, {source.size:,} B, left RGB {index['connections'][conn]['count']:,}", flush=True)

    if args.stage == "preview":
        catalog, infos, offsets, classes, expected = annotation_catalog(index, source, args.proxy, root)
        print(f"{args.season}: official RGB/mask pairs {sum(expected.values())}, splits {expected}", flush=True)
        for name in ("gallery-rgb", "label-bag-rgb", "label-official-rgb", "label-mask", "label-mask-color"):
            (root / name).mkdir(exist_ok=True)
        targets = list(range(start, index["end_ns"], 10 * NS))
        with DownloadPool(source, args.proxy, cache, int(conn), args.workers) as pool:
            gallery = [
                to_row(row, target, link_frame(row, cache, root / "gallery-rgb"), index["start_ns"], root)
                for target, row in sample_targets(pool, camera, targets, "gallery")
            ]
            write_csv(root / "gallery.csv", gallery, FRAME_COLUMNS)
            matches = matched_targets(pool, camera, sorted(catalog))
        labels = prepare_labels(root, args.proxy, args.workers, matches, catalog, infos, offsets, classes, index["start_ns"])
        write_csv(root / "labels.csv", labels, FRAME_COLUMNS + [
            "split", "official_rgb", "mask", "color_mask", "official_rgb_member", "mask_member", "ids",
            "grass_pixels", "dirt_pixels", "trees_pixels", "sky_pixels",
        ])
        write_text_manifest(root / "preview-summary.json", {
            "gallery_targets": len(targets),
            "gallery_frames": len(gallery),
            "official_splits": expected,
            "matched_frames": len(labels),
            "unmatched_stamps_ns": sorted(set(catalog) - set(matches)),
            "frames_with_class": {
                key: sum(row[f"{key}_pixels"] > 0 for row in labels)
                for key in ("grass", "dirt", "trees", "sky")
            },
        })
        print(f"{args.season}: gallery {len(gallery)}/{len(targets)}, exact label matches {len(labels)}/{len(catalog)}", flush=True)
        if len(labels) != len(catalog) or len(gallery) != len(targets):
            raise SystemExit(1)
    else:
        (root / "sequence-rgb").mkdir(exist_ok=True)
        targets = [start + tick * NS // 6 for tick in range(3600)]
        with DownloadPool(source, args.proxy, cache, int(conn), args.workers) as pool:
            frames = [
                to_row(row, target, link_frame(row, cache, root / "sequence-rgb"), index["start_ns"], root)
                for target, row in sample_targets(pool, camera, targets, "sequence")
            ]
        write_csv(root / "sequence.csv", frames, FRAME_COLUMNS)
        stamps = [row["stamp_ns"] for row in frames]
        write_text_manifest(root / "sequence-summary.json", {
            "planned_frames": len(targets),
            "frames": len(frames),
            "first_ns": min(stamps, default=None),
            "last_ns": max(stamps, default=None),
            "maximum_gap_ns": max((b - a for a, b in zip(stamps, stamps[1:])), default=None),
            "missed_targets_ns": sorted(set(targets) - {row["target_ns"] for row in frames}),
        })
        print(f"{args.season}: sequence {len(frames)}/{len(targets)}", flush=True)
        if len(frames) != len(targets):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
