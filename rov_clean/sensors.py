# sensors.py
import time, math, threading
from collections import deque
import adafruit_lps28, board, qwiic_lsm6dso
import RPi.GPIO as GPIO
# Ensure GPIO mode is set before sensor thread starts
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
from logger import log
from config import sensor_data, leak_pin
from calibration import calib, cal_lock

# Track leak state for logging
_last_leak_state = False
_leak_emergency_triggered = False

# Lock for protecting sensor integration variables
sensor_lock = threading.Lock()

# Thread supervision
_sensor_thread = None
_supervisor_running = True

# Shared/internal state
pressure_buf = deque(maxlen=5)
roll_f = pitch_f = yaw_f = 0.0
roll_i = pitch_i = yaw_i = 0.0
last_time = time.time()
alpha_c = 0.98   # Complementary filter: 98% gyro, 2% accelerometer
ema_alpha = 0.1  # EMA smoothing factor for display

accel_offsets = {'x': 0.0, 'y': 0.0, 'z': 0.0}
gyro_offsets  = {'x': 0.0, 'y': 0.0, 'z': 0.0}
imu_offsets_enabled = False

def init_imu(max_retries=5):
    """Initialize IMU with retry logic."""
    for attempt in range(max_retries):
        try:
            imu = qwiic_lsm6dso.QwiicLSM6DSO()
            if imu.connected:
                imu.begin()
                log("[SENSORS] IMU initialized (SparkFun LSM6DSO @ 0x6B)")
                return imu
            else:
                log(f"[ERROR] LSM6DSO not found (attempt {attempt + 1}/{max_retries})")
        except Exception as e:
            log(f"[ERROR] IMU init failed (attempt {attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            wait_time = min(30, 2 ** attempt)  # Exponential backoff: 1, 2, 4, 8, 16 seconds
            log(f"[SENSORS] Retrying IMU init in {wait_time}s...")
            time.sleep(wait_time)

    log("[SENSORS] CRITICAL: IMU initialization failed after all retries")
    return None


def init_pressure_sensor(max_retries=5):
    """Initialize pressure sensor with retry logic."""
    for attempt in range(max_retries):
        try:
            ps = adafruit_lps28.LPS28(board.I2C())
            log("[SENSORS] Pressure sensor initialized (LPS28)")
            return ps
        except Exception as e:
            log(f"[SENSOR] LPS28 init failed (attempt {attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            wait_time = min(30, 2 ** attempt)
            log(f"[SENSORS] Retrying pressure sensor init in {wait_time}s...")
            time.sleep(wait_time)

    log("[SENSORS] CRITICAL: Pressure sensor initialization failed after all retries")
    return None

def sensor_loop():
    global roll_i, pitch_i, yaw_i, roll_f, pitch_f, yaw_f, last_time
    global accel_offsets, gyro_offsets, imu_offsets_enabled
    global _last_leak_state, _leak_emergency_triggered

    # Initialize sensors with retry logic
    ps = init_pressure_sensor()
    if not ps:
        log("[SENSOR] Running without pressure sensor - depth data unavailable")

    imu = init_imu()
    if not imu:
        log("[SENSOR] Running without IMU - orientation data unavailable")

    if ps or imu:
        log("[SENSOR] Sensors ready")
    else:
        log("[SENSOR] WARNING: No sensors available, but continuing for leak detection")

    while True:
        try:
            now = time.time()
            dt = max(1e-3, now - last_time)
            last_time = now

            # Default values if sensors unavailable
            depth_ft = 0.0
            tf = 0.0  # Water temp
            itf = 0.0  # Internal temp
            ax = ay = az = 0.0
            gx = gy = gz = 0.0

            # Pressure / temp / depth (only if sensor available)
            if ps:
                try:
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
                except Exception as e:
                    log(f"[SENSOR] Pressure read error: {e}")

            # IMU readings (only if sensor available)
            if imu:
                try:
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
                        temp_c = temp_raw
                    elif -35 <= temp_raw <= 60:
                        temp_c = temp_raw + 25.0
                    else:
                        temp_c = 0.0

                    itf = (temp_c * 9 / 5) + 32
                except Exception as e:
                    log(f"[SENSOR] IMU read error: {e}")

            # Integration (protected by lock)
            with sensor_lock:
                roll_i += gx * dt
                pitch_i += gy * dt
                yaw_i += gz * dt

                ar = math.degrees(math.atan2(ay, az))
                ap = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

                roll_i = alpha_c * roll_i + (1 - alpha_c) * ar
                pitch_i = alpha_c * pitch_i + (1 - alpha_c) * ap

            # EMA filtering (protected by lock)
            with sensor_lock:
                roll_f = ema_alpha * roll_i + (1 - ema_alpha) * roll_f
                pitch_f = ema_alpha * pitch_i + (1 - ema_alpha) * pitch_f
                yaw_f = ema_alpha * yaw_i + (1 - ema_alpha) * yaw_f

                with cal_lock:
                    ro = calib['roll_offset']; po = calib['pitch_offset']; yo = calib['yaw_offset']

                yaw_display = (yaw_f - yo + 180) % 360 - 180
                roll_display = roll_f - ro
                pitch_display = pitch_f - po

            # Check leak sensor (active LOW - LOW means water detected)
            try:
                leak_detected = GPIO.input(leak_pin) == GPIO.LOW
            except Exception:
                leak_detected = False

            if leak_detected and not _last_leak_state:
                log("[WARNING] LEAK DETECTED! TRIGGERING EMERGENCY STOP!")
                # Trigger emergency stop on first leak detection
                if not _leak_emergency_triggered:
                    _leak_emergency_triggered = True
                    try:
                        # Import here to avoid circular import
                        from motors import pwm_motor
                        pwm_motor.emergency_stop()
                        log("[SAFETY] Motors stopped due to leak detection")
                    except Exception as e:
                        log(f"[SAFETY] Failed to stop motors on leak: {e}")
            elif not leak_detected and _last_leak_state:
                # Leak cleared - allow emergency stop to be triggered again
                _leak_emergency_triggered = False
                log("[SENSOR] Leak condition cleared")

            _last_leak_state = leak_detected

            # Calculate pressure in inches Hg (default to 0 if no sensor)
            pressure_inhg = 0.0
            if ps and pressure_buf:
                med = sorted(pressure_buf)[len(pressure_buf)//2]
                pressure_inhg = round(med, 2)

            # Update shared dict
            sensor_data.update({
                'pressure_inhg': pressure_inhg,
                'temperature_f': round(tf, 1),
                'depth_ft': round(depth_ft, 2),
                'accel_x': round(ax, 2), 'accel_y': round(ay, 2), 'accel_z': round(az, 2),
                'gyro_x': round(gx, 1), 'gyro_y': round(gy, 1), 'gyro_z': round(gz, 1),
                'imu_temp_f': round(itf, 1),
                'roll': round(roll_display, 1),
                'pitch': round(pitch_display, 1),
                'yaw': round(yaw_display, 1),
                'leak_detected': leak_detected
            })
        except Exception as e:
            log(f"[SENSOR] error: {e}")

        time.sleep(0.05)

def _start_sensor_thread():
    """Start the sensor loop thread."""
    global _sensor_thread
    _sensor_thread = threading.Thread(target=sensor_loop, daemon=True, name="SensorThread")
    _sensor_thread.start()
    log("[SUPERVISOR] Sensor thread started")

def _supervisor_loop():
    """Monitor sensor thread and restart if it dies."""
    global _sensor_thread
    restart_count = 0
    max_restarts = 10  # Limit restarts to prevent infinite loop on persistent errors

    while _supervisor_running:
        try:
            if _sensor_thread is None or not _sensor_thread.is_alive():
                if restart_count < max_restarts:
                    restart_count += 1
                    log(f"[SUPERVISOR] Sensor thread died, restarting (attempt {restart_count}/{max_restarts})...")
                    _start_sensor_thread()
                elif restart_count == max_restarts:
                    restart_count += 1  # Only log once
                    log("[SUPERVISOR] CRITICAL: Max sensor restarts reached, giving up")
            else:
                # Thread is healthy, reset restart counter gradually
                if restart_count > 0:
                    restart_count = max(0, restart_count - 1)
        except Exception as e:
            log(f"[SUPERVISOR] Error: {e}")
        time.sleep(2)  # Check every 2 seconds

# Start sensor thread and supervisor at import
_start_sensor_thread()
threading.Thread(target=_supervisor_loop, daemon=True, name="SensorSupervisor").start()
