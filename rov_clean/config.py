# config.py
import RPi.GPIO as GPIO
from logger import log

# Hardware config
# Horizontal thrusters: 8, 12, 13, 16
# Vertical thrusters: 6, 20 (descend only — ascend hardware not installed)
horizontal_pins = [8, 12, 13, 16]
descend_pins = [6, 20]
# ascend_pins = []  # NOT INSTALLED — assign real GPIO pins when hardware is added
ASCEND_INSTALLED = False

# motor_pins only includes pins that physically exist on the board
motor_pins = horizontal_pins + descend_pins

led_pin = 24
led_state = False

# Leak sensor
leak_pin = 25

# Legacy motor groups (kept for backward compatibility with toggle mode)
MOTOR_GROUPS = {
    'x': [12, 13],
    'y': [8, 12],
    'b': [8, 16],
    'a': [13, 16],
    'left_trigger': [12, 16],
    'right_trigger': [8, 13],
    'descend': [6, 20],
}
motor_states = {name: "off" for name in MOTOR_GROUPS}

MAX_ACTIVE_GROUPS = 1
GROUP_STAGGER_S = 0.25
MIN_ACTIVATE_INTERVAL_S = 0.5

# =============================================================================
# PWM VECTORED THRUST CONFIGURATION
# =============================================================================

# PWM settings
PWM_CONFIG = {
    'frequency': 200,       # PWM frequency in Hz
    'deadband': 0.05,       # Ignore inputs below 5%
    'ramp_rate': 0.15,      # Max duty cycle change per update (prevents voltage spikes)
    'stagger_delay': 0.05,  # Delay between motor updates to prevent inrush current
    'watchdog_timeout': 0.5,# Stop motors if no command received in 500ms
    'heartbeat_timeout': 2.0# Stop motors if no heartbeat received in 2s
}

# Thruster layout (based on motor groups analysis):
#         FRONT
#     [8]-------[12]
#      |         |
#      |   ROV   |
#      |         |
#    [16]-------[13]
#         REAR
#
# Vertical thrusters:
#   Descend: pins 6, 20
#   Ascend:  NOT INSTALLED — assign real pins when hardware is added

# Thrust mixing matrix for horizontal thrusters
# Each motor's contribution to surge (forward/back), sway (strafe), yaw (rotation)
# Values: +1.0 = responds to positive input, -1.0 = responds to negative input
# NOTE: Only horizontal thrusters are used for surge/sway/yaw
#
# Surge: Forward (push stick up) = front motors, Backward = rear motors
# Sway:  Left strafe = left motors, Right strafe = right motors
# Yaw:   Turn right = left motors push, right motors don't (differential thrust)
THRUST_MIX = {
    # pin: [surge, sway, yaw]
    8:  [+1.0, -1.0, +1.0],  # Front-Left: forward, strafe-left, turn-right
    12: [+1.0, +1.0, -1.0],  # Front-Right: forward, strafe-right, turn-left
    16: [-1.0, -1.0, -1.0],  # Rear-Left: backward, strafe-left, turn-left
    13: [-1.0, +1.0, +1.0],  # Rear-Right: backward, strafe-right, turn-right
}

# Vertical thrust mixing - descend only (ascend not installed)
# Descend motors (left trigger) - pins 6, 20
DESCEND_MIX = {
    6:  1.0,   # Descend motor 1
    20: 1.0,   # Descend motor 2
}

# Ascend motors — empty until hardware is installed
ASCEND_MIX = {}

# Current PWM state (duty cycles for each motor, 0.0-1.0)
pwm_state = {
    'duties': {p: 0.0 for p in motor_pins},
    'active': False,
    'last_update': 0.0,
    'control_mode': 'manual'  # 'manual' or 'pwm'
}

# Shared sensor data
sensor_data = {
    'pressure_inhg': 0.0, 'temperature_f': 0.0, 'depth_ft': 0.0,
    'accel_x': 0.0, 'accel_y': 0.0, 'accel_z': 0.0,
    'gyro_x': 0.0, 'gyro_y': 0.0, 'gyro_z': 0.0,
    'imu_temp_f': 0.0, 'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0,
    # Magnetometer (MMC5603) — calibrated µT
    'mag_x': 0.0, 'mag_y': 0.0, 'mag_z': 0.0, 'mag_ok': False,
    # Madgwick quaternion output
    'quat_w': 1.0, 'quat_x': 0.0, 'quat_y': 0.0, 'quat_z': 0.0,
    # Server-side dead reckoning (NED, metres / m/s)
    'dr_x': 0.0, 'dr_y': 0.0, 'dr_vx': 0.0, 'dr_vy': 0.0,
    'leak_detected': False,
    'sensor_ok': False,
}

# GPIO setup (run at import)
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(led_pin, GPIO.OUT)
GPIO.output(led_pin, GPIO.LOW)
# Leak sensor - input with pull-up (active LOW when wet)
GPIO.setup(leak_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
# Setup only real motor pins
for p in horizontal_pins + descend_pins:
    GPIO.setup(p, GPIO.OUT)
    GPIO.output(p, GPIO.LOW)

if not ASCEND_INSTALLED:
    log("[CONFIG] Ascend motors not configured — right trigger input ignored")
