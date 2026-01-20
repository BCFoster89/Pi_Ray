# sensors.py
import time
import math
import threading
from collections import deque

import adafruit_lps28
import board
import qwiic_lsm6dso

from logger import log
from config import sensor_data, sensor_lock
from calibration import calib, cal_lock

# -----------------------------
# Constants / tuning parameters
# -----------------------------
ALPHA_C = 0.98        # complementary filter coefficient
EMA_ALPHA = 0.1       # output smoothing
LOOP_DELAY = 0.05     # seconds (20 Hz)

INHG_TO_HPA = 1 / 0.02953
HPA_TO_FT_WATER = 0.033488

# -----------------------------
# Shared / internal state
# -----------------------------
pressure_buf = deque(maxlen=5)

roll_f = pitch_f = yaw_f = 0.0
roll_i = pitch_i = yaw_i = 0.0

last_time = None  # initialized when thread starts

accel_offsets = {'x': 0.0, 'y': 0.0, 'z': 0.0}
gyro_offsets  = {'x': 0.0, 'y': 0.0, 'z': 0.0}
imu_offsets_enabled = False


def init_imu():
    try:
        imu = qwiic_lsm6dso.QwiicLSM6DSO()
        if imu.connected:
            imu.begin()
            log("[SENSORS] IMU initialized (SparkFun LSM6DSO @ 0x6B)")
            return imu
        else:
            log("[ERROR] LSM6DSO not found on I2C bus")
            return None
    except Exception as e:
        log(f"[ERROR] IMU init failed: {e}")
        return None


def sensor_loop():
    global roll_i, pitch_i, yaw_i
    global roll_f, pitch_f, yaw_f
    global last_time
    global accel_offsets, gyro_offsets, imu_offsets_enabled

    # Initialize timing when thread actually starts
    last_time = time.time()

    try:
        ps = adafruit_lps28.LPS28(board.I2C())
    except Exception as e:
        log(f"[SENSOR] LPS28 init failed: {e}")
        return

    imu = init_imu()
    if not imu:
        return

    log("[SENSOR] Sensors ready")

    while True:
        try:
            now = time.time()
            dt = max(1e-3, now - last_time)
            last_time = now

            # -----------------------------
            # Pressure / temperature / depth
            # -----------------------------
            ph = ps.pressure          # hPa
            tc = ps.temperature       # °C

            pin = ph * 0.02953        # inHg
            tf = tc * 9 / 5 + 32      # °F

            pressure_buf.append(pin)

            if pressure_buf:
                buf = list(pressure_buf)
                buf.sort()
                med = buf[len(buf) // 2]
            else:
                med = pin

            depth_ft_raw = max(
                0.0,
                ((med * INHG_TO_HPA) - 1013.25) * HPA_TO_FT_WATER
            )

            with cal_lock:
                dz = calib['depth_zero_ft']

            depth_ft = max(0.0, depth_ft_raw - dz)

            # -----------------------------
            # IMU readings
            # -----------------------------
            ax, ay, az = imu.read_float_accel_all()
            gx, gy, gz = imu.read_float_gyro_all()

            if imu_offsets_enabled:
                ax -= accel_offsets['x']
                ay -= accel_offsets['y']
                az -= accel_offsets['z']
                gx -= gyro_offsets['x']
                gy -= gyro_offsets['y']
                gz -= gyro_offsets['z']

            # -----------------------------
            # IMU temperature (robust clamp)
            # -----------------------------
            temp_raw = imu.read_temp_c()

            if temp_raw is None or not (-40.0 <= temp_raw <= 125.0):
                temp_c = 0.0
            else:
                temp_c = temp_raw

            itf = (temp_c * 9 / 5) + 32

            # -----------------------------
            # Orientation estimation
            # -----------------------------
            # Gyro integration
            roll_i  += gx * dt
            pitch_i += gy * dt
            yaw_i   += gz * dt

            # Wrap yaw to prevent unbounded growth
            yaw_i = (yaw_i + 180.0) % 360.0 - 180.0

            # Accelerometer tilt (assumes gravity dominance)
            ar = math.degrees(math.atan2(ay, az))
            ap = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))

            # Complementary filter
            roll_i  = ALPHA_C * roll_i  + (1.0 - ALPHA_C) * ar
            pitch_i = ALPHA_C * pitch_i + (1.0 - ALPHA_C) * ap

            # Output smoothing
            roll_f  = EMA_ALPHA * roll_i  + (1.0 - EMA_ALPHA) * roll_f
            pitch_f = EMA_ALPHA * pitch_i + (1.0 - EMA_ALPHA) * pitch_f
            yaw_f   = EMA_ALPHA * yaw_i   + (1.0 - EMA_ALPHA) * yaw_f

            with cal_lock:
                ro = calib['roll_offset']
                po = calib['pitch_offset']
                yo = calib['yaw_offset']

            yaw_display = (yaw_f - yo + 180.0) % 360.0 - 180.0

            # -----------------------------
            # Publish shared sensor data
            # -----------------------------
            with sensor_lock:
                sensor_data.update({
                    'pressure_inhg': round(med, 2),
                    'temperature_f': round(tf, 1),
                    'depth_ft': round(depth_ft, 2),

                    'accel_x': round(ax, 2),
                    'accel_y': round(ay, 2),
                    'accel_z': round(az, 2),

                    'gyro_x': round(gx, 1),
                    'gyro_y': round(gy, 1),
                    'gyro_z': round(gz, 1),

                    'imu_temp_f': round(itf, 1),

                    'roll': round(roll_f - ro, 1),
                    'pitch': round(pitch_f - po, 1),
                    'yaw': round(yaw_display, 1)
                })

        except Exception as e:
            log(f"[SENSOR] error: {e}")

        time.sleep(LOOP_DELAY)


# Start sensor thread on import
threading.Thread(target=sensor_loop, daemon=True).start()
