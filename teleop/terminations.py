"""
terminations.py  -  Unitree's G1 safety checks, ported from the C++ SDK

Source: unitree_sdk2/include/unitree/robot/g1/common/terminations.hpp (unitree_sdk2 07493e4).
Each check reads one message and returns True when the robot should stop being driven.
Unitree's advice when one trips is to put the motors in passive mode. Our scripts don't
use low-level control, so for them it means: hand the arms back to the robot's own
controller (arm_sdk weight to 0) and stop walking.

  bad_orientation(lowstate)         body tilted more than 1.0 rad (57°) from upright
  joint_vel_out_of_limit(lowstate)  any motor turning faster than 10 rad/s
  ang_vel_out_of_limit(lowstate)    the body rotating faster than 6 rad/s about any axis
  motor_winding_overheat(lowstate)  any motor coil above 120 °C
  motor_casing_overheat(lowstate)   any motor case above 85 °C
  low_battery(bms_state)            charge below 20 %
  lost_connection(last_time)        no message for 1 s

readings(lowstate) -> the five rt/lowstate values; check(readings) -> what tripped.

Differences from the C++:
  - lost_connection takes the time.monotonic() of the last message, because the Python
    ChannelSubscriber doesn't keep one.
  - A reading that can't be trusted counts as a trip: an all-zero IMU quaternion (no
    orientation yet) or a NaN. The C++ treats an all-zero quaternion as upright.

Pure logic, no robot or network code, so all of it can be checked on the VM.
"""

import math
import time

# Unitree's default limits from terminations.hpp
LIMITS = {
    "tilt":         1.0,     # rad between the body's up axis and vertical (57°)
    "joint_speed":  10.0,    # rad/s, fastest motor
    "spin":         6.0,     # rad/s, fastest IMU gyro axis
    "winding_temp": 120.0,   # °C, hottest motor coil  (MotorState_.temperature[1])
    "casing_temp":  85.0,    # °C, hottest motor case  (MotorState_.temperature[0])
}
LOW_BATTERY_SOC = 20.0       # %
LOST_CONNECTION_MS = 1000


# ── readings ─────────────────────────────────────────────────────────────────
def tilt(lowstate) -> float:
    """Angle (rad) between the body's up axis and vertical, from the IMU quaternion
    (w, x, y, z). NaN when the quaternion is all zero."""
    w, x, y, z = lowstate.imu_state.quaternion
    norm2 = w * w + x * x + y * y + z * z
    if norm2 == 0.0:
        return math.nan
    # the z of world "down" seen in the body frame, as the C++ computes it with Eigen
    cos_tilt = (w * w + z * z - x * x - y * y) / norm2
    return math.acos(min(1.0, max(-1.0, cos_tilt)))


def _largest(values) -> float:
    """max(), except that any NaN makes the result NaN (Python's max skips a NaN that isn't first)."""
    values = list(values)
    return math.nan if any(math.isnan(v) for v in values) else max(values)


def joint_speed(lowstate) -> float:
    return _largest(abs(m.dq) for m in lowstate.motor_state)


def spin(lowstate) -> float:
    return _largest(abs(g) for g in lowstate.imu_state.gyroscope)


def winding_temp(lowstate) -> float:
    return _largest(m.temperature[1] for m in lowstate.motor_state)


def casing_temp(lowstate) -> float:
    return _largest(m.temperature[0] for m in lowstate.motor_state)


def readings(lowstate) -> dict:
    return {"tilt": tilt(lowstate), "joint_speed": joint_speed(lowstate), "spin": spin(lowstate),
            "winding_temp": winding_temp(lowstate), "casing_temp": casing_temp(lowstate)}


# ── Unitree's checks, same names and default limits as terminations.hpp ──────
# Written as "not value <= limit" so that a NaN reading trips too.
def bad_orientation(lowstate, limit_angle: float = LIMITS["tilt"]) -> bool:
    return not tilt(lowstate) <= limit_angle


def joint_vel_out_of_limit(lowstate, limit_vel: float = LIMITS["joint_speed"]) -> bool:
    return not joint_speed(lowstate) <= limit_vel


def ang_vel_out_of_limit(lowstate, limit_vel: float = LIMITS["spin"]) -> bool:
    return not spin(lowstate) <= limit_vel


def motor_winding_overheat(lowstate, limit_temp: float = LIMITS["winding_temp"]) -> bool:
    return not winding_temp(lowstate) <= limit_temp


def motor_casing_overheat(lowstate, limit_temp: float = LIMITS["casing_temp"]) -> bool:
    return not casing_temp(lowstate) <= limit_temp


def low_battery(bms_state, limit_soc: float = LOW_BATTERY_SOC) -> bool:
    """bms_state: unitree_hg BmsState_."""
    return bms_state.soc < limit_soc


def lost_connection(last_time: float, timeout_ms: float = LOST_CONNECTION_MS, now: float = None) -> bool:
    """last_time: time.monotonic() when the last message arrived. Unitree's note: on a wired
    connection a loose cable can drop messages, and a program that keeps sending commands
    through the gap can make the motors jump when it comes back."""
    now = time.monotonic() if now is None else now
    return (now - last_time) * 1000.0 > timeout_ms


# ── all of them at once ──────────────────────────────────────────────────────
_MESSAGES = {
    "tilt":         "body tilted {:.1f}° from upright (limit {:.1f}°)",
    "joint_speed":  "a joint turned at {:.1f} rad/s (limit {:g})",
    "spin":         "body rotated at {:.1f} rad/s (limit {:g})",
    "winding_temp": "a motor coil reached {:.0f} °C (limit {:g})",
    "casing_temp":  "a motor case reached {:.0f} °C (limit {:g})",
}


def check(values: dict, limits: dict = LIMITS) -> dict:
    """values from readings(). Returns {name: what tripped} for each check that tripped,
    so an empty dict means all clear."""
    trips = {}
    for name, value in values.items():
        limit = limits[name]
        if value <= limit:
            continue
        if math.isnan(value):
            trips[name] = "no IMU orientation (all-zero quaternion)" if name == "tilt" else f"{name} reading is NaN"
        elif name == "tilt":
            trips[name] = _MESSAGES[name].format(math.degrees(value), math.degrees(limit))
        else:
            trips[name] = _MESSAGES[name].format(value, limit)
    return trips


def summary(values: dict) -> str:
    """One line for a status print."""
    return (f"tilt {math.degrees(values['tilt']):.0f}°, fastest joint {values['joint_speed']:.1f} rad/s, "
            f"rotation {values['spin']:.1f} rad/s, hottest motor {values['casing_temp']:.0f} °C case / "
            f"{values['winding_temp']:.0f} °C coil")
