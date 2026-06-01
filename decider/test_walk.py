#!/usr/bin/env python3
"""
Test: all robots just walk forward (vx=1, vy=0, vw=0)
to understand k1 physical behavior
"""
import sys, os, math, time, json, argparse, threading
import zmq
import logging
from datetime import datetime

HALF_LENGTH = 4.5
HALF_WIDTH = 3.0
BLUE_OFFSET = 7

log = logging.getLogger("TEST")
log.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_ch = logging.StreamHandler(sys.stdout); _ch.setFormatter(_fmt); log.addHandler(_ch)

def _norm(a):
    return (a + math.pi) % (2 * math.pi) - math.pi

class ZMQComm(threading.Thread):
    def __init__(self, port, zmq_hz=50):
        super().__init__(daemon=True)
        self.port = port; self.zmq_hz = zmq_hz
        self.running = True; self.lock = threading.Lock()
        self.state_data = None; self.state_ts = 0.0
        self.send_count = 0; self.err_count = 0

    def get_state(self):
        with self.lock: return self.state_data, self.state_ts

    def _connect(self):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.REQ)
        self.sock.setsockopt(zmq.RCVTIMEO, 5000)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(f"tcp://127.0.0.1:{self.port}")

    def run(self):
        self._connect()
        period = 1.0 / self.zmq_hz
        while self.running:
            try:
                t0 = time.perf_counter()
                # Send commands for all 6 robots
                cmds = []
                for i in range(3):
                    cmds.append({"cmd": [1.0, 0.0, 0.0], "id": i, "timestamp": time.time()})
                for i in range(3):
                    cmds.append({"cmd": [1.0, 0.0, 0.0], "id": BLUE_OFFSET + i, "timestamp": time.time()})
                self.sock.send_json({"commands": cmds, "timestamp": time.time()})
                raw = self.sock.recv_string()
                resp = json.loads(raw)
                with self.lock:
                    self.state_data = resp.get("state")
                    self.state_ts = time.time()
                self.send_count += 1
                el = time.perf_counter() - t0
                s = period - el
                if s > 0: time.sleep(s)
            except Exception as e:
                self.err_count += 1
                log.error(f"Error: {e}")
                time.sleep(0.5)
                try: self.sock.close()
                except: pass
                try: self.ctx.term()
                except: pass
                self._connect()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5563)
    args = parser.parse_args()
    
    comm = ZMQComm(args.port)
    comm.start()
    
    log.info("Test: all robots vx=1 vy=0 vw=0")
    tick = 0
    ball_trace = []
    
    while tick < 2000:  # ~40 seconds
        state, ts = comm.get_state()
        if state:
            rd = state.get("robots", [])
            bl = state.get("ball", {})
            bx, by = bl.get("x", 0), bl.get("y", 0)
            
            rm = {r.get("name", ""): r for r in rd}
            
            if tick % 100 == 0:
                parts = [f"B({bx:.2f},{by:.2f})"]
                for name in ["robot_rp0", "robot_rp1", "robot_rp2"]:
                    d = rm.get(name, {})
                    if d:
                        parts.append(f"{name}@({d['x']:.1f},{d['y']:.1f})θ={math.degrees(d['theta']):.0f}°")
                log.info(f"[T{tick}] sc={comm.send_count} ec={comm.err_count} | " + " | ".join(parts))
            
            ball_trace.append((bx, by))
        
        tick += 1
        time.sleep(0.02)
    
    comm.running = False
    comm.join(timeout=2)
    
    # Summary
    log.info(f"Ball trace: start=({ball_trace[0][0]:.2f},{ball_trace[0][1]:.2f}) "
             f"end=({ball_trace[-1][0]:.2f},{ball_trace[-1][1]:.2f})")
    max_x = max(b[0] for b in ball_trace)
    min_x = min(b[0] for b in ball_trace)
    log.info(f"Ball x range: [{min_x:.2f}, {max_x:.2f}]")

if __name__ == "__main__":
    main()
