import threading, json

calib = {"depth_zero_ft": 0.0}
cal_lock = threading.Lock()

def save_calib():
    with open("calibration.json", "w") as f:
        json.dump(calib, f)
