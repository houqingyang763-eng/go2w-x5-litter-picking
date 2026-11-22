# GO 春冬轨迹离线数据准备

本目录承接 [Issue #3](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/3)。用 GO 官方两条轨迹准备前向 RGB、逐帧语义标签和本地浏览页。提取和检查均在 Windows 本机完成。

## 来源与索引核验

| 轨迹 | 官方归档 | 实际字节数 | 索引时长 | 前左 RGB | 前右 RGB | 后向 RGB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 春季 | [`tamu_full_stack_morning_run_1_2024-04-24-08-30-42_filtered.bag`](https://drive.google.com/file/d/1CXmHX61njEUhmRBZ1nQ_798o6kviDRta/view) | 45,242,711,455 | 781.557 s | 23,438 | 23,432 | 23,432 |
| 冬季 | [`2025-01-24-10-42-36_newcal.bag`](https://drive.google.com/file/d/1qlGjFenEoXRKXIm6-0w9XRefIRavMWUg/view) | 61,499,289,407 | 827.583 s | 24,816 | 24,815 | 24,806 |

- Drive 文件元数据与 HTTP `Content-Range` 的总字节数一致。时长、话题与上表帧数来自 ROS bag v2 末尾索引。两条轨迹的起止时间分别是 2024-04-24 12:30:44.572–12:43:46.129 UTC 和 2025-01-24 15:42:38.836–15:56:26.419 UTC。
- 两条轨迹提取 `/lester/stereo_left/image_rect_color/compressed`，验证分辨率为 1440×1080。前右、后向话题分别为 `/lester/stereo_right/image_rect_color/compressed` 和 `/lester/rear_center/image_rect_color/compressed`。原始 JPEG 从 ROS 消息直接落盘。
- [官方 RGB 标注 ZIP](https://drive.google.com/file/d/1S5kNhSlOlikyaN6_ooWUGdD0YK7sVE9l/view) 大小 1,589,952,606 B。ZIP 中的 `bag_split_report.json` 记录春季 119 帧（train）、冬季 110 帧（val 60、test 50）。官方 RGB、ID 掩膜和彩色掩膜共用同一个纳秒时间戳文件名。

[GO 官方下载页](https://unmannedlab.org/the-great-outdoors-dataset/download/) · [平台与相机](https://unmannedlab.org/the-great-outdoors-dataset/platform/) · [标注说明](https://unmannedlab.org/the-great-outdoors-dataset/annotation/)

## 已完成的离线验收

| 轨迹 | 全程预览 | 官方标注精确匹配 | 含草 | 含土 | 含树 | 含天空 | 含雪 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 春季 | 79 帧 | 119 / 119 | 116 | 108 | 119 | 75 | 0 |
| 冬季 | 83 帧 | 110 / 110 | 19 | 0 | 110 | 54 | 110 |

标注通过左相机 `header.stamp` 与文件名中的整数纳秒值精确匹配。下载的 ZIP 条目通过大小及 CRC 检查，全部 `RGB / ID 掩膜 / 彩色掩膜` 尺寸一致。官方 ZIP 中的 JPEG 与 bag JPEG 解码后逐对比较，平均每通道绝对像素差的最大值约 1.32（春季）和 0.92（冬季，8 位像素标度）。类别覆盖按对应 ID 出现至少一个像素计数。

春季预览约 03:30–09:30 可见绿草、树林和双辙土路。官方标注有 106 帧同时含 `grass` 与 `dirt`。冬季预览主要是覆雪路面和落叶树林。两条轨迹的官方分组与雪地覆盖应在后续比较中保留。

从前向相机开始有图的时刻起，取第一段约 10 分钟。按 6 Hz 的目标时间网格定位并保留接近目标时刻的原始帧。两条序列各 3,600 张，时间戳均唯一，所有照片完整解码通过。

| 轨迹 | 序列首末帧间隔 | 平均 FPS | 最大相邻帧间隔 | 6 FPS 序列中有官方标注 |
| --- | ---: | ---: | ---: | ---: |
| 春季 | 599.818 s | 6.0002 | 233.379 ms | 16 / 3,600 |
| 冬季 | 599.849 s | 5.9998 | 200.041 ms | 15 / 3,600 |

剩余 3,584 张春季序列帧与 3,585 张冬季序列帧无本次核实的官方标签。完整标签子集仍保留春季 119 和冬季 110 对。全程预览和映射中也保存区间外的标注时间戳。

下载前 D 盘可用空间为 148,750,217,216 B。本次远程读取 bag 数据块 8,498,248,747 B，另外读取索引及标注 ZIP 的必要条目。提取期间解压数据块只在内存处理，验收后已清理临时 JPEG 缓存。D 盘输出为 2,291,201,564 B，按文件 ID 去除硬链接重复统计。详细数值见 [验收统计](validation.json)。

## 复现

从仓库根目录运行。依赖装在个人虚拟环境内。数据目录选择空间充足的本地数据盘，命令中的路径可替换。

```powershell
py -3.12 -m venv local/go-tracks-venv
$goPython = 'local/go-tracks-venv/Scripts/python.exe'
& $goPython -m pip install -r scripts/go_tracks/requirements.txt
$goOutput = 'D:/Go2W-data/go_issue3'

& $goPython scripts/go_tracks/extract_go.py spring --stage preview --output $goOutput
& $goPython scripts/go_tracks/extract_go.py winter --stage preview --output $goOutput
& $goPython scripts/go_tracks/extract_go.py spring --stage benchmark --output $goOutput
& $goPython scripts/go_tracks/extract_go.py winter --stage benchmark --output $goOutput
& $goPython scripts/go_tracks/make_preview.py $goOutput
& $goPython scripts/go_tracks/verify_go.py $goOutput
```

如直连 Drive 失败，可给提取命令追加 `--proxy`，使用已有且能够访问官方 Drive 下载域名的 HTTP 代理。所有请求保留 TLS 证书校验，要求服务器返回匹配的 206 响应。工作目录既存成功数据块可复用，按原命令重跑会继续补齐缺失范围。大规模下载前脚本逐阶段检查当前可用空间和计划读取字节数。

## 文件与清理

打开数据目录中的 `index.html`。每条轨迹页面提供全程联系表、原始时间戳和官方标注预览。每个季节子目录内的主要文件如下。

| 文件或目录 | 用途 |
| --- | --- |
| `gallery.csv`、`gallery-rgb/` | 全程约每 10 秒取一帧，覆盖完整轨迹 |
| `sequence.csv`、`sequence-rgb/` | 约 10 分钟的 6 Hz 目标时间网格及对应原始 RGB |
| `labels.csv`、`label-bag-rgb/` | 官方标注对应的完整原始 RGB 子集，含序列区间外的已标注帧 |
| `label-official-rgb/`、`label-mask/`、`label-mask-color/` | 官方原配 JPEG、可用于评估的整数 ID PNG、彩色预览 PNG |
| `classes.json`、`class_id_mapping.json` | 官方类别名称、原始 ID、连续 ID 对照 |
| `source-index.json`、`chunks.json`、`*-summary.json` | 索引、分段定位和提取统计 |

`stamp_ns` 是相机消息时间，`bag_ns` 是 bag 记录时间，`target_ns` 是采样网格或标注的目标时间。用同一季节的 `stamp_ns` 可把序列和 `labels.csv` 关联。未出现在映射中的序列帧没有本次取得的官方标注。纳秒时间戳应按整数或文本导入，避免电子表格浮点取整。

运行期间临时 JPEG 位于各季节的 `.chunk-cache/`。检查 CSV 引用与图片可打开后，可仅清理这两个缓存目录，最终 RGB 与掩膜仍可使用。若需移除全部本地数据，可移除整个 GO 数据目录；代码与本地依赖位于仓库工作区。
