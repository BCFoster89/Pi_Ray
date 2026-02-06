# config.py
import RPi.GPIO as GPIO

# Hardware config
# Horizontal thrusters: 8, 12, 13, 16
# Vertical thrusters: 6, 20 (descend), 1, 2 (ascend - placeholder pins)
horizontal_pins = [8, 12, 13, 16]
descend_pins = [6, 20]
ascend_pins = [1, 2]  # PLACEHOLDER - will control same motors as descend but reversed
motor_pins = horizontal_pins + descend_pins + ascend_pins

led_pin = 24
led_state = False

# Legacy motor groups (kept for backward compatibility with toggle mode)
MOTOR_GROUPS = {
    'x': [12, 13],
    'y': [8, 12],
    'b': [8, 16],
    'a': [13, 16],
    'left_trigger': [12, 16],
    'right_trigger': [8, 13],
    'descend': [6, 20],
    'ascend': [1, 2]  # PLACEHOLDER
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
    'watchdog_timeout': 0.5 # Stop motors if no command received in 500ms
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
#   Ascend:  pins 1, 2 (PLACEHOLDER - same motors, reversed direction)

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

# Vertical thrust mixing - SEPARATE descend and ascend
# Descend motors (left trigger) - pins 6, 20
DESCEND_MIX = {
    6:  1.0,   # Descend motor 1
    20: 1.0,   # Descend motor 2
}

# Ascend motors (right trigger) - pins 1, 2 (PLACEHOLDER)
# These will be the same physical motors as descend but with reversed direction
ASCEND_MIX = {
    1: 1.0,   # Ascend motor 1 (PLACEHOLDER)
    2: 1.0,   # Ascend motor 2 (PLACEHOLDER)
}

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
    'imu_temp_f': 0.0, 'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0
}

# GPIO setup (run at import)
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(led_pin, GPIO.OUT)
GPIO.output(led_pin, GPIO.LOW)
# Only setup pins that exist on the Pi (skip placeholder pins 1, 2)
for p in horizontal_pins + descend_pins:
    GPIO.setup(p, GPIO.OUT)
    GPIO.output(p, GPIO.LOW)
