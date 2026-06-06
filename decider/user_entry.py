# user_entry.py
#
#   @description:   3v3 Soccer Strategy for MotrixArena S2
#                   v32: v25 champion core + new-rule compliance
#
#   Compliance features (active only with referee):
#     - Game state machine: Initial/Ready/Set/Playing/Finished
#     - Set play positioning: kickoff/corner/goal_kick/throw_in/free_kick
#     - Ball holding avoidance (4.5s field / 9s GK, rule limit 5/10)
#     - Ball stall avoidance (8s, rule limit 10)
#     - Boundary safety clamp
#
#   Without referee: behavior identical to v25 champion.

import time
import traceback
import sys
import os
import math
import numpy as np

# Ensure we can find the logic package
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.append(CUR_DIR)

from logic.sub_statemachines import chase_ball, find_ball, go_back_to_field, dribble
from logic.policy_statemachines import goalkeeper


# ============================================================
# Field constants for S league (9x6m)
# ============================================================
FIELD_LENGTH = 9.0
FIELD_WIDTH = 6.0
HALF_LENGTH = FIELD_LENGTH / 2.0
HALF_WIDTH = FIELD_WIDTH / 2.0
GOAL_HALF = 1.3  # goal opening half-width

# Role assignments by local id (0-based within team)
ROLE_FORWARD = 0
ROLE_DEFENDER = 1
ROLE_GOALKEEPER = 2

# Position targets for each role (X, Y) — own-side home positions
ROLE_POSITIONS = {
    ROLE_FORWARD:    (-1.0,  0.0),
    ROLE_DEFENDER:   (-2.5,  0.0),
    ROLE_GOALKEEPER: (-HALF_LENGTH + 0.3,  0.0),
}

# v32: Set-play formations (own-side perspective, red=left)
KICKOFF_POSITIONS_RED = {
    ROLE_FORWARD:    (-0.5,  0.0),
    ROLE_DEFENDER:   (-2.5,  0.0),
    ROLE_GOALKEEPER: (-HALF_LENGTH + 0.3,  0.0),
}
WALL_POSITIONS_RED = {
    ROLE_FORWARD:    (-2.0,  0.0),
    ROLE_DEFENDER:   (-3.0,  0.5),
    ROLE_GOALKEEPER: (-HALF_LENGTH + 0.3, -0.5),
}

# ============================================================
# v32: Rule-compliance constants
# ============================================================
BALL_HOLD_LIMIT_FIELD = 4.5    # rule: 5s, we back off at 4.5
BALL_HOLD_LIMIT_GK = 9.0       # rule: 10s for GK
BALL_STALL_RADIUS = 0.15       # ball must move this much (m) to count as "moved"
BALL_STALL_TIME = 8.0          # rule: 10s, we trigger at 8
NEAR_BALL_DIST = 0.6           # within this distance counts as "near ball"
FIELD_BOUNDARY_MARGIN = 0.5    # stay this far inside boundary

# GC state constants (must match gamecontroller.py)
GC_INITIAL = 0
GC_READY = 1
GC_SET = 2
GC_PLAYING = 3
GC_FINISHED = 4

# Set play constants
SP_NONE = 0
SP_KICK_OFF = 1
SP_KICK_IN = 2
SP_CORNER_KICK = 3
SP_GOAL_KICK = 4
SP_DIRECT_FREE = 5
SP_INDIRECT_FREE = 6


# ============================================================
# v32: Per-robot state trackers
# ============================================================
class RuleComplianceState:
    """Tracks ball-holding time and stall status for rule avoidance.
    Each robot instance gets one of these."""
    def __init__(self):
        self.near_ball_time = 0.0
        # Stall tracking
        self.last_ball_x = 0.0
        self.last_ball_y = 0.0
        self.stall_time = 0.0
        self.last_check_time = 0.0


