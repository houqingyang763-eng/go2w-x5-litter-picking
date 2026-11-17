# Go2-W + X5 野外垃圾捡拾

宇树 **Go2-W 轮足机器人 + ARX X5 机械臂** 项目的工程仓库。目标场景是高速公路路侧等人工清理困难区域的垃圾捡拾，目前处于入组学习、资料核对和本机环境准备阶段。

本仓库用于部署记录、接口对接和小型验证，也为网页版 GPT 和不同聊天提供共同上下文。**当前没有机器人控制程序，也没有完成环境部署或真机验证。**

## 从哪里开始

| 文件 | 用途 |
| --- | --- |
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | 学习入口：整套系统如何组成、如何协作，三个方向分别解决什么问题 |
| [STATUS.md](STATUS.md) | 当前做到哪里、接下来做什么、哪些事项留到真机或需要服务器 |
| [docs/SETUP.md](docs/SETUP.md) | 本机环境现状、官方依赖线索和分阶段部署路线 |
| [docs/RESOURCES.md](docs/RESOURCES.md) | 官方资料入口及核验情况 |
| [WORKLOG.md](WORKLOG.md) | 按日期记录实际工作、验证结果和重要决定 |
| [AGENTS.md](AGENTS.md) | 本仓库内 AI 协作的简短约定 |

## 项目范围

2026-11-17 更新：个人准备优先探索 **视觉语义感知、地形可通行性估计与语义代价地图**，同时理解导航、感知、抓取三个模块的接口。近期先在本机跑通视觉 Demo，再研究并复现 WVN，随后探索地图融合与 ROS 2 接口；算法方案尚未定版。

机械臂上计划安装近距离抓取相机，导航/SLAM 传感器及板载计算设备配置仍待核实。Ubuntu 22.04 + ROS 2 Humble 是当前计划，尚未验证整套兼容性；WVN 官方现有机器人集成使用 ROS 1，需要单独评估复现环境和适配方式。

仓库以工程落地为主。需要真机才能解决的事项集中列入 [STATUS.md](STATUS.md)，留待统一上机；需要部署到服务器或连接服务器时，先向项目使用者说明。本轮仅同步新资料，没有执行部署或 Demo。

## 给网页版 GPT 的入口

公开仓库：<https://github.com/houqingyang763-eng/go2w-x5-litter-picking>

- [项目上下文原文](https://raw.githubusercontent.com/houqingyang763-eng/go2w-x5-litter-picking/main/PROJECT_CONTEXT.md)
- [当前状态原文](https://raw.githubusercontent.com/houqingyang763-eng/go2w-x5-litter-picking/main/STATUS.md)

可以这样开始新聊天：

> 请先读取这个仓库的 PROJECT_CONTEXT.md 和 STATUS.md，再根据我的问题解释。把已核实事实、设计建议和待确认事项分开；不要把未运行的方案说成实验结果。如果无法读取链接，请告诉我需要粘贴哪份文件。

## 如何维护

有实质进展时，在 `WORKLOG.md` 追加一条简短记录，并更新 `STATUS.md`。系统理解发生变化时才修改 `PROJECT_CONTEXT.md`。Git 保存代码和文档历史，无需另建复杂日志系统。大数据、模型、运行输出和本地配置留在 Git 之外。
