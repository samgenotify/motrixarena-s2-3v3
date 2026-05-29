# user_entry.py
#
#   @description:   3v3 Soccer Strategy for MotrixArena S2
#                   Role assignment by robot id:
#                     id 0 = Forward (chase ball, shoot)
#                     id 1 = Defender (defensive position)
#                     id 2 = Goalkeeper (guard goal)

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

# Role assignments by local id (0-based within team)
ROLE_FORWARD = 0
ROLE_DEFENDER = 1
ROLE_GOALKEEPER = 2

# Position targets for each role (X, Y)
ROLE_POSITIONS = {
    ROLE_FORWARD:    (-1.0,  0.0),
    ROLE_DEFENDER:   (-2.5,  0.0),
    ROLE_GOALKEEPER: (-HALF_LENGTH + 0.3,  0.0),
}


def init(agent) -> None:
    agent.get_logger().info("[UserEntry] Initializing 3v3 Strategy...")
    agent._debug_tick = 0  # Periodic debug counter

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

    # Relocalize
    agent.relocate()


def loop(agent) -> None:
    try:
        agent._debug_tick += 1
        # Periodic position debug every 10 ticks
        if agent._debug_tick % 10 == 0:
            try:
                my_pos = agent.get_self_pos()
                my_yaw = agent.get_self_yaw()
                local_id = agent.get_config().get("id", 0)
                color = getattr(agent, 'color', '?')
                role_names = {0: "FWD", 1: "DEF", 2: "GK"}
                ball_seen = agent.get_if_ball()
                ball_dist = agent.get_ball_distance() if ball_seen else -1
                logger = agent.get_logger()
                pos_str = f"({my_pos[0]:.2f},{my_pos[1]:.2f})" if my_pos is not None else "None"
                logger.info(
                    f"[DBG] {color}#{local_id}({role_names.get(local_id,'?')}) "
                    f"pos={pos_str} yaw={my_yaw:.1f}° "
                    f"ball_dist={ball_dist:.2f} ball_seen={ball_seen}"
                )
            except Exception as de:
                agent.get_logger().warning(f"[DBG-ERR] {de}")
        game(agent)
    except Exception as e:
        agent.get_logger().error(f"Error in user_entry loop: {e}")
        traceback.print_exc()


def game(agent) -> None:
    """
    Main game loop with GameController integration.
    When no referee is active, falls through to direct PLAYING mode.
    """
    gc = agent.gamecontroller
    state = gc.game_state

    gc_active = gc.game_state_int != 0 or gc.secs_remaining != 0 or gc.set_play != 0

    if gc_active:
        if state in ("STATE_INITIAL", "STATE_READY"):
            local_id = agent.get_config().get("id", 0)
            pos = ROLE_POSITIONS.get(local_id, ROLE_POSITIONS[ROLE_FORWARD])
            agent.state_machine_runners['go_back_to_field'](
                aim_x=pos[0], aim_y=pos[1], aim_yaw=0
            )
            return

        if state == "STATE_SET":
            agent.stop()
            return

        if state in ("STATE_FINISHED", "STATE_STANDBY"):
            agent.stop()
            return

        if state == "STATE_PLAYING":
            _execute_role(agent)
            return

        agent.stop()
    else:
        # No referee active — go straight to playing
        _execute_role(agent)


def _execute_role(agent):
    local_id = agent.get_config().get("id", 0)

    if local_id == ROLE_GOALKEEPER:
        _role_goalkeeper(agent)
    elif local_id == ROLE_DEFENDER:
        _role_defender(agent)
    else:
        _role_forward(agent)


def _role_forward(agent):
    """
    Forward: Move directly to ball's map position for reliability at low Hz,
    then dribble towards goal when close.
    """
    if not agent.get_if_ball():
        agent.state_machine_runners['find_ball']()
        return

    ball_dist = agent.get_ball_distance()

    # If very close to ball, dribble towards goal
    if ball_dist < 0.8:
        _dribble_towards_goal(agent)
        return

    # Far from ball: move directly to ball's map position
    # This is more reliable than chase_ball FSM at low control frequency
    ball_map = agent.get_ball_pos_in_map()
    if ball_map is not None:
        _move_to_position(agent, float(ball_map[0]), float(ball_map[1]))
    else:
        # Fallback to chase_ball FSM
        agent.state_machine_runners['chase_ball']()


