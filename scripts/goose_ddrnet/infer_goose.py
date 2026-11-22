"""Run GOOSE ddrnet_category_512 on Jetson CUDA and save a class-ID PNG."""

import argparse
import json
from pathlib import Path
import statistics

import numpy as np
from PIL import Image
import torch
from torch.nn import functional as F

from ddrnet_forward import DDRNet39, HpmStruct
from extract_ddrnet import file_sha256


CLASSES = 12
SIZE = (512, 512)
WARMUPS = 3
REPEATS = 10


def timed_forward(model, image):
    times = []
    with torch.inference_mode():
        for _ in range(WARMUPS):
            model(image)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        start = torch.cuda.Event(enable_timing=True)
        stop = torch.cuda.Event(enable_timing=True)
        for _ in range(REPEATS):
            start.record()
            logits = model(image)
            stop.record()
            stop.synchronize()
            times.append(start.elapsed_time(stop))
            if len(times) < REPEATS:
                del logits
    return logits, times


def main():
    code = Path(__file__).resolve().parent
    workspace = code.parent
    assets = json.loads((code / "assets.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=workspace / "inputs" / assets["image"]["file"])
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("The Jetson CUDA device is unavailable.")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    weights = workspace / "inputs" / assets["checkpoint"]["file"]
    if file_sha256(weights) != assets["checkpoint"]["sha256"]:
        raise ValueError("GOOSE checkpoint SHA256 mismatch.")
    if args.image == parser.get_default("image") and file_sha256(args.image) != assets["image"]["sha256"]:
        raise ValueError("GOOSE sample SHA256 mismatch.")
    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    state = checkpoint["net"]
    model = DDRNet39(HpmStruct(num_classes=CLASSES))
    model.load_state_dict(state, strict=True)
    loaded_tensors = len(state)
    del checkpoint, state
    model.eval().to("cuda:0")

    with Image.open(args.image) as source:
        width, height = source.size
        rgb = np.array(source.convert("RGB"))
    image = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(dtype=torch.float32).div_(255)
    image = F.interpolate(image, size=SIZE, mode="bilinear", align_corners=False).to("cuda:0")

    logits, times = timed_forward(model, image)
    if tuple(logits.shape) != (1, CLASSES, *SIZE) or not logits.is_cuda or not torch.isfinite(logits).all().item():
        raise RuntimeError("The model did not produce finite 12-class CUDA logits at 512x512.")
    labels = logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
    summary = {
        "weights": weights.name,
        "strictly_loaded_state_entries": loaded_tensors,
        "image": str(args.image),
        "image_width_height": [width, height],
        "input_shape": list(image.shape),
        "output_shape": list(logits.shape),
        "output_dtype": str(logits.dtype),
        "device": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "warmup_count": WARMUPS,
        "forward_ms": times,
        "forward_median_ms": statistics.median(times),
        "peak_cuda_allocated_mib": torch.cuda.max_memory_allocated() / (1024 ** 2),
        "peak_cuda_reserved_mib": torch.cuda.max_memory_reserved() / (1024 ** 2),
        "class_pixel_counts": np.bincount(labels.ravel(), minlength=CLASSES).tolist(),
    }
    outputs = workspace / "outputs"
    if outputs.is_symlink():
        raise ValueError("outputs must be a directory inside the project.")
    outputs.mkdir(exist_ok=True)
    mask_path = outputs / "ddrnet_mask_512.png"
    metrics_path = outputs / "ddrnet_run.json"
    if mask_path.is_symlink() or metrics_path.is_symlink():
        raise ValueError("Refusing to write through a result symlink.")
    Image.fromarray(labels).save(mask_path)
    metrics = json.dumps(summary, indent=2) + "\n"
    metrics_path.write_text(metrics, encoding="utf-8")
    print(metrics, end="")


if __name__ == "__main__":
    main()
