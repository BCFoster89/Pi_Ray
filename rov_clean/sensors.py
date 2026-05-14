# sensors.py
import time, math, threading
from collections import deque
import adafruit_lps28, board, qwiic_lsm6dso
import RPi.GPIO as GPIO
from logger import log
from config import sensor_data, leak_pin
from calibration import calib, cal_lock

# Track leak state for logging (protected by _sensor_lock)
_last_leak_state = False
_sensor_lock = threading.Lock()

# Shared/internal state
pressure_buf = deque(maxlen=5)
roll_f = pitch_f = yaw_f = 0.0
last_time = time.time()
alpha_c = 0.98

# IMU calibration offsets
accel_offsets = {'x': 0.0, 'y': 0.0, 'z': 0.0}
gyro_offsets  = {'x': 0.0, 'y': 0.0, 'z': 0.0}
imu_offsets_enabled = False

# Integration state (exposed for calibration reset from routes.py)
roll_i = pitch_i = yaw_i = 0.0

# Consecutive error tracking for sensor_ok flag
_consecutive_errors = 0
_MAX_CONSECUTIVE_ERRORS = 10  # Mark sensor as offline after 10 failures (0.5s)


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
    global _last_leak_state, _consecutive_errors

    try:
        ps = adafruit_lps28.LPS28(board.I2C())
    except Exception as e:
        log(f"[SENSOR] LPS28 init failed: {e}")
        sensor_data['sensor_ok'] = False
        return

    imu = init_imu()
    if not imu:
        sensor_data['sensor_ok'] = False
        return

    log("[SENSOR] Sensors ready")
    sensor_data['sensor_ok'] = True
    _consecutive_errors = 0

    while True:
        try:
            now = time.time()
            dt = max(1e-3, now - last_time)
            last_time = now

            # Pressure / temp / depth — work in hPa directly
            pressure_hpa = ps.pressure
            tc = ps.temperature
            tf = tc * 9.0 / 5.0 + 32.0

            # Median filter on pressure (hPa)
            pressure_buf.append(pressure_hpa)
            med_hpa = sorted(pressure_buf)[len(pressure_buf) // 2]

            # Depth from gauge pressure: (hPa - atmospheric) * conversion factor
            # 0.033488 ft/hPa is correct for freshwater (rho=998 kg/m3)
            depth_ft_raw = max(0.0, (med_hpa - 1013.25) * 0.033488)
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
            temp_raw = imu.read_temp_c()

            if temp_raw is None:
                temp_c = 0.0
            elif -10 <= temp_raw <= 85:
                # Value is in reasonable range — library likely applies offset
                temp_c = temp_raw
            elif -35 <= temp_raw <= 60:
                # Value looks like it's missing the +25C offset
                temp_c = temp_raw + 25.0
            else:
                temp_c = 0.0

            # Convert to Fahrenheit for display
            itf = (temp_c * 9.0 / 5.0) + 32.0

            # Complementary filter for roll/pitch
            # Gyro integration
            roll_i += gx * dt
            pitch_i += gy * dt
            # Yaw: gyro-only integration (no magnetometer — will drift over time)
            yaw_i += gz * dt

            # Accelerometer angles
            ar = math.degrees(math.atan2(ay, az))
            ap = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

            # Complementary filter fuses gyro + accelerometer (roll/pitch only)
            roll_f = alpha_c * (roll_f + gx * dt) + (1 - alpha_c) * ar
            pitch_f = alpha_c * (pitch_f + gy * dt) + (1 - alpha_c) * ap
            # Yaw uses raw integration only — no EMA, no accelerometer correction
            yaw_f = yaw_i

            with cal_lock:
                ro = calib['roll_offset']; po = calib['pitch_offset']; yo = calib['yaw_offset']

            yaw_display = (yaw_f - yo + 180) % 360 - 180

            # Check leak sensor (active LOW - LOW means water detected)
            with _sensor_lock:
                leak_detected = GPIO.input(leak_pin) == GPIO.LOW
                if leak_detected and not _last_leak_state:
                    log("[WARNING] LEAK DETECTED!")
                _last_leak_state = leak_detected

            # Update shared dict
            sensor_data.update({
                'pressure_inhg': round(med_hpa * 0.02953, 2),
                'temperature_f': round(tf, 1),
                'depth_ft': round(depth_ft, 2),
                'accel_x': round(ax, 2), 'accel_y': round(ay, 2), 'accel_z': round(az, 2),
                'gyro_x': round(gx, 1), 'gyro_y': round(gy, 1), 'gyro_z': round(gz, 1),
                'imu_temp_f': round(itf, 1),
                'roll': round(roll_f - ro, 1),
                'pitch': round(pitch_f - po, 1),
                'yaw': round(yaw_display, 1),
                'leak_detected': leak_detected,
                'sensor_ok': True
            })

            # Reset error counter on successful read
            _consecutive_errors = 0

        except Exception as e:
            _consecutive_errors += 1
            log(f"[SENSOR] error ({_consecutive_errors}): {e}")
            if _consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                sensor_data['sensor_ok'] = False

        time.sleep(0.05)


# Start thread at import
threading.Thread(target=sensor_loop, daemon=True).start()
