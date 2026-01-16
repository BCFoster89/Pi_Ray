import json, threading, os
from logging_utils import log

CALIB_FILE = "calibration.json"

calib = {
    'roll_offset': 0,
    'pitch_offset': 0,
    'yaw_offset': 0,
    'depth_zero_ft': 0
}

if os.path.exists(CALIB_FILE):
    with open(CALIB_FILE, 'r') as f:
        calib.update(json.load(f))

cal_lock = threading.Lock()

def save_calib():
    with cal_lock:
        with open(CALIB_FILE, 'w') as f:
            json.dump(calib, f, indent=2)
    log("[CAL] Saved calibration data.")

if __name__ == "__main__":
    print("[TEST] Calibration file")
    calib['roll_offset'] = 10
    save_calib()
    print("Saved calib:", calib)
