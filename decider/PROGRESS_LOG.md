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
   - GC fallback: 无裁判时直接进入 PLAYING
4. **Blue team offset bug 排查** — decider 读 isaac_sim match_config, count 必须保持 7

---

## 2026-05-31 Session 3 — v16 智能策略 & v17 优化

### v16 — 首个进球版本
- 动态角色分配：离球最近→FWD，次近→DEF，lid=2→GK
- 前锋三档追球：远(>2.5m)→中(0.8-2.5m)→近(<0.8m)
- ZMQ 50Hz 稳定，球到达 x=5.40（超过蓝队球门线 4.5）

### v17 — 系统性优化
- GK 站位：ogx+1.0 → ogx+0.5（球门线前 0.5m）
- 前锋 y 修正：y_bias = -0.5*by（比例修正，球越偏修正越强）
- walk_towards vw 增益：2.5 → 3.0
- DEF 追球距离：1.0m → 1.5m，站位 60% 插值
- ball_max_x 追踪

### v17.1 测试结果（10分钟长时）
- ✅ **进球！** max_x=5.46，球多次到达 x>5.0
- ✅ 进球时球 y=1.0-1.1（球门口内）
- ✅ ZMQ 完美：26198 ticks, ec=0
- ✅ GK 深度：x=-3.5~-3.9
- ⚠️ 球 y 方向仍有偏移（-3.4~-3.7）

### 当前运行状态
- Sim engine: sim2sim_runner.py, team-size=3, ZMQ port 5555, --no-webview --no-real-time
- Controller: multi_controller.py v17.1, 50Hz strategy + 50Hz ZMQ
- 6 robots: red(0,1,2) + blue(7,8,9)
