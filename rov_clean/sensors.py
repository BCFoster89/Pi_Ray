# sensors.py
import time, math, threading
from collections import deque
import numpy as np
import adafruit_lps28, board, qwiic_lsm6dso
import RPi.GPIO as GPIO
from logger import log
from config import sensor_data, leak_pin
from calibration import calib, cal_lock
from dead_reckoning import dr_estimator

try:
    from ahrs.filters import Madgwick as _MadgwickFilter
    _AHRS_OK = True
except ImportError:
    _AHRS_OK = False
    log("[SENSORS] ahrs library not found — pip install ahrs. Falling back to complementary filter.")

try:
    import adafruit_mmc56x3 as _mmc56x3_mod
    _MAG_LIB_OK = True
except ImportError:
    _MAG_LIB_OK = False
    log("[SENSORS] adafruit_mmc56x3 not found — pip install adafruit-circuitpython-mmc56x3")

# Track leak state (protected by _sensor_lock)
_last_leak_state = False
_sensor_lock = threading.Lock()

# Shared orientation state (Euler angles, degrees) — read by routes.py
roll_f = pitch_f = yaw_f = 0.0

# Quaternion state [w, x, y, z] — NED frame
_q = np.array([1.0, 0.0, 0.0, 0.0])
_q_lock = threading.Lock()

# Madgwick filter instance
_madgwick = None
_beta = 1.0
if _AHRS_OK:
    _madgwick = _MadgwickFilter(frequency=20.0, beta=_beta)

# Pressure median filter
pressure_buf = deque(maxlen=5)

# IMU calibration offsets (applied before filter)
accel_offsets = {'x': 0.0, 'y': 0.0, 'z': 0.0}
gyro_offsets  = {'x': 0.0, 'y': 0.0, 'z': 0.0}
imu_offsets_enabled = False

# Magnetometer calibration collection state
_mag_cal_samples = []
_mag_cal_collecting = False
_mag_cal_lock = threading.Lock()

# Consecutive error tracking
_consecutive_errors = 0
_MAX_CONSECUTIVE_ERRORS = 10

# Complementary heading filter gain (gyro weight vs. mag absolute reference)
# 0.90 → ~0.5 s convergence time-constant at 20 Hz
_COMPASS_ALPHA = 0.90

# Display-layer EMA smoothing (separate from filter state, so feedback is unaffected)
# 0.30 at 20 Hz ≈ 250 ms lag — good for slow ROV where stability > refresh rate
_DISP_ALPHA = 0.30
_disp_roll  = 0.0
_disp_pitch = 0.0
_disp_yaw   = 0.0

# Ferrous object detection — ambient field baseline EMA
_mag_baseline = None
_MAG_BASELINE_ALPHA = 0.999  # ~50 s time-constant at 20 Hz

# Complementary filter fallback (used only when ahrs not available)
_alpha_c = 0.98
last_time = time.time()


def reset_orientation():
    """Reset quaternion from current accel reading — no convergence drift after zero."""
    global _q, roll_f, pitch_f, yaw_f, _madgwick, _disp_roll, _disp_pitch, _disp_yaw
    ax = sensor_data.get('accel_x', 0.0)
    ay = sensor_data.get('accel_y', 0.0)
    az = sensor_data.get('accel_z', 1.0)
    q_init     = _quat_from_accel(ax, ay, az)
    roll_init  = math.degrees(math.atan2(ay, az))
    pitch_init = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))
    with _q_lock:
        _q      = q_init
        roll_f  = roll_init
        pitch_f = pitch_init
        yaw_f   = 0.0
    _disp_roll  = roll_init
    _disp_pitch = pitch_init
    _disp_yaw   = 0.0
    if _AHRS_OK:
        _madgwick = _MadgwickFilter(frequency=20.0, beta=_beta)
        _madgwick.Q = q_init


def set_madgwick_beta(beta):
    """Tune the Madgwick beta parameter at runtime."""
    global _beta, _madgwick
    _beta = max(0.01, min(10.0, float(beta)))
    if _madgwick is not None:
        _madgwick.beta = _beta
    log(f"[SENSORS] Madgwick beta set to {_beta}")


def start_mag_cal():
    """Begin collecting magnetometer samples for calibration."""
    global _mag_cal_collecting
    with _mag_cal_lock:
        _mag_cal_samples.clear()
        _mag_cal_collecting = True
    log("[MAG_CAL] Collection started — rotate ROV through all orientations")


