import time, threading
from logger import log
from config import sensor_data
import qwiic_lsm6dso

imu = qwiic_lsm6dso.QwiicLSM6DSO()

def sensor_loop():
    if not imu.begin():
        log("[SENSORS] IMU not detected")
        return

    log("[SENSORS] IMU initialized")

    while True:
        try:
            sensor_data["ax"] = imu.getAccelX()
            sensor_data["ay"] = imu.getAccelY()
            sensor_data["az"] = imu.getAccelZ()

            sensor_data["gx"] = imu.getGyroX()
            sensor_data["gy"] = imu.getGyroY()
            sensor_data["gz"] = imu.getGyroZ()

        except Exception as e:
            log(f"[SENSORS] Error reading sensors: {e}")

        time.sleep(0.05)

threading.Thread(target=sensor_loop, daemon=True).start()
