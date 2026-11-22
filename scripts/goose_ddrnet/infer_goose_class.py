"""Run the official 64-class DDRNet-39 with the existing Issue #2 Jetson environment."""

import argparse
import csv
from html import escape
import json
from pathlib import Path
import re
import statistics
import sys
import time

import numpy as np
from PIL import Image
import torch
from torch.nn import functional as F


VOID_IDS = (0, 8, 56)
MASK_ALPHA = 0.45
COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def read_palette(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        mapping = sorted(csv.DictReader(stream), key=lambda row: int(row["label_key"]))
    ids = [int(row["label_key"]) for row in mapping]
    names = [row["class_name"] for row in mapping]
    if ids != list(range(64)) or len(set(names)) != 64 or any(not COLOR.fullmatch(row["hex"]) for row in mapping):
        raise ValueError("Expected the 64 official GOOSE label keys, class names and hex colors.")
    if [names[i] for i in VOID_IDS] != ["undefined", "ego_vehicle", "outlier"]:
        raise ValueError("The official GOOSE Void class IDs do not match.")
    palette = np.array([
        [int(row["hex"][offset:offset + 2], 16) for offset in (1, 3, 5)]
        for row in mapping
    ], dtype=np.uint8)
    return mapping, palette


def preprocess(path, size):
    with Image.open(path) as source:
        rgb = source.convert("RGB")
    pixels = np.array(rgb)
    data = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).to(dtype=torch.float32).div_(255)
    data = F.interpolate(data, size=size, mode="bilinear", align_corners=False).to("cuda:0")
    return rgb, data


def labels_from(logits):
    return logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)


def timed_single_image(model, path, size):
    """Measure one warm-model image from file decode to the CPU ID mask, without output saving."""
    torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.inference_mode():
        rgb, data = preprocess(path, size)
        torch.cuda.synchronize()
        prepared = time.perf_counter()
        logits = model(data)
        torch.cuda.synchronize()
        forwarded = time.perf_counter()
        labels = labels_from(logits)
    complete = time.perf_counter()
    return rgb, labels, {
        "preprocess_ms": (prepared - start) * 1000,
        "forward_wall_ms": (forwarded - prepared) * 1000,
        "argmax_and_copy_ms": (complete - forwarded) * 1000,
        "single_image_no_save_ms": (complete - start) * 1000,
    }


def render_review(root, rgb, labels, mapping, palette, counts, title):
    rgb.save(root / "input_rgb.png")
    mask_native = Image.fromarray(palette[labels]).resize(rgb.size, Image.Resampling.NEAREST)
    mask_native.save(root / "mask_color.png")
    Image.blend(rgb, mask_native, MASK_ALPHA).save(root / "overlay.png")

    def legend_row(index):
        info = mapping[index]
        count = int(counts[index])
        share = count / labels.size
        name = escape(info["class_name"])
        color = info["hex"].lower()
        return (
            f"<tr><td>{index}</td><td>{name}</td>"
            f'<td><span class="swatch" style="background:{color}"></span>{color}</td>'
            f"<td>{count:,}</td><td>{share:.2%}</td></tr>"
        )

    visible = sorted((i for i, n in enumerate(counts) if n), key=lambda i: -int(counts[i]))
    header = "<thead><tr><th>ID</th><th>GOOSE 类名</th><th>颜色</th><th>像素数</th><th>比例</th></tr></thead>"
    present = f'<table>{header}<tbody>{"".join(map(legend_row, visible))}</tbody></table>'
    all_classes = f'<table>{header}<tbody>{"".join(map(legend_row, range(64)))}</tbody></table>'
    media = []
    for name, caption in (
        ("input_rgb.png", "原图"), ("mask_color.png", "官方颜色分割"), ("overlay.png", "叠加图"),
    ):
        media.append(f'<figure><a href="{name}"><img src="{name}" alt="{caption}"></a><figcaption>{caption}</figcaption></figure>')
    style = """
*{box-sizing:border-box}body{font:16px/1.55 system-ui,sans-serif;color:#e9eee9;background:#171c19;margin:0}
main{max-width:1460px;margin:auto;padding:24px}a{color:#cbf5a8;text-underline-offset:.2em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px}
figure{margin:0;background:#252c28;border:1px solid #455148;border-radius:7px;overflow:hidden}
figure img{display:block;width:100%;height:auto}figcaption{padding:8px 10px}
table{border-collapse:collapse;text-align:left}th,td{padding:6px 11px;border-bottom:1px solid #455148}
.swatch{display:inline-block;width:18px;height:18px;margin-right:8px;border:1px solid #94a092;vertical-align:middle}
details{margin-top:20px}h1{overflow-wrap:anywhere}.links{display:flex;gap:16px;flex-wrap:wrap}
"""
    heading = escape(title)
    index = (
        f'<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{heading}</title><style>{style}</style><main><h1>{heading}</h1>'
        f'<div class="grid">{"".join(media)}</div>'
        '<p class="links"><a href="mask_ids_512.png">512×512 ID 掩膜</a>'
        '<a href="run.json">验收记录 JSON</a></p>'
        f'<h2>这张图的预测类别</h2>{present}'
        f'<details><summary>全部 64 类颜色图例</summary>{all_classes}</details></main></html>\n'
    )
    (root / "index.html").write_text(index, encoding="utf-8")


