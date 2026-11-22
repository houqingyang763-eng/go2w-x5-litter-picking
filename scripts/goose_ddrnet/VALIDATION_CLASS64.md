# GOOSE DDRNet-39 64 类板载验收

对应 [Issue #4](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/4)。本次在 Go2-W 的 Orin NX 16GB 上完成 GOOSE 官方 64 类模型的静态 RGB 前向，保存 ID 掩膜、官方颜色掩膜、叠加图和图例，并在同一台板上复测 12 类作为对照。运行环境复用 [Issue #2](VALIDATION.md) 的虚拟环境与 DDRNet-39 前向实现。

## 权重与类别

- 官方 GOOSE-2D 512×512、64 类检查点为 `ddrnet_class_512.pth`，下载内容为 259,419,077 B。PC 通过官方 HTTPS 链接分段取得，传到板上后复算 SHA256，均为 `b99c2838051bcd7b092fd3970aa62a77d5c0bbb809c9b9afb2ff4b0ebdaa4ee6`。该值是本次下载与传输的内容校验记录。 [官方模型下载页](https://goose-dataset.de/docs/setup/) · [资产清单](assets_class64.json)
- 从官方 `goose_2d_val.zip` 读取 `goose_label_mapping.csv`，校验 64 个连续的原始 ID（0–63）、唯一类名和颜色。图例以该 CSV 为准，例如 `24 gravel`、`31 soil`、`50 low_grass`、`51 high_grass`、`53 sky`、`16 forest`、`27 tree_crown`、`28 tree_trunk`、`62 tree_root`。官方发布包中的 `59 hedge` 已使用更新颜色 `#e8d317`。 [官方分类](https://goose-dataset.de/docs/class-definitions/) · [颜色修订日志](https://goose-dataset.de/docs/changelog/)
- 官方 Void 组由 `0 undefined`、`8 ego_vehicle` 和 `56 outlier` 组成。本脚本把这些 ID 与其他类别一并保留在预测 PNG 和图例中。255 位于该 64 类取值域之外。核对的官方通用图像评估示例构造 Jaccard 指标时没有显式设置 `ignore_index`。本次核查保留预测 ID，数据集级 IoU 待另行约定类别映射和忽略区域。 [官方图像评估源码](https://github.com/FraunhoferIOSB/goose_dataset/blob/fbbc0e755e54bbdc65a9fa7a3f327533425025f6/image_processing/evaluation.py)

## 真机对照

2026-11-22 在 Orin NX 的 **15W** 模式中运行。Python 3.8.10、NVIDIA PyTorch `2.0.0+nv23.05`、CUDA 11.4、L4T 35.3.1。两种权重均经 `torch.load(..., weights_only=True)` 读取 `net`，`strict=True` 加载 501 个状态项。官方图为 Issue #2 的同一张 2048×1000 GOOSE 可见光验证图，归档成员和 SHA256 见 [样本清单](assets.json)。

同一套输入处理和计时条件为 Batch 1、512×512、单模型单尺度、FP32、关闭 TF32。沿用 #2 的整图双线性缩放及 RGB 除以 255。前向通过 CUDA Event 计时，预热 3 次后测 10 次。下表将前向期间已分配张量峰值与本次首次 argmax 和有限值检查完成前的累计峰值分开列出。后一个口径对应 #2 的显存记录。

| 模式 | 输出与观测 ID | 前向中位数 | 前向范围 | 前向 CUDA 分配峰值 | 含有限性检查及 argmax 的分配峰值 | 单张热模型到 ID 掩膜 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 12 类同场复测 | 1×12×512×512，1–9 | 167.09 ms | 166.68–167.91 ms | 164.98 MiB | 164.98 MiB | 291.86 ms |
| 64 类 | 1×64×512×512，11–53 | 171.49 ms | 170.96–171.90 ms | 217.85 MiB | 305.35 MiB | 298.94 ms |

64 类前向中位数较同场 12 类增加 4.41 ms（2.64%）。12 类在 Issue #2 的历史单图前向中位数为 167.17 ms，范围 166.85–167.48 ms，当时 PyTorch 分配峰值为 164.98 MiB。

`run.json` 保留各次前向和各阶段计时。单张热模型墙钟计时从读图开始，到 CPU 取得整数 ID 掩膜为止，含解码、缩放、迁移和推理。模型加载、可视化与 PNG 写盘在该计时之外。上述时间适用于本次静态条件。12 类同场复测的 ID 掩膜和 Issue #2 保存的掩膜逐像素一致，原工作目录内样本、权重、前向源码及两个结果文件的前后校验值一致。详细数值见 [性能 JSON](validation_class64.json)。

## 场景检查

- GOOSE 官方图可区分路面的 `asphalt` 与 `road_marking`，路旁出现 `high_grass`、`low_grass` 和 `gravel`，远处出现 `sky`、`forest` 与 `tree_crown`。该图的官方 `tree_crown` 区域常被模型分到 `forest`，两者的边界值得在正式评测中量化。
- GO 春季两张图来自 [Issue #3 的已匹配样本](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/3#issuecomment-7075744278)。`1713962184962129664` 是草与土路样例，GO 草区大多输出 `low_grass`，土路区域有 **77.0%** 像素输出 `gravel`、**18.7%** 输出 `soil`。`1713962488321584896` 的 GO 碎石区域大部分输出 `gravel`。这些区域统计只描述这两张图上的模型输出分布。
- GO 大类与 GOOSE 细类只能先做定性对应。`grass` 可对应 `low_grass` 和 `high_grass`，`dirt` 与 `soil` 语义接近，`gravel` 和 `sky` 可初步按同名对应。`trees` 涉及 `forest`、`tree_crown`、`tree_trunk`、`tree_root`，仍需约定边界。精度验收待固定测试集与对应规则后进行。 [GO 官方标注体系](https://unmannedlab.org/the-great-outdoors-dataset/annotation/)

## 复现与产物

板载目录为 `/home/unitree/hqy/goose_ddrnet64`。若需重建该目录，从 [官方模型下载页](https://goose-dataset.de/docs/setup/) 取得检查点，从 [官方验证集 ZIP](https://goose-dataset.de/storage/goose_2d_val.zip) 解出 `goose_label_mapping.csv`，按 [清单](assets_class64.json) 核对。用 SFTP 把两者放到新目录的 `inputs/`，将本目录的 `infer_goose_class.py`、`assets_class64.json` 放到新目录的 `code/`。已有 #2 虚拟环境、前向代码和官方验证图可直接复用。

在板载 SSH 终端运行以下命令。

```bash
(
  go_base="$HOME/hqy/goose_ddrnet"
  go_run="$HOME/hqy/goose_ddrnet64"
  umask 077
  mkdir -p "$go_run/cache" "$go_run/tmp" "$go_run/outputs"
  unset PYTHONPATH PYTHONHOME
  export XDG_CACHE_HOME="$go_run/cache" TMPDIR="$go_run/tmp"
  export CUDA_CACHE_DISABLE=1 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2

  "$go_base/.venv/bin/python" -B "$go_run/code/infer_goose_class.py" \
    --base "$go_base" --classes 64 --output "$go_run/outputs/goose_64"
  "$go_base/.venv/bin/python" -B "$go_run/code/infer_goose_class.py" \
    --base "$go_base" --classes 12 --output "$go_run/outputs/goose_12_control"
)
```

给 64 类入口追加 `--image /path/to/rgb.jpg` 和对应的独立 `--output` 可运行自选静态图。每个 64 类样例目录内的 `index.html` 包含三视图和颜色图例，`mask_ids_512.png` 保存整数 ID，`mask_color.png` 和 `overlay.png` 用最近邻把结果放回原图尺寸。可视化使用 45% 的官方掩膜颜色。横纵比例沿用原始 RGB 图。

本机浏览入口为 `local/goose_issue4/preview/index.html`。板载四个目录位于 `outputs/goose_64`、`outputs/goose_12_control`、`outputs/go_spring_dirt_grass`、`outputs/go_spring_gravel`。已逐文件校验板载与本机的 SHA256，核对 ID 充满 512×512 的像素数、原图像素、调色和叠加输出，并检查全部 HTML 图片链接。
