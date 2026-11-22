# GOOSE DDRNet 板载 CUDA 环境

对应 [Issue #2](https://github.com/houqingyang763-eng/go2w-x5-litter-picking/issues/2)。板载工作目录是 `/home/unitree/hqy/goose_ddrnet`。本次输入为 GOOSE 2D 验证集的可见光 RGB 图片，使用官方 `ddrnet_category_512` 权重输出 12 类分割。目录内保存仅用于该项目的 `.venv`、依赖 wheel、输入和结果。

## 使用板载环境

在 SSH 终端中运行下面的命令。已准备好的环境可以直接执行。输出写入 `outputs/ddrnet_run.json` 和 `outputs/ddrnet_mask_512.png`，PNG 的像素值是类别 ID。

```bash
(
  cd "$HOME/hqy/goose_ddrnet"
  unset PYTHONPATH PYTHONHOME
  export HOME="$PWD" XDG_CACHE_HOME="$PWD/cache" TMPDIR="$PWD/tmp"
  export CUDA_CACHE_DISABLE=1 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
  .venv/bin/python -B code/infer_goose.py
)
```

可加 `--image /path/to/rgb.png` 验证其他静态 RGB 文件。脚本用 RGB 除以 255 并做双线性缩放，输入为 `1×3×512×512` 的 FP32 张量。检查点通过 `torch.load(..., weights_only=True)` 读取 `net`，用 `strict=True` 加载权重。板载 CUDA 上验证有限的 `1×12×512×512` logits，按通道取最大值得到分割。测试含 3 次预热和 10 次 CUDA Event 计时，延迟统计对应模型前向，显存指标来自 PyTorch 分配器的张量分配和保留量。 [GOOSE 重现示例](https://goose-dataset.de/docs/examples/)

## 准备和重建

- 已验证板载为 Jetson Orin NX 16GB、Jetson Linux 35.3.1（JetPack 5.1.1）和系统 CPython 3.8.10。虚拟环境独立安装 NVIDIA PyTorch 2.0.0+nv23.05 的 CPython 3.8 ARM64 wheel、NumPy 1.24.4 与 Pillow 10.4.0，动态链接板上已有的 CUDA 11.4、cuDNN 和 OpenBLAS。`setup_jetson.sh` 引导离线 pip，按带 SHA256 的锁文件安装并运行 CUDA 小测试。 [NVIDIA JetPack](https://developer.nvidia.com/embedded/jetpack-sdk-511) · [NVIDIA Jetson PyTorch 安装文档](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html)
- 官方 GOOSE 示例使用 SuperGradients 3.7.1。`extract_ddrnet.py` 从固定 SHA256 的官方 wheel 提取 DDRNet-39 前向和配套层，适配参数容器和基类，保留网络计算以及源许可证。官方检查点的双第三阶段和 12 类输出层与此结构匹配。 [GOOSE 图像处理源码](https://github.com/FraunhoferIOSB/goose_dataset/tree/fbbc0e755e54bbdc65a9fa7a3f327533425025f6/image_processing) · [DDRNet 作者仓库](https://github.com/ydhongHIT/DDRNet) · [SuperGradients 3.7.1](https://pypi.org/project/super-gradients/3.7.1/)

在联网的笔记本上，从仓库根目录执行下列命令。下载文件保存在 Git 忽略的 `local/` 下。

```bash
stage='local/goose_ddrnet'
mkdir -p "$stage/wheelhouse" "$stage/inputs"
grep -v '^torch==' scripts/goose_ddrnet/requirements-jetson.txt > "$stage/pypi-requirements.txt"
python -m pip download --dest "$stage/wheelhouse" --require-hashes --only-binary=:all: \
  --platform manylinux2014_aarch64 --python-version 3.8 --implementation cp --abi cp38 \
  -r "$stage/pypi-requirements.txt"
wheel='torch-2.0.0+nv23.05-cp38-cp38-linux_aarch64.whl'
curl -fL "https://developer.download.nvidia.com/compute/redist/jp/v511/pytorch/$wheel" -o "$stage/wheelhouse/$wheel"
python -m pip download --dest "$stage/inputs" --no-deps super-gradients==3.7.1
curl -fL https://goose-dataset.de/models/ddrnet_category_512.pth -o "$stage/inputs/ddrnet_category_512.pth"
# val ZIP 来源见 assets.json。下列命令只解出指定成员。
unzip -p goose_2d_val.zip 'images/val/2022-07-22_flight/2022-07-22_flight__0071_1658494234334310308_windshield_vis.png' > "$stage/inputs/goose_val_rgb.png"
```

GOOSE 的下载地址以及所选 RGB 图片的成员名和 SHA256 见 [assets.json](assets.json)。本次整文件传输停滞后，用 HTTP Range 下载了权重并逐项校验 ZIP CRC，也以 Range 从验证集归档取出单张样本。 [GOOSE 官方下载页](https://goose-dataset.de/docs/setup/)

先在板载终端创建目录。

```bash
(umask 077; mkdir -p "$HOME/hqy/goose_ddrnet"/{code,inputs,wheelhouse,outputs,cache,tmp})
```

用 SSH/SFTP 将依赖 wheel 传到板载 `wheelhouse/`，将权重、样本和 SuperGradients wheel 传到 `inputs/`，将 `scripts/goose_ddrnet/` 的脚本、锁文件和 `assets.json` 传到 `code/`。在板载执行以下命令。

```bash
cd "$HOME/hqy/goose_ddrnet"
bash code/setup_jetson.sh
.venv/bin/python -I -B code/extract_ddrnet.py \
  inputs/super_gradients-3.7.1-py3-none-any.whl code/ddrnet_forward.py
```

随后运行上面的单图验证命令。仓库追踪脚本、锁文件、来源和校验值，归档、权重、wheel、原始图片与输出保存在任务目录或本地忽略目录。

## 2026-11-22 真机验收

在 Orin NX 16GB 的 15W 模式下，用 GOOSE 官方验证集的一张 2048×1000 可见光图片测试。官方检查点中 501 项权重与缓冲区严格加载，输入为 1×3×512×512，输出为有限的 1×12×512×512 CUDA FP32 logits。预热 3 次后的 10 次前向中位数为 167.17 ms，范围 166.85–167.48 ms。PyTorch 张量分配峰值为 164.98 MiB，分配器保留峰值为 214 MiB。单图验收完成度以权重、设备、形状和输出文件为准，分割准确率需另做带标注数据评估。
