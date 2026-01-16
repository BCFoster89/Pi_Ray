import json, os, threading
from logger import log

CALIB_FILE = "calibration.json"
calib = {'roll_offset': 0, 'pitch_offset': 0, 'yaw_offset': 0, 'depth_zero_ft': 0}
cal_lock = threading.Lock()

if os.path.exists(CALIB_FILE):
    with open(CALIB_FILE, 'r') as f:
        calib.update(json.load(f))

def save_calib():
    with cal_lock:
        with open(CALIB_FILE, 'w') as f:
            json.dump(calib, f, indent=2)
    log("[CAL] Saved.")

if __name__ == "__main__":
    print("Calibration data:", calib)
    calib['roll_offset'] = 5
    save_calib()
