"""Validate the offline GO previews, labels and 6 Hz RGB frame manifests."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageStat

from go_source import NS
from make_preview import read_rows


DIMENSIONS = (1440, 1080)


class LocalLinks(HTMLParser):
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.checked = 0

    def handle_starttag(self, _tag, attrs):
        for key, value in attrs:
            if key not in ("src", "href") or not value:
                continue
            url = urlsplit(value)
            if url.scheme or not url.path:
                continue
            if not (self.filename.parent / url.path).is_file():
                raise ValueError(f"Broken preview link {value} in {self.filename}")
            self.checked += 1


def check_jpeg(path):
    with Image.open(path) as image:
        if image.format != "JPEG" or image.size != DIMENSIONS:
            raise ValueError(f"Unexpected RGB frame format or size: {path}")
        image.load()


def check_pair(root, row):
    stamp = row["stamp_ns"]
    match_fields = [row["target_ns"], Path(row["official_rgb_member"]).stem, Path(row["mask_member"]).stem]
    if any(field != stamp for field in match_fields):
        raise ValueError(f"Label and source timestamps disagree at {stamp}")
    with (
        Image.open(root / row["rgb"]) as source,
        Image.open(root / row["official_rgb"]) as official,
        Image.open(root / row["mask"]) as mask,
        Image.open(root / row["color_mask"]) as color,
    ):
        if any(image.size != DIMENSIONS for image in (source, official, mask, color)):
            raise ValueError(f"Invalid label pair dimensions at {stamp}")
        mask.load()
        color.load()
        difference = ImageChops.difference(source.convert("RGB"), official.convert("RGB"))
        return sum(ImageStat.Stat(difference).mean) / 3


def summarize(root, pool):
    preview = json.loads((root / "preview-summary.json").read_text(encoding="utf-8"))
    indices = json.loads((root / "source-index.json").read_text(encoding="utf-8"))
    gallery = read_rows(root / "gallery.csv")
    sequence = read_rows(root / "sequence.csv")
    labels = read_rows(root / "labels.csv")
    stamps = [int(row["stamp_ns"]) for row in sequence]
    targets = [int(row["target_ns"]) for row in sequence]
    if len(gallery) != preview["gallery_targets"] or len(labels) != sum(preview["official_splits"].values()):
        raise ValueError(f"Incomplete previews or labels in {root}")
    if len(stamps) != 3600 or len(set(stamps)) != len(stamps):
        raise ValueError(f"Incomplete or duplicate 6 Hz frames in {root}")
    if any(target != targets[0] + i * NS // 6 for i, target in enumerate(targets)):
        raise ValueError(f"Invalid sample time grid in {root}")
    gaps = [right - left for left, right in zip(stamps, stamps[1:])]
    max_offset = max(abs(stamp - target) for stamp, target in zip(stamps, targets))
    if max_offset > 120_000_000:
        raise ValueError(f"Frame too far from its sampling tick in {root}")

    for _ in pool.map(check_jpeg, (root / row["rgb"] for row in sequence + gallery)):
        pass
    difference = list(pool.map(lambda row: check_pair(root, row), labels))
    classes = json.loads((root / "classes.json").read_text(encoding="utf-8"))
    frame_presence = Counter(int(key) for row in labels for key in row["ids"].split())
    label_stamps = {int(row["stamp_ns"]) for row in labels}
    return {
        "source": indices["name"],
        "archive_bytes": indices["bytes"],
        "bag_duration_s": round((indices["end_ns"] - indices["start_ns"]) / NS, 9),
        "gallery_frames": len(gallery),
        "label_splits": dict(Counter(row["split"] for row in labels)),
        "matched_labels": len(labels),
        "label_frames_by_class": {
            name: frame_presence[classes[name]] for name in ("grass", "dirt", "trees", "sky", "snow")
        },
        "labels_with_grass_and_dirt": sum(
            int(row["grass_pixels"]) > 0 and int(row["dirt_pixels"]) > 0 for row in labels
        ),
        "bag_official_rgb_mean_absolute_pixel_difference": {
            "median": round(median(difference), 6),
            "maximum": round(max(difference), 6),
        },
        "sequence_frames": len(sequence),
        "sequence_seconds": round((stamps[-1] - stamps[0]) / NS, 9),
        "sequence_mean_fps": round((len(stamps) - 1) * NS / (stamps[-1] - stamps[0]), 6),
        "sequence_max_gap_ms": round(max(gaps) / 1e6, 6),
        "sequence_max_target_offset_ms": round(max_offset / 1e6, 6),
        "sequence_frames_with_official_label": len(set(stamps) & label_stamps),
        "successful_bag_range_bytes": sum(
            json.loads(path.read_text(encoding="utf-8"))["transferred_bytes"]
            for path in root.glob("*-transfer.json")
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for season in ("spring", "winter"):
            result[season] = summarize(args.output / season, pool)
    result["preview_local_links"] = 0
    for filename in ("index.html", "spring/index.html", "winter/index.html"):
        path = args.output / filename
        parser = LocalLinks(path)
        parser.feed(path.read_text(encoding="utf-8"))
        result["preview_local_links"] += parser.checked
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