def finish_mag_cal():
    """
    Stop collection and compute hard-iron offset + diagonal soft-iron scale.
    Returns (hard_iron, soft_iron_matrix) or None on failure.
    """
    global _mag_cal_collecting
    with _mag_cal_lock:
        _mag_cal_collecting = False
        n = len(_mag_cal_samples)
        if n < 50:
            log(f"[MAG_CAL] Not enough samples ({n}), need ≥50")
            return None
        arr = np.array(_mag_cal_samples)

    # Hard-iron: centre of the measurement cloud
    mins = arr.min(axis=0)
    maxs = arr.max(axis=0)
    hard_iron = ((mins + maxs) / 2.0).tolist()

    # Soft-iron: normalise each axis range to a common average
    ranges = (maxs - mins) / 2.0  # half-ranges per axis
    avg_range = float(np.mean(ranges))
    with np.errstate(divide='ignore', invalid='ignore'):
        scales = np.where(ranges > 0, avg_range / ranges, 1.0)
    # Store as a diagonal 3x3 matrix for consistent JSON format
    soft_iron = np.diag(scales).tolist()

    with cal_lock:
        calib['mag_hard_iron'] = hard_iron
        calib['mag_soft_iron'] = soft_iron

    from calibration import save_calib
    save_calib()
    log(f"[MAG_CAL] Done: hard_iron={[round(v,2) for v in hard_iron]}, "
        f"scale={[round(v,2) for v in scales.tolist()]}")
    return hard_iron, soft_iron


def _apply_mag_cal(mx, my, mz):
    """Apply hard-iron offset and diagonal soft-iron correction."""
    with cal_lock:
        hi = calib['mag_hard_iron']
        si = calib['mag_soft_iron']
    cx = mx - hi[0]
    cy = my - hi[1]
    cz = mz - hi[2]
    # Diagonal element of the soft-iron matrix
    cx *= si[0][0]
    cy *= si[1][1]
    cz *= si[2][2]
    return cx, cy, cz


def _apply_mag_remap(mx, my, mz):
    """Permute and/or flip mag axes to align with the IMU body frame."""
    with cal_lock:
        idx  = calib.get('mag_axis_map',  [0, 1, 2])
        sign = calib.get('mag_axis_sign', [1, 1, 1])
    raw = (mx, my, mz)
    return (raw[idx[0]] * sign[0],
            raw[idx[1]] * sign[1],
            raw[idx[2]] * sign[2])


def _quat_from_accel(ax, ay, az):
    """Compute a gravity-referenced quaternion (yaw=0) from an accelerometer reading."""
    norm = math.sqrt(ax**2 + ay**2 + az**2)
    if norm < 0.1:
        return np.array([1.0, 0.0, 0.0, 0.0])
    ax, ay, az = ax / norm, ay / norm, az / norm
    roll  = math.atan2(ay, az)
    pitch = math.atan2(-ax, math.sqrt(ay**2 + az**2))
    cr, sr = math.cos(roll / 2),  math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    return np.array([cp * cr, cp * sr, sp * cr, -sp * sr])


def _quat_to_euler(q):
    """Convert quaternion [w, x, y, z] to (roll, pitch, yaw) in degrees."""
    w, x, y, z = q
    roll  = math.degrees(math.atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y)))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2*(w*y - z*x)))))
    yaw   = math.degrees(math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z)))
    return roll, pitch, yaw


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


def _init_mag(i2c_bus):
    if not _MAG_LIB_OK:
        return None
    try:
        mag = _mmc56x3_mod.MMC5603(i2c_bus)
        log("[SENSORS] Magnetometer initialized (Adafruit MMC5603 @ 0x30)")
        sensor_data['mag_ok'] = True
        return mag
    except Exception as e:
        log(f"[SENSORS] MMC5603 not found — {e}")
        sensor_data['mag_ok'] = False
        return None


