#!/usr/bin/env python3
"""
multi_controller.py — v25: Smarter sideline recovery + faster heading correction
Based on v17+1s (proven baseline, avg max_x=1.64 in 10min tests)
Changes:
  1. walk_towards: vw gain 3.0→4.0 for faster heading correction
  2. TILT_LIMIT 70°→60°: recover from tilt faster, less time frozen
  3. FWD sideline recovery: when ball near sideline + opponent half,
     position behind ball on sideline side before pushing
  4. DEF unchanged from v17 (proven to work)
"""

import sys, os, math, time, json, argparse, threading
import numpy as np
import zmq
import logging
from datetime import datetime

# --- Constants ---
HALF_LENGTH = 4.5
HALF_WIDTH = 3.0
GOAL_WIDTH = 1.9
GOAL_HALF = GOAL_WIDTH / 2.0
BLUE_OFFSET = 7

ROLE_FWD, ROLE_DEF, ROLE_GK = 0, 1, 2
TILT_LIMIT = math.radians(60)  # v25: reduced from 70°

# Logging
log = logging.getLogger("MC")
log.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_ch = logging.StreamHandler(sys.stdout); _ch.setFormatter(_fmt); log.addHandler(_ch)
try:
    _ld = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(_ld, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(_ld, f"mc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"))
    _fh.setFormatter(_fmt); log.addHandler(_fh)
except: pass

def _norm(a):
    return (a + math.pi) % (2 * math.pi) - math.pi

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

# --- Robot State ---
class RS:
    __slots__ = ['id','name','team','lid','fixed_role','role',
                 'x','y','th','vx','vy','vw',
                 'bd','bf','bl','bs','bmx','bmy']
    def __init__(self, rid, team, lid, fixed_role):
        self.id = rid; self.team = team; self.lid = lid
        self.fixed_role = fixed_role; self.role = fixed_role
        self.name = f"robot_{'bp' if team=='blue' else 'rp'}{lid}"
        self.x = self.y = self.th = 0.0
        self.vx = self.vy = self.vw = 0.0
        self.bd = 1e6; self.bf = self.bl = 0.0
        self.bs = False; self.bmx = self.bmy = 0.0

# --- Motion Primitives ---
def stabilize_if_tilted(rs):
    """Rotation-only recovery when severely tilted."""
    if abs(rs.th) > TILT_LIMIT:
        rs.vx = 0.0; rs.vy = 0.0
        rs.vw = _clamp(-2.0 * rs.th, -1.0, 1.0)
        return True
    return False

def return_to_field(rs):
    """Override if robot is outside field bounds."""
    margin = 0.5
    if abs(rs.x) > HALF_LENGTH + margin or abs(rs.y) > HALF_WIDTH + margin:
        move_to(rs, 0.0, 0.0, speed=0.8)
        return True
    return False

def walk_towards(rs, world_angle, speed=0.8):
    """Walk towards a world-frame direction with body-frame commands."""
    ad = _norm(world_angle - rs.th)
    fwd_factor = max(0.0, math.cos(ad))
    rs.vx = _clamp(speed * fwd_factor, 0.0, 1.0)
    rs.vy = _clamp(0.5 * math.sin(ad), -0.3, 0.3)
    # v25: higher vw gain for faster heading correction
    rs.vw = _clamp(4.0 * ad, -2.0, 2.0)

def move_to(rs, tx, ty, speed=0.8):
    """Move to target (world frame), clamped to field bounds."""
    tx = _clamp(tx, -HALF_LENGTH - 0.3, HALF_LENGTH + 0.3)
    ty = _clamp(ty, -HALF_WIDTH - 0.3, HALF_WIDTH + 0.3)
    dx, dy = tx - rs.x, ty - rs.y
    d = math.hypot(dx, dy)
    if d < 0.08:
        rs.vx = rs.vy = rs.vw = 0.0
        return
    ta = math.atan2(dy, dx)
    spd = min(1.0, max(0.3, speed * min(d, 2.0)))
    walk_towards(rs, ta, spd)

