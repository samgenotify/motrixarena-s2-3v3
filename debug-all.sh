#!/bin/bash
# 一键调试脚本 — 合并所有检查为一次执行，减少 tool call 次数
# 用法: bash /opt/sim_soccer2/debug-all.sh
# 输出: 一次返回所有状态信息

cd /opt/sim_soccer2
PYTHON=/home/7dhjogiy/miniconda3/envs/k1/bin/python

echo "============================================"
echo "  MotrixArena S2 3v3 综合调试报告"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

# 1. 进程状态
echo ""
echo "=== 进程状态 ==="
echo "Sim Manager: $(pgrep -f 'sim_manager.py' | head -1 || echo 'NOT RUNNING')"
echo "Sim Engine:  $(pgrep -f 'sim2sim_runner.py' | head -1 || echo 'NOT RUNNING')"
DECIDER_PIDS=$(pgrep -f "decider.py.*--simulation")
DECIDER_COUNT=$(echo "$DECIDER_PIDS" | grep -c . 2>/dev/null || echo 0)
echo "Deciders:    $DECIDER_COUNT/6 (PIDs: $(echo $DECIDER_PIDS | tr '\n' ' '))"

# 2. ZMQ 状态 (机器人位置)
echo ""
echo "=== ZMQ 机器人状态 ==="
$PYTHON -c "
import zmq, json, time
try:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect('tcp://127.0.0.1:5555')
    sock.setsockopt(zmq.RCVTIMEO, 5000)
    sock.send_json({'cmd':[0,0,0],'id':99,'timestamp':time.time()})
    resp = sock.recv_json()
    state = resp.get('state',{})
    robots = state.get('robots',[])
    ball = state.get('ball',{})
    print(f'Ball: x={ball[\"x\"]:.3f}, y={ball[\"y\"]:.3f}, z={ball[\"z\"]:.3f}')
    for r in robots:
        print(f'  {r[\"name\"]}(id={r[\"id\"]}): x={r[\"x\"]:+.2f}, y={r[\"y\"]:+.2f}, θ={r[\"theta\"]:+.2f}')
except Exception as e:
    print(f'ZMQ ERROR: {e}')
" 2>&1

# 3. 最新日志分析
echo ""
echo "=== 最新 Decider 日志 ==="
LATEST_LOG=$(ls -t /opt/sim_soccer2/decider/logs/sim_decider_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    LINES=$(wc -l < "$LATEST_LOG")
    ERRORS=$(grep -c "Error\|Traceback" "$LATEST_LOG" 2>/dev/null || echo 0)
    WARNINGS=$(grep -c "WARNING" "$LATEST_LOG" 2>/dev/null || echo 0)
    echo "文件: $(basename $LATEST_LOG) ($LINES 行)"
    echo "错误: $ERRORS, 警告: $WARNINGS"
    
    echo ""
    echo "--- Final Robot IDs ---"
    grep "Final Robot ID" "$LATEST_LOG" | sort -u
    
    echo ""
    echo "--- Role Assignments ---"
    grep "UserEntry.*Role=" "$LATEST_LOG" | sort -u
    
    echo ""
    echo "--- FSM State Distribution ---"
    grep "Current state:" "$LATEST_LOG" | sort | uniq -c | sort -rn
    
    echo ""
    echo "--- Debug Lines (last 12) ---"
    grep "\[DBG\]" "$LATEST_LOG" | tail -12
    
    echo ""
    echo "--- Recent Errors (last 5) ---"
    grep -i "error\|exception\|traceback" "$LATEST_LOG" | grep -v "Obstacle avoidance" | tail -5
else
    echo "没有找到日志文件"
fi

# 4. 配置验证
echo ""
echo "=== 配置验证 ==="
$PYTHON -c "
import json, yaml
# match_config (isaac_sim)
with open('simulation/isaac_sim/config/match_config.json') as f:
    mc = json.load(f)
rc = mc['teams']['red']['count']
bc = mc['teams']['blue']['count']
fp = mc['field']['preset']
print(f'match_config: {rc}v{bc}, field={fp}, blue_offset=+{rc}')

# config.yaml
with open('decider/config.yaml') as f:
    cfg = yaml.safe_load(f)
league = cfg.get('league', '?')
sim_hz = cfg.get('sim_hz', '?')
chase = cfg.get('chase', {}).get('default_chase_distance', '?')
print(f'config.yaml: league={league}, sim_hz={sim_hz}, chase_dist={chase}')
" 2>&1

echo ""
echo "============================================"
echo "  报告结束"
echo "============================================"
