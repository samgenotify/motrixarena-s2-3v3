# 梦飞队 - MotrixArena S2 仿真3v3足球赛

- 队伍: 梦飞 (序号2)
- 比赛: MotrixArena S2 仿真3v3足球赛
- 人数: 1人

## 代码说明
- `decider/` — 决策端代码 (可修改部分)
  - `user_entry.py` — 游戏逻辑入口
  - `config.yaml` — 参数配置
  - `logic/` — 状态机 (find_ball, chase_ball, dribble, goalkeeper)
  - `interfaces/` — ZMQ通信、视觉、动作接口

## ZMQ协议
```json
{"cmd": [vx, vy, w], "id": 0, "timestamp": 0, "source": "梦飞"}
```
- id: 0-6 红队, 7-13 蓝队
- cmd: 机器人坐标系速度 [-1.0, 1.0]
