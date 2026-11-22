"""Build offline first-person galleries from the extracted GO images and manifests."""

import argparse
import csv
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from go_source import FORWARD_LEFT, NS


SEASONS = {"spring": "春季", "winter": "冬季"}
CSS = """
*{box-sizing:border-box}
body{font:16px/1.55 system-ui,sans-serif;margin:0;color:#edf0ee;background:#171b19}
main{max-width:1300px;margin:auto;padding:32px 22px 56px}
h1{font-size:clamp(25px,5vw,42px);margin:0 0 12px}
h2{margin-top:38px}
p{max-width:70ch}
a{color:#c1eb9a;text-underline-offset:.18em}
nav{display:flex;flex-wrap:wrap;gap:10px 22px;margin-bottom:26px}
code{overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,245px),1fr));gap:16px}
figure,.route{padding:0;margin:0;border:1px solid #424b43;background:#232a26;border-radius:8px;overflow:hidden}
figcaption,.detail{padding:11px 13px}
img{display:block;width:100%;height:auto}
.time{font-weight:700;font-size:17px}
.muted{color:#b9c5bb}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:2px}
.links{display:flex;gap:7px 12px;flex-wrap:wrap}
"""


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return sorted(csv.DictReader(stream), key=lambda row: int(row["stamp_ns"]))


def clock(seconds):
    minutes, seconds = divmod(max(float(seconds), 0), 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


def timestamp(ns):
    seconds, fraction = divmod(int(ns), NS)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + f".{fraction:09d} UTC"


def thumb(root, relative):
    source = root / relative
    gallery = root / "thumbnails"
    gallery.mkdir(exist_ok=True)
    export = gallery / f"{source.parent.name}_{source.stem}.jpg"
    if not export.is_file():
        with Image.open(source) as image:
            image.thumbnail((420, 315), Image.Resampling.LANCZOS)
            image.convert("RGB").save(export, "JPEG", quality=86, optimize=True)
    return export.relative_to(root).as_posix()


def page(path, title, body):
    path.write_text(
        f'<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title><style>{CSS}</style><main><h1>{escape(title)}</h1>{body}</main></html>\n',
        encoding="utf-8",
    )


def tag(root, path, alt):
    return f'<a href="{escape(path)}"><img loading="lazy" src="{thumb(root, path)}" alt="{escape(alt)}"></a>'


def frame_caption(row):
    return (
        f'<div class="time">{clock(row["elapsed_s"])}</div>'
        f'<div class="muted"><code>{timestamp(row["stamp_ns"])}</code></div>'
    )


def contact_sheet(root, season, rows):
    count = min(len(rows), 12)
    selected = [rows[round(i * (len(rows) - 1) / max(count - 1, 1))] for i in range(count)]
    width, height, gap = 320, 240, 12
    columns = 4
    rows_count = (count + columns - 1) // columns
    canvas = Image.new("RGB", (columns * (width + gap) + gap, 48 + rows_count * (height + 40)), "#171b19")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=17)
    draw.text((gap, 13), f"GO  |  {season.title()}  |  Front-left view", fill="#ffffff", font=font)
    for index, row in enumerate(selected):
        x = gap + index % columns * (width + gap)
        y = 48 + index // columns * (height + 40)
        with Image.open(root / row["rgb"]) as image:
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            canvas.paste(image.convert("RGB"), (x, y))
        draw.text((x, y + height + 4), clock(row["elapsed_s"]), fill="#ffffff", font=font)
    canvas.save(root / "contact-sheet.jpg", "JPEG", quality=89, optimize=True)


def show_season(parent, season, title):
    root = parent / season
    source = json.loads((root / "source-index.json").read_text(encoding="utf-8"))
    gallery = read_rows(root / "gallery.csv")
    contact_sheet(root, season, gallery)
    links = '<a href="../index.html">季节对照</a><a href="gallery.csv">预览索引 CSV</a><a href="contact-sheet.jpg">12 张联系表</a>'
    if (root / "sequence.csv").exists():
        links += '<a href="sequence.csv">6 FPS 序列索引 CSV</a>'
    header = f'<p><code>{escape(source["name"])}</code></p><p>前向左相机 <code>{FORWARD_LEFT}</code></p>'
    cards = []
    for row in gallery:
        cards.append(f'<figure>{tag(root, row["rgb"], "前向左相机原图")}<figcaption>{frame_caption(row)}</figcaption></figure>')

    body = f"<nav>{links}</nav>{header}<p>全程约每 10 秒取一帧，共 {len(gallery)} 帧。点击缩略图打开原图。</p>"
    body += f'<div class="grid">{"".join(cards)}</div>'
    labels_path = root / "labels.csv"
    if labels_path.is_file():
        labels = read_rows(labels_path)
        cards = []
        for row in labels:
            pair = tag(root, row["rgb"], "同时间戳的 bag 原图") + tag(root, row["color_mask"], "官方彩色标签")
            links = (
                f'<a href="{row["official_rgb"]}">官方 RGB</a>'
                f'<a href="{row["mask"]}">整数 ID 掩膜</a>'
            )
            cards.append(
                f'<figure><div class="pair">{pair}</div><figcaption>{frame_caption(row)}'
                f'<div class="links">{links}</div></figcaption></figure>'
            )
        body += (
            f'<h2 id="labels">官方标注 · {len(labels)} 帧</h2>'
            f'<nav><a href="labels.csv">逐帧映射 CSV</a><a href="classes.json">官方类别 ID</a></nav>'
            '<p>左图为同时间戳的 bag 原图，右图为官方彩色掩膜。</p>'
            f'<div class="grid">{"".join(cards)}</div>'
        )

    page(root / "index.html", f"GO {title}第一视角", body)
    cover = next((row for row in gallery if 70 <= float(row["elapsed_s"]) <= 95), gallery[0])
    return (
        f'<article class="route"><a href="{season}/index.html">'
        f'<img src="{season}/{thumb(root, cover["rgb"])}" alt="{title}前向左相机"></a>'
        f'<div class="detail"><a href="{season}/index.html">{title} · {len(gallery)} 帧</a>'
        f'<div class="muted"><code>{escape(source["name"])}</code></div></div></article>'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    cards = [show_season(args.output, season, label) for season, label in SEASONS.items()]
    page(
        args.output / "index.html",
        "GO 春冬轨迹 · 第一视角",
        f'<p>按原始时间戳浏览两条轨迹。每条轨迹的相应页面提供原图、联系表和已匹配的官方标注。</p>'
        f'<div class="grid">{"".join(cards)}</div>',
    )


if __name__ == "__main__":
    main()
