# README_决策.md — 决策端交付说明

## 队伍信息

- **队伍名称**: 梦飞 (mengfei)
- **队伍ID**: 12
- **联系人**: （填入队长姓名 + 联系方式）
- **版本**: v32 (2026-06-06)
- **基线 commit**: 基于 `team_mengfei` 分支 `22ce7fb`

## 入口与启动

### 单机器人启动模式（官方推荐）

```bash
cd /opt/sim_soccer2
conda activate k1

# 必须设置环境变量（让 sim_client 找到 zmq_wrapper）
export MOS_BRAIN_MUJOCO_COMMON_PATH=/opt/sim_soccer2/legged_gym/sim_soccer2/simulation/isaac_sim/src/common

# 红队三台机器人，分别在三个终端启动：
python decider/decider.py --simulation --ip 127.0.0.1 --port 5555 --color red --id 0   # Forward
python decider/decider.py --simulation --ip 127.0.0.1 --port 5555 --color red --id 1   # Defender
python decider/decider.py --simulation --ip 127.0.0.1 --port 5555 --color red --id 2   # Goalkeeper

# 蓝队三台：
python decider/decider.py --simulation --ip 127.0.0.1 --port 5555 --color blue --id 0
python decider/decider.py --simulation --ip 127.0.0.1 --port 5555 --color blue --id 1
python decider/decider.py --simulation --ip 127.0.0.1 --port 5555 --color blue --id 2
```

`--color blue --id N` 会自动加上 `red_count`（默认 3）的偏移，得到正确的全局 robot_id。

### 一键启动

```bash
./decider/scripts/start_team.sh                 # 默认 3v3
./decider/scripts/start_team.sh --red 3 --blue 3 # 显式指定
```

## 角色分配（按 local id）

| local_id | 角色 | 主要职责 | 初始位置 |
|----------|------|---------|---------|
| 0 | Forward (FWD) | 追球、运球、射门 | (-1.0, 0.0) |
| 1 | Defender (DEF) | 防守、拦截、推球 | (-2.5, 0.0) |
| 2 | Goalkeeper (GK) | 守门、扑救 | (-4.2, 0.0) 门线 |

## ZMQ 报文格式

```json
{"cmd": [vx, vy, vw], "id": <robot_id>, "timestamp": <float>, "source": "mengfei"}
```

- `cmd`: 机器人本体坐标系下速度（vx 前进、vy 左移、vw 逆时针），数值已在 config.yaml 限幅
- `id`: 0..2 红队，3..5 蓝队（自动偏移）
- `source`: 固定 "mengfei"

## config.yaml 关键字段

| 字段 | 默认值 | 比赛现场说明 |
|------|--------|-------------|
| `server_ip` | `"127.0.0.1"` | **由赛事方统一分配，本地调试用 127.0.0.1** |
| `server_port` | `5555` | **由赛事方统一分配** |
| `auto_find_server_ip_token` | (注释) | **比赛时取消注释并填入赛事方提供的 token** |
| `team_id` | `12` | 梦飞队 ID |
| `color` | `"red"` | 由 `--color` 参数覆盖 |
| `league` | `"S"` | 3v3 使用 S 级（9×6m 球场） |
| `sim_hz` | `50.0` | 控制频率 |

## v32 新增规则合规功能（仅在裁判模式下激活）

无裁判模式行为与 v25 冠军版本完全一致。

| 功能 | 阈值 | 规则上限 | 触发动作 |
|------|------|---------|---------|
| 持球规避 (Field) | 4.5s | 5s | 后退绕球 |
| 持球规避 (GK) | 9.0s | 10s | 退回门线 |
| 球卡住规避 | 8.0s | 10s | 远离球 |
| 边界回归 | ±0.5m margin | 离场 5s | 回到场内 |
| Initial/Ready 阶段 | - | - | 移到角色 home 位 |
| Set 阶段 | - | 必须静止 | 发送 cmd=(0,0,0) |
| Finished 阶段 | - | - | 停止 |

### 定位球站位（Set Play）

- **KICK_OFF**: 开球方按 KICKOFF_POSITIONS 站位，防守方按 WALL_POSITIONS
- **KICK_IN**: 我方 FWD 移向球；其他人回 home
- **CORNER_KICK**: 我方 FWD 移向角球区；DEF/GK 缩后
- **GOAL_KICK**: 我方 DEF 罚球；FWD 前压
- **FREE_KICK**: 我方 FWD 主罚；其他人组墙

## 环境前提

```bash
# Python 环境（必装）
conda create -n k1 python=3.8 -y
conda activate k1
pip install -r decider/requirements.txt

# 环境变量（必设）
export MOS_BRAIN_MUJOCO_COMMON_PATH=<sim_soccer2>/legged_gym/sim_soccer2/simulation/isaac_sim/src/common
```

## 文件清单

```
decider/
├── decider.py             # 入口（SimAgent + Agent）
├── user_entry.py          # v32 策略（角色 + 状态机 + 规则合规）
├── config.yaml            # 队伍配置（本地默认 127.0.0.1:5555）
├── requirements.txt       # numpy, PyYAML, transitions, pyzmq
├── interfaces/            # ZMQ/Action/Vision/GameController/Communication
│   ├── action.py
│   ├── communication.py
│   ├── gamecontroller.py
│   ├── sim_client.py
│   └── vision.py
├── logic/                 # 状态机实现
│   ├── policy_statemachines/
│   │   └── goalkeeper.py
│   ├── sub_statemachines/
│   │   ├── chase_ball.py
│   │   ├── dribble.py
│   │   ├── find_ball.py
│   │   ├── go_back_to_field.py
│   │   └── kick.py
│   └── strategy_statemachines/
└── scripts/
    └── start_team.sh      # 一键启动脚本
```

## 联调步骤

1. 启动 Sim Manager（赛事方提供）
2. 创建仿真实例（team_size=3, robot_type=k1, use_referee=true）
3. 在 3 个终端分别启动 3 个 decider（红队 --color red --id 0/1/2）
4. 在另外 3 个终端启动蓝队（或由对手启动）
5. 通过 Sim Manager 网页观察状态，确认 robots 数量 = 6
6. 启动比赛（裁判系统自动推进状态机）
