# routes.py
from flask import render_template, jsonify, Response
import io, time
import RPi.GPIO as GPIO

from logger import log, log_buffer
from config import sensor_data, led_pin, motor_states, MOTOR_GROUPS, led_state
from calibration import calib, cal_lock, save_calib
from motors import motor
import sensors   # ensures sensor loop is running
from camera_module import generate_frames

# This function will be called by main.py to attach routes to the Flask app.
def init_app(app):

    @app.route("/")
    def index():
        # serve the index.html from templates (static assets from web/static)
        return render_template("index.html")

    @app.route("/status")
    def status():
        return jsonify({'sensor': sensor_data})

    @app.route("/logs")
    def logs():
        return "<br>".join(log_buffer)

    @app.route("/toggle_led")
    def toggle_led():
        # update global led state in config
        # import inside function to avoid circular import issues on reload
        from config import led_state as _led_state_var
        # we must update mutable in config module
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
        return "Horizon Zeroed"

    @app.route("/zero_imu")
    def zero_imu():
        import sensors as s
        global_vars_changed_msg = ""
        with cal_lock:
            if not s.imu_offsets_enabled:
                # expected gravity vector along Z in body frame? original assumed X; keep original semantics:
                expected = {'x': 0.0, 'y': 0.0, 'z': 1.0}

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
                msg = "IMU calibration offsets applied (gravity aligned to X)"
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
        state = motor.toggle(name)
        motor_states[name] = state
        return jsonify({"group": name, "state": state})

    @app.route("/motor_status")
    def motor_status():
        return jsonify(motor_states)

    @app.route("/cal_depth")
    def cal_depth():
        with cal_lock:
            calib['depth_zero_ft'] = sensor_data['depth_ft']
        save_calib()
        return "Surface Set"

    @app.route("/video_feed")
    def video_feed():
        return Response(generate_frames(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
