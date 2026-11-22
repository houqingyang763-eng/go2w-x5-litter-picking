# Issue #2 板载验收记录

2026-11-22 在 Go2-W 的 Jetson Orin NX 16GB 上完成真机单图验收。测试时为 15W 模式，环境位于 `/home/unitree/hqy/goose_ddrnet`。 [Issue #2](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/2) · [验收回评](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/2#issuecomment-7074153739)

## 环境与输入

- 板载系统 Ubuntu 20.04.5 ARM64，L4T 35.3.1。项目虚拟环境使用系统 Python 3.8.10 和 NVIDIA PyTorch `2.0.0+nv23.05`，复用板载 CUDA 11.4、cuDNN 和 OpenBLAS。离线安装后的 `pip check` 和 CUDA 小测试通过。
- 以 SuperGradients 3.7.1 的 DDRNet-39 构建网络。GOOSE 官方 `ddrnet_category_512.pth` 中的 `net` 共 501 项，用 `strict=True` 完整加载。
- 输入来自 GOOSE 2D 官方验证集的可见光图片 `2022-07-22_flight__0071_1658494234334310308_windshield_vis.png`，原始尺寸 2048×1000。测试将 RGB 转为 FP32 后缩放到 512×512。权重、样本和上游 wheel 的来源与 SHA256 见 [资产清单](assets.json)。 [GOOSE 官方下载](https://goose-dataset.de/docs/setup/)

## 实测结果

| 检查项 | 结果 |
| --- | --- |
| CUDA 前向 | 得到有限的 `1×12×512×512` FP32 logits |
| 前向用时 | 预热 3 次后测 10 次。中位数 **167.17 ms**，范围 166.85–167.48 ms |
| PyTorch GPU 内存 | 分配峰值 164.98 MiB，分配器保留峰值 214 MiB |
| 输出核对 | 512×512 类别掩膜的像素计数与运行报告一致 |
| 隔离复核 | 项目包均解析到 `.venv`，板载系统的 Python 及所查 L4T、CUDA、TensorRT 和 ROS 2 软件包版本与开工前一致 |

10 次 CUDA Event 前向耗时（ms）依次为 166.97, 167.09, 167.21, 166.85, 167.48, 167.24, 167.33, 166.98, 167.47, 167.14。这组数值对应单图模型前向，分割准确率需要用带标注数据评估。

复现及运行命令见 [README](README.md)。板载结果文件为 `outputs/ddrnet_run.json` 和 `outputs/ddrnet_mask_512.png`。
