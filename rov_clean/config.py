# config.py
import RPi.GPIO as GPIO

# Hardware config
motor_pins = [6, 8, 12, 13, 16, 20]
led_pin = 24
led_state = False

MOTOR_GROUPS = {
    'x': [12, 13],
    'y': [8, 12],
    'b': [8, 16],
    'a': [13, 16],
    'left_trigger': [12, 16],
    'right_trigger': [8, 13],
    'dive': [6, 20]
}
motor_states = {name: "off" for name in MOTOR_GROUPS}

MAX_ACTIVE_GROUPS = 1
GROUP_STAGGER_S = 0.25
MIN_ACTIVATE_INTERVAL_S = 0.5

# Shared sensor data
sensor_data = {
    'pressure_inhg': 0.0, 'temperature_f': 0.0, 'depth_ft': 0.0,
    'accel_x': 0.0, 'accel_y': 0.0, 'accel_z': 0.0,
    'gyro_x': 0.0, 'gyro_y': 0.0, 'gyro_z': 0.0,
    'imu_temp_f': 0.0, 'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0
}

# GPIO setup (run at import)
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(led_pin, GPIO.OUT)
GPIO.output(led_pin, GPIO.LOW)
for p in motor_pins:
    GPIO.setup(p, GPIO.OUT)
    GPIO.output(p, GPIO.LOW)