def update_rule_state(agent, rule_state, dt, with_rule_avoidance):
    """Update ball-holding and stall tracking.
    Returns (near_ball_time_exceeded, ball_stalled)."""
    if not with_rule_avoidance:
        rule_state.near_ball_time = 0.0
        rule_state.stall_time = 0.0
        return False, False

    ball_seen = agent.get_if_ball()
    ball_dist = agent.get_ball_distance() if ball_seen else 999.0

    # Ball holding tracker
    if ball_dist < NEAR_BALL_DIST:
        rule_state.near_ball_time += dt
    else:
        rule_state.near_ball_time = 0.0

    near_exceeded = rule_state.near_ball_time > BALL_HOLD_LIMIT_FIELD

    # Ball stall detector
    ball_map = agent.get_ball_pos_in_map()
    now = time.time()
    stalled = False
    if ball_map is not None:
        bx, by = float(ball_map[0]), float(ball_map[1])
        if now - rule_state.last_check_time > 0.5:
            moved = math.hypot(bx - rule_state.last_ball_x, by - rule_state.last_ball_y)
            if moved > BALL_STALL_RADIUS:
                rule_state.stall_time = 0.0
            else:
                rule_state.stall_time += now - rule_state.last_check_time
            rule_state.last_ball_x = bx
            rule_state.last_ball_y = by
            rule_state.last_check_time = now
        stalled = rule_state.stall_time > BALL_STALL_TIME

    return near_exceeded, stalled


# ============================================================
# Init / Loop
# ============================================================
def init(agent) -> None:
    agent.get_logger().info("[UserEntry] Initializing v32 3v3 Strategy...")
    agent._debug_tick = 0
    agent._last_loop_time = time.time()

    # Initialize State Machines
    agent.chase_ball_machine = chase_ball.ChaseBallStateMachine(agent)
    agent.find_ball_machine = find_ball.FindBallStateMachine(agent)
    agent.go_back_machine = go_back_to_field.GoBackToFieldStateMachine(agent)
    agent.dribble_machine = dribble.DribbleStateMachine(agent)
    agent.goalkeeper_machine = goalkeeper.GoalkeeperStateMachine(agent)

    agent.state_machine_runners = {
        "chase_ball": agent.chase_ball_machine.run,
        "find_ball": agent.find_ball_machine.run,
        "go_back_to_field": agent.go_back_machine.run,
        "dribble": agent.dribble_machine.run,
        "stop": agent.stop,
        "goalkeeper": agent.goalkeeper_machine.run,
    }

    # Basic Configs
    agent.default_chase_distance = agent.get_config().get("chase", {}).get("default_chase_distance", 0.7)

    # Determine role from config id (local id within team, 0-2)
    local_id = agent.get_config().get("id", 0)
    agent.role = local_id  # 0=forward, 1=defender, 2=goalkeeper
    role_names = {0: "Forward", 1: "Defender", 2: "Goalkeeper"}
    agent.get_logger().info(f"[UserEntry] Robot id={local_id}, Role={role_names.get(local_id, 'Unknown')}")

    # v32: Per-robot rule compliance tracker
    agent.rule_state = RuleComplianceState()

    # Relocalize
    agent.relocate()


