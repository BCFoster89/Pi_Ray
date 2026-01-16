from flask import render_template, jsonify, Response
import io, time
import RPi.GPIO as GPIO
from logger import log, log_buffer
from config import sensor_data, led_pin, motor_states, MOTOR_GROUPS
from calibration import calib, cal_lock, save_calib
from motors import motor
import sensors   # ensure sensor loop is running
from picamera2 import Picamera2

cam = None  # gets initialized in main.py

def init_app(app):
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/status")
    def status():
        return jsonify({"sensor": sensor_data})

    @app.route("/logs")
    def logs():
        return "<br>".join(log_buffer)

    @app.route("/toggle_led")
    def toggle_led():
        from config import led_state
        new_state = not led_state
        GPIO.output(led_pin, GPIO.HIGH if new_state else GPIO.LOW)
        log(f"[LED] {'ON' if new_state else 'OFF'}")
        return "OK"

    @app.route("/cal_depth")
    def cal_depth():
        with cal_lock:
            calib["depth_zero_ft"] = sensor_data["depth_ft"]
        save_calib()
        return "Surface Set"

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

    @app.route("/video_feed")
    def video_feed():
        def gen():
            global cam
            if not cam:
                cam = Picamera2()
                vc = cam.create_video_configuration(main={"size": (1280, 720)}, controls={"FrameRate": 30})
                cam.configure(vc)
                cam.start()
            stream = io.BytesIO()
            while True:
                try:
                    cam.capture_file(stream, format="jpeg")
                    stream.seek(0)
                    frame = stream.read()
                    stream.seek(0)
                    stream.truncate()
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                    time.sleep(1 / 30)
                except:
                    time.sleep(1)
        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
