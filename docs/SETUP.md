# 本机部署路线

更新日期：2026-11-17。**本轮只更新项目资料，没有安装软件、运行 Demo 或连接设备。** 本仓库尚无确认的模型、ROS、SDK 或仿真环境部署结果。

## 1. 本机已有条件

下表是 **2026-11-11 的只读检查记录**，11-17 未重新盘点；不能把它理解为当前所有环境的完整清单。用户已补充有 Linux、Docker、模型训练与 ROS 2 相关经验，这与本项目尚无部署记录并不冲突。

| 项目 | 本次检查结果 | 对部署的含义 |
| --- | --- | --- |
| 操作系统 | Windows 11 家庭版，64 位，版本 10.0.26200 | 可继续使用 Windows 编辑与管理仓库；厂商 Linux 开发依赖需另定运行环境 |
| 内存 / GPU | 约 31.4 GiB 物理内存；RTX 5060 Laptop 与 Intel 图形设备 | 说明本机有 GPU；未验证 CUDA、训练框架或仿真兼容性 |
| Git / GitHub CLI | Git 2.54；gh 2.96 | 可用于版本管理；公开仓库发布状态见项目当前状态文档 |
| WSL | 有既有项目的 WSL 2 发行版，检查时停止 | 保留现状；不向其他项目环境安装本项目依赖 |
| Python | 当前 PowerShell 的 PATH 指向 Anaconda Python 3.7.0 | 不能直接当作本项目 Python；后续建立独立环境 |
| ROS 2 / Docker / CMake | 当前 PowerShell 的 PATH 未找到对应命令 | 只表示当前 shell 未发现，不等于整台电脑所有环境均未安装 |

11-11 建仓时，常规 Git HTTPS 访问 `github.com` 遇到不可信证书链，独立 DNS 查询与本机解析结果不同；临时指定地址仍未完成推送，最终通过 GitHub 官方 `api.github.com` 发布并同步本地提交。11-17 继续使用 API，未复测常规 `git fetch/push`，也未修改系统 DNS、证书或全局 Git 配置。

## 2. 先确定兼容组合，再安装

用户当前计划采用 **Ubuntu 22.04 + ROS 2 Humble + Python**，与此前 Unitree ROS 2 官方 README 的推荐组合一致。PyTorch、CUDA/NVIDIA GPU 按视觉模型和训练需求配置。这是开发计划，尚未通过 X5 与交付 Go2-W 的联合兼容验证，也不表示软件已经装好。

