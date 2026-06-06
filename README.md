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
- `gait/` — 步态模型
  - `k1_amp_20000.onnx` — K1 AMP 步态策略 ONNX 模型

## ZMQ协议
```json
{"cmd": [vx, vy, w], "id": 0, "timestamp": 0, "source": "梦飞"}
```
- id: 0-6 红队, 7-13 蓝队
- cmd: 机器人坐标系速度 [-1.0, 1.0]

## 版本历史
- v32-official: 官方提交规范合规版 (初始)
- v32-official-fix1: 官方提交规范合规版修复版
  - 修复 user_entry.py 开球位置索引 bug (KICKOFF_POSITIONS_RED[we_kick][role] → [role])
  - requirements.txt 补充 matplotlib 依赖
- v32-official-fix2: 官方提交规范合规版修复版2
  - 修复 strategy/team_manager.py:20 ImportError (StateMachine → AttackStateMachine)
  - README_步态.md 补充 ONNX 模型 SHA256 校验值