def loop(agent) -> None:
    try:
        now = time.time()
        dt = now - agent._last_loop_time
        agent._last_loop_time = now
        agent._debug_tick += 1

        if agent._debug_tick % 50 == 0:
            try:
                my_pos = agent.get_self_pos()
                my_yaw = agent.get_self_yaw()
                local_id = agent.get_config().get("id", 0)
                color = getattr(agent, 'color', '?')
                role_names = {0: "FWD", 1: "DEF", 2: "GK"}
                ball_seen = agent.get_if_ball()
                ball_dist = agent.get_ball_distance() if ball_seen else -1
                ball_map = agent.get_ball_pos_in_map() if ball_seen else None
                ball_rel = agent.get_ball_pos() if ball_seen else [None, None]
                logger = agent.get_logger()
                pos_str = f"({my_pos[0]:.2f},{my_pos[1]:.2f})" if my_pos is not None else "None"
                bm_str = f"({ball_map[0]:.2f},{ball_map[1]:.2f})" if ball_map is not None else "None"
                br_str = f"({ball_rel[0]:.2f},{ball_rel[1]:.2f})" if ball_rel[0] is not None else "None"
                logger.info(
                    f"[DBG] {color}#{local_id}({role_names.get(local_id,'?')}) "
                    f"pos={pos_str} yaw={my_yaw:.1f}° "
                    f"ball_dist={ball_dist:.2f} "
                    f"ball_map={bm_str} ball_rel={br_str} "
                    f"nb_t={agent.rule_state.near_ball_time:.1f}s"
                )
            except Exception as de:
                agent.get_logger().warning(f"[DBG-ERR] {de}")
        game(agent, dt)
    except Exception as e:
        agent.get_logger().error(f"Error in user_entry loop: {e}")
        traceback.print_exc()


def game(agent, dt=0.02) -> None:
    """Main game loop with GameController integration.
    When no referee is active, falls through to direct PLAYING mode (v25 behavior)."""
    gc = agent.gamecontroller
    state = gc.game_state

    gc_active = (gc.game_state_int != GC_INITIAL
                 or gc.set_play != SP_NONE
                 or gc.secs_remaining != 0
                 or gc.game_state == "STATE_PLAYING")

    if gc_active:
        # Update rule-compliance tracking
        near_exceeded, ball_stalled = update_rule_state(
            agent, agent.rule_state, dt, with_rule_avoidance=True)

        if state in ("STATE_INITIAL",):
            # Pre-game: hold formation
            _go_to_role_home(agent)
            return

        if state == "STATE_READY":
            # Set play positioning phase (robots can move)
            _set_play_positioning(agent, gc)
            return

        if state == "STATE_SET":
            # SET: must be stationary (rule)
            agent.stop()
            return

        if state in ("STATE_FINISHED", "STATE_STANDBY"):
            agent.stop()
            return

        if state == "STATE_PLAYING":
            _execute_role(agent, with_rule_avoidance=True,
                          near_exceeded=near_exceeded, ball_stalled=ball_stalled)
            return

        agent.stop()
    else:
        # No referee — identical to v25 behavior
        update_rule_state(agent, agent.rule_state, dt, with_rule_avoidance=False)
        _execute_role(agent, with_rule_avoidance=False,
                      near_exceeded=False, ball_stalled=False)


# ============================================================
# Set Play Positioning (v32)
# ============================================================
def _set_play_positioning(agent, gc):
    """Position robot correctly during set plays (READY phase)."""
    sp = gc.set_play
    we_kick = (gc.kicking_side == "left")  # we are red=left

    role = agent.role

    if sp == SP_KICK_OFF:
        pos = KICKOFF_POSITIONS_RED[role] if we_kick else WALL_POSITIONS_RED[role]
        _move_to_position(agent, pos[0], pos[1])

    elif sp == SP_KICK_IN:
        if we_kick and role == ROLE_FORWARD:
            ball_map = agent.get_ball_pos_in_map()
            if ball_map is not None:
                _move_to_position(agent, float(ball_map[0]), float(ball_map[1]))
            else:
                _move_to_position(agent, -1.0, 0.0)
        else:
            _go_to_role_home(agent)

    elif sp == SP_CORNER_KICK:
        if we_kick and role == ROLE_FORWARD:
            ball_map = agent.get_ball_pos_in_map()
            if ball_map is not None:
                _move_to_position(agent, float(ball_map[0]), float(ball_map[1]))
            else:
                _move_to_position(agent, 4.0, 0.0)
        elif role == ROLE_GOALKEEPER:
            _move_to_position(agent, -HALF_LENGTH + 0.3, 0.0)
        elif role == ROLE_DEFENDER:
            _move_to_position(agent, -3.5, 0.0)
        else:
            _go_to_role_home(agent)

    elif sp == SP_GOAL_KICK:
        if we_kick and role == ROLE_DEFENDER:
            ball_map = agent.get_ball_pos_in_map()
            if ball_map is not None:
                _move_to_position(agent, float(ball_map[0]), float(ball_map[1]))
            else:
                _move_to_position(agent, -HALF_LENGTH + 0.5, 0.0)
        elif role == ROLE_GOALKEEPER:
            _move_to_position(agent, -HALF_LENGTH + 0.3, 0.0)
        elif role == ROLE_FORWARD:
            _move_to_position(agent, 2.0, 0.0)
        else:
            _go_to_role_home(agent)

    elif sp in (SP_DIRECT_FREE, SP_INDIRECT_FREE):
        if we_kick and role == ROLE_FORWARD:
            ball_map = agent.get_ball_pos_in_map()
            if ball_map is not None:
                _move_to_position(agent, float(ball_map[0]), float(ball_map[1]))
            else:
                _go_to_role_home(agent)
        else:
            pos = WALL_POSITIONS_RED[role]
            _move_to_position(agent, pos[0], pos[1])

    else:
        _go_to_role_home(agent)


