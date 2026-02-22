# main.py
import logging
from flask import Flask
import RPi.GPIO as GPIO
from logger import log
import routes  # imports init_app (but camera is lazy)
# camera_module is lazy-init, no side-effect required here

# Suppress Flask/werkzeug request logging for noisy endpoints
class QuietRequestFilter(logging.Filter):
    """Filter out noisy request logs (video_feed, status polling)."""
    QUIET_PATHS = ['/video_feed', '/status', '/motor/pwm_status', '/depth_hold/status']

    def filter(self, record):
        msg = record.getMessage()
        # Filter GET requests to noisy endpoints
        for path in self.QUIET_PATHS:
            if f'GET {path}' in msg or f'"GET {path}' in msg:
                return False
        return True

# Apply filter to werkzeug logger
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(QuietRequestFilter())

app = Flask(__name__, static_folder="web/static", template_folder="web/templates")
routes.init_app(app)

if __name__ == "__main__":
    try:
        log("[START] ROV Control server running @ http://0.0.0.0:5000/")
        app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
    finally:
        GPIO.cleanup()
