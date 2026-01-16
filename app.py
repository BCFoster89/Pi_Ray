from flask import Flask, render_template, Response, jsonify, request
import threading
from sensors import sensor_loop, telemetry, zero_imu, zero_horizon

from motors import toggle_motor, toggle_lights

import subprocess

app = Flask(__name__)

# --- Video feed using libcamera (from your working V21 code) ---
def generate_frames():
    # This launches libcamera-vid in MJPEG mode and pipes to Flask
    cmd = [
        "libcamera-vid",
        "-t", "0",                 # run indefinitely
        "--inline",                # embed SPS/PPS
        "-n",                      # no preview
        "--codec", "mjpeg",        # MJPEG encoding
        "--width", "1280",
        "--height", "720",
        "-o", "-"                  # output to stdout
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)

    while True:
        frame = process.stdout.read(1024)
        if not frame:
            break
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/telemetry")
def get_telemetry():
    return jsonify(telemetry)


@app.route("/motor/<name>", methods=["POST"])
def motor_control(name):
    if name == "lights":
        toggle_lights()
    else:
        toggle_motor(name)
    return ("", 204)


# --- Main entry ---
if __name__ == "__main__":
    print("[APP] Starting ROV server...")

    # Start sensor thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()

    # Run Flask server
    app.run(host="0.0.0.0", port=5000)
