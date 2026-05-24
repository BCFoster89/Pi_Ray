# telemetry_logger.py
"""
CSV telemetry logger for post-dive analysis.
Writes timestamped sensor snapshots and motor duty cycles once per second.
Log files are rotated by date and capped at 50MB per file.
"""

import os, time, csv, threading
from datetime import datetime
from logger import log
from config import sensor_data, pwm_state

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dive_logs')
os.makedirs(LOGS_DIR, exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per log file

CSV_FIELDS = [
    'timestamp', 'depth_ft', 'pitch', 'roll', 'yaw',
    'temperature_f', 'imu_temp_f', 'pressure_inhg',
    'accel_x', 'accel_y', 'accel_z',
    'gyro_x', 'gyro_y', 'gyro_z',
    'mag_x', 'mag_y', 'mag_z',
    'dr_x', 'dr_y', 'dr_vx', 'dr_vy',
    'leak_detected', 'sensor_ok',
    'motor_8', 'motor_12', 'motor_13', 'motor_16',
    'motor_6', 'motor_20',
    'control_mode'
]


def _get_log_path():
    """Return path for today's log file."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOGS_DIR, f"telemetry_{date_str}.csv")


def _log_loop():
    """Background thread that writes one CSV row per second."""
    current_file = None
    writer = None
    fh = None

    while True:
        try:
            path = _get_log_path()

            # Rotate file if date changed or file too large
            if fh is None or current_file != path or (fh and fh.tell() > MAX_FILE_SIZE):
                if fh:
                    fh.close()
                need_header = not os.path.exists(path) or os.path.getsize(path) == 0
                fh = open(path, 'a', newline='')
                writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
                if need_header:
                    writer.writeheader()
                current_file = path

            # Build row from current sensor_data and pwm_state
            duties = pwm_state.get('duties', {})
            row = {
                'timestamp': datetime.now().strftime("%H:%M:%S.%f")[:-3],
                'depth_ft': sensor_data.get('depth_ft', 0.0),
                'pitch': sensor_data.get('pitch', 0.0),
                'roll': sensor_data.get('roll', 0.0),
                'yaw': sensor_data.get('yaw', 0.0),
                'temperature_f': sensor_data.get('temperature_f', 0.0),
                'imu_temp_f': sensor_data.get('imu_temp_f', 0.0),
                'pressure_inhg': sensor_data.get('pressure_inhg', 0.0),
                'accel_x': sensor_data.get('accel_x', 0.0),
                'accel_y': sensor_data.get('accel_y', 0.0),
                'accel_z': sensor_data.get('accel_z', 0.0),
                'gyro_x': sensor_data.get('gyro_x', 0.0),
                'gyro_y': sensor_data.get('gyro_y', 0.0),
                'gyro_z': sensor_data.get('gyro_z', 0.0),
                'mag_x': sensor_data.get('mag_x', 0.0),
                'mag_y': sensor_data.get('mag_y', 0.0),
                'mag_z': sensor_data.get('mag_z', 0.0),
                'dr_x':  sensor_data.get('dr_x', 0.0),
                'dr_y':  sensor_data.get('dr_y', 0.0),
                'dr_vx': sensor_data.get('dr_vx', 0.0),
                'dr_vy': sensor_data.get('dr_vy', 0.0),
                'leak_detected': sensor_data.get('leak_detected', False),
                'sensor_ok': sensor_data.get('sensor_ok', False),
                'motor_8': duties.get(8, duties.get('8', 0.0)),
                'motor_12': duties.get(12, duties.get('12', 0.0)),
                'motor_13': duties.get(13, duties.get('13', 0.0)),
                'motor_16': duties.get(16, duties.get('16', 0.0)),
                'motor_6': duties.get(6, duties.get('6', 0.0)),
                'motor_20': duties.get(20, duties.get('20', 0.0)),
                'control_mode': pwm_state.get('control_mode', 'manual'),
            }

            writer.writerow(row)
            fh.flush()

        except Exception as e:
            log(f"[TELEM_LOG] Error: {e}")

        time.sleep(1.0)


def start():
    """Start the telemetry logging thread."""
    t = threading.Thread(target=_log_loop, daemon=True)
    t.start()
    log(f"[TELEM_LOG] Logging to {LOGS_DIR}/")
