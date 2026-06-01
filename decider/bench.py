#!/usr/bin/env python3
"""Quick benchmark: run N short tests and record max_x for each."""
import subprocess, time, re, os, sys, signal, glob

PORT_START = 5600
TESTS = 5
DURATION = 300  # 5 minutes each
SIM_CMD = "/home/7dhjogiy/miniconda3/envs/motrixsim0508/bin/python /opt/sim_soccer2/simulation/motrixsim/sim2sim_runner.py --robot-type k1 --team-size 3 --port {port} --policy-device gpu --no-webview --no-real-time --no-allow-keyboard-control --zmq --no-use-referee"
CTL_CMD = "/home/7dhjogiy/miniconda3/envs/k1/bin/python multi_controller.py --port {port} --hz 50 --zmq-hz 50"

results = []

for i in range(TESTS):
    port = PORT_START + i * 2
    print(f"\n=== Test {i+1}/{TESTS} (port {port}) ===")
    
    # Clean up any previous processes
    subprocess.run("kill -9 $(ps aux | grep 'sim2sim_runner.py' | grep python | grep -v grep | awk '{print $2}') 2>/dev/null", shell=True)
    subprocess.run("pgrep -f 'multi_controller.py' | xargs kill -9 2>/dev/null", shell=True)
    time.sleep(3)
    
    # Start sim
    sim = subprocess.Popen(SIM_CMD.format(port=port), shell=True, 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(15)  # wait for sim init
    
    # Find log directory and clean old logs
    log_dir = "/opt/sim_soccer2/decider/logs"
    old_logs = set(glob.glob(os.path.join(log_dir, "mc_*.log")))
    
    # Start controller
    ctl = subprocess.Popen(CTL_CMD.format(port=port), shell=True, cwd="/opt/sim_soccer2/decider",
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for test duration
    time.sleep(DURATION)
    
    # Find new log file
    new_logs = set(glob.glob(os.path.join(log_dir, "mc_*.log"))) - old_logs
    if not new_logs:
        # Fallback: get most recent
        new_logs = {max(glob.glob(os.path.join(log_dir, "mc_*.log")), key=os.path.getmtime)}
    
    log_file = list(new_logs)[0] if new_logs else None
    max_x = 0.0
    ball_y_range = [0, 0]
    
    if log_file and os.path.exists(log_file):
        with open(log_file) as f:
            content = f.read()
        # Find max_x
        mx_matches = re.findall(r'max_x=([\d.-]+)', content)
        if mx_matches:
            max_x = max(float(x) for x in mx_matches)
        # Find ball y range
        by_matches = re.findall(r'B\(-?[\d.]+,(-?[\d.]+)\)', content)
        if by_matches:
            bys = [float(y) for y in by_matches]
            ball_y_range = [min(bys), max(bys)]
    
    results.append(max_x)
    print(f"  max_x={max_x:.2f}, ball_y=[{ball_y_range[0]:.2f}, {ball_y_range[1]:.2f}]")
    
    # Kill processes
    sim.kill(); ctl.kill()
    sim.wait(); ctl.wait()

# Summary
print(f"\n{'='*50}")
print(f"RESULTS: {TESTS} tests x {DURATION}s each")
for i, mx in enumerate(results):
    print(f"  Test {i+1}: max_x={mx:.2f}")
print(f"  AVERAGE: max_x={sum(results)/len(results):.2f}")
print(f"  BEST:    max_x={max(results):.2f}")
print(f"  WORST:   max_x={min(results):.2f}")
above_3 = sum(1 for x in results if x > 3.0)
above_4 = sum(1 for x in results if x > 4.0)
print(f"  x>3.0: {above_3}/{TESTS} ({100*above_3/TESTS:.0f}%)")
print(f"  x>4.0: {above_4}/{TESTS} ({100*above_4/TESTS:.0f}%)")
