# Issue #7 · GO 春季 600 帧 DDRNet-39 64 类真机验收

运行场景为 Orin NX 16GB 现有 15W 模式上的录制静态序列。板载工作区为 `/home/unitree/hqy/goose_issue7`，直接复用 #2 的 Python 3.8/CUDA 虚拟环境和 #4 的官方 64 类 checkpoint、前向实现与类别表。模型在同一进程严格加载一次，官方权重的 SHA256 为 `b99c2838051bcd7b092fd3970aa62a77d5c0bbb809c9b9afb2ff4b0ebdaa4ee6`。 [Issue #7](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/7) · [64 类基线](VALIDATION_CLASS64.md)

## 数据与核验

从 #3 春季前向左相机的 `sequence.csv` 原顺序取第 **1621–2220** 条，共 600 张 1440×1080 JPEG。选段依据为春季联系表，覆盖绿草、树木和双辙土路。首末时间为轨迹相对 **04:30.143–06:09.962**，相机时间跨越 99.819606272 s，实际采样为 6.000825 FPS。相邻间隔最小 133.359 ms、中位 166.700 ms、最大 200.040 ms。 [Issue #3 的数据与来源](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/3#issuecomment-7075744278)

| 项目 | 首 | 末 |
| --- | --- | --- |
| 相机时间戳（ns） | 1713962114715012352 | 1713962214534618624 |
| 输入文件 | `1713962114715012352_12811.jpg` | `1713962214534618624_15805.jpg` |

对全部输入逐张解码和 SHA256 校验后打包，归档 215,470,638 B。板载核对归档 SHA256，再校验所有 JPEG 的字节数、SHA256、行号与相机时间顺序。原始记录以 `inputs.csv` 和 `window.json` 保持可追溯。

## 性能与稳定性

输入为整图双线性缩放、RGB 除以 255。Batch 1、FP32、关闭 TF32、单模型单尺度、512×512。帧循环前统一预热 3 次并检查有限的 1×64×512×512 CUDA logits。

