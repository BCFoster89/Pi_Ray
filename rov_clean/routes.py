# routes.py
from flask import render_template, jsonify, Response, request, send_from_directory
import io, time, os
import RPi.GPIO as GPIO

from logger import log, log_buffer
from config import sensor_data, led_pin, motor_states, MOTOR_GROUPS, led_state, pwm_state
from calibration import calib, cal_lock, save_calib
from motors import motor, pwm_motor
import sensors   # ensures sensor loop is running
from camera_module import (
    generate_frames, capture_still, start_recording, stop_recording,
    get_recording_status, list_recordings, list_images,
    RECORDINGS_DIR, IMAGES_DIR
)
from depth_hold import depth_controller

# Wire depth hold to respect E-stop state (avoids circular import)
depth_controller.set_estop_check(pwm_motor.get_estop_state)

# This function will be called by main.py to attach routes to the Flask app.
def init_app(app):

    @app.route("/")
    def index():
        # serve the index.html from templates (static assets from web/static)
        return render_template("index.html")

    @app.route("/status")
    def status():
        return jsonify({'sensor': sensor_data})



    @app.route("/heartbeat")
    def heartbeat():
        # Record heartbeat time so the watchdog knows the controller is alive
        pwm_motor.record_heartbeat()
        return "OK"


    @app.route("/logs")
    def logs():
        return "<br>".join(log_buffer)

