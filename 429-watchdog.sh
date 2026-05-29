#!/bin/bash
# 429 Recovery Watchdog
# 每5分钟由 cron 调用，检测仿真环境健康状况并自动恢复
# 用法: bash /opt/sim_soccer2/429-watchdog.sh

cd /opt/sim_soccer2
LOG="/opt/sim_soccer2/decider/logs/watchdog_$(date +%Y%m%d).log"
PYTHON=/home/7dhjogiy/miniconda3/envs/k1/bin/python
timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(timestamp)] Watchdog started" >> "$LOG"

# 1. 检查 sim engine 是否存活
SIM_PID=$(pgrep -f "sim2sim_runner.py" | head -1)
if [ -z "$SIM_PID" ]; then
    echo "[$(timestamp)] ERROR: sim2sim_runner.py not running!" >> "$LOG"
    echo "[$(timestamp)] Attempting restart..." >> "$LOG"
    # 重启 sim (需要 sim_manager)
    curl -s -X POST http://127.0.0.1:8000/sims/start \
      -H "Content-Type: application/json" \
      -d '{"team_size":3, "robot_type":"k1"}' >> "$LOG" 2>&1
    sleep 5
fi

# 2. 检查 decider 进程数量 (应为6个)
DECIDER_COUNT=$(pgrep -f "decider.py.*--simulation" | wc -l)
echo "[$(timestamp)] Active deciders: $DECIDER_COUNT" >> "$LOG"

if [ "$DECIDER_COUNT" -lt 6 ]; then
    echo "[$(timestamp)] WARNING: Only $DECIDER_COUNT/6 deciders running. Restarting..." >> "$LOG"
    pkill -f "decider.py.*--simulation" 2>/dev/null
    sleep 2
    rm -f /opt/sim_soccer2/decider/logs/sim_decider_*.log 2>/dev/null
    cd /opt/sim_soccer2/decider
    for color in red blue; do
      for id in 0 1 2; do
        nohup $PYTHON decider.py --color $color --id $id --simulation > /dev/null 2>&1 &
      done
    done
    echo "[$(timestamp)] Restarted 6 deciders" >> "$LOG"
fi

# 3. 检查 ZMQ 连通性 (尝试通信)
ZMQ_OK=$($PYTHON -c "
import zmq, json, time
try:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect('tcp://127.0.0.1:5555')
    sock.setsockopt(zmq.RCVTIMEO, 3000)
    sock.send_json({'cmd':[0,0,0],'id':99,'timestamp':time.time()})
    resp = sock.recv_json()
    robots = resp.get('state',{}).get('robots',[])
    print(f'OK: {len(robots)} robots visible')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1)
echo "[$(timestamp)] ZMQ: $ZMQ_OK" >> "$LOG"

# 4. 检查最新 decider 日志是否有错误
LATEST_LOG=$(ls -t /opt/sim_soccer2/decider/logs/sim_decider_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    ERROR_COUNT=$(grep -c "Error\|Traceback\|Exception" "$LATEST_LOG" 2>/dev/null || echo 0)
    echo "[$(timestamp)] Log errors: $ERROR_COUNT in $(basename $LATEST_LOG)" >> "$LOG"
    
    # 打印最后几条DBG日志
    DBG_LINES=$(grep "\[DBG\]" "$LATEST_LOG" 2>/dev/null | tail -6)
    if [ -n "$DBG_LINES" ]; then
        echo "[$(timestamp)] Latest debug:" >> "$LOG"
        echo "$DBG_LINES" >> "$LOG"
    fi
fi

echo "[$(timestamp)] Watchdog complete" >> "$LOG"
echo "---" >> "$LOG"