def _go_to_role_home(agent):
    """Move to role's home position."""
    role = agent.role
    pos = ROLE_POSITIONS.get(role, (-1.0, 0.0))
    _move_to_position(agent, pos[0], pos[1])


# ============================================================
# Role Behaviors
# ============================================================
def _execute_role(agent, with_rule_avoidance=False,
                  near_exceeded=False, ball_stalled=False):
    local_id = agent.get_config().get("id", 0)

    if local_id == ROLE_GOALKEEPER:
        _role_goalkeeper(agent, with_rule_avoidance, near_exceeded, ball_stalled)
    elif local_id == ROLE_DEFENDER:
        _role_defender(agent, with_rule_avoidance, near_exceeded, ball_stalled)
    else:
        _role_forward(agent, with_rule_avoidance, near_exceeded, ball_stalled)


def _role_forward(agent, with_rule_avoidance=False,
                  near_exceeded=False, ball_stalled=False):
    """Forward: chase ball, dribble to goal.
    v32: ball-holding + stall avoidance when referee active."""
    # v32: Ball holding avoidance
    if with_rule_avoidance and near_exceeded:
        if not agent.get_if_ball():
            agent.state_machine_runners['find_ball']()
            return
        ball_map = agent.get_ball_pos_in_map()
        if ball_map is not None:
            # Back off from ball
            _move_to_position(agent, float(ball_map[0]) - 1.0, float(ball_map[1]) + 0.5)
            return

    # v32: Stall avoidance
    if with_rule_avoidance and ball_stalled:
        ball_map = agent.get_ball_pos_in_map()
        if ball_map is not None and agent.get_ball_distance() < 1.0:
            _move_to_position(agent, float(ball_map[0]) - 1.5,
                              float(ball_map[1]) + 0.8)
            return

    if not agent.get_if_ball():
        # 看不到球时：先尝试从其他机器人获取球位置
        ball_from_team = None
        if hasattr(agent, 'get_ball_angle_from_other_robots'):
            try:
                ball_from_team = agent.get_ball_angle_from_other_robots()
            except Exception:
                ball_from_team = None
        if ball_from_team is not None:
            # 有队友看到球，旋转到球方向
            agent.state_machine_runners['find_ball']()
            return
        # 无队友信息：朝球场中央(0,0)走去，同时旋转找球
        my_pos = agent.get_self_pos()
        if my_pos is not None:
            dist_to_center = math.hypot(float(my_pos[0]), float(my_pos[1]))
            if dist_to_center > 1.0:
                # 朝中央移动，不走find_ball原地转
                _move_to_position(agent, 0.0, 0.0)
                return
        # 离中央很近了还没看到球，旋转找球
        agent.state_machine_runners['find_ball']()
        return

    ball_dist = agent.get_ball_distance()

    if ball_dist < 0.8:
        _dribble_towards_goal(agent)
        return

    ball_map = agent.get_ball_pos_in_map()
    if ball_map is not None:
        _move_to_position(agent, float(ball_map[0]), float(ball_map[1]))
    else:
        agent.state_machine_runners['chase_ball']()