def _role_defender(agent):
    """
    Defender: Aggressive ball chase in our half, position hold otherwise.
    Uses direct position movement for low-Hz reliability.
    """
    if not agent.get_if_ball():
        _move_to_position(agent, -2.0, 0.0)
        return

    ball_pos = agent.get_ball_pos_in_map()
    my_pos = agent.get_self_pos()
    ball_dist = agent.get_ball_distance()

    if ball_pos is not None and my_pos is not None:
        ball_x = float(ball_pos[0])

        # If ball is close, chase and dribble
        if ball_dist < 0.8:
            _dribble_towards_goal(agent)
            return

        # Chase ball in our half or if close enough
        if ball_x < 1.0 or ball_dist < 2.0:
            _move_to_position(agent, float(ball_pos[0]), float(ball_pos[1]))
            return

    # Ball is far in opponent half - hold defensive position
    _move_to_position(agent, -2.5, 0.0)


def _role_goalkeeper(agent):
    """
    Goalkeeper: Track ball Y on goal line, dive when ball is close.
    Uses direct cmd_vel for fast response instead of slow go_back_to_field FSM.
    """
    gk_x = -HALF_LENGTH + 0.3  # Goal line x position

    if not agent.get_if_ball():
        # No ball - go to center of goal
        _move_to_position(agent, gk_x, 0.0)
        return

    ball_pos = agent.get_ball_pos_in_map()
    ball_dist = agent.get_ball_distance()

    if ball_pos is not None:
        ball_x = float(ball_pos[0])
        ball_y = float(ball_pos[1])

        # If ball is very close and heading towards goal, intercept!
        if ball_dist < 1.5 and ball_x < -2.0:
            agent.state_machine_runners['goalkeeper']()
            return

        # Track ball Y on goal line (clamp to goal width ~1.3m)
        target_y = max(-1.3, min(1.3, ball_y))

        _move_to_position(agent, gk_x, target_y)
        return

    # Fallback
    _move_to_position(agent, gk_x, 0.0)


def _move_to_position(agent, target_x, target_y):
    """
    Fast position movement using direct cmd_vel.
    More responsive than go_back_to_field FSM for simple positioning.
    """
    my_pos = agent.get_self_pos()
    my_yaw_deg = agent.get_self_yaw()

    if my_pos is None:
        agent.cmd_vel(0, 0, 0)
        return

    dx = target_x - float(my_pos[0])
    dy = target_y - float(my_pos[1])
    dist = math.hypot(dx, dy)

    if dist < 0.2:
        # Close enough, stop
        agent.cmd_vel(0, 0, 0)
        return

    # Calculate desired heading
    target_angle = math.atan2(dy, dx)
    yaw_rad = math.radians(my_yaw_deg)
    angle_diff = target_angle - yaw_rad
    # Normalize to [-pi, pi]
    while angle_diff > math.pi:
        angle_diff -= 2 * math.pi
    while angle_diff < -math.pi:
        angle_diff += 2 * math.pi

    # If angle is too far off, rotate first
    if abs(angle_diff) > 0.5:
        agent.cmd_vel(0.0, 0.0, np.sign(angle_diff) * 0.8)
        return

    # Move forward with steering
    speed = min(1.0, dist * 1.5)
    # Transform to robot-local frame
    local_vx = speed * math.cos(angle_diff)
    local_vy = speed * math.sin(angle_diff)
    vw = -0.5 * angle_diff  # P-control steering

    agent.cmd_vel(local_vx, local_vy, max(-0.5, min(0.5, vw)))


def _dribble_towards_goal(agent):
    """
    Dribble ball towards opponent goal with aggressive forward velocity.
    Uses proportional control to steer while pushing.
    """
    if not agent.get_if_ball():
        agent.state_machine_runners['find_ball']()
        return

    ball_pos = agent.get_ball_pos()  # Relative [forward, left]
    my_pos = agent.get_self_pos()
    my_yaw = agent.get_self_yaw()

    if ball_pos is None:
        agent.state_machine_runners['find_ball']()
        return

    b_x = float(ball_pos[0])  # Forward
    b_y = float(ball_pos[1])  # Left
    ball_dist = math.hypot(b_x, b_y)

    # If ball is far, chase it first
    if ball_dist > 0.6:
        agent.state_machine_runners['chase_ball']()
        return

    # Calculate angle to opponent goal (at +HALF_LENGTH, 0)
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

    # Ball is close - AGGRESSIVE dribble
    # Forward: push hard if ball is in front
    if b_x > 0.02:
        vx = min(1.5, 0.8 + 0.5 * b_x)  # Up to 1.5 m/s
    else:
        vx = 0.3  # Slow approach to get behind ball

    # Lateral: center the ball
    vy = -2.0 * b_y

    # Angular: steer towards goal
    vw = -1.0 * goal_angle_local

    # Clamp velocities
    vx = max(-1.5, min(1.5, vx))
    vy = max(-1.5, min(1.5, vy))
    vw = max(-1.0, min(1.0, vw))

    agent.cmd_vel(vx, vy, vw)
