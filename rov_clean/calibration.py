# calibration.py
import json, os, threading
from logger import log

# Use absolute path relative to this module's location
CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
calib = {'roll_offset': 0, 'pitch_offset': 0, 'yaw_offset': 0, 'depth_zero_ft': 0}
cal_lock = threading.Lock()

if os.path.exists(CALIB_FILE):
    try:
        with open(CALIB_FILE, 'r') as f:
            calib.update(json.load(f))
    except Exception as e:
        log(f"[CAL] unable to load calibration file: {e}")

def save_calib():
    with cal_lock:
        with open(CALIB_FILE, 'w') as f:
            json.dump(calib, f, indent=2)
    log("[CAL] Saved.")