- `forward_ms` 为每帧模型前向的 CUDA Event 耗时，等待该前向完成再取 CPU 掩膜。
- `processing_ms` 从读图和解码开始，经预处理、前向、argmax 到 CPU 得到掩膜，包含同步开销。
- `mask_write_ms` 为编码 PNG 并写入文件，操作系统负责后续刷盘。含写盘 FPS 取 600 帧的循环墙钟，也计入逐行写 CSV 等少量开销。不含写盘 FPS 用 600 除以逐帧 `processing_ms` 总和。
- 首帧耗时从 Python 入口启动开始，包含导入、校验、载入、预热，分别记到 CPU 取得掩膜和 PNG 生成。传输和 PC 渲染另计。
- `tegrastats` 采样周期设为 500 ms。特权用于读取电源轨，推理以普通用户运行。功耗为 Orin 模组 VDD_IN 瞬时值。系统 RAM 是整机共享内存，PyTorch CUDA 分配和保留值来自本进程分配器。 [NVIDIA tegrastats 指标](https://docs.nvidia.com/jetson/l4t/Tegra%20Linux%20Driver%20Package%20Development%20Guide/AppendixTegraStats.html)

板载 **600/600** 帧成功，按原时间顺序输出。循环墙钟 **126.241 s**，含写盘 **4.753 FPS**，不含写盘 **4.889 FPS**。启动到首帧 CPU 掩膜 **11.854 s**，到首个 PNG **11.858 s**，其中模型载入 2.950 s。

| 延迟（ms） | P50 | P95 | P99 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| 模型前向 | 171.94 | 172.48 | 172.58 | 173.04 |
| 读图、解码、预处理及迁移 | 29.01 | 29.32 | 29.79 | 35.03 |
| argmax 与回传 CPU | 3.48 | 3.71 | 3.74 | 4.64 |
| 读图至 CPU 掩膜 | 204.52 | 205.28 | 205.80 | 211.72 |
| PNG 编码与文件写入 | 4.69 | 4.87 | 4.91 | 7.17 |
| 整帧含 PNG 写入 | 209.21 | 210.03 | 211.31 | 216.31 |

资源记录共 258 条，帧循环内 246 条，实际采样间隔中位数 513.5 ms。循环内 GPU 利用率平均 82.36%，在线 CPU 核平均利用率 27.52%。GPU 温度最高 58.25°C，CPU 最高 61.56°C，VDD_IN 平均 9.49 W、最高 10.02 W。

| 稳定性 | 最初 100 帧 | 末尾 100 帧 |
| --- | ---: | ---: |
| 含写盘 FPS | 4.749 | 4.757 |
| 模型前向 P50（ms） | 171.99 | 171.97 |
| GPU 温度 P50（°C） | 54.09 | 57.91 |
| CPU 温度 P50（°C） | 57.50 | 61.25 |
| GPU 利用率 ≥70% 时的频率 P50（MHz） | 611 | 611 |
| VDD_IN 平均值（W） | 9.51 | 9.51 |
| 系统 RAM P50（MB，tegrastats 单位） | 5656 | 5658 |

本段内 GPU 温度上升，忙时频率和前向延迟保持稳定，未观察到热降频导致的持续掉速。系统 RAM 在 5655–5658 MB 范围内，交换空间为 0。PyTorch 实测分配峰值 218.85 MiB，保留峰值 342.00 MiB。600 个帧尾的已分配值一致，约 126.35 MiB。模型保持平稳运行约两分钟，更长运行的热状态待测。

**工程结论**　现有 15W、512×512 FP32 串行流程的 4.89 FPS 低于源 6 FPS。离线顺序处理完整保留了 600 帧。若同样的串行流程直接接入持续 6 FPS 输入，待处理帧会积压。D435i 实时流未验证。

600 张 ID PNG 均通过解码和逐帧映射核对，实际出现的 ID 落在 0–59。H.264 视频复解码验证 600 帧、100 秒、1280×572，页面共验证 43 个本地链接。已核对的板载 #4 权重、类表、脚本与验收产物，以及 #2 的既有结果，前后 SHA256 一致。 [汇总 JSON](sequence_validation.json)

## 复现和产物

- 在电脑上用仓库的 `prepare_go_sequence.py` 将用户的 #3 春季数据目录打包到新的数据目录，`--start-seconds 270` 对应上述连续选段。
- 在板载新目录准备 `code`、`inputs`、`cache` 和 `tmp`。传输 `inputs.zip`，两端对照归档 SHA256 后解到 `inputs`。将本目录的 `run_go_sequence.py` 和本次版本的 `infer_goose_class.py` 放入新目录的 `code`。复用 #2 和 #4 目录中的既有文件。
- 复现板上 500 ms 电源轨采样时，在自己的 SSH 终端对只读 `tegrastats` 使用当前 sudo 授权。运行命令如下。

```bash
(
  go_task="$HOME/hqy/goose_issue7"
  go_base="$HOME/hqy/goose_ddrnet"
  go_class="$HOME/hqy/goose_ddrnet64"
  unset PYTHONPATH PYTHONHOME
  export XDG_CACHE_HOME="$go_task/cache" TMPDIR="$go_task/tmp"
  export CUDA_CACHE_DISABLE=1 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
  sudo -v
  "$go_base/.venv/bin/python" -B "$go_task/code/run_go_sequence.py" \
    --inputs "$go_task/inputs" --output "$go_task/replay_results" \
    --base "$go_base" --class-root "$go_class" --monitor-sudo
)
```

将板载运行结果放入本机数据目录的 `board/` 子目录，与 `inputs.csv` 同级。PC 端用 Pillow、NumPy 和带 H.264 编码器的 FFmpeg 构建预览。字体使用支持中文的本地字体文件。示例中的 `$goFfmpeg` 指向本机 FFmpeg 可执行文件。

```powershell
$goData = 'D:/Go2W-data/go_issue7'
$goSpring = 'D:/Go2W-data/go_issue3/spring'
$goPalette = 'local/goose_issue4/inputs/goose_label_mapping.csv'
python scripts/goose_ddrnet/prepare_go_sequence.py $goSpring $goData --start-seconds 270
python scripts/goose_ddrnet/build_go_sequence_preview.py --source $goSpring --output $goData `
  --palette $goPalette --ffmpeg $goFfmpeg --font 'C:/Windows/Fonts/msyh.ttc'
```

本机入口为 `D:/Go2W-data/go_issue7/index.html`。`sequence.mp4` 是左原图、右叠加的 H.264 视频，按 6 FPS 播放。页面提供 12 个代表帧、官方色表和原始时间戳，以及以下文件。

| 文件 | 内容 |
| --- | --- |
| `board/masks/` | 600 张 512×512 的 8 位原始类别 ID PNG |
| `inputs.csv` 与 `board/frames.csv` | 逐帧原图、相机时间戳、掩膜映射和分阶段延迟 |
| `board/tegrastats.tsv` 与 `resource_samples.csv` | 原始日志与解析后的板载资源时间序列 |
| `board/run.json` 与 `resource_summary.json` | 逐阶段统计、前后 100 帧对照与资源汇总 |
| `review.json` | 逐帧文件核验、视频逐帧解码及预览链接统计 |

代表帧类别比例为预测像素分布。数据集级 IoU 和 D435i 实时链路需另行实测。
