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

# Position targets for each role (X, Y, YAW in degrees)
# These are for red team; blue team uses coordinate mirroring in vision.py
ROLE_POSITIONS = {
    ROLE_FORWARD:    (-1.0,  0.0,   0),    # Center forward
    ROLE_DEFENDER:   (-2.5,  0.0,   0),    # Center back
    ROLE_GOALKEEPER: (-3.8,  0.0,   0),    # Goal line center
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
    State machine:
      INITIAL -> READY -> SET -> PLAYING -> FINISHED

    When no referee is active (GC never updated), falls through to
    direct PLAYING mode so robots can still play.
    """
    gc = agent.gamecontroller
    state = gc.game_state
    logger = agent.get_logger()

    local_id = agent.get_config().get("id", 0)

    # Check if GameController has ever been updated (referee active)
    gc_active = gc.game_state_int != 0 or gc.secs_remaining != 0 or gc.set_play != 0

    if gc_active:
        # ==========================================
        # STATE_INITIAL / STATE_READY: Go to position
        # ==========================================
        if state in ("STATE_INITIAL", "STATE_READY"):
            pos = ROLE_POSITIONS.get(local_id, ROLE_POSITIONS[ROLE_FORWARD])
            agent.state_machine_runners['go_back_to_field'](
                aim_x=pos[0], aim_y=pos[1], aim_yaw=pos[2]
            )
            return

        # ==========================================
        # STATE_SET: Stand still
        # ==========================================
        if state == "STATE_SET":
            agent.stop()
            return

        # ==========================================
        # STATE_FINISHED / STATE_STANDBY: Stop
        # ==========================================
        if state in ("STATE_FINISHED", "STATE_STANDBY"):
            agent.stop()
            return

        # ==========================================
        # STATE_PLAYING: Execute role strategy
        # ==========================================
        if state == "STATE_PLAYING":
            _execute_role(agent)
            return

        # Fallback: unknown state
        logger.warning(f"[Game] Unknown state: {state}")
        agent.stop()
    else:
        # No referee active — go straight to playing
        _execute_role(agent)


def _execute_role(agent):
    """
    Execute role-based strategy during PLAYING state.
    """
    local_id = agent.get_config().get("id", 0)

    if local_id == ROLE_GOALKEEPER:
        _role_goalkeeper(agent)
    elif local_id == ROLE_DEFENDER:
        _role_defender(agent)
    else:
        _role_forward(agent)


def _role_forward(agent):
    """
    Forward: Chase ball and dribble towards opponent goal.
    """
    logger = agent.get_logger()

    if not agent.get_if_ball():
        logger.debug("[Forward] Ball not detected, searching...")
        agent.state_machine_runners['find_ball']()
        return

    ball_dist = agent.get_ball_distance()
    chase_dist = agent.default_chase_distance

    if ball_dist > chase_dist:
        # Far from ball: use chase FSM to approach
        logger.debug(f"[Forward] Chasing ball (dist={ball_dist:.2f})")
        agent.state_machine_runners['chase_ball']()
        return

    # Close to ball: dribble towards goal directly
    # DO NOT call chase_ball FSM here - it would enter 'arrived' and stop
    _dribble_towards_goal(agent)


def _role_defender(agent):
    """
    Defender: Stay in defensive position, chase ball if it's in our half.
    """
    logger = agent.get_logger()

    if not agent.get_if_ball():
        # No ball visible, go to defensive position
        agent.state_machine_runners['go_back_to_field'](
            aim_x=-2.0, aim_y=0.0, aim_yaw=0
        )
        return

    ball_pos = agent.get_ball_pos_in_map()
    my_pos = agent.get_self_pos()

    if ball_pos is not None and my_pos is not None:
        ball_x = ball_pos[0] if hasattr(ball_pos, '__len__') else 0

        # If ball is in our half (negative X for red), chase it
        if ball_x < 0.5:
            ball_dist = agent.get_ball_distance()
            if ball_dist > agent.default_chase_distance:
                agent.state_machine_runners['chase_ball']()
                return
            # Close enough, clear the ball (kick towards opponent goal)
            _dribble_towards_goal(agent)
            return

    # Ball is in opponent half or we can't see it - hold defensive position
    agent.state_machine_runners['go_back_to_field'](
        aim_x=-2.5, aim_y=0.0, aim_yaw=0
    )


def _role_goalkeeper(agent):
    """
    Goalkeeper: Track ball Y position and stay on goal line.
    Use goalkeeper state machine for advanced behavior.
    """
    logger = agent.get_logger()

    if not agent.get_if_ball():
        # No ball, stay at center of goal
        agent.state_machine_runners['go_back_to_field'](
            aim_x=-HALF_LENGTH + 0.3, aim_y=0.0, aim_yaw=0
        )
        return

    ball_pos = agent.get_ball_pos_in_map()
    ball_dist = agent.get_ball_distance()

    if ball_pos is not None:
        ball_x = ball_pos[0] if hasattr(ball_pos, '__len__') else 0
        ball_y = ball_pos[1] if hasattr(ball_pos, '__len__') else 0

        # If ball is very close, use the goalkeeper state machine for save
        if ball_dist < 1.0 and ball_x < -2.0:
            logger.debug("[Goalkeeper] Ball close, using GK state machine")
            agent.state_machine_runners['goalkeeper']()
            return

        # Track ball Y position on goal line
        target_y = max(-1.0, min(1.0, ball_y))  # Clamp to goal width
        target_x = -HALF_LENGTH + 0.3

        agent.state_machine_runners['go_back_to_field'](
            aim_x=target_x, aim_y=target_y, aim_yaw=0
        )
        return

    # Fallback
    agent.state_machine_runners['go_back_to_field'](
        aim_x=-HALF_LENGTH + 0.3, aim_y=0.0, aim_yaw=0
    )


def _dribble_towards_goal(agent):
    """
    Simple dribble: move forward towards opponent goal while keeping ball close.
    Uses proportional control to steer towards goal.
    """
    logger = agent.get_logger()

    if not agent.get_if_ball():
        agent.state_machine_runners['find_ball']()
        return

    ball_pos = agent.get_ball_pos()  # Relative [forward, left]
    my_pos = agent.get_self_pos()
    my_yaw = agent.get_self_yaw()

    if ball_pos[0] is None:
        agent.state_machine_runners['find_ball']()
        return

    b_x = ball_pos[0]  # Forward
    b_y = ball_pos[1]  # Left

    # Calculate angle to opponent goal (at +HALF_LENGTH, 0)
    if my_pos is not None:
        goal_dx = HALF_LENGTH - my_pos[0]
        goal_dy = 0.0 - my_pos[1]
        goal_angle_global = math.atan2(goal_dy, goal_dx)
        yaw_rad = math.radians(my_yaw)
        goal_angle_local = goal_angle_global - yaw_rad
        # Normalize
        while goal_angle_local > math.pi:
            goal_angle_local -= 2 * math.pi
        while goal_angle_local < -math.pi:
            goal_angle_local += 2 * math.pi
    else:
        goal_angle_local = 0

    ball_dist = math.hypot(b_x, b_y)

    # If ball is far, chase it first
    if ball_dist > 0.5:
        agent.state_machine_runners['chase_ball']()
        return

    # Ball is close - approach and push forward
    # Simple P controller:
    # - Forward velocity proportional to how far ball is in front
    # - Lateral velocity to center ball
    # - Angular velocity to align with goal

    # Forward: push if ball is in front, approach if behind
    if b_x > 0.05:
        vx = 0.6 + 0.3 * b_x  # Push forward
    else:
        vx = 0.2  # Slow approach

    # Lateral: center the ball
    vy = -1.5 * b_y  # Move to put ball in center

    # Angular: steer towards goal
    vw = -0.8 * goal_angle_local

    # Clamp
    vx = max(-1.0, min(1.0, vx))
    vy = max(-1.0, min(1.0, vy))
    vw = max(-1.0, min(1.0, vw))

    logger.debug(f"[Dribble] cmd=({vx:.2f},{vy:.2f},{vw:.2f}) ball=({b_x:.2f},{b_y:.2f})")
    agent.cmd_vel(vx, vy, vw)


# Keep old function names for compatibility with state machines
def _playing_logic(agent):
    """Fallback: basic playing without GameController."""
    if not agent.get_if_ball():
        agent.state_machine_runners['find_ball']()
        return
    if agent.get_ball_distance() > agent.default_chase_distance:
        agent.state_machine_runners['chase_ball']()
        return
    _dribble_towards_goal(agent)
