from flask import Flask
from picamera2 import Picamera2
import RPi.GPIO as GPIO
from logger import log
import routes  # this imports and registers Flask routes

app = Flask(__name__, static_folder="web/static", template_folder="web/templates")
routes.init_app(app)  # register routes

if __name__ == "__main__":
    cam = Picamera2()
    vc = cam.create_video_configuration(main={"size": (1280, 720)}, controls={"FrameRate": 30})
    cam.configure(vc)
    cam.start()

    log("[START] ROV Control server running @ http://0.0.0.0:5000/")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
    GPIO.cleanup()
