# 官方资源与核验记录

核验日期：2026-11-11。下表区分“入口已找到”和“内容已读”，避免把网页链接当作已经确认的接口说明。本仓库不复制厂商 SDK、账号信息或交付资料。

## 1. 宇树 Go2-W

| 资源 | 用途 | 本次核验情况 |
| --- | --- | --- |
| [宇树官网](https://www.unitree.com/cn/) | 产品入口 | 用户提供的官方入口 |
| [Go2-W 开发文档](https://support.unitree.com/home/zh/Go2-W_developer/about_Go2-W) | 型号对应的开发说明 | 页面可定位，但本次抓取无可读正文；尚未逐节核实 |
| [Go2-W 例程参考](https://support.unitree.com/home/zh/Go2-W_developer/Case_reference) | 厂商例程索引 | 本次网页工具访问失败，保留入口 |
| [Go2-W SDK 获取页](https://support.unitree.com/home/zh/Go2-W_developer/Obtain_SDK) | SDK、模型等下载入口 | 本次抓取无可读正文，不能据此确认具体文件或版本 |
| [Go2-W 帮助资料](https://serviceconsole.unitree.com/#/help/031201) | 产品与售后资料 | 动态页面无可读正文，待人工查看 |
| [板卡信息帮助页](https://serviceconsole.unitree.com/#/help/031202) | 上机时查交付配置 | 动态页面无可读正文；本仓库只保留入口，不记录登录信息 |
| [unitree_sdk2](https://github.com/unitreerobotics/unitree_sdk2) | 厂商 C++ 通信与控制 SDK | 已读 README 并检查 Go2-W 例程目录 |
| [unitree_ros2](https://github.com/unitreerobotics/unitree_ros2) | ROS 2 消息、通信配置与例程 | 已读 README；不能直接视为交付机器的已验证驱动 |

### 已核实的开发线索

- `unitree_sdk2` 实际包含 [example/go2w](https://github.com/unitreerobotics/unitree_sdk2/tree/main/example/go2w)，可优先研究 Go2-W 对应的运动服务与站立例程。目录存在说明有型号相关示例，不等于它们已在本项目机器上验证。
- SDK2 README 的预构建环境为 Ubuntu 20.04、aarch64 / x86_64、GCC 9.4.0；这是该 SDK 的说明，不能自动推导出整套项目应采用 Ubuntu 20.04。
- `unitree_ros2` README 明确列出的系统组合为 Ubuntu 20.04 / Foxy、Ubuntu 22.04 / Humble，并推荐后者；介绍中列的是 Go2、B2、H1。Go2-W 所需分支、消息和固件适配仍需核对。
- `unitree_ros2` 提供使用本机回环接口的本地配置。这有利于无真机学习与编译，但尚未在本机执行。
- 普通 Go2 的示例可用于理解通信方式；不能默认其中的运动模式、低层电机布局、限制参数适用于 Go2-W。

## 2. ARX X5 机械臂

| 资源 | 用途 | 本次核验情况 |
| --- | --- | --- |
| [ARX 官网](https://www.arx-x.com/) | 厂商入口 | 已打开，官网链接指向 ARXroboticsX 开源组织 |
| [X5 SDK 仓库](https://github.com/ARXroboticsX/X5) | 用户所获交付资源入口 | 已读实际文件 `readme.md`，并检查部分构建、测试代码 |
| [X5 说明](https://github.com/ARXroboticsX/X5/blob/master/readme.md) | 型号、CAN、Python 接口 | 明确区分 X5 2023 与 X5 2025，夹爪控制范围不同 |
| [运动学示例](https://github.com/ARXroboticsX/X5/blob/master/py/arx_x5_python/test_kinematic_solver.py) | 正/逆运动学调用入口 | 已读；存在 `forward_kinematics` 和 `inverse_kinematics` 示例，未运行 |
| [构建文件](https://github.com/ARXroboticsX/X5/blob/master/py/arx_x5_python/bimanual/CMakeLists.txt) | Python 绑定与二进制依赖 | 已读；使用 CMake、pybind11、厂商 `.so` / `.a` 库，包含架构分支 |

### 对本项目有用的结论

- 该入口是 **Python SDK**。本次查阅的 README 未给出明确的 Ubuntu / Python / ROS / ROS 2 版本兼容矩阵，不应凭项目名称直接安装某个 ROS 驱动。
- SDK 已暴露末端位姿控制、关节控制、夹爪控制、状态读取，以及独立的运动学求解入口。机械臂方向应先验证这些接口的单位、坐标系、型号参数与返回行为，再决定是否需要另写逆运动学。
- 找到逆运动学入口，只能证明已有求解接口；不代表已具备避障、轨迹规划、抓取点选择或可达性保证。
- 实物只有“X5”这一名称还不够，需要确认 2023 / 2025 等具体版本、夹爪、CAN 适配器和交付代码版本。示例里的默认型号不能直接套用。
- CAN 配置依赖实体设备；安装脚本包含系统级设置。本次只阅读，不运行厂商安装、CAN 或机械臂示例。

## 3. 本次读取对应的上游版本

后续部署应固定实际采用的提交；以下仅用于追溯本次资料核对，并非本项目已选定依赖。

| 仓库 | 本次读取分支 | 核验时分支提交 |
| --- | --- | --- |
| `unitreerobotics/unitree_sdk2` | `main` | `aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1` |
| `unitreerobotics/unitree_ros2` | `master` | `668d1ec5a05d1c38d3306bdca7d59f2ba3581a88` |
| `ARXroboticsX/X5` | `master` | `9a255e38156e3f5a263f341df209ab028d49dad9` |

遇到网页不可读时，应先查看原始官方页面或向交付方确认。不能把抓取失败解释为设备不支持某项功能，也不能用其他型号文档补成“已确认”。