# --- Role Behaviors ---
def do_forward(rs, gx):
    """Forward: chase ball, smart sideline recovery, push toward goal."""
    if not rs.bs:
        move_to(rs, 1.0, 0.0)
        return

    bx, by = rs.bmx, rs.bmy
    bd = rs.bd

    # Goal direction from ball
    dx_g = gx - bx
    dy_g = 0.0 - by
    d_g = math.hypot(dx_g, dy_g)
    if d_g < 0.01: d_g = 0.01
    gdx, gdy = dx_g / d_g, dy_g / d_g

    # Y-bias: pull towards y=0 when ball drifts
    y_bias = 0.0
    if abs(by) > 1.0:
        y_bias = -0.5 * by

    # v27: sideline recovery — when ball near sideline in any positive x
    near_sideline = abs(by) > 2.0 and bx > 0.0

    if near_sideline and bd > 0.5:
        # Phase 1: position BEHIND ball on the sideline side
        # Use smaller offset for quicker repositioning
        behind_x = bx - 0.5
        behind_y = by + 0.3 * (1.0 if by > 0 else -1.0)
        # Clamp to field
        behind_y = _clamp(behind_y, -HALF_WIDTH + 0.3, HALF_WIDTH - 0.3)
        move_to(rs, behind_x, behind_y, speed=0.9)
    elif bd < 0.8:
        # CLOSE: push ball through towards goal
        target_x = bx + gdx * 0.5
        target_y = by + gdy * 0.5 + y_bias
        ta = math.atan2(target_y - rs.y, target_x - rs.x)
        walk_towards(rs, ta, speed=1.0)
    elif bd < 2.5:
        # MEDIUM: approach from behind ball
        apx = bx - gdx * 0.5
        apy = by - gdy * 0.5
        ta = math.atan2(apy - rs.y, apx - rs.x)
        spd = min(1.0, max(0.5, bd * 0.6))
        walk_towards(rs, ta, spd)
    else:
        # FAR: direct chase
        move_to(rs, bx, by, speed=0.9)

def do_defender(rs, ogx):
    """Defender: position between ball and own goal, chase if close."""
    if not rs.bs:
        def_x = ogx + (2.0 if ogx < 0 else -2.0)
        move_to(rs, def_x, 0.0, speed=0.6)
        return

    bx, by = rs.bmx, rs.bmy
    bd = rs.bd

    if bd < 1.5:
        move_to(rs, bx, by, speed=1.0)
        return

    # v27: if ball near sideline, help center it
    if abs(rs.bmy) > 2.5 and bd < 3.0:
        # Move to behind ball on sideline side to help push toward center
        center_x = bx - 0.5 * (1.0 if ogx < 0 else -1.0)
        center_y = by + 0.3 * (1.0 if by > 0 else -1.0)
        move_to(rs, center_x, center_y, speed=0.8)
        return

    # Defensive position: 60% between ball and own goal
    def_x = bx + (ogx - bx) * 0.6
    def_y = by * 0.4

    if ogx < 0:
        def_x = _clamp(def_x, -HALF_LENGTH + 0.3, 1.0)
    else:
        def_x = _clamp(def_x, -1.0, HALF_LENGTH - 0.3)
    def_y = _clamp(def_y, -HALF_WIDTH + 0.3, HALF_WIDTH - 0.3)

    move_to(rs, def_x, def_y, speed=0.7)

def do_goalkeeper(rs, ogx):
    """Goalkeeper: deep on goal line, track ball Y."""
    gk_base_x = ogx + (0.5 if ogx < 0 else -0.5)
    if not rs.bs:
        move_to(rs, gk_base_x, 0.0, speed=0.5)
        return
    bx, by = rs.bmx, rs.bmy
    bd = rs.bd
    ball_goal_dist = abs(bx - ogx)
    if ball_goal_dist < 2.5 and bd < 1.5:
        move_to(rs, bx, by, speed=1.0)
    else:
        target_y = _clamp(by * 0.8, -GOAL_HALF + 0.1, GOAL_HALF - 0.1)
        move_to(rs, gk_base_x, target_y, speed=0.6)

