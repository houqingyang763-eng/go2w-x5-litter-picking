"""Verify the 600 board masks and make the local GO replay video and review page."""

import argparse
import csv
import hashlib
from html import escape
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont


FRAME_COUNT = 600
DISPLAY_FPS = 6
MASK_ALPHA = 0.45
IMAGE_SIZE = (640, 480)
VIDEO_SIZE = (1280, 572)
FOCUS = [24, 31, 50, 51, 16, 27, 28, 53]


def read_rows(file):
    with file.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def palette_rows(path, expected_sha):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("The preview must use the official board palette.")
    rows = sorted(read_rows(path), key=lambda row: int(row["label_key"]))
    if [int(row["label_key"]) for row in rows] != list(range(64)):
        raise ValueError("The palette must cover every GOOSE class ID.")
    palette = np.array([
        [int(row["hex"][offset:offset + 2], 16) for offset in (1, 3, 5)] for row in rows
    ], dtype=np.uint8)
    return rows, palette


def optional_number(pattern, text, divisor=1):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match[1]) / divisor if match else None


def parse_tegrastats(path, run):
    samples = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            elapsed = float(row["elapsed_s"])
            raw = row["tegrastats"]
            cpus = re.search(r" CPU \[([^\]]+)\]", raw)
            online = [int(n) for n in re.findall(r"(\d+)%", cpus[1])] if cpus else []
            ram = re.search(r" RAM (\d+)/(\d+)MB", raw)
            gpu = re.search(r" GR3D_FREQ (\d+)%(?:@(\[[\d, ]+\]|\d+))?", raw)
            clocks = [int(n) for n in re.findall(r"\d+", gpu[2])] if gpu and gpu[2] else []
            phase = "run"
            if elapsed < run["loop_started_s"]:
                phase = "before"
            elif elapsed > run["loop_finished_s"]:
                phase = "after"
            sample = {
                "elapsed_s": elapsed,
                "phase": phase,
                "cpu_average_online_pct": sum(online) / len(online) if online else None,
                "cpu_online_core_pct": " ".join(map(str, online)),
                "gpu_pct": int(gpu[1]) if gpu else None,
                "gpu_clock_mhz": max(clocks, default=None),
                "ram_used_mb": int(ram[1]) if ram else None,
                "ram_total_mb": int(ram[2]) if ram else None,
                "swap_used_mb": optional_number(r" SWAP (\d+)/", raw),
                "gpu_c": optional_number(r" GPU@(-?\d+(?:\.\d+)?)C", raw),
                "cpu_c": optional_number(r" CPU@(-?\d+(?:\.\d+)?)C", raw),
                "junction_c": optional_number(r" tj@(-?\d+(?:\.\d+)?)C", raw),
                "vdd_in_w": optional_number(r" VDD_IN (\d+(?:\.\d+)?)(?:mW)?\s*/", raw, 1000),
            }
            samples.append(sample)
    return samples


def resource_stats(samples):
    def describe(field, rows=samples):
        values = [row[field] for row in rows if row[field] is not None]
        return (
            {"count": len(values), "mean": float(np.mean(values)), "p50": float(np.median(values)),
             "min": min(values), "max": max(values)}
            if values else {"count": 0}
        )

    return {
        "samples": len(samples),
        **{key: describe(key) for key in (
            "cpu_average_online_pct", "gpu_pct", "gpu_clock_mhz", "ram_used_mb", "swap_used_mb",
            "gpu_c", "cpu_c", "junction_c", "vdd_in_w",
        )},
        "gpu_clock_mhz_at_70pct_or_higher": describe(
            "gpu_clock_mhz", [row for row in samples if row["gpu_pct"] is not None and row["gpu_pct"] >= 70],
        ),
    }


