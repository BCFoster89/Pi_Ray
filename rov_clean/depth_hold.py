# depth_hold.py
"""
PID-based depth hold controller for ROV.
Uses pressure sensor depth reading as input and controls descend/ascend motors.
"""

import time
import threading
from logger import log
from config import sensor_data

class DepthHoldController:
    """
    PID controller for maintaining target depth.

    Positive error (too shallow) -> increase descend
    Negative error (too deep) -> increase ascend
    """

    def __init__(self, kp=0.5, ki=0.1, kd=0.2):
        # PID gains (tunable)
        self.kp = kp  # Proportional gain
        self.ki = ki  # Integral gain
        self.kd = kd  # Derivative gain

        # Controller state
        self.target_depth = 0.0
        self.enabled = False

        # PID internal state
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = time.time()

        # Output limits
        self.max_output = 0.8  # Max motor duty (80% to prevent aggressive corrections)
        self.deadband = 0.1   # Depth deadband in feet (no correction within this range)

        # Thread control
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        # Current output values
        self.descend_output = 0.0
        self.ascend_output = 0.0

    def set_gains(self, kp=None, ki=None, kd=None):
        """Update PID gains."""
        with self._lock:
            if kp is not None:
                self.kp = kp
            if ki is not None:
                self.ki = ki
            if kd is not None:
                self.kd = kd
            log(f"[DEPTH] PID gains updated: Kp={self.kp}, Ki={self.ki}, Kd={self.kd}")

    def set_target(self, depth_ft):
        """Set target depth in feet."""
        with self._lock:
            self.target_depth = depth_ft
            # Reset integral to prevent windup when target changes
            self.integral = 0.0
            log(f"[DEPTH] Target depth set to {depth_ft:.2f} ft")

    def enable(self):
        """Enable depth hold at current depth."""
        with self._lock:
            if self.enabled:
                return

            # Set target to current depth
            current_depth = sensor_data.get('depth_ft', 0.0)
            self.target_depth = current_depth

            # Reset PID state
            self.integral = 0.0
            self.last_error = 0.0
            self.last_time = time.time()

            self.enabled = True
            self._running = True

            # Start background thread
            self._thread = threading.Thread(target=self._control_loop, daemon=True)
            self._thread.start()

            log(f"[DEPTH] Depth hold ENABLED at {current_depth:.2f} ft")

    def go_to_depth(self, target_ft):
        """
        Go to a specific target depth.
        Enables depth hold and drives to the specified depth.
        """
        with self._lock:
            was_enabled = self.enabled

            # Set the target depth
            self.target_depth = target_ft

            # Reset PID state for fresh start
            self.integral = 0.0
            self.last_error = 0.0
            self.last_time = time.time()

            if not was_enabled:
                self.enabled = True
                self._running = True

                # Start background thread
                self._thread = threading.Thread(target=self._control_loop, daemon=True)
                self._thread.start()

            current_depth = sensor_data.get('depth_ft', 0.0)
            log(f"[DEPTH] Go to depth: {target_ft:.2f} ft (current: {current_depth:.2f} ft)")

    def disable(self):
        """Disable depth hold and return to manual control."""
        with self._lock:
            if not self.enabled:
                return

            self.enabled = False
            self._running = False
            self.descend_output = 0.0
            self.ascend_output = 0.0

            log("[DEPTH] Depth hold DISABLED")

    def _control_loop(self):
        """Background thread that runs the PID control loop at 20Hz."""
        while self._running:
            try:
                self._update()
            except Exception as e:
                log(f"[DEPTH] Control loop error: {e}")
            time.sleep(0.05)  # 20Hz update rate

    def _update(self):
        """Calculate PID output based on current depth error."""
        with self._lock:
            if not self.enabled:
                return

            # Get current depth
            current_depth = sensor_data.get('depth_ft', 0.0)

            # Calculate error (positive = too shallow, need to descend)
            error = self.target_depth - current_depth

            # Apply deadband
            if abs(error) < self.deadband:
                error = 0.0
                self.integral = 0.0  # Reset integral within deadband

            # Time delta
            now = time.time()
            dt = now - self.last_time
            self.last_time = now

            # Prevent division by zero or huge jumps
            if dt <= 0 or dt > 1.0:
                dt = 0.05

            # PID calculations
            # Proportional
            p_term = self.kp * error

            # Integral (with anti-windup)
            self.integral += error * dt
            self.integral = max(-2.0, min(2.0, self.integral))  # Clamp integral
            i_term = self.ki * self.integral

            # Derivative
            derivative = (error - self.last_error) / dt
            d_term = self.kd * derivative
            self.last_error = error

            # Total output
            output = p_term + i_term + d_term

            # Convert output to motor commands
            # Positive output = need to descend (go deeper)
            # Negative output = need to ascend (go shallower)
            if output > 0:
                self.descend_output = min(output, self.max_output)
                self.ascend_output = 0.0
            else:
                self.descend_output = 0.0
                self.ascend_output = min(-output, self.max_output)

    def get_output(self):
        """Get current descend/ascend output values."""
        with self._lock:
            return (self.descend_output, self.ascend_output)

    def get_status(self):
        """Return full status for API."""
        with self._lock:
            current_depth = sensor_data.get('depth_ft', 0.0)
            return {
                "enabled": self.enabled,
                "target_depth": round(self.target_depth, 2),
                "current_depth": round(current_depth, 2),
                "error": round(self.target_depth - current_depth, 2),
                "descend_output": round(self.descend_output, 3),
                "ascend_output": round(self.ascend_output, 3),
                "kp": self.kp,
                "ki": self.ki,
                "kd": self.kd
            }

# Global instance
depth_controller = DepthHoldController()