def sensor_loop():
    global roll_f, pitch_f, yaw_f, _q, last_time
    global accel_offsets, gyro_offsets, imu_offsets_enabled
    global _last_leak_state, _consecutive_errors, _mag_baseline
    global _disp_roll, _disp_pitch, _disp_yaw

    try:
        i2c = board.I2C()
        ps = adafruit_lps28.LPS28(i2c)
    except Exception as e:
        log(f"[SENSOR] LPS28 init failed: {e}")
        sensor_data['sensor_ok'] = False
        return

    imu = init_imu()
    if not imu:
        sensor_data['sensor_ok'] = False
        return

    mag = _init_mag(i2c)

    log("[SENSOR] Sensors ready")
    sensor_data['sensor_ok'] = True
    _consecutive_errors = 0

    while True:
        try:
            now = time.time()
            dt = max(1e-3, now - last_time)
            last_time = now

            # ── Pressure / depth ────────────────────────────────────────────
            pressure_hpa = ps.pressure
            tc = ps.temperature
            tf = tc * 9.0 / 5.0 + 32.0

            pressure_buf.append(pressure_hpa)
            med_hpa = sorted(pressure_buf)[len(pressure_buf) // 2]

            depth_ft_raw = max(0.0, (med_hpa - 1013.25) * 0.033488)
            with cal_lock:
                dz = calib['depth_zero_ft']
            depth_ft = max(0.0, depth_ft_raw - dz)

            # ── IMU ─────────────────────────────────────────────────────────
            ax, ay, az = imu.read_float_accel_all()   # g
            gx, gy, gz = imu.read_float_gyro_all()   # deg/s

            if imu_offsets_enabled:
                ax -= accel_offsets['x']; ay -= accel_offsets['y']; az -= accel_offsets['z']
                gx -= gyro_offsets['x'];  gy -= gyro_offsets['y'];  gz -= gyro_offsets['z']

            temp_raw = imu.read_temp_c()
            if temp_raw is None:
                temp_c = 0.0
            elif -10 <= temp_raw <= 85:
                temp_c = temp_raw
            elif -35 <= temp_raw <= 60:
                temp_c = temp_raw + 25.0
            else:
                temp_c = 0.0
            itf = temp_c * 9.0 / 5.0 + 32.0

            # ── Magnetometer ─────────────────────────────────────────────────
            mx_cal = my_cal = mz_cal = 0.0
            if mag is not None:
                try:
                    mx_raw, my_raw, mz_raw = mag.magnetic   # µT
                    mx_cal, my_cal, mz_cal = _apply_mag_cal(mx_raw, my_raw, mz_raw)

                    # Collect samples for calibration if active
                    with _mag_cal_lock:
                        if _mag_cal_collecting:
                            _mag_cal_samples.append([mx_raw, my_raw, mz_raw])
                except Exception:
                    pass  # transient mag read error — skip this sample

            # ── Attitude fusion (Madgwick 9-DOF or complementary fallback) ──
            gyro_rad = np.array([gx, gy, gz]) * (math.pi / 180.0)
            accel_g  = np.array([ax, ay, az])
            mag_cal  = np.array([mx_cal, my_cal, mz_cal])
            mag_norm = np.linalg.norm(mag_cal)

            # ── Ferrous anomaly baseline (slow EMA, excludes Earth field) ────
            mag_anomaly = 0.0
            if mag is not None and mag_norm > 0.5:
                if _mag_baseline is None:
                    _mag_baseline = mag_norm
                else:
                    _mag_baseline = (_MAG_BASELINE_ALPHA * _mag_baseline
                                     + (1 - _MAG_BASELINE_ALPHA) * mag_norm)
                mag_anomaly = abs(mag_norm - _mag_baseline)

            with _q_lock:
                q_in = _q.copy()

            if _madgwick is not None:
                try:
                    # 6-DOF only — mag never enters Madgwick (separate breakout boards
                    # have different axis orientations; MARG would corrupt pitch/roll)
                    q_out = _madgwick.updateIMU(q_in, gyr=gyro_rad, acc=accel_g)
                    with _q_lock:
                        _q = q_out
                    roll_f, pitch_f, _ = _quat_to_euler(q_out)

                    # ── Tilt-compensated compass for yaw ─────────────────
                    if mag is not None and mag_norm > 1.0:
                        rmx, rmy, rmz = _apply_mag_remap(mx_cal, my_cal, mz_cal)
                        roll_r  = math.radians(roll_f)
                        pitch_r = math.radians(pitch_f)
                        cr, sr  = math.cos(roll_r), math.sin(roll_r)
                        cp, sp  = math.cos(pitch_r), math.sin(pitch_r)
                        # Project onto horizontal plane (NED: x=fwd, y=right, z=down)
                        Mx = rmx * cp + rmz * sp
                        My = rmx * sr * sp + rmy * cr - rmz * sr * cp
                        mag_yaw  = math.degrees(math.atan2(-My, Mx))
                        # Complementary filter — wrap-safe blend of gyro+mag
                        gyro_yaw = yaw_f + math.degrees(gyro_rad[2]) * dt
                        diff = ((mag_yaw - gyro_yaw) + 180.0) % 360.0 - 180.0
                        yaw_f = gyro_yaw + (1.0 - _COMPASS_ALPHA) * diff
                    else:
                        # No mag available — gyro integration only (slow drift)
                        yaw_f += math.degrees(gyro_rad[2]) * dt

                except Exception as e:
                    log(f"[SENSORS] Madgwick error: {e}")
                    # Keep previous Euler values on error
            else:
                # ── Complementary filter fallback (no ahrs library) ───────
                ar = math.degrees(math.atan2(ay, az))
                ap = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))
                roll_f  = _alpha_c * (roll_f  + gx * dt) + (1 - _alpha_c) * ar
                pitch_f = _alpha_c * (pitch_f + gy * dt) + (1 - _alpha_c) * ap
                if mag is not None and mag_norm > 1.0:
                    rmx, rmy, rmz = _apply_mag_remap(mx_cal, my_cal, mz_cal)
                    roll_r  = math.radians(roll_f)
                    pitch_r = math.radians(pitch_f)
                    cr, sr  = math.cos(roll_r), math.sin(roll_r)
                    cp, sp  = math.cos(pitch_r), math.sin(pitch_r)
                    Mx = rmx * cp + rmz * sp
                    My = rmx * sr * sp + rmy * cr - rmz * sr * cp
                    mag_yaw  = math.degrees(math.atan2(-My, Mx))
                    gyro_yaw = yaw_f + gz * dt
                    diff = ((mag_yaw - gyro_yaw) + 180.0) % 360.0 - 180.0
                    yaw_f = gyro_yaw + (1.0 - _alpha_c) * diff
                else:
                    yaw_f += gz * dt

            # ── Display smoothing (EMA) — separate from filter state ───────
            _disp_roll  += _DISP_ALPHA * (roll_f  - _disp_roll)
            _disp_pitch += _DISP_ALPHA * (pitch_f - _disp_pitch)
            _yaw_diff    = ((yaw_f - _disp_yaw) + 180.0) % 360.0 - 180.0
            _disp_yaw   += _DISP_ALPHA * _yaw_diff

            # ── Apply calibration offsets to display output ───────────────
            with cal_lock:
                ro = calib['roll_offset']
                po = calib['pitch_offset']
                yo = calib['yaw_offset']
            with _q_lock:
                q_snap = _q.copy()

            # ── Server-side dead reckoning ────────────────────────────────
            dr_estimator.update(q_snap, ax, ay, az, dt)
            dr_state = dr_estimator.get_state()

            # ── Leak sensor ──────────────────────────────────────────────
            with _sensor_lock:
                leak_detected = GPIO.input(leak_pin) == GPIO.LOW
                if leak_detected and not _last_leak_state:
                    log("[WARNING] LEAK DETECTED!")
                _last_leak_state = leak_detected

            # ── Publish to shared dict ───────────────────────────────────
            sensor_data.update({
                'pressure_inhg': round(med_hpa * 0.02953, 2),
                'temperature_f': round(tf, 1),
                'depth_ft': round(depth_ft, 2),
                'accel_x': round(ax, 3), 'accel_y': round(ay, 3), 'accel_z': round(az, 3),
                'gyro_x': round(gx, 1),  'gyro_y': round(gy, 1),  'gyro_z': round(gz, 1),
                'imu_temp_f': round(itf, 1),
                'roll':  round(_disp_roll  - ro, 1),
                'pitch': round(_disp_pitch - po, 1),
                'yaw':   round((_disp_yaw  - yo) % 360.0, 1),
                'mag_x': round(mx_cal, 2), 'mag_y': round(my_cal, 2), 'mag_z': round(mz_cal, 2),
                'mag_ok': mag is not None,
                'mag_anomaly': round(mag_anomaly, 2),
                'mag_baseline': round(_mag_baseline or 0.0, 1),
                'quat_w': round(float(q_snap[0]), 4),
                'quat_x': round(float(q_snap[1]), 4),
                'quat_y': round(float(q_snap[2]), 4),
                'quat_z': round(float(q_snap[3]), 4),
                **dr_state,
                'leak_detected': leak_detected,
                'sensor_ok': True,
            })

            _consecutive_errors = 0

        except Exception as e:
            _consecutive_errors += 1
            log(f"[SENSOR] error ({_consecutive_errors}): {e}")
            if _consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                sensor_data['sensor_ok'] = False

        time.sleep(0.05)


threading.Thread(target=sensor_loop, daemon=True).start()