def sequence_evidence(data, run):
    samples = parse_tegrastats(data / "board/tegrastats.tsv", run)
    if not samples or len(samples) != run["tegrastats_samples"]:
        raise ValueError("The raw monitoring log does not match the run manifest.")
    with (data / "resource_samples.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)

    running = [row for row in samples if row["phase"] == "run"]
    differences = [(b["elapsed_s"] - a["elapsed_s"]) * 1000 for a, b in zip(samples, samples[1:])]
    result = {
        "all_recorded_samples": len(samples),
        "observed_interval_p50_ms": float(np.median(differences)) if differences else None,
        "whole_run": resource_stats(running),
        "first_100": resource_stats([
            row for row in running if run["first_100"]["start_s"] <= row["elapsed_s"] <= run["first_100"]["end_s"]
        ]),
        "last_100": resource_stats([
            row for row in running if run["last_100"]["start_s"] <= row["elapsed_s"] <= run["last_100"]["end_s"]
        ]),
    }
    (data / "resource_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def clock(value):
    milliseconds = round(float(value) * 1000)
    minutes, seconds = divmod(milliseconds, 60000)
    return f"{minutes:02d}:{seconds // 1000:02d}.{seconds % 1000:03d}"


def validate_pairs(selections, result):
    if len(selections) != FRAME_COUNT or len(result) != FRAME_COUNT:
        raise ValueError("The input or output manifest does not contain 600 records.")
    for frame, (source, recorded) in enumerate(zip(selections, result), 1):
        if recorded["status"] != "ok" or int(recorded["frame"]) != frame:
            raise ValueError(f"Frame {frame} did not complete")
        for key in ("frame", "source_row", "stamp_ns", "bag_ns", "image", "source_elapsed_s"):
            if source[key] != recorded[key]:
                raise ValueError(f"Input-to-result map differs at frame {frame}, field {key}")
        if recorded["mask"] != "masks/" + Path(source["image"]).with_suffix(".png").name:
            raise ValueError(f"Mask path is incorrect for frame {frame}.")


def decode_pair(source_dir, board_dir, source, recorded):
    filename = Path(source["image"]).name
    original = (source_dir / "sequence-rgb" / filename).read_bytes()
    if hashlib.sha256(original).hexdigest() != source["sha256"]:
        raise ValueError(f"Source changed since transfer: {filename}")
    with Image.open(io.BytesIO(original)) as frame, Image.open(board_dir / recorded["mask"]) as mask:
        rgb = frame.convert("RGB")
        labels = np.array(mask)
        if (
            rgb.size != (1440, 1080) or mask.mode != "L" or mask.size != (512, 512)
            or int(labels.max()) >= 64 or int(labels.max()) != int(recorded["id_max"])
            or int(labels.min()) != int(recorded["id_min"])
        ):
            raise ValueError(f"Unexpected output size or class IDs at {filename}")
    return rgb, labels


def compose(rgb, ids, palette, font, frame, source_time):
    original = rgb.resize(IMAGE_SIZE, Image.Resampling.LANCZOS)
    color = Image.fromarray(palette[ids]).resize(IMAGE_SIZE, Image.Resampling.NEAREST)
    overlay = Image.blend(original, color, MASK_ALPHA)
    video = Image.new("RGB", VIDEO_SIZE, "#16201c")
    video.paste(original, (0, 42))
    video.paste(overlay, (640, 42))
    draw = ImageDraw.Draw(video)
    draw.text((20, 10), "原图", fill="#ecf3ed", font=font)
    draw.text((660, 10), "DDRNet-39 64 类 · 叠加", fill="#ecf3ed", font=font)
    draw.text((20, 532), f"GO 春季  |  源轨迹 {source_time}  |  {frame:03d} / 600", fill="#dce8dd", font=font)
    return video, original, overlay


def encode(args, source_frames, result, rows, palette):
    data = args.output
    thumbnails = data / "thumbs"
    thumbnails.mkdir(exist_ok=True)
    temporary = data / "sequence.partial.mp4"
    args_ffmpeg = [
        str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
        "-pixel_format", "rgb24", "-video_size", f"{VIDEO_SIZE[0]}x{VIDEO_SIZE[1]}",
        "-framerate", str(DISPLAY_FPS), "-i", "pipe:0", "-an", "-c:v", "libx264",
        "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary),
    ]
    font = ImageFont.truetype(str(args.font), size=23)
    indices = {1 + round(i * (FRAME_COUNT - 1) / 11) for i in range(12)}
    cards = []
    all_pixels = np.zeros(64, dtype=np.int64)
    with subprocess.Popen(args_ffmpeg, stdin=subprocess.PIPE) as ffmpeg:
        for frame, (original, recorded) in enumerate(zip(source_frames, result), 1):
            rgb, ids = decode_pair(args.source, data / "board", original, recorded)
            counts = np.bincount(ids.ravel(), minlength=64)
            all_pixels += counts
            stamp = clock(original["source_elapsed_s"])
            combined, resized, overlay = compose(rgb, ids, palette, font, frame, stamp)
            ffmpeg.stdin.write(combined.tobytes())
            if frame == 1:
                combined.save(data / "poster.jpg", quality=92)
            if frame in indices:
                before, after = f"thumbs/{frame:03d}-original.jpg", f"thumbs/{frame:03d}-overlay.jpg"
                resized.save(data / before, quality=88)
                overlay.save(data / after, quality=88)
                classes = sorted(np.flatnonzero(counts), key=lambda i: -counts[i])[:5]
                top = " · ".join(f"{rows[i]['class_name']} {counts[i] / ids.size:.1%}" for i in classes)
                cards.append(
                    f'<article><div class="pair"><img loading="lazy" src="{before}" alt="原图">'
                    f'<img loading="lazy" src="{after}" alt="叠加"></div><div class="caption">'
                    f'<strong>第 {frame} 帧 · {stamp}</strong><br><code>{original["stamp_ns"]}</code>'
                    f'<br>{escape(top)} · <a href="board/{recorded["mask"]}">ID 掩膜</a></div></article>'
                )
            if frame % 150 == 0:
                print(f"Verified and rendered {frame}/{FRAME_COUNT} frames", flush=True)
        ffmpeg.stdin.close()
        if ffmpeg.wait():
            raise RuntimeError("FFmpeg did not complete video encoding.")

    decoded = subprocess.run(
        [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-progress", "pipe:1",
         "-i", str(temporary), "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    values = dict(line.split("=", 1) for line in decoded.stdout.splitlines() if "=" in line)
    if int(values["frame"]) != FRAME_COUNT or int(values["out_time_us"]) != FRAME_COUNT * 1000000 // DISPLAY_FPS:
        raise ValueError(f"Encoded clip has incorrect timing or frame count: {values}")
    final = data / "sequence.mp4"
    temporary.replace(final)
    result = {
        "frames": int(values["frame"]),
        "duration_s": int(values["out_time_us"]) / 1000000,
        "display_fps": DISPLAY_FPS,
        "resolution": list(VIDEO_SIZE),
        "bytes": final.stat().st_size,
        "representative_frames": sorted(indices),
        "key_class_output_pixels": {rows[i]["class_name"]: int(all_pixels[i]) for i in FOCUS},
    }
    return cards, result


class LocalLinks(HTMLParser):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.checked = 0

    def handle_starttag(self, tag, pairs):
        for field, destination in pairs:
            if field in ("src", "href", "poster") and destination:
                if not (self.directory / destination).is_file():
                    raise FileNotFoundError(destination)
                self.checked += 1


def write_page(data, run, sample_cards, rows):
    window = run["window"]
    palette_html = "".join(
        f'<li><span class="swatch" style="background:{row["hex"]}"></span>'
        f'{row["label_key"]} · {escape(row["class_name"])}</li>' for row in rows
    )
    style = """
*{box-sizing:border-box}body{font:16px/1.6 system-ui,sans-serif;background:#141c18;color:#eef4ef;margin:0}
main{max-width:1240px;padding:28px 20px 70px;margin:auto}h1{line-height:1.25;font-size:clamp(24px,4vw,44px)}
h2{margin-top:34px}p{max-width:75ch}a{color:#bcf6a1;text-underline-offset:.22em}
video{width:100%;border-radius:9px;display:block;background:#0c110e}
nav{display:flex;gap:10px 22px;flex-wrap:wrap;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,365px),1fr));gap:17px}
article{background:#232e27;border:1px solid #415147;border-radius:8px;overflow:hidden}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:2px}.pair img{width:100%;height:auto;display:block}
.caption{padding:10px 12px}.swatch{display:inline-block;width:16px;height:16px;border:1px solid #a4b1a8;
vertical-align:middle;margin-right:6px}ul{columns:220px;list-style:none;padding-left:0}
"""
    filename = data / "index.html"
    filename.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>GO 春季 600 帧 · DDRNet-39 64 类</title>'
        f'<style>{style}</style><main><h1>GO 春季 600 帧 · DDRNet-39 64 类</h1>'
        f'<p>源轨迹 {clock(window["source_elapsed_first_last_s"][0])}–{clock(window["source_elapsed_first_last_s"][1])}'
        f'。板载 15W 含写盘实测 {run["fps_with_mask_write"]:.2f} FPS，视频按 6 FPS 播放。</p>'
        '<video controls preload="metadata" src="sequence.mp4" poster="poster.jpg"></video>'
        '<nav><a href="sequence.mp4">打开视频</a><a href="board/frames.csv">逐帧计时与掩膜</a>'
        '<a href="inputs.csv">原始帧索引</a><a href="resource_samples.csv">资源监测</a>'
        '<a href="board/run.json">板载性能摘要</a></nav>'
        '<h2>代表帧</h2><p>每组左侧是原图，右侧按 45% 的掩膜颜色权重叠加。类别比例来自模型输出。</p>'
        f'<div class="grid">{"".join(sample_cards)}</div>'
        f'<h2>GOOSE 官方色表</h2><ul>{palette_html}</ul></main></html>\n',
        encoding="utf-8",
    )
    checker = LocalLinks(data)
    checker.feed(filename.read_text(encoding="utf-8"))
    return checker.checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing spring dataset output directory")
    parser.add_argument("--output", type=Path, required=True, help="Issue #7 data directory")
    parser.add_argument("--palette", type=Path, required=True, help="Original official GOOSE mapping CSV")
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True, help="Local TrueType font supporting Chinese text")
    args = parser.parse_args()
    root = args.output
    run = json.loads((root / "board/run.json").read_text(encoding="utf-8"))
    inputs = read_rows(root / "inputs.csv")
    frames = read_rows(root / "board/frames.csv")
    validate_pairs(inputs, frames)
    rows, palette = palette_rows(args.palette, run["class_mapping_sha256"])
    telemetry = sequence_evidence(root, run)
    cards, video = encode(args, inputs, frames, rows, palette)
    video["preview_local_links"] = write_page(root, run, cards, rows)
    evidence = {"verified_mask_files": FRAME_COUNT, "video": video, "resource_summary": telemetry}
    (root / "review.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(video, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