本机视觉 Demo 可以先按所选模型的官方依赖建立独立环境，不必等待真机信息，也不预设它必须依赖 ROS。WVN 官方现有机器人集成使用 **ROS 1/Noetic**，不能直接作为 Humble 包安装；其离线算法复现环境与后续 ROS 2 适配需要分开。官方 Docker 演示在 Ubuntu 测试，Windows/WSL 图形与 GPU 路线未在本项目验证，详见 [资料索引](RESOURCES.md#视觉与可通行性参考)。

推进机器人 SDK 和系统集成前，确认三件事：

1. 交付 Go2-W 使用的 SDK / ROS 包、分支或提交；高层运动服务是否可用。
2. X5 具体版本及交付 SDK 所需的 Linux、Python、CPU 架构；预编译库是否匹配本机环境。
3. 小组已有开发环境、相机型号、板载计算机及其系统；优先与可复用的交付环境对齐。

本地电脑或工作站计划承担开发、模型复现、离线训练、仿真和调试，最终必要模块再部署到实际机器人端；机器人端计算设备配置尚未确认。当前无需服务器即可推进文档和最小视觉实验。如后续模型规模或训练需要服务器、远程 GPU 或服务器部署，先向用户说明用途与拟执行内容。

## 3. 后续可以在本机做的工作

以下为待执行路线，不是已通过的安装步骤；本轮没有下载安装包或修改系统设置。

| 顺序 | 工作 | 可检查的结果 |
| --- | --- | --- |
| A | 为选定视觉基线建立独立模型环境 | 记录 Python、框架、设备与依赖；不改其他项目环境 |
| B | 使用来源明确的野外图像运行特征提取/分割 Demo | 保存可复现命令、输出、速度与显存；准确率另需标签与评价方式 |
| C | 梳理并复现 WVN 可离线运行的部分 | 确认数据是否可得、监督来源、ROS 1 依赖和输出；记录实际跑通范围 |
| D | 核对交付栈后准备 ROS 2 与厂商 SDK | 本地通信或编译检查；不运行连接真机的运动例程 |
| E | 将视觉预测投影到空间，融合几何信息并接入规划器 | 检查 TF、时间戳、代价更新和路径影响，区分离线/仿真与实机 |
| F | 按需做无硬件 X5 运动学/模型验证，准备未来抓取接口 | 型号和库匹配后检查正逆解；真机抓取留到统一上机 |

WSL 可作为本机 Linux 候选，但本次尚未验证 ROS 图形显示、GPU、DDS 多播及 USB/CAN 支持。离线学习环境能跑，不意味着同一配置已经适合真机通信。

本仓库后续只维护自己的代码、配置模板和依赖版本记录；不把整个 SDK、虚拟环境或模型权重复制进 Git。

## 4. 统一留到上机时确认

具体待办及完成状态统一维护在 [STATUS.md 的上机清单](../STATUS.md#留到统一上机核实)，此处不重复维护。上机时先读取设备状态与数据，再安排现场受控运动验证；当前不执行。不能通过猜测补全型号、标定或控制协议，但这些未知项不影响独立的文档和离线工作。

## 5. 部署时只留必要记录

一次部署记录保留：日期、做了什么、关键版本/命令、是否成功、下一步。只有安装或运行真实执行并检查后，才把状态改为“已部署”或“已通过”。

来源及访问限制见 [官方资源与核验记录](RESOURCES.md)。

## 板载目录与开发数据流

### 11-22 真机只读盘点

板载电脑为 Orin NX（ARM64、Ubuntu 20.04.5），系统 Python 3.8.10，Git 2.25.1。SSH 本次经板载 `eth0` 直达，网口协商为 1 Gb/s 全双工。通过 SFTP 将已有的 `~/gemini_preview/color.png` 完整读入本机内存，文件大小为 298,140 字节，PNG 文件头显示 640×480 RGB。

| 板载路径 | 盘点结果 |
| --- | --- |
| `~/go2wlcy_ws` | LCY 学长的 ROS 2 Git 工作空间。源码和安装目录各对应 10 个包，涵盖底盘驱动、速度指令桥接、机器人描述、宇树消息、Nav2 和 RTAB-Map。已核对 `package.xml`、启动文件和安装目录。 |
| `~/realsense_ws`、`~/orbbec_ws` | 两套相机驱动工作空间。当前 D435i 从 `realsense_ws` 运行，板载已实测彩色和深度话题。 |
| `~/unitree_ws`、`~/arx_x5_ws` | 现有宇树及 X5 相关工作空间。 |
| `~/cyclonedds_ws` | 当前 D435i 使用 Foxy 和 `rmw_cyclonedds_cpp`，域 ID 沿用默认值 0。`cyclonedds.xml` 绑定 `eth0`，组播用于参与者发现（`spdp`）。 [Cyclone DDS 配置文档](https://cyclonedds.io/docs/cyclonedds/0.10.2/config/cyclonedds_specifics.html#multicasting) |
| `~/camera_ws/src`、`~/.vscode-server` | 前者盘点时为空，后者已有 VS Code Server 缓存。 |

板载交互 Bash 由 `~/.bashrc` 提供 ROS 选择。输入 `1` 加载 Foxy、Cyclone DDS overlay 和板载 XML，输入 `2` 加载 ROS 1 Noetic。非交互式 SSH 命令如需 ROS 2，应显式加载 Foxy 及相应 DDS 环境。板载系统 Python 可找到 `cv2` 和 `numpy`，在该解释器下未找到 `torch` 或 `transformers`。

### 建议的个人开发方式

1. **连接和隔离**　沿用 VS Code Remote-SSH 的主机别名。板载个人工作树建议用 `~/workspaces/hou/go2w-litter-picking/`，在远程 VS Code 打开该目录。用 `pwd` 和 `git rev-parse --show-toplevel` 确认操作位置。Python 项目用自己的 `.venv/`，后续 ROS 包用自己的构建目录和显式加载的依赖。共用 `unitree` 账号时，个人目录提供项目隔离，账号权限仍共用。需要新增匹配的 VS Code Server 时，可在笔记本设置 `"remote.SSH.localServerDownload": "always"`，由笔记本下载再经 SSH 传入。 [VS Code Remote-SSH 文档](https://code.visualstudio.com/docs/remote/ssh)
2. **代码和交接**　以现有笔记本 Git 仓库为主工作树。需要经常在两端写代码时，可在板载用 `git init --bare` 建 `~/workspaces/hou/git/go2w-litter-picking.git`。笔记本将它配为 `robot` remote，经同一 SSH 别名推送选定分支，板载个人目录从这个裸仓克隆。板载提交先推到机内裸仓，笔记本用 `git fetch robot` 拉回审阅。GitHub 同步从笔记本按授权执行，交接任务在 Issue 写目标、输入、输出和验收标准。 [Git 裸仓](https://git-scm.com/docs/git-init) · [Git SSH 地址格式](https://git-scm.com/docs/git-push) · [协作约定](../AGENTS.md)
3. **照片和推理**　照片走 SFTP 或 `scp`，存到仓库已忽略的 `data/`，分割结果放 `outputs/`，权重留在本机模型缓存。今天建议在笔记本的 `Go2W-Foxy` WSL 中用 `~/venvs/go2w-vision/bin/python` 做静态 RGB 分割。已复核 Python 3.11.14、PyTorch 2.7.1+cu128 和 Transformers 4.57.6。SegFormer-B0 ADE20K 是先前筛选的候选，默认 Hugging Face 缓存尚未发现模型快照。一次运行保存语义分割叠加图和推理耗时。 [OpenSSH 文件传输](https://man.openbsd.org/scp.1) · [SegFormer-B0 模型](https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512)
4. **实时话题**　需要持续收流时，先按已测的 Foxy、Cyclone DDS 和域 0 检查话题发现，再用板载 `/camera/color/image_raw` 验证实际收帧。目前笔记本 WSL 网络实查为 NAT，跨机发现和收帧待测。按现有 30 FPS 的 RGB8 和 Z16 分辨率估算，双路原始图像载荷约 107 MB/s，实时预览可按需要选择路数、分辨率和频率。

下面是笔记本项目 PowerShell 中的取图示例。把 `go2-dev` 换成当前 Windows SSH 主机别名。

```powershell
New-Item -ItemType Directory -Force .\data | Out-Null
scp 'go2-dev:/home/unitree/gemini_preview/color.png' '.\data\go2-preview-color.png'
```
