# position_hold.py
import time
import threading
from logger import log
from config import sensor_data

# Accuracy note: Without an external position reference (DVL, USBL, GPS), this is
# velocity-damping station keeping. It opposes measured velocity to slow drift.
# Effective for ~15–30 seconds before accelerometer integration error dominates.


class _AxisPID:
    """Simple PID for a single axis."""
    def __init__(self, kp, ki, kd, max_out=0.6, integral_limit=5.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.max_out = max_out
        self.integral_limit = integral_limit
        self.integral = 0.0
        self.last_error = 0.0

    def reset(self):
        self.integral = 0.0
        self.last_error = 0.0

    def compute(self, error, dt):
        self.integral += error * dt
        self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))
        derivative = (error - self.last_error) / dt if dt > 0 else 0.0
        self.last_error = error
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        return max(-self.max_out, min(self.max_out, output))


class PositionHoldController:
    """
    Velocity-damping station keeping.

    Reads dead-reckoning velocity from sensor_data (dr_vx, dr_vy) and commands
    surge/sway to oppose it. This minimises drift rather than holding a fixed XY
    coordinate, and degrades gracefully as DR error accumulates.
    """

    def __init__(self, kp=0.8, ki=0.0, kd=0.1):
        self._surge_pid = _AxisPID(kp, ki, kd)
        self._sway_pid  = _AxisPID(kp, ki, kd)

        self.enabled = False
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        self.surge_output = 0.0
        self.sway_output  = 0.0
        self.last_time = time.time()

        self._estop_check_fn = None

    def set_estop_check(self, fn):
        self._estop_check_fn = fn

    def set_gains(self, kp=None, ki=None, kd=None):
        with self._lock:
            for pid in (self._surge_pid, self._sway_pid):
                if kp is not None:
                    pid.kp = kp
                if ki is not None:
                    pid.ki = ki
                if kd is not None:
                    pid.kd = kd
            log(f"[POSHOLD] PID gains updated: Kp={self._surge_pid.kp}")

    def enable(self):
        with self._lock:
            if self.enabled:
                return
            self._surge_pid.reset()
            self._sway_pid.reset()
            self.last_time = time.time()
            self.enabled = True
            self._running = True
            self._thread = threading.Thread(target=self._control_loop, daemon=True)
            self._thread.start()
            log("[POSHOLD] Position hold ENABLED (velocity damping)")

    def disable(self):
        with self._lock:
            if not self.enabled:
                return
            self.enabled = False
            self._running = False
            self.surge_output = 0.0
            self.sway_output  = 0.0
            log("[POSHOLD] Position hold DISABLED")

    def _control_loop(self):
        while self._running:
            try:
                self._update()
            except Exception as e:
                log(f"[POSHOLD] Control loop error: {e}")
            time.sleep(0.05)

    def _update(self):
        with self._lock:
            if not self.enabled:
                return

            if self._estop_check_fn and self._estop_check_fn():
                self.surge_output = self.sway_output = 0.0
                return

            now = time.time()
            dt = now - self.last_time
            self.last_time = now
            if dt <= 0 or dt > 1.0:
                dt = 0.05

            # Velocity error: we want vx=0, vy=0
            vx = sensor_data.get('dr_vx', 0.0)
            vy = sensor_data.get('dr_vy', 0.0)

            # Oppose current velocity (negative feedback)
            self.surge_output = self._surge_pid.compute(-vx, dt)
            self.sway_output  = self._sway_pid.compute(-vy, dt)

    def get_output(self):
        with self._lock:
            return (self.surge_output, self.sway_output)

    def get_status(self):
        with self._lock:
            return {
                "enabled": self.enabled,
                "surge_output": round(self.surge_output, 3),
                "sway_output":  round(self.sway_output, 3),
                "dr_vx": round(sensor_data.get('dr_vx', 0.0), 3),
                "dr_vy": round(sensor_data.get('dr_vy', 0.0), 3),
                "dr_x":  round(sensor_data.get('dr_x', 0.0), 2),
                "dr_y":  round(sensor_data.get('dr_y', 0.0), 2),
                "kp": self._surge_pid.kp,
                "ki": self._surge_pid.ki,
                "kd": self._surge_pid.kd,
            }


position_controller = PositionHoldController()