# inside init_app(app) alongside other routes
    @app.route("/motor/all_stop")
    def motor_all_stop():
        # Stop PWM motors first (this LATCHES the E-stop)
        try:
            pwm_motor.emergency_stop()
        except Exception as e:
            log(f"[MOTOR] PWM emergency stop failed: {e}")

        # Disable depth hold so PID doesn't fight the E-stop
        try:
            depth_controller.disable()
        except Exception as e:
            log(f"[MOTOR] Depth hold disable failed during E-stop: {e}")

        # Also turn off any legacy groups currently reported as "on"
        stopped = []
        for name, state in list(motor_states.items()):
            if state == "on":
                try:
                    result = motor.toggle(name)
                    if result == "off":
                        motor_states[name] = "off"
                        stopped.append(name)
                except Exception as e:
                    log(f"[MOTOR] failed stopping {name}: {e}")
        return jsonify({"stopped": stopped, "pwm_stopped": True, "estop_locked": True})

    @app.route("/motor/estop_release", methods=["POST"])
    def estop_release():
        """Release the E-stop latch. Requires explicit action — not automatic."""
        released = pwm_motor.estop_release()
        if released:
            return jsonify({"success": True, "estop_locked": False})
        else:
            return jsonify({"success": False, "message": "E-stop was not engaged"})

    @app.route("/motor/estop_status")
    def estop_status():
        """Return current E-stop state for UI polling."""
        return jsonify({"estop_locked": pwm_motor.get_estop_state()})

    @app.route("/toggle_led")
    def toggle_led():
        # Update LED state in config module
        import config as cfg
        cfg.led_state = not cfg.led_state
        GPIO.output(led_pin, GPIO.HIGH if cfg.led_state else GPIO.LOW)
        log(f"[LED] {'ON' if cfg.led_state else 'OFF'}")
        return "OK"

    @app.route("/cal_horizon")
    def cal_horizon():
        # reset integrated orientation and zero offsets
        import sensors as s
        with cal_lock:
            s.roll_i = s.pitch_i = s.yaw_i = 0.0
            s.roll_f = s.pitch_f = s.yaw_f = 0.0
            calib['roll_offset'] = 0.0
            calib['pitch_offset'] = 0.0
            calib['yaw_offset'] = 0.0
            log("[CAL] Zero Horizon pressed")
        save_calib()
        return "Horizon Zeroed"

    @app.route("/zero_imu")
    def zero_imu():
        import sensors as s
        with cal_lock:
            if not s.imu_offsets_enabled:
                # Expected gravity vector along Z axis in body frame (1g downward)
                expected = {'x': 0.0, 'y': 0.0, 'z': 1.0}

                # Note: sensor_data values may be up to one sensor cycle (50ms) stale
                # since sensor_data is updated by the sensor thread without cal_lock.
                # This is acceptable for a one-shot calibration operation.
                ax = sensor_data['accel_x']
                ay = sensor_data['accel_y']
                az = sensor_data['accel_z']

                s.accel_offsets['x'] = ax - expected['x']
                s.accel_offsets['y'] = ay - expected['y']
                s.accel_offsets['z'] = az - expected['z']

                s.gyro_offsets['x'] = sensor_data['gyro_x']
                s.gyro_offsets['y'] = sensor_data['gyro_y']
                s.gyro_offsets['z'] = sensor_data['gyro_z']

                s.imu_offsets_enabled = True
                msg = "IMU calibration offsets applied (gravity aligned to Z)"
            else:
                s.accel_offsets = {'x': 0.0, 'y': 0.0, 'z': 0.0}
                s.gyro_offsets  = {'x': 0.0, 'y': 0.0, 'z': 0.0}
                s.imu_offsets_enabled = False
                msg = "IMU calibration offsets cleared"

            # Reset orientation integration
            s.roll_i = s.pitch_i = s.yaw_i = 0.0
            s.roll_f = s.pitch_f = s.yaw_f = 0.0

        log("[CAL] Zero IMU pressed")
        return msg

    @app.route("/motor/<name>")
    def motor_toggle(name):
        if name not in MOTOR_GROUPS:
            return jsonify({"error": "Invalid motor group"}), 400
        result = motor.toggle(name)
        if result in ("on", "off"):
            motor_states[name] = result
        return jsonify({"group": name, "state": result})

    @app.route("/motor_status")
    def motor_status():
        return jsonify(motor_states)

    @app.route("/cal_depth")
    def cal_depth():
        with cal_lock:
            # Add current offset back to get raw depth, then set that as new zero
            calib['depth_zero_ft'] = sensor_data['depth_ft'] + calib['depth_zero_ft']
        save_calib()
        return "Surface Set"

    # ==========================================================================
    # PWM VECTORED THRUST CONTROL ENDPOINTS
    # ==========================================================================

    @app.route("/motor/pwm", methods=["POST"])
    def motor_pwm():
        """
        Receive axis values from controller and set motor PWM duty cycles.

        Expected JSON body:
        {
            "surge": 0.0,    # -1.0 to 1.0 (forward/back from left stick Y)
            "sway": 0.0,     # -1.0 to 1.0 (strafe from left stick X)
            "yaw": 0.0,      # -1.0 to 1.0 (rotation from right stick X)
            "descend": 0.0,  # 0.0 to 1.0 (left trigger - descend intensity)
            "ascend": 0.0    # 0.0 to 1.0 (right trigger - ascend intensity)
        }

        When depth hold is enabled, descend/ascend values are overridden by PID output.
        Returns zeros immediately if E-stop is engaged.
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data received"}), 400

            surge = float(data.get('surge', 0.0))
            sway = float(data.get('sway', 0.0))
            yaw = float(data.get('yaw', 0.0))
            descend = float(data.get('descend', 0.0))
            ascend = float(data.get('ascend', 0.0))

            # Clamp values to valid range
            surge = max(-1.0, min(1.0, surge))
            sway = max(-1.0, min(1.0, sway))
            yaw = max(-1.0, min(1.0, yaw))
            descend = max(0.0, min(1.0, descend))  # 0-1 range for triggers
            ascend = max(0.0, min(1.0, ascend))    # 0-1 range for triggers

            # If depth hold is enabled, override descend/ascend with PID output
            if depth_controller.enabled:
                pid_descend, pid_ascend = depth_controller.get_output()
                descend = pid_descend
                ascend = pid_ascend

            # Set thrust vector and get resulting duty cycles
            # (returns zeros if E-stop is engaged)
            duties = pwm_motor.set_thrust_vector(surge, sway, yaw, descend, ascend)

            return jsonify({
                "success": True,
                "duties": {str(k): round(v, 3) for k, v in duties.items()},
                "depth_hold_active": depth_controller.enabled,
                "estop_locked": pwm_motor.get_estop_state()
            })

        except Exception as e:
            log(f"[PWM] Error processing PWM command: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/motor/pwm_status")
    def motor_pwm_status():
        """Return current PWM duty cycles for all motors."""
        try:
            status = pwm_motor.get_status()
            return jsonify({
                "duties": {str(k): round(v, 3) for k, v in status['duties'].items()},
                "descend": round(status['descend'], 3),
                "ascend": round(status['ascend'], 3),
                "active": status['active'],
                "last_update": status['last_update'],
                "control_mode": status['control_mode'],
                "estop_locked": status['estop_locked']
            })
        except Exception as e:
            log(f"[PWM] Error getting PWM status: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/video_feed")
    def video_feed():
        return Response(generate_frames(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')

    # ==========================================================================
    # STILL IMAGE CAPTURE
    # ==========================================================================

    @app.route("/capture_image", methods=["POST"])
    def capture_image():
        """Capture a high-resolution still image."""
        try:
            filename = capture_still()
            if filename:
                return jsonify({"success": True, "filename": filename})
            else:
                return jsonify({"success": False, "error": "Capture failed"}), 500
        except Exception as e:
            log(f"[CAM] Capture error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/images/<filename>")
    def serve_image(filename):
        """Serve a captured image file."""
        return send_from_directory(IMAGES_DIR, filename)

    @app.route("/images")
    def list_images_route():
        """List all captured images."""
        return jsonify({"images": list_images()})

    # ==========================================================================
    # VIDEO RECORDING
    # ==========================================================================

    @app.route("/recording/start", methods=["POST"])
    def recording_start():
        """Start video recording."""
        try:
            filename = start_recording()
            if filename:
                return jsonify({"success": True, "filename": filename})
            else:
                return jsonify({"success": False, "error": "Failed to start recording"}), 500
        except Exception as e:
            log(f"[CAM] Recording start error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/recording/stop", methods=["POST"])
    def recording_stop():
        """Stop video recording."""
        try:
            filename = stop_recording()
            if filename:
                return jsonify({"success": True, "filename": filename})
            else:
                return jsonify({"success": False, "error": "No recording in progress"}), 400
        except Exception as e:
            log(f"[CAM] Recording stop error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/recording/status")
    def recording_status():
        """Get current recording status."""
        return jsonify(get_recording_status())

    @app.route("/recordings/<filename>")
    def serve_recording(filename):
        """Serve a recorded video file."""
        return send_from_directory(RECORDINGS_DIR, filename)

    @app.route("/recordings")
    def list_recordings_route():
        """List all recorded videos."""
        return jsonify({"recordings": list_recordings()})

    # ==========================================================================
    # DEPTH HOLD PID CONTROL
    # ==========================================================================

    @app.route("/depth_hold/enable", methods=["POST"])
    def depth_hold_enable():
        """Enable depth hold at current depth."""
        try:
            # Don't allow depth hold while E-stop is engaged
            if pwm_motor.get_estop_state():
                return jsonify({"success": False, "error": "Cannot enable depth hold while E-stop is engaged"}), 400

            depth_controller.enable()
            status = depth_controller.get_status()
            return jsonify({"success": True, "status": status})
        except Exception as e:
            log(f"[DEPTH] Enable error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/depth_hold/disable", methods=["POST"])
    def depth_hold_disable():
        """Disable depth hold."""
        try:
            depth_controller.disable()
            return jsonify({"success": True})
        except Exception as e:
            log(f"[DEPTH] Disable error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/depth_hold/status")
    def depth_hold_status():
        """Get depth hold controller status."""
        return jsonify(depth_controller.get_status())

    @app.route("/depth_hold/tune", methods=["POST"])
    def depth_hold_tune():
        """Adjust PID gains with bounds checking."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data received"}), 400

            kp = data.get('kp')
            ki = data.get('ki')
            kd = data.get('kd')

            # Validate PID gain ranges to prevent dangerous oscillation
            PID_LIMITS = {'kp': (0.0, 5.0), 'ki': (0.0, 2.0), 'kd': (0.0, 5.0)}
            errors = []
            if kp is not None:
                kp = float(kp)
                lo, hi = PID_LIMITS['kp']
                if not (lo <= kp <= hi):
                    errors.append(f"Kp must be {lo}-{hi}, got {kp}")
            if ki is not None:
                ki = float(ki)
                lo, hi = PID_LIMITS['ki']
                if not (lo <= ki <= hi):
                    errors.append(f"Ki must be {lo}-{hi}, got {ki}")
            if kd is not None:
                kd = float(kd)
                lo, hi = PID_LIMITS['kd']
                if not (lo <= kd <= hi):
                    errors.append(f"Kd must be {lo}-{hi}, got {kd}")

            if errors:
                return jsonify({"error": "; ".join(errors)}), 400

            depth_controller.set_gains(kp=kp, ki=ki, kd=kd)

            return jsonify({"success": True, "status": depth_controller.get_status()})
        except Exception as e:
            log(f"[DEPTH] Tune error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
