# 梦飞队(#2) MotrixArena S2 3v3 开发日志

> 索引文件，每次调试进展在此追加记录。
> 详细项目架构见 [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md)

---

## 2026-05-29 Session 1 — 3v3 配置改造 & 首次启动调试

### 完成事项
1. **match_config.json 3v3 改造**
   - `simulation/motrixsim/assets/config/match_config.json` — 7v7→3v3 ✅
   - `simulation/isaac_sim/config/match_config.json` — 7v7→3v3 ✅ (decider 实际读取此文件)
   - red: 3 机器人, blue: 3 机器人, field preset: S (9x6m)
2. **config.yaml 联赛改 S** — `league: "M"` → `"S"`
3. **user_entry.py 完整重写** — 3v3 策略：
   - 角色分配: id0=Forward(前锋), id1=Defender(后卫), id2=Goalkeeper(守门员)
   - GC fallback: 无裁判时直接进入 PLAYING，不再卡 INITIAL
   - Forward: 追球→旋转对准→前进踢球
   - Defender: 防守位置→追球→回防
   - Goalkeeper: 球门线巡逻→扑球
4. **Blue team offset bug 排查**
   - 初始误判: 以为 decider.py +7 offset 错误
   - 实际发现: decider 读的是 `isaac_sim/config/match_config.json`，不是 `motrixsim` 下的
   - 该文件仍为 count=7，导致 blue offset=7（蓝队发到不存在的 robot ID 7,8,9）
   - **修复**: isaac_sim match_config 也改为 3v3 → offset 自动变 +3

### 待验证
- [x] 重启 decider 后 blue team 是否正常通信 ✅ 6/6
- [x] 6 个 decider 是否都有日志输出 ✅ 
- [x] 机器人能否站立行走 ✅ 位置持续变化
- [x] Forward 是否追球 ✅ FSM forward/arrived
- [ ] 机器人能否有效推球前进（球移动极慢）
- [ ] GK 是否回到球门线（目前 GK 在场中央游荡）
- [ ] kick 在 sim 模式下是否生效（action.py 是 TODO stub）
- [ ] 球能否被推入球门得分

### 已修复 Bug
1. **isaac_sim match_config** — decider 读的是此文件而非 motrixsim 下的。必须保持 count=7（因 sim 内部 MAX_ROBOTS_PER_TEAM=7，blue offset=+7 是正确的）
2. **--sim 参数歧义** — decider.py 不接受 --sim，必须用 --simulation 全称
3. **numpy array truth value** — `if my_pos:` 对 numpy array 报错，改为 `if my_pos is not None:`
4. **Forward 到达球后不推球** — chase_ball FSM 的 arrived 状态只停止。修改 _role_forward 在球距 < chase_dist 时直接调 _dribble_towards_goal() 而不再调 chase_ball FSM

### 关键文件变更
| 文件 | 变更 |
|------|------|
| `simulation/isaac_sim/config/match_config.json` | 7v7→3v3 |
| `simulation/motrixsim/assets/config/match_config.json` | 7v7→3v3 |
| `decider/config.yaml` | league M→S |
| `decider/user_entry.py` | 完整重写 3v3 策略 |

### 当前运行状态
- Sim Manager: FastAPI :8000
- Sim engine: sim2sim_runner.py, team-size=3, ZMQ port 5555
- 6 decider: red(0,1,2) + blue(0,1,2)
