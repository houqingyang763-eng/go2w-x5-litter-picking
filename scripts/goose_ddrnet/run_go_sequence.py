"""Replay the verified 600-frame GO input bundle with the official DDRNet-39 class64 on Jetson."""

import time

# Start timing before loading PyTorch and the other runtime modules.
START = time.perf_counter()

import argparse
import csv
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from threading import Thread

import numpy as np
from PIL import Image
import torch

from infer_goose_class import labels_from, load_model, preprocess, read_palette


FRAMES = 600
CLASSES = 64
MODEL_SIZE = (512, 512)
WARMUP = 3
SAMPLE_MS = 500
COLUMNS = [
    "frame", "source_row", "stamp_ns", "bag_ns", "source_elapsed_s", "image", "mask",
    "started_s", "cpu_mask_ready_s", "finished_s", "preprocess_ms", "forward_ms", "forward_wall_ms",
    "postprocess_ms", "processing_ms", "mask_write_ms", "frame_wall_ms",
    "cuda_allocated_mib", "cuda_reserved_mib", "id_min", "id_max", "status", "error",
]


def power_mode():
    result = subprocess.run(
        ["/usr/sbin/nvpmodel", "-q"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True,
    )
    return next(line for line in result.stdout.splitlines() if line.startswith("NV Power Mode:")).split(":", 1)[1].strip()


class Telemetry:
    def __init__(self, output, privileged):
        self.output = output
        self.privileged = privileged
        self.samples = 0

    def __enter__(self):
        self.log = (self.output / "tegrastats.tsv").open("w", encoding="utf-8", buffering=1)
        self.log.write("elapsed_s\ttegrastats\n")
        self.err = (self.output / "tegrastats.stderr").open("w", encoding="utf-8")
        command = ["/usr/bin/tegrastats", "--interval", str(SAMPLE_MS)]
        if self.privileged:
            command = ["sudo", "-n", "/usr/bin/timeout", "--foreground", "-k", "3s", "300s", *command]
        self.proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=self.err, text=True, bufsize=1,
        )
        self.reader = Thread(target=self.capture, daemon=True)
        self.reader.start()
        return self

    def capture(self):
        for line in self.proc.stdout:
            if line.strip():
                self.log.write(f"{time.perf_counter() - START:.9f}\t{line.rstrip()}\n")
                self.samples += 1

    def stop_tegrastats(self, signal):
        if not self.privileged:
            self.proc.send_signal(signal)
            return

        # Only signal the tegrastats child of this sudo/timeout command, never another monitor.
        lines = subprocess.check_output(["ps", "-eo", "pid=,ppid=,comm="], text=True)
        records = [line.split(maxsplit=2) for line in lines.splitlines()]
        owned = {str(self.proc.pid)}
        while True:
            descendants = {pid for pid, parent, name in records if parent in owned}
            if descendants <= owned:
                break
            owned.update(descendants)
        targets = [pid for pid, parent, name in records if pid in owned and name == "tegrastats"]
        if targets:
            subprocess.run(
                ["sudo", "-n", "/usr/bin/kill", f"-{signal.value}", "--", *targets],
                check=True, timeout=5,
            )

    def __exit__(self, *_):
        from signal import SIGTERM, SIGKILL

        try:
            if self.proc.poll() is None:
                self.stop_tegrastats(SIGTERM)
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.stop_tegrastats(SIGKILL)
                    self.proc.wait(timeout=5)
            self.reader.join(timeout=5)
        finally:
            self.proc.stdout.close()
            self.log.close()
            self.err.close()


