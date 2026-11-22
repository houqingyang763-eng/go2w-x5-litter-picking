"""Pack 600 consecutive GO spring RGB frames for the isolated Orin replay."""

import argparse
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import statistics
import zipfile

from PIL import Image


FRAME_COUNT = 600
INPUT_SIZE = (1440, 1080)
SOURCE_IMAGE = re.compile(r"\d+_\d+\.jpg")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Issue #3 spring output directory")
    parser.add_argument("output", type=Path, help="Local directory for the input manifest and archive")
    parser.add_argument("--start-seconds", type=Decimal, default=Decimal("270"))
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        raise ValueError("Place the new input bundle outside the Issue #3 data directory.")
    sequence = source / "sequence.csv"
    with sequence.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    elapsed = [Decimal(row["elapsed_s"]) for row in rows]
    stamps = [int(row["stamp_ns"]) for row in rows]
    if any(later <= earlier for earlier, later in zip(stamps, stamps[1:])):
        raise ValueError("The Issue #3 sequence must already be in increasing source timestamp order.")
    start = next((index for index, t in enumerate(elapsed) if t >= args.start_seconds), len(rows))
    stop = start + FRAME_COUNT
    if stop > len(rows):
        raise ValueError("Fewer than 600 consecutive rows remain at the selected start time.")
    selected = rows[start:stop]
    stamps = stamps[start:stop]
    gaps_ms = [(later - earlier) / 1e6 for earlier, later in zip(stamps, stamps[1:])]
    declared = json.loads((source / "source-index.json").read_text(encoding="utf-8"))
    span_s = (stamps[-1] - stamps[0]) / 1e9
    window = {
        "bag": declared["name"],
        "camera_topic": "/lester/stereo_left/image_rect_color/compressed",
        "frame_count": FRAME_COUNT,
        "source_row_first_last_1based": [start + 1, stop],
        "source_elapsed_first_last_s": [selected[0]["elapsed_s"], selected[-1]["elapsed_s"]],
        "first_stamp_ns": selected[0]["stamp_ns"],
        "last_stamp_ns": selected[-1]["stamp_ns"],
        "first_file": PurePosixPath(selected[0]["rgb"]).name,
        "last_file": PurePosixPath(selected[-1]["rgb"]).name,
        "span_s": span_s,
        "actual_fps": (FRAME_COUNT - 1) / span_s,
        "gap_ms": {"min": min(gaps_ms), "median": statistics.median(gaps_ms), "max": max(gaps_ms)},
        "source_sequence_sha256": hashlib.sha256(sequence.read_bytes()).hexdigest(),
    }

    output.mkdir(parents=True, exist_ok=True)
    archive = output / "inputs.zip"
    temporary = archive.with_suffix(".part")
    manifest = []
    with zipfile.ZipFile(temporary, mode="w", compression=zipfile.ZIP_STORED) as bundle:
        for ordinal, row in enumerate(selected, 1):
            original = PurePosixPath(row["rgb"])
            if original.parent != PurePosixPath("sequence-rgb") or not SOURCE_IMAGE.fullmatch(original.name):
                raise ValueError(f"Unexpected source image path {original}")
            body = (source / original.as_posix()).read_bytes()
            with Image.open(io.BytesIO(body)) as image:
                image.load()
                if image.size != INPUT_SIZE or image.format != "JPEG":
                    raise ValueError(f"Unexpected source dimensions or format: {original}")
            filename = f"rgb/{original.name}"
            bundle.writestr(filename, body)
            manifest.append({
                "frame": ordinal, "source_row": start + ordinal,
                "stamp_ns": row["stamp_ns"], "bag_ns": row["bag_ns"], "target_ns": row["target_ns"],
                "source_elapsed_s": row["elapsed_s"], "source_seq": row["seq"],
                "image": filename, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            })

        window["input_bytes"] = sum(row["bytes"] for row in manifest)
        csv_stream = io.StringIO(newline="")
        writer = csv.DictWriter(csv_stream, fieldnames=list(manifest[0]))
        writer.writeheader()
        writer.writerows(manifest)
        data = {
            "inputs.csv": csv_stream.getvalue(),
            "window.json": json.dumps(window, ensure_ascii=False, indent=2) + "\n",
        }
        for name, contents in data.items():
            bundle.writestr(name, contents)
    temporary.replace(archive)
    for name, contents in data.items():
        (output / name).write_bytes(contents.encode("utf-8"))
    print(json.dumps({**window, "archive_bytes": archive.stat().st_size}, indent=2))


if __name__ == "__main__":
    main()
