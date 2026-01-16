# main.py
from flask import Flask
import RPi.GPIO as GPIO
from logger import log
import routes  # imports init_app (but camera is lazy)
# camera_module is lazy-init, no side-effect required here

app = Flask(__name__, static_folder="web/static", template_folder="web/templates")
routes.init_app(app)

if __name__ == "__main__":
    try:
        log("[START] ROV Control server running @ http://0.0.0.0:5000/")
        app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
    finally:
        GPIO.cleanup()
