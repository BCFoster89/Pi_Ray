# dead_reckoning.py
import threading
import numpy as np

_G = 9.80665  # m/s²


class DeadReckoningEstimator:
    """
    Server-side dead reckoning using quaternion rotation to transform body-frame
    accelerometer readings into world-frame (NED) velocity and position.

    Integrates at 20Hz with velocity damping to limit unbounded drift.
    Accuracy degrades over time without an external position fix (~0.5–2 m/min drift).
    """

    def __init__(self):
        self.x = 0.0       # North displacement (m)
        self.y = 0.0       # East displacement (m)
        self.vx = 0.0      # North velocity (m/s)
        self.vy = 0.0      # East velocity (m/s)
        self.damping = 0.95
        self.deadzone = 0.05   # m/s² — below this, accel treated as zero
        self._lock = threading.Lock()

    def update(self, q, ax_g, ay_g, az_g, dt):
        """
        q       : quaternion [w, x, y, z] representing body→world rotation (NED)
        ax/ay/az: accelerometer in g (body frame, with gravity)
        dt      : seconds since last call
        """
        if dt <= 0 or dt > 0.5:
            return

        # Body-frame accel in m/s²
        a_body = np.array([ax_g * _G, ay_g * _G, az_g * _G])

        # Rotation matrix from quaternion (body → world, NED convention)
        w, x, y, z = q
        R = np.array([
            [1 - 2*(y*y + z*z),  2*(x*y - w*z),      2*(x*z + w*y)],
            [2*(x*y + w*z),       1 - 2*(x*x + z*z),  2*(y*z - w*x)],
            [2*(x*z - w*y),       2*(y*z + w*x),      1 - 2*(x*x + y*y)],
        ])

        # World-frame accel; remove gravity (NED: gravity is +9.81 on Z/Down axis)
        a_world = R @ a_body
        a_world[2] -= _G

        with self._lock:
            # Apply deadzone on horizontal axes only
            axw = a_world[0] if abs(a_world[0]) > self.deadzone else 0.0
            ayw = a_world[1] if abs(a_world[1]) > self.deadzone else 0.0

            # Velocity integration with damping
            self.vx = (self.vx + axw * dt) * self.damping
            self.vy = (self.vy + ayw * dt) * self.damping

            # Position integration
            self.x += self.vx * dt
            self.y += self.vy * dt

    def reset(self):
        with self._lock:
            self.x = self.y = self.vx = self.vy = 0.0

    def set_params(self, damping=None, deadzone=None):
        with self._lock:
            if damping is not None:
                self.damping = max(0.5, min(1.0, float(damping)))
            if deadzone is not None:
                self.deadzone = max(0.0, min(2.0, float(deadzone)))

    def get_state(self):
        with self._lock:
            return {
                'dr_x':  round(self.x,  3),
                'dr_y':  round(self.y,  3),
                'dr_vx': round(self.vx, 3),
                'dr_vy': round(self.vy, 3),
            }


# Module-level singleton used by sensors.py and routes.py
dr_estimator = DeadReckoningEstimator()