def read_manifest(root):
    with (root / "inputs.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != FRAMES:
        raise ValueError(f"Expected {FRAMES} input rows.")
    prior_stamp = 0
    base_row = int(rows[0]["source_row"])
    for frame, row in enumerate(rows, 1):
        filename = PurePosixPath(row["image"])
        stamp = int(row["stamp_ns"])
        if (
            int(row["frame"]) != frame or int(row["source_row"]) != base_row + frame - 1
            or stamp <= prior_stamp or filename.parent != PurePosixPath("rgb")
            or not re.fullmatch(r"\d+_\d+\.jpg", filename.name)
        ):
            raise ValueError(f"Input manifest lost source order at frame {frame}.")
        prior_stamp = stamp
    return rows


def validate_warmup(logits):
    if (
        list(logits.shape) != [1, CLASSES, *MODEL_SIZE] or logits.dtype != torch.float32
        or not logits.is_cuda or not torch.isfinite(logits).all().item()
    ):
        raise RuntimeError("The warmup did not produce finite 64-class FP32 CUDA logits.")


def measure_frame(model, path, mask_path, start_event, stop_event):
    start = time.perf_counter()
    _, tensor = preprocess(path, MODEL_SIZE)
    torch.cuda.synchronize()
    prepared = time.perf_counter()
    start_event.record()
    logits = model(tensor)
    stop_event.record()
    stop_event.synchronize()
    forwarded = time.perf_counter()
    labels = labels_from(logits)
    ready = time.perf_counter()
    del tensor, logits
    write_start = time.perf_counter()
    Image.fromarray(labels).save(mask_path, compress_level=3)
    finish = time.perf_counter()
    lo, hi = int(labels.min()), int(labels.max())
    if not 0 <= lo <= hi < CLASSES:
        raise ValueError("Saved mask contains IDs outside the official 0–63 range.")
    return {
        "started_s": start - START,
        "cpu_mask_ready_s": ready - START,
        "finished_s": finish - START,
        "preprocess_ms": (prepared - start) * 1000,
        "forward_ms": start_event.elapsed_time(stop_event),
        "forward_wall_ms": (forwarded - prepared) * 1000,
        "postprocess_ms": (ready - forwarded) * 1000,
        "processing_ms": (ready - start) * 1000,
        "mask_write_ms": (finish - write_start) * 1000,
        "frame_wall_ms": (finish - start) * 1000,
        "cuda_allocated_mib": torch.cuda.memory_allocated() / 1024 ** 2,
        "cuda_reserved_mib": torch.cuda.memory_reserved() / 1024 ** 2,
        "id_min": lo,
        "id_max": hi,
    }


def latency_stats(rows, field):
    values = [row[field] for row in rows]
    return {
        "mean": float(np.mean(values)),
        **{f"p{p}": float(np.percentile(values, p)) for p in (50, 95, 99)},
        "max": max(values),
    }


def segment(rows):
    return {
        "frames": len(rows),
        "start_s": rows[0]["started_s"],
        "end_s": rows[-1]["finished_s"],
        "fps_with_mask_write": len(rows) / (rows[-1]["finished_s"] - rows[0]["started_s"]),
        "fps_without_mask_write": len(rows) * 1000 / sum(row["processing_ms"] for row in rows),
        "forward_p50_ms": float(np.median([row["forward_ms"] for row in rows])),
        "processing_p50_ms": float(np.median([row["processing_ms"] for row in rows])),
        "cuda_allocated_end_of_frame_mib": [
            rows[0]["cuda_allocated_mib"], rows[-1]["cuda_allocated_mib"],
        ],
        "cuda_reserved_end_of_frame_mib": [
            rows[0]["cuda_reserved_mib"], rows[-1]["cuda_reserved_mib"],
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True, help="Existing Issue #2 DDRNet environment root")
    parser.add_argument("--class-root", type=Path, required=True, help="Existing Issue #4 class64 root")
    parser.add_argument("--monitor-sudo", action="store_true", help="Use existing non-interactive sudo authorization for tegrastats")
    args = parser.parse_args()

    output = args.output.resolve()
    for protected in (args.inputs, args.base, args.class_root):
        path = protected.resolve()
        if output == path or path in output.parents:
            raise ValueError("Keep this run outside the existing inputs and upstream workspaces.")
    inputs = read_manifest(args.inputs)
    assets = json.loads((args.class_root / "code/assets_class64.json").read_text(encoding="utf-8"))
    weight = args.class_root / "inputs" / assets["checkpoint"]["file"]
    mapping = args.class_root / "inputs" / assets["class_mapping"]["file"]
    window = json.loads((args.inputs / "window.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(args.base / "code"))
    from extract_ddrnet import file_sha256

    mode_before = power_mode()
    if mode_before != "15W" or not torch.cuda.is_available():
        raise RuntimeError("Expected the existing 15W mode and an available Orin CUDA device.")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    output.mkdir(parents=True, exist_ok=False)
    (output / "masks").mkdir()
    with Telemetry(output, args.monitor_sudo) as telemetry:
        weight_sha = file_sha256(weight)
        mapping_sha = file_sha256(mapping)
        if weight_sha != assets["checkpoint"]["sha256"] or mapping_sha != assets["class_mapping"]["sha256"]:
            raise ValueError("The official Issue #4 weight or mapping SHA256 did not match.")
        read_palette(mapping)
        load_start = time.perf_counter()
        model, states = load_model(weight, CLASSES)
        torch.cuda.synchronize()
        load_ms = (time.perf_counter() - load_start) * 1000

        good = []
        failures = []
        with torch.inference_mode():
            warm_start = time.perf_counter()
            _, tensor = preprocess(args.inputs / inputs[0]["image"], MODEL_SIZE)
            for _ in range(WARMUP):
                logits = model(tensor)
            validate_warmup(logits)
            del logits, tensor
            torch.cuda.synchronize()
            warm_ms = (time.perf_counter() - warm_start) * 1000
            torch.cuda.reset_peak_memory_stats()
            start_event = torch.cuda.Event(enable_timing=True)
            stop_event = torch.cuda.Event(enable_timing=True)

            with (output / "frames.csv").open("w", encoding="utf-8", newline="", buffering=1) as stream:
                writer = csv.DictWriter(stream, fieldnames=COLUMNS)
                writer.writeheader()
                loop_started = time.perf_counter()
                for source in inputs:
                    frame = int(source["frame"])
                    item = {key: source[key] for key in COLUMNS if key in source}
                    mask = "masks/" + Path(source["image"]).with_suffix(".png").name
                    try:
                        item.update(measure_frame(model, args.inputs / source["image"], output / mask, start_event, stop_event))
                        item.update(status="ok", mask=mask)
                        good.append(item)
                    except (OSError, ValueError, RuntimeError) as error:
                        item.update(status="error", error=f"{type(error).__name__}: {error}")
                        failures.append(frame)
                    writer.writerow(item)
                    if frame % 100 == 0:
                        print(f"{frame}/{FRAMES} records, {len(good)} successful", flush=True)
                loop_finished = time.perf_counter()

    loop_s = loop_finished - loop_started
    summary = {
        "board": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "power_mode_before": mode_before,
        "power_mode_after": power_mode(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "weights": weight.name,
        "weights_sha256": weight_sha,
        "class_mapping_sha256": mapping_sha,
        "strictly_loaded_state_entries": states,
        "model_load_count": 1,
        "dtype": "torch.float32",
        "input_shape": [1, 3, *MODEL_SIZE],
        "output_shape_verified_in_warmup": [1, CLASSES, *MODEL_SIZE],
        "warmup_frames": WARMUP,
        "model_load_ms": load_ms,
        "warmup_ms": warm_ms,
        "window": window,
        "attempted_frames": FRAMES,
        "successful_frames": len(good),
        "failed_frame_numbers": failures,
        "wall_s": loop_s,
        "loop_started_s": loop_started - START,
        "loop_finished_s": loop_finished - START,
        "fps_with_mask_write": len(good) / loop_s,
        "peak_cuda_allocated_mib": torch.cuda.max_memory_allocated() / 1024 ** 2,
        "peak_cuda_reserved_mib": torch.cuda.max_memory_reserved() / 1024 ** 2,
        "tegrastats_interval_ms": SAMPLE_MS,
        "tegrastats_samples": telemetry.samples,
        "tegrastats_access": "sudo read-only" if args.monitor_sudo else "unprivileged",
    }
    if good:
        summary.update(
            fps_without_mask_write=len(good) * 1000 / sum(row["processing_ms"] for row in good),
            first_frame_cpu_mask_s=good[0]["cpu_mask_ready_s"],
            first_frame_saved_s=good[0]["finished_s"],
            id_min_max=[min(row["id_min"] for row in good), max(row["id_max"] for row in good)],
            milliseconds={
                field: latency_stats(good, field)
                for field in ("preprocess_ms", "forward_ms", "postprocess_ms", "processing_ms", "mask_write_ms", "frame_wall_ms")
            },
            first_100=segment(good[:100]),
            last_100=segment(good[-100:]),
        )
    (output / "run.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Processed {len(good)}/{FRAMES}, wall {loop_s:.3f} s, FPS {summary['fps_with_mask_write']:.3f}")
    if failures or summary["power_mode_after"] != mode_before:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