def _role_defender(agent, with_rule_avoidance=False,
                   near_exceeded=False, ball_stalled=False):
    """Defender: chase in our half, hold position otherwise."""
    # v32: Ball holding avoidance
    if with_rule_avoidance and near_exceeded:
        ball_map = agent.get_ball_pos_in_map()
        if ball_map is not None and agent.get_ball_distance() < 0.5:
            _move_to_position(agent, float(ball_map[0]) - 1.5,
                              float(ball_map[1]) + 1.0)
            return

    # v32: Stall avoidance
    if with_rule_avoidance and ball_stalled:
        ball_map = agent.get_ball_pos_in_map()
        if ball_map is not None and agent.get_ball_distance() < 1.0:
            _move_to_position(agent, -3.5, float(ball_map[1]) * 0.5)
            return

    if not agent.get_if_ball():
        _move_to_position(agent, -2.0, 0.0)
        return

    ball_pos = agent.get_ball_pos_in_map()
    my_pos = agent.get_self_pos()
    ball_dist = agent.get_ball_distance()

    if ball_pos is not None and my_pos is not None:
        ball_x = float(ball_pos[0])

        if ball_dist < 0.8:
            _dribble_towards_goal(agent)
            return

        if ball_x < 1.0 or ball_dist < 2.0:
            _move_to_position(agent, float(ball_pos[0]), float(ball_pos[1]))
            return

    _move_to_position(agent, -2.5, 0.0)


def _role_goalkeeper(agent, with_rule_avoidance=False,
                     near_exceeded=False, ball_stalled=False):
    """Goalkeeper: track ball Y on goal line, intercept when close.
    v32: GK has longer ball-hold limit (10s vs 5s)."""
    gk_x = -HALF_LENGTH + 0.3

    # v32: GK ball holding — uses longer limit
    if with_rule_avoidance and agent.rule_state.near_ball_time > BALL_HOLD_LIMIT_GK:
        if not agent.get_if_ball():
            _move_to_position(agent, gk_x, 0.0)
            return
        ball_map = agent.get_ball_pos_in_map()
        if ball_map is not None and agent.get_ball_distance() < 0.5:
            target_y = max(-GOAL_HALF + 0.1, min(GOAL_HALF - 0.1, float(ball_map[1]) * 0.4))
            _move_to_position(agent, gk_x, target_y)
            return

    if not agent.get_if_ball():
        _move_to_position(agent, gk_x, 0.0)
        return

    ball_pos = agent.get_ball_pos_in_map()
    ball_dist = agent.get_ball_distance()

    if ball_pos is not None:
        ball_x = float(ball_pos[0])
        ball_y = float(ball_pos[1])

        if ball_dist < 1.5 and ball_x < -2.0:
            agent.state_machine_runners['goalkeeper']()
            return

        target_y = max(-1.3, min(1.3, ball_y))
        _move_to_position(agent, gk_x, target_y)
        return

    _move_to_position(agent, gk_x, 0.0)