def main():
    code = Path(__file__).resolve().parent
    workspace = code.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=workspace.parent / "goose_ddrnet", help="Existing Issue #2 root")
    parser.add_argument("--image", type=Path, help="Static RGB image. Defaults to the verified GOOSE sample.")
    parser.add_argument("--classes", type=int, choices=(64, 12), default=64, help="12 runs the control in the new workspace")
    parser.add_argument("--output", type=Path, help="Write results outside the Issue #2 root.")
    args = parser.parse_args()
    base = args.base.resolve()
    sys.path.insert(0, str(base / "code"))
    from infer_goose import DDRNet39, HpmStruct, REPEATS, SIZE, WARMUPS, file_sha256, timed_forward

    base_assets = json.loads((base / "code/assets.json").read_text(encoding="utf-8"))
    class_assets = json.loads((code / "assets_class64.json").read_text(encoding="utf-8"))
    checkpoint_record = class_assets["checkpoint"] if args.classes == 64 else base_assets["checkpoint"]
    inputs = workspace / "inputs" if args.classes == 64 else base / "inputs"
    weights = inputs / checkpoint_record["file"]
    default_image = (base / "inputs" / base_assets["image"]["file"]).resolve()
    image_path = args.image.resolve() if args.image else default_image
    out = (args.output or workspace / "outputs" / f"{args.classes}_{image_path.stem}").resolve()
    if out == base or base in out.parents:
        raise ValueError("The output directory must be outside the Issue #2 workspace.")

    if not torch.cuda.is_available():
        raise SystemExit("The Jetson CUDA device is unavailable.")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    weight_sha = file_sha256(weights)
    if weight_sha != checkpoint_record["sha256"]:
        raise ValueError("GOOSE checkpoint SHA256 mismatch.")
    image_sha = file_sha256(image_path)
    if image_path == default_image and image_sha != base_assets["image"]["sha256"]:
        raise ValueError("GOOSE sample SHA256 mismatch.")
    if args.classes == 64:
        mapping_info = class_assets["class_mapping"]
        mapping_path = inputs / mapping_info["file"]
        if file_sha256(mapping_path) != mapping_info["sha256"]:
            raise ValueError("GOOSE label mapping SHA256 mismatch.")
        mapping, palette = read_palette(mapping_path)

    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    state = checkpoint["net"]
    model = DDRNet39(HpmStruct(num_classes=args.classes))
    model.load_state_dict(state, strict=True)
    state_count = len(state)
    del checkpoint, state
    model.eval().to("cuda:0")

    _, tensor = preprocess(image_path, SIZE)
    logits, times = timed_forward(model, tensor)
    forward_allocated = torch.cuda.max_memory_allocated() / (1024 ** 2)
    forward_reserved = torch.cuda.max_memory_reserved() / (1024 ** 2)
    output_shape = list(logits.shape)
    dtype = str(logits.dtype)
    if (
        output_shape != [1, args.classes, *SIZE]
        or not logits.is_cuda
        or logits.dtype != torch.float32
        or not torch.isfinite(logits).all().item()
    ):
        raise RuntimeError("Expected finite CUDA FP32 logits at the selected class count and resolution.")
    reference = labels_from(logits)
    allocated = torch.cuda.max_memory_allocated() / (1024 ** 2)
    reserved = torch.cuda.max_memory_reserved() / (1024 ** 2)
    del logits, tensor

    rgb, labels, single = timed_single_image(model, image_path, SIZE)
    counts = np.bincount(labels.ravel(), minlength=args.classes)
    if len(counts) != args.classes or not np.array_equal(reference, labels):
        raise RuntimeError("Prediction deviated from the timed forward pass or exceeded the class map.")
    metrics = {
        "classes": args.classes,
        "weights": weights.name,
        "weights_sha256": weight_sha,
        "strictly_loaded_state_entries": state_count,
        "image": image_path.name,
        "image_sha256": image_sha,
        "image_width_height": list(rgb.size),
        "input_shape": [1, 3, *SIZE],
        "output_shape": output_shape,
        "output_dtype": dtype,
        "finite_cuda_logits": True,
        "device": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "tf32": False,
        "warmup_count": WARMUPS,
        "forward_count": REPEATS,
        "forward_ms": times,
        "forward_min_ms": min(times),
        "forward_median_ms": statistics.median(times),
        "forward_max_ms": max(times),
        "peak_forward_cuda_allocated_mib": forward_allocated,
        "peak_forward_cuda_reserved_mib": forward_reserved,
        "peak_cuda_allocated_mib": allocated,
        "peak_cuda_reserved_mib": reserved,
        "id_min_max": [int(labels.min()), int(labels.max())],
        "class_pixel_counts": counts.tolist(),
        "one_warm_image_wall_ms": single,
    }

    out.mkdir(parents=True, exist_ok=True)
    names = ["mask_ids_512.png", "run.json"]
    if args.classes == 64:
        names += ["input_rgb.png", "mask_color.png", "overlay.png", "index.html"]
    if any((out / name).is_symlink() for name in names):
        raise ValueError("Refusing to write through an output symlink.")
    Image.fromarray(labels).save(out / "mask_ids_512.png")
    if args.classes == 64:
        render_review(out, rgb, labels, mapping, palette, counts, f"GOOSE DDRNet-39 · {image_path.stem}")
        metrics["legend_mapping_sha256"] = mapping_info["sha256"]
        metrics["goose_void_ids"] = list(VOID_IDS)
        metrics["overlay_alpha"] = MASK_ALPHA
        metrics["predicted_classes"] = [
            {"id": i, "name": row["class_name"], "color": row["hex"], "pixels": int(counts[i])}
            for i, row in enumerate(mapping) if counts[i]
        ]
    (out / "run.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"{args.classes} classes, CUDA logits {output_shape}, median {statistics.median(times):.2f} ms, results {out}")


if __name__ == "__main__":
    main()
