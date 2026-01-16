import time
import threading
import qwiic_lsm6dso
from logger import log
from config import sensor_data

# Optional: if you have other sensors (pressure, temp, etc.)
# import qwiic_bme280 or your ADC interface here

imu = None
running = True


def init_sensors():
    """Initialize IMU and other sensors."""
    global imu
    try:
        imu = qwiic_lsm6dso.QwiicLsm6dso()
        if not imu.connected:
            log("[SENSORS] IMU not detected on I2C bus")
            return False
        imu.begin()
        log("[SENSORS] IMU initialized (SparkFun LSM6DSO @ 0x6B)")
        return True
    except Exception as e:
        log(f"[SENSORS] IMU init failed: {e}")
        return False


def read_sensors():
    """Reads IMU and other sensor values into sensor_data."""
    global imu
    try:
        if imu is None:
            return

        # --- IMU (Accelerometer + Gyro) ---
        ax = imu.getAccelX()
        ay = imu.getAccelY()
        az = imu.getAccelZ()
        gx = imu.getGyroX()
        gy = imu.getGyroY()
        gz = imu.getGyroZ()

        # Optionally convert raw accel/gyro to usable angles here if needed
        sensor_data["ax"] = ax
        sensor_data["ay"] = ay
        sensor_data["az"] = az
        sensor_data["gx"] = gx
        sensor_data["gy"] = gy
        sensor_data["gz"] = gz

        # --- Placeholder for other sensors (depth, pressure, temp) ---
        # Replace with real sensor read calls if available
        # Example:
        # sensor_data["depth_ft"] = read_depth_sensor()
        # sensor_data["pressure"] = read_pressure_sensor()
        # sensor_data["temp_c"] = read_temp_sensor()

    except Exception as e:
        log(f"[SENSORS] Error reading sensors: {e}")


def sensor_loop():
    """Background loop to continuously read sensors."""
    global running
    log("[SENSORS] Sensor loop started")
    while running:
        read_sensors()
        time.sleep(0.2)  # 5 Hz update rate
    log("[SENSORS] Sensor loop stopped")


def start_sensor_thread():
    """Starts the background thread for sensor reading."""
    thread = threading.Thread(target=sensor_loop, daemon=True)
    thread.start()
    return thread


# --- Run independently for testing/debugging ---
if __name__ == "__main__":
    if init_sensors():
        start_sensor_thread()
        while True:
            print(sensor_data)
            time.sleep(1)
    else:
        print("IMU not found.")
