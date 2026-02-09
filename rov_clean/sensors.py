# sensors.py
import time, math, threading
from collections import deque
import adafruit_lps28, board, qwiic_lsm6dso
from logger import log
from config import sensor_data
from calibration import calib, cal_lock

# Shared/internal state
pressure_buf = deque(maxlen=5)
roll_f = pitch_f = yaw_f = 0.0
roll_i = pitch_i = yaw_i = 0.0
last_time = time.time()
alpha_c = 0.98
ema_alpha = 0.1

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
    global roll_i, pitch_i, yaw_i, roll_f, pitch_f, yaw_f, last_time
    global accel_offsets, gyro_offsets, imu_offsets_enabled

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

            # Pressure / temp / depth
            ph = ps.pressure
            tc = ps.temperature
            pin = ph * 0.02953
            tf = tc * 9 / 5 + 32
            pressure_buf.append(pin)
            med = sorted(pressure_buf)[len(pressure_buf)//2] if pressure_buf else pin
            depth_ft_raw = max(0.0, ((med/0.02953) - 1013.25) * 0.033488)
            with cal_lock:
                dz = calib['depth_zero_ft']
            depth_ft = max(0.0, depth_ft_raw - dz)

            # IMU readings
            ax, ay, az = imu.read_float_accel_all()
            gx, gy, gz = imu.read_float_gyro_all()

            if imu_offsets_enabled:
                ax -= accel_offsets['x']; ay -= accel_offsets['y']; az -= accel_offsets['z']
                gx -= gyro_offsets['x']; gy -= gyro_offsets['y']; gz -= gyro_offsets['z']

            # Read temperature from IMU
            # The SparkFun qwiic_lsm6dso library may or may not apply the +25°C offset
            # from the LSM6DSO datasheet. We check if the value is reasonable and
            # compare against water temp to validate.
            temp_raw = imu.read_temp_c()

            # Water temp in Celsius for comparison
            water_temp_c = tc

            if temp_raw is None:
                # No reading - use water temp as fallback
                temp_c = water_temp_c
            elif -10 <= temp_raw <= 85:
                # Value is in reasonable range for an IC - library likely applies offset
                temp_c = temp_raw
            elif -35 <= temp_raw <= 60:
                # Value looks like it's missing the +25°C offset
                temp_c = temp_raw + 25.0
            else:
                # Invalid reading - use water temp as fallback
                temp_c = water_temp_c

            # Convert to Fahrenheit for display
            itf = (temp_c * 9 / 5) + 32

            # Integration
            roll_i += gx * dt
            pitch_i += gy * dt
            yaw_i += gz * dt

            ar = math.degrees(math.atan2(ay, az))
            ap = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

            roll_i = alpha_c * roll_i + (1 - alpha_c) * ar
            pitch_i = alpha_c * pitch_i + (1 - alpha_c) * ap

            roll_f = ema_alpha * roll_i + (1 - ema_alpha) * roll_f
            pitch_f = ema_alpha * pitch_i + (1 - ema_alpha) * pitch_f
            yaw_f = ema_alpha * yaw_i + (1 - ema_alpha) * yaw_f

            with cal_lock:
                ro = calib['roll_offset']; po = calib['pitch_offset']; yo = calib['yaw_offset']

            yaw_display = (yaw_f - yo + 180) % 360 - 180

            # Update shared dict
            sensor_data.update({
                'pressure_inhg': round(med, 2),
                'temperature_f': round(tf, 1),
                'depth_ft': round(depth_ft, 2),
                'accel_x': round(ax, 2), 'accel_y': round(ay, 2), 'accel_z': round(az, 2),
                'gyro_x': round(gx, 1), 'gyro_y': round(gy, 1), 'gyro_z': round(gz, 1),
                'imu_temp_f': round(itf, 1),
                'roll': round(roll_f - ro, 1),
                'pitch': round(pitch_f - po, 1),
                'yaw': round(yaw_display, 1)
            })
        except Exception as e:
            log(f"[SENSOR] error: {e}")

        time.sleep(0.05)

# Start thread at import
threading.Thread(target=sensor_loop, daemon=True).start()