# --- Role Assignment ---
def assign_roles(red_robots, blue_robots):
    for team_robots in [red_robots, blue_robots]:
        for r in team_robots:
            if r.lid == 2: r.role = ROLE_GK
        non_gk = [r for r in team_robots if r.lid != 2]
        if len(non_gk) >= 2:
            non_gk.sort(key=lambda r: r.bd)
            non_gk[0].role = ROLE_FWD
            non_gk[1].role = ROLE_DEF
        elif len(non_gk) == 1:
            non_gk[0].role = ROLE_FWD

# --- ZMQ Communication Thread ---
class ZMQComm(threading.Thread):
    def __init__(self, port, robots, zmq_hz=50):
        super().__init__(daemon=True)
        self.port = port; self.robots = robots; self.zmq_hz = zmq_hz
        self.running = True; self.lock = threading.Lock()
        self.commands = {r.id: [0.0, 0.0, 0.0] for r in robots}
        self.state_data = None; self.state_ts = 0.0
        self.send_count = 0; self.err_count = 0; self.last_err = ""

    def set_command(self, rid, vx, vy, vw):
        with self.lock: self.commands[rid] = [vx, vy, vw]

    def get_state(self):
        with self.lock: return self.state_data, self.state_ts

    def _connect(self):
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.REQ)
        self.sock.setsockopt(zmq.RCVTIMEO, 5000)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(f"tcp://127.0.0.1:{self.port}")

    def _reconnect(self):
        try: self.sock.close()
        except: pass
        try: self.ctx.term()
        except: pass
        time.sleep(0.2); self._connect()

    def run(self):
        self._connect()
        log.info(f"[ZMQ] Connected :{self.port} @ {self.zmq_hz}Hz")
        period = 1.0 / self.zmq_hz
        while self.running:
            try:
                t0 = time.perf_counter()
                with self.lock:
                    cmds = [{"cmd": self.commands[r.id], "id": r.id, "timestamp": time.time()} for r in self.robots]
                self.sock.send_json({"commands": cmds, "timestamp": time.time()})
                raw = self.sock.recv_string()
                resp = json.loads(raw)
                with self.lock:
                    self.state_data = resp.get("state")
                    self.state_ts = time.time()
                self.send_count += 1; self.last_err = ""
                el = time.perf_counter() - t0
                s = period - el
                if s > 0: time.sleep(s)
            except zmq.Again:
                self.err_count += 1; self.last_err = "timeout"
                if self.err_count % 5 == 1: log.warning(f"[ZMQ] Timeout #{self.err_count}")
                self._reconnect()
            except Exception as e:
                self.err_count += 1; self.last_err = str(e)
                log.error(f"[ZMQ] Error: {e}")
                self._reconnect(); time.sleep(0.5)
        try: self.sock.close()
        except: pass
        try: self.ctx.term()
        except: pass

