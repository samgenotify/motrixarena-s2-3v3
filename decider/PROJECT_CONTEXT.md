# MotrixArena S2 3v3足球赛 - 梦飞队 项目索引

## 基本信息
- 队名: 梦飞(#2), 1人队, 截止6月5日
- 项目: /opt/sim_soccer2, Conda环境: k1
- 只改 decider/ 目录

## GitHub
- 仓库: github.com/samgenotify/motrixarena-s2-3v3 (仅decider/)
- Token: /tmp/.gh_token
- 本地分支: team_mengfei
- push工作流: rsync decider/ → /tmp/mengfei-repo/ → commit+push

## 技术架构
- ZMQ REQ/REP tcp://127.0.0.1:5555
- 协议: {"cmd":[vx,vy,w],"id":N,"source":"梦飞"}
- ID: 0-6红队, 7-13蓝队, config.yaml team_id=12
- cmd_vel(vx,vy,vtheta) [-1,1]
- 步态: model_20000_new.onnx (AMP, 375obs→22act)
- 场地: M尺寸 14×9m, match_config当前7v7需改3v3
- 状态机库: transitions

## 关键文件 (decider/)
| 文件 | 行数 | 说明 |
|------|------|------|
| decider.py | 558 | Agent类, ZMQ sim, 10Hz调loop() |
| user_entry.py | 513 | 游戏逻辑入口, L419待改 |
| config.yaml | 199 | 所有可调参数 |
| interfaces/action.py | 140 | cmd_vel/kick/save, sim下kick未实现 |
| interfaces/vision.py | 488 | 球检测/自定位 |
| interfaces/sim_client.py | 93 | ZMQ客户端 |
| interfaces/gamecontroller.py | 259 | 比赛状态解析 |
| interfaces/communication.py | 55 | 多机器人数据共享 |
| logic/sub_statemachines/ | - | find_ball, chase_ball, dribble, go_back_to_field |
| logic/policy_statemachines/goalkeeper.py | 388 | 守门员4状态FSM |
| logic/strategy_statemachines/ | - | attack, defend_ball, dribble_ball, shoot_ball |
| strategy/team_manager.py | 216 | 角色分配+StrategyServer |

## 待办 (按优先级)
1. 实现3v3策略 — user_entry.py按ID分配前锋/后卫/守门员
2. 改match_config.json 从7v7→3v3 + spawn位置
3. 启动测试 (3红+3蓝decider实例)
4. 准备提交包: team_梦飞_日期/ (README + README_决策 + README_步态 + gait/ + decider/)
5. action.py sim模式kick实现

## 已知问题
- user_entry.py L419 当前调用 _gc_test_go_back_to_field, 需改为实际比赛逻辑
- action.py kick/head sim模式未实现(TODO)
- match_config.json 当前7v7配置