# ============================================================
# Motion primitives
# ============================================================
def _move_to_position(agent, target_x, target_y, debug_label=""):
    """Fast position movement using direct cmd_vel."""
    my_pos = agent.get_self_pos()
    my_yaw_deg = agent.get_self_yaw()

    if my_pos is None:
        agent.cmd_vel(0, 0, 0)
        return

    # v32: Boundary clamp
    target_x = max(-HALF_LENGTH - 0.3, min(HALF_LENGTH + 0.3, target_x))
    target_y = max(-HALF_WIDTH - 0.3, min(HALF_WIDTH + 0.3, target_y))

    dx = target_x - float(my_pos[0])
    dy = target_y - float(my_pos[1])
    dist = math.hypot(dx, dy)

    if dist < 0.2:
        agent.cmd_vel(0, 0, 0)
        return

    target_angle = math.atan2(dy, dx)
    yaw_rad = math.radians(my_yaw_deg)
    angle_diff = target_angle - yaw_rad
    while angle_diff > math.pi:
        angle_diff -= 2 * math.pi
    while angle_diff < -math.pi:
        angle_diff += 2 * math.pi

    if abs(angle_diff) > 0.5:
        vw = np.sign(angle_diff) * 0.8
        if getattr(agent, '_debug_tick', 0) % 50 == 0:
            agent.get_logger().info(
                f"[MTP{debug_label}] ROTATE pos=({my_pos[0]:.2f},{my_pos[1]:.2f}) "
                f"yaw={my_yaw_deg:.1f}° tgt=({target_x:.2f},{target_y:.2f}) "
                f"tgt_ang={math.degrees(target_angle):.1f}° adiff={math.degrees(angle_diff):.1f}° vw={vw:.1f}"
            )
        agent.cmd_vel(0.0, 0.0, vw)
        return

    speed = min(1.0, dist * 1.5)
    local_vx = speed * math.cos(angle_diff)
    local_vy = speed * math.sin(angle_diff)
    vw = -0.5 * angle_diff
    if getattr(agent, '_debug_tick', 0) % 50 == 0:
        agent.get_logger().info(
            f"[MTP{debug_label}] WALK pos=({my_pos[0]:.2f},{my_pos[1]:.2f}) "
            f"yaw={my_yaw_deg:.1f}° tgt=({target_x:.2f},{target_y:.2f}) "
            f"vx={local_vx:.2f} vy={local_vy:.2f} vw={vw:.2f}"
        )
    agent.cmd_vel(local_vx, local_vy, max(-0.5, min(0.5, vw)))


def _dribble_towards_goal(agent):
    """Dribble ball towards opponent goal with aggressive forward velocity."""
    if not agent.get_if_ball():
        agent.state_machine_runners['find_ball']()
        return

    ball_pos = agent.get_ball_pos()  # Relative [forward, left]
    my_pos = agent.get_self_pos()
    my_yaw = agent.get_self_yaw()

    if ball_pos is None:
        agent.state_machine_runners['find_ball']()
        return

    b_x = float(ball_pos[0])
    b_y = float(ball_pos[1])
    ball_dist = math.hypot(b_x, b_y)

    if ball_dist > 0.6:
        # Use _move_to_position toward ball instead of chase_ball FSM
        # (chase_ball FSM gets stuck in rotate due to slow gait rotation)
        ball_map = agent.get_ball_pos_in_map()
        if ball_map is not None:
            _move_to_position(agent, float(ball_map[0]), float(ball_map[1]), debug_label="/dribble")
        return

    goal_angle_local = 0
    if my_pos is not None:
        goal_dx = HALF_LENGTH - float(my_pos[0])
        goal_dy = 0.0 - float(my_pos[1])
        goal_angle_global = math.atan2(goal_dy, goal_dx)
        yaw_rad = math.radians(my_yaw)
        goal_angle_local = goal_angle_global - yaw_rad
        while goal_angle_local > math.pi:
            goal_angle_local -= 2 * math.pi
        while goal_angle_local < -math.pi:
            goal_angle_local += 2 * math.pi

    if b_x > 0.02:
        vx = min(1.5, 0.8 + 0.5 * b_x)
    else:
        vx = 0.3

    vy = -2.0 * b_y
    vw = -1.0 * goal_angle_local

    vx = max(-1.5, min(1.5, vx))
    vy = max(-1.5, min(1.5, vy))
    vw = max(-1.0, min(1.0, vw))

    agent.cmd_vel(vx, vy, vw)
