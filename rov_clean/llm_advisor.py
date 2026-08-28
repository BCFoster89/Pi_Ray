# llm_advisor.py
"""
Advisory-only bridge from ROV telemetry to a Routron (ComputeRouter) LLM
proxy. Polls a redacted slice of sensor_data on a slow interval, asks a
routine low-priority question most ticks and escalates to a high-priority
question when a locally-cheap check (magnetometer anomaly) fires, and
stores the result for the HUD/logs to display.

This controller has NO get_output() and is never read by motor_pwm() in
routes.py — it cannot influence motor commands, by construction. Routron
gives no response-time guarantee (a cold local model can take up to two
minutes), so nothing here may sit in the motor command path.
"""

import os
import time
import threading
import requests
from logger import log
from config import sensor_data

ROUTER_URL = "http://localhost:8000/v1/chat/completions"

# Sustained/large magnetometer deviation (µT) that promotes a tick from a
# routine local query to a high-priority cloud-escalation query.
MAG_ANOMALY_ESCALATE_UT = 15.0

# Only needed if Routron's config has auth.enabled: true. Set the same value
# Routron was started with: export COMPUTEROUTER_AUTH_TOKEN=... before
# running main.py. Matches the convention already used in Routron's own
# test_client.py.
AUTH_TOKEN = os.environ.get("COMPUTEROUTER_AUTH_TOKEN")


def _auth_headers():
    return {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}


class LLMAdvisorController:
    """Polls sensor_data, queries Routron, stores the result. Advisory only."""

    def __init__(self, router_url=ROUTER_URL, poll_interval_s=10.0):
        self.router_url = router_url
        self.poll_interval_s = poll_interval_s

        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        self.enabled = False
        self.last_query_time = 0.0
        self.last_rung = None
        self.last_rung_name = None
        self.last_response_text = ""
        self.last_error = None

        # E-stop callback: set by routes.py to check E-stop state.
        # Avoids a circular import (llm_advisor -> motors -> config -> ...).
        self._estop_check_fn = None

    def set_estop_check(self, fn):
        """Register a function that returns True if E-stop is engaged."""
        self._estop_check_fn = fn

    def enable(self):
        with self._lock:
            if self.enabled:
                return
            self.enabled = True
            self._running = True
            self._thread = threading.Thread(target=self._advisor_loop, daemon=True)
            self._thread.start()
            log("[LLM] Advisor ENABLED")

    def disable(self):
        with self._lock:
            if not self.enabled:
                return
            self.enabled = False
            self._running = False
            log("[LLM] Advisor DISABLED")

    def _advisor_loop(self):
        while self._running:
            try:
                if not (self._estop_check_fn and self._estop_check_fn()):
                    self._run_query()
            except Exception as e:
                log(f"[LLM] Advisor loop error: {e}")
            time.sleep(self.poll_interval_s)

    def _build_query(self):
        """
        Build a redacted telemetry line and pick priority/complexity.

        Only an explicit allow-list of fields is ever included. Position and
        velocity fields (dr_x, dr_y, dr_vx, dr_vy) are never sent, local or
        cloud — Routron forwards message content verbatim to whichever rung
        it picks, and this module cannot control that choice, so the safest
        rule is to never include them at all.
        """
        depth_ft = sensor_data.get('depth_ft', 0.0)
        temperature_f = sensor_data.get('temperature_f', 'ERR')
        roll = sensor_data.get('roll', 0.0)
        pitch = sensor_data.get('pitch', 0.0)
        yaw = sensor_data.get('yaw', 0.0)
        mag_anomaly = sensor_data.get('mag_anomaly', 0.0)
        mag_ok = sensor_data.get('mag_ok', False)

        if mag_ok and abs(mag_anomaly) >= MAG_ANOMALY_ESCALATE_UT:
            accel_x = sensor_data.get('accel_x', 0.0)
            accel_y = sensor_data.get('accel_y', 0.0)
            accel_z = sensor_data.get('accel_z', 0.0)
            gyro_x = sensor_data.get('gyro_x', 0.0)
            gyro_y = sensor_data.get('gyro_y', 0.0)
            gyro_z = sensor_data.get('gyro_z', 0.0)
            line = (
                f"DEPTH_FT={depth_ft:.2f} ROLL_DEG={roll:.1f} PITCH_DEG={pitch:.1f} "
                f"YAW_DEG={yaw:.1f} MAG_ANOMALY_UT={mag_anomaly:.1f} "
                f"ACCEL_XYZ=({accel_x:.2f},{accel_y:.2f},{accel_z:.2f}) "
                f"GYRO_XYZ=({gyro_x:.2f},{gyro_y:.2f},{gyro_z:.2f})"
            )
            question = (
                "A magnetometer anomaly was detected alongside this multi-sensor "
                "reading. Briefly assess whether the readings together look "
                "consistent with a nearby ferrous object versus a vehicle attitude "
                "or depth problem, and what (if anything) the operator should check."
            )
            return line, question, "high", "high"

        line = f"DEPTH_FT={depth_ft:.2f} TEMP_F={temperature_f} ROLL_DEG={roll:.1f} PITCH_DEG={pitch:.1f}"
        question = "Summarize the current depth and attitude in one short sentence."
        return line, question, "low", "low"

    def _run_query(self):
        line, question, priority, complexity = self._build_query()
        timeout = 5 if priority == "low" else 30
        payload = {
            "messages": [
                {"role": "user", "content": f"{question} Telemetry: {line}"}
            ],
            "priority": priority,
            "complexity": complexity,
            "max_tokens": 100,
        }

        try:
            r = requests.post(self.router_url, json=payload, headers=_auth_headers(), timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                with self._lock:
                    self.last_query_time = time.time()
                    self.last_rung = r.headers.get("X-Compute-Rung")
                    self.last_rung_name = r.headers.get("X-Compute-Rung-Name")
                    self.last_response_text = text
                    self.last_error = None
            else:
                with self._lock:
                    self.last_error = f"HTTP {r.status_code}"
                log(f"[LLM] Advisor request failed: HTTP {r.status_code}")
        except requests.exceptions.Timeout:
            with self._lock:
                self.last_error = "timeout"
            log("[LLM] Advisor request timed out")
        except requests.exceptions.ConnectionError:
            with self._lock:
                self.last_error = "connection error"
            log("[LLM] Advisor connection error - is Routron running?")
        except Exception as e:
            with self._lock:
                self.last_error = str(e)
            log(f"[LLM] Advisor request error: {e}")

    def get_status(self):
        with self._lock:
            estop_active = bool(self._estop_check_fn and self._estop_check_fn())
            return {
                "enabled": self.enabled,
                "advisory_active": self.enabled and not estop_active,
                "last_query_time": self.last_query_time,
                "last_rung": self.last_rung,
                "last_rung_name": self.last_rung_name,
                "last_response_text": self.last_response_text,
                "last_error": self.last_error,
            }


# Global instance
advisor_controller = LLMAdvisorController()