# --- Main Controller ---
class MC:
    def __init__(self, port=5555, hz=50, zmq_hz=50, blue=True):
        self.hz = hz; self.tick = 0
        self.warmup_ticks = hz * 1
        self.red_robots = []; self.blue_robots = []; self.all_robots = []
        for i in range(3):
            r = RS(i, "red", i, i); self.red_robots.append(r); self.all_robots.append(r)
        if blue:
            for i in range(3):
                r = RS(BLUE_OFFSET + i, "blue", i, i); self.blue_robots.append(r); self.all_robots.append(r)
        self.bsx = self.bsy = 0.0
        self.ball_max_x = 0.0
        self.comm = ZMQComm(port, self.all_robots, zmq_hz=zmq_hz)
        self.comm.start()

    def _parse(self, state):
        if not state: return
        rd = state.get("robots", []); bl = state.get("ball", {})
        if bl: self.bsx, self.bsy = bl.get("x", 0), bl.get("y", 0)
        rm = {r.get("name", ""): r for r in rd}
        for rs in self.all_robots:
            d = rm.get(rs.name) or rm.get(rs.name.replace("robot_", ""))
            if not d: continue
            sx, sy, st = d["x"], d["y"], d["theta"]
            if rs.team == "blue":
                mx, my, mt = -sx, -sy, st + math.pi
                bmx, bmy = -self.bsx, -self.bsy
            else:
                mx, my, mt = sx, sy, st
                bmx, bmy = self.bsx, self.bsy
            mt = _norm(mt)
            rs.x, rs.y, rs.th = mx, my, mt
            rs.bmx, rs.bmy = bmx, bmy
            dx, dy = bmx - mx, bmy - my
            rs.bd = math.hypot(dx, dy); rs.bs = True
            va = _norm(math.atan2(dy, dx) - mt)
            rs.bf = rs.bd * math.cos(va); rs.bl = rs.bd * math.sin(va)

    def _strategy_for_team(self, team_robots, is_red):
        attack_gx = HALF_LENGTH; own_gx = -HALF_LENGTH
        for rs in team_robots:
            if return_to_field(rs): continue
            if rs.role != ROLE_GK and stabilize_if_tilted(rs): continue
            if rs.role == ROLE_FWD:    do_forward(rs, attack_gx)
            elif rs.role == ROLE_DEF:  do_defender(rs, own_gx)
            elif rs.role == ROLE_GK:   do_goalkeeper(rs, own_gx)

    def run(self):
        period = 1.0 / self.hz
        log.info(f"[MC v27] Strategy @ {self.hz}Hz, ZMQ @ {self.comm.zmq_hz}Hz, "
                 f"{len(self.all_robots)} robots, warmup={self.warmup_ticks} ticks")
        while True:
            try:
                t0 = time.perf_counter()
                state, ts = self.comm.get_state()
                if state: self._parse(state)
                if self.bsx > self.ball_max_x:
                    self.ball_max_x = self.bsx
                if self.tick < self.warmup_ticks:
                    for rs in self.all_robots:
                        self.comm.set_command(rs.id, 0.0, 0.0, 0.0)
                else:
                    assign_roles(self.red_robots, self.blue_robots)
                    self._strategy_for_team(self.red_robots, is_red=True)
                    self._strategy_for_team(self.blue_robots, is_red=False)
                    for rs in self.all_robots:
                        self.comm.set_command(rs.id, rs.vx, rs.vy, rs.vw)
                self.tick += 1
                if self.tick % 100 == 0: self._dbg()
                el = time.perf_counter() - t0
                s = period - el
                if s > 0: time.sleep(s)
            except KeyboardInterrupt:
                log.info("Stopped"); break
        self.comm.running = False; self.comm.join(timeout=2)

    def _dbg(self):
        rn = {ROLE_FWD: "FWD", ROLE_DEF: "DEF", ROLE_GK: "GK"}
        p = [f"B({self.bsx:.2f},{self.bsy:.2f}) max_x={self.ball_max_x:.2f}"]
        for rs in self.all_robots:
            role = rn.get(rs.role, "?")
            p.append(f"{rs.team}#{rs.lid}({role})@({rs.x:.1f},{rs.y:.1f})θ={math.degrees(rs.th):.0f}°"
                     f"bd={rs.bd:.2f}v({rs.vx:.2f},{rs.vy:.2f},{rs.vw:.2f})")
        log.info(f"[T{self.tick}] sc={self.comm.send_count} ec={self.comm.err_count} | " + " | ".join(p))

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="MotrixArena S2 3v3 Multi-Controller v27")
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--hz", type=float, default=50.0)
    p.add_argument("--zmq-hz", type=float, default=50.0)
    p.add_argument("--no-blue", action="store_true")
    a = p.parse_args()
    MC(port=a.port, hz=a.hz, zmq_hz=a.zmq_hz, blue=not a.no_blue).run()
