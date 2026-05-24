# heading_hold.py
import time
import threading
from logger import log
from config import sensor_data


class HeadingHoldController:
    """
    PID controller for maintaining a target magnetic heading.

    Uses the Madgwick-fused yaw (degrees, -180 to +180) as the process variable.
    Output is a yaw command in [-1.0, +1.0] that overrides the manual yaw stick.

    Heading wrap-around is handled by normalising error to [-180, +180].
    """

    def __init__(self, kp=1.5, ki=0.05, kd=0.3):
        self.kp = kp
        self.ki = ki
        self.kd = kd

        self.target_heading = 0.0
        self.enabled = False

        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = time.time()

        self.max_output = 0.8
        self.deadband = 2.0      # degrees — no correction within ±2°

        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        self.yaw_output = 0.0

        self._estop_check_fn = None

    def set_estop_check(self, fn):
        self._estop_check_fn = fn

    def set_gains(self, kp=None, ki=None, kd=None):
        with self._lock:
            if kp is not None:
                self.kp = kp
            if ki is not None:
                self.ki = ki
            if kd is not None:
                self.kd = kd
            log(f"[HEADING] PID gains updated: Kp={self.kp}, Ki={self.ki}, Kd={self.kd}")

    def set_target(self, heading_deg):
        with self._lock:
            self.target_heading = float(heading_deg)
            self.integral = 0.0
            log(f"[HEADING] Target heading set to {heading_deg:.1f}°")

    def enable(self):
        with self._lock:
            if self.enabled:
                return
            self.target_heading = sensor_data.get('yaw', 0.0)
            self.integral = 0.0
            self.last_error = 0.0
            self.last_time = time.time()
            self.enabled = True
            self._running = True
            self._thread = threading.Thread(target=self._control_loop, daemon=True)
            self._thread.start()
            log(f"[HEADING] Heading hold ENABLED at {self.target_heading:.1f}°")

    def disable(self):
        with self._lock:
            if not self.enabled:
                return
            self.enabled = False
            self._running = False
            self.yaw_output = 0.0
            log("[HEADING] Heading hold DISABLED")

    def _control_loop(self):
        while self._running:
            try:
                self._update()
            except Exception as e:
                log(f"[HEADING] Control loop error: {e}")
            time.sleep(0.05)

    def _update(self):
        with self._lock:
            if not self.enabled:
                return

            if self._estop_check_fn and self._estop_check_fn():
                self.yaw_output = 0.0
                return

            current = sensor_data.get('yaw', 0.0)

            # Heading error normalised to [-180, +180]
            error = self.target_heading - current
            error = (error + 180.0) % 360.0 - 180.0

            if abs(error) < self.deadband:
                error = 0.0
                self.integral = 0.0

            now = time.time()
            dt = now - self.last_time
            self.last_time = now
            if dt <= 0 or dt > 1.0:
                dt = 0.05

            p_term = self.kp * error

            self.integral += error * dt
            self.integral = max(-10.0, min(10.0, self.integral))
            i_term = self.ki * self.integral

            derivative = (error - self.last_error) / dt
            d_term = self.kd * derivative
            self.last_error = error

            output = p_term + i_term + d_term
            self.yaw_output = max(-self.max_output, min(self.max_output, output / 180.0))

    def get_output(self):
        with self._lock:
            return self.yaw_output

    def get_status(self):
        with self._lock:
            current = sensor_data.get('yaw', 0.0)
            error = self.target_heading - current
            error = (error + 180.0) % 360.0 - 180.0
            return {
                "enabled": self.enabled,
                "target_heading": round(self.target_heading, 1),
                "current_heading": round(current, 1),
                "error": round(error, 1),
                "yaw_output": round(self.yaw_output, 3),
                "kp": self.kp,
                "ki": self.ki,
                "kd": self.kd,
            }


heading_controller = HeadingHoldController()
