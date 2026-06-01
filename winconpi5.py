# winconpi5.py - PWM Controller Client for ROV
# Reads Xbox controller axes and sends PWM commands to the ROV
import pygame
import requests
import time
import json

# Initialize pygame
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    raise RuntimeError("No joystick detected!")

controller = pygame.joystick.Joystick(0)
controller.init()

print(f"Controller: {controller.get_name()}")
print(f"Axes: {controller.get_numaxes()}, Buttons: {controller.get_numbuttons()}")

# Flask server base URL (replace with your Pi's IP if needed)
BASE_URL = "http://192.168.4.31:5000"
# BASE_URL = "http://127.0.0.1:5000"    # for local testing

# =============================================================================
# AXIS MAPPING - Adjust these based on your specific controller
# =============================================================================
# Your controller mapping (based on testing):
# Axis 0: Left stick X (left=-1, right=+1)
# Axis 1: Left stick Y (up=-1, down=+1)
# Axis 2: Right stick X (left=-1, right=+1)
# Axis 3: Right stick Y (up=-1, down=+1)
# Axis 4: Left trigger (released=0, pressed=1)
# Axis 5: Right trigger (released=0, pressed=1)

AXIS_MAP = {
    'left_x': 0,     # Left stick horizontal (yaw/rotation)
    'left_y': 1,     # Left stick vertical (unused)
    'right_x': 2,    # Right stick horizontal (strafe/sway)
    'right_y': 3,    # Right stick vertical (forward/surge)
    'lt': 4,         # Left trigger (ascend)
    'rt': 5,         # Right trigger (descend)
}

# Trigger calibration - adjust these based on your controller
# Your triggers: released = 0.0, fully pressed = 1.0
TRIGGER_MIN = 0.0    # Value when trigger is released
TRIGGER_MAX = 1.0    # Value when trigger is fully pressed

# Button mapping (pygame Xbox indices: A=0, B=1, X=2, Y=3, LB=4, RB=5, Back=6, Start=7)
BUTTON_MAP = {
    3: 'lights',     # Y button -> toggle LED
    1: 'estop',      # B button -> emergency stop (LATCH ON)
}

# E-stop release: Start button (single press)
ESTOP_RELEASE_BTN = 7   # Start button

# =============================================================================
# CONFIGURATION
# =============================================================================
DEADBAND = 0.10           # Ignore inputs below this threshold
SEND_INTERVAL = 0.05      # 20Hz update rate (50ms)
SMOOTHING_ALPHA = 0.3     # EMA smoothing factor (0.0-1.0, higher = less smoothing)
CHANGE_THRESHOLD = 0.02   # Only send if values changed more than this
HEARTBEAT_INTERVAL = 0.5  # Send heartbeat every 500ms

# =============================================================================
# STATE TRACKING
# =============================================================================
last_sent = {'surge': 0.0, 'sway': 0.0, 'yaw': 0.0, 'descend': 0.0, 'ascend': 0.0}
smoothed = {'surge': 0.0, 'sway': 0.0, 'yaw': 0.0, 'descend': 0.0, 'ascend': 0.0, 'tilt': 0.0}
previous_buttons = [0] * controller.get_numbuttons()
estop_active = False       # Local tracking of E-stop state
last_heartbeat_time = 0.0  # Last time a heartbeat was sent
last_tilt_sent = 0.0       # Last tilt value sent to ROV
last_tilt_time = 0.0       # Last time a tilt command was sent (for keepalive)


def apply_deadband(value, deadband=DEADBAND):
    """Apply deadband and normalize the remaining range."""
    if abs(value) < deadband:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - deadband) / (1.0 - deadband)


def normalize_trigger(raw_value):
    """
    Normalize trigger value from controller range to 0.0-1.0.
    Output: released = 0.0, fully pressed = 1.0
    """
    # Map from [TRIGGER_MIN, TRIGGER_MAX] to [0, 1]
    normalized = (raw_value - TRIGGER_MIN) / (TRIGGER_MAX - TRIGGER_MIN)
    # Clamp to valid range
    return max(0.0, min(1.0, normalized))


def smooth_value(key, new_value, alpha=SMOOTHING_ALPHA):
    """Apply exponential moving average smoothing."""
    smoothed[key] = alpha * new_value + (1.0 - alpha) * smoothed[key]
    return smoothed[key]


def read_axes():
    """Read and process all controller axes."""
    pygame.event.pump()

    # Read raw axis values for sticks
    left_x  = controller.get_axis(AXIS_MAP['left_x'])
    left_y  = controller.get_axis(AXIS_MAP['left_y'])
    right_x = controller.get_axis(AXIS_MAP['right_x'])
    right_y = controller.get_axis(AXIS_MAP['right_y'])

    # Read and normalize triggers: LT = ascend, RT = descend
    try:
        lt_raw = controller.get_axis(AXIS_MAP['lt'])
        rt_raw = controller.get_axis(AXIS_MAP['rt'])

        ascend_raw  = normalize_trigger(lt_raw)
        descend_raw = normalize_trigger(rt_raw)
    except (pygame.error, IndexError):
        ascend_raw  = 0.0
        descend_raw = 0.0

    # Apply deadband to stick axes
    surge_raw = apply_deadband(-right_y)  # Invert Y: push up = forward = positive
    sway_raw  = apply_deadband(right_x)   # Right stick X → strafe right = positive
    yaw_raw   = apply_deadband(left_x)    # Left stick X → turn right = positive

    # Apply deadband to triggers (already 0-1 range)
    ascend_raw  = ascend_raw  if ascend_raw  > DEADBAND else 0.0
    descend_raw = descend_raw if descend_raw > DEADBAND else 0.0

    # Camera tilt: left stick Y — push up = tilt up (negative Y → negative tilt)
    tilt_raw = apply_deadband(-left_y)

    # Apply smoothing
    return {
        'surge':   smooth_value('surge',   surge_raw),
        'sway':    smooth_value('sway',    sway_raw),
        'yaw':     smooth_value('yaw',     yaw_raw),
        'descend': smooth_value('descend', descend_raw),
        'ascend':  smooth_value('ascend',  ascend_raw),
        'tilt':    smooth_value('tilt',    tilt_raw),
    }


def values_changed(new_vals, threshold=CHANGE_THRESHOLD):
    """Check if values changed enough to warrant sending an update."""
    for key in ['surge', 'sway', 'yaw', 'descend', 'ascend']:
        if abs(new_vals[key] - last_sent[key]) > threshold:
            return True
    return False


def send_pwm_command(values):
    """Send PWM command to ROV via POST request."""
    global last_sent
    try:
        r = requests.post(
            f"{BASE_URL}/motor/pwm",
            json=values,
            timeout=0.2
        )
        if r.status_code == 200:
            last_sent = values.copy()
            return True
        else:
            print(f"PWM command failed: {r.status_code}")
    except requests.exceptions.Timeout:
        print("Timeout sending PWM command")
    except requests.exceptions.ConnectionError:
        print("Connection error - is the ROV online?")
    except Exception as e:
        print(f"Error sending PWM command: {e}")
    return False


def send_heartbeat():
    """Send heartbeat to ROV so the watchdog knows we're alive."""
    global last_heartbeat_time
    now = time.time()
    if now - last_heartbeat_time >= HEARTBEAT_INTERVAL:
        try:
            requests.get(f"{BASE_URL}/heartbeat", timeout=0.3)
            last_heartbeat_time = now
        except Exception:
            pass  # Heartbeat failure is non-fatal; watchdog on server handles it


def check_buttons():
    """Handle button presses for lights, E-stop, and E-stop release."""
    global previous_buttons, estop_active
    buttons = [controller.get_button(i) for i in range(controller.get_numbuttons())]

    # --- E-STOP RELEASE: Start button (rising edge) ---
    start_now = buttons[ESTOP_RELEASE_BTN] if ESTOP_RELEASE_BTN < len(buttons) else 0
    start_was = previous_buttons[ESTOP_RELEASE_BTN] if ESTOP_RELEASE_BTN < len(previous_buttons) else 0
    if estop_active and start_now and not start_was:
        try:
            r = requests.post(f"{BASE_URL}/motor/estop_release", timeout=0.5)
            data = r.json()
            if data.get('success'):
                estop_active = False
                print("\n*** E-STOP RELEASED — motors unlocked ***")
        except Exception as e:
            print(f"Error releasing E-stop: {e}")

    # --- Normal button handling ---
    for i, state in enumerate(buttons):
        if i in BUTTON_MAP and state and not previous_buttons[i]:
            action = BUTTON_MAP[i]
            try:
                if action == 'lights':
                    r = requests.get(f"{BASE_URL}/toggle_led", timeout=0.5)
                    print(f"Toggled LED: {r.text}")
                elif action == 'estop':
                    r = requests.get(f"{BASE_URL}/motor/all_stop", timeout=0.5)
                    estop_active = True
                    print("\n*** EMERGENCY STOP ENGAGED — press Start to release ***")
                    for key in smoothed:
                        smoothed[key] = 0.0
            except Exception as e:
                print(f"Error handling button {i}: {e}")

    previous_buttons = buttons


def print_status(values):
    """Print current control values (for debugging)."""
    surge = values['surge']
    sway = values['sway']
    yaw = values['yaw']
    descend = values['descend']
    ascend = values['ascend']
    tilt = values['tilt']
    estop_tag = " [E-STOP]" if estop_active else ""
    print(f"\rSurge: {surge:+.2f} | Sway: {sway:+.2f} | Yaw: {yaw:+.2f} | Desc: {descend:.2f} | Asc: {ascend:.2f} | Tilt: {tilt:+.2f}{estop_tag}  ", end='')


# =============================================================================
# MAIN LOOP
# =============================================================================
print(f"\nPWM Controller ready. Sending to: {BASE_URL}")
print("=" * 60)
print("Controls:")
print("  Right stick Y : Forward / Backward (surge)")
print("  Right stick X : Strafe Left / Right (sway)")
print("  Left stick X  : Rotate Left / Right (yaw)")
print("  Left stick Y  : Camera Tilt (up/down)")
print("  Left trigger  : Ascend (0-100%)")
print("  Right trigger : Descend (0-100%)")
print("  B button      : EMERGENCY STOP (latching)")
print("  Start button  : Release E-Stop")
print("  Y button      : Toggle LED")
print("=" * 60)
print(f"Trigger calibration: min={TRIGGER_MIN}, max={TRIGGER_MAX}")
print("\nPress Ctrl+C to exit\n")

try:
    last_send_time = time.time()

    while True:
        values = read_axes()
        check_buttons()
        send_heartbeat()

        # Only send motor commands if E-stop is not active
        # (server also enforces this, but skip the network call entirely)
        if not estop_active:
            now = time.time()
            if values_changed(values) or (now - last_send_time > 0.25):
                if send_pwm_command(values):
                    last_send_time = now
                    print_status(values)
        else:
            # While E-stop is active, keep smoothed values at zero
            for key in smoothed:
                smoothed[key] = 0.0

        # Camera tilt — independent of E-stop (tilt is always active)
        # Rate control: send on change OR keepalive every 0.25 s while stick is held
        tilt = values['tilt']
        now_t = time.time()
        tilt_changed   = abs(tilt - last_tilt_sent) > CHANGE_THRESHOLD
        tilt_keepalive = abs(tilt) > 0.05 and (now_t - last_tilt_time) > 0.25
        if tilt_changed or tilt_keepalive:
            try:
                requests.post(f"{BASE_URL}/camera/tilt", json={'value': tilt}, timeout=0.2)
                last_tilt_sent = tilt
                last_tilt_time = now_t
            except Exception as e:
                print(f"Tilt error: {e}")

        time.sleep(SEND_INTERVAL)

except KeyboardInterrupt:
    print("\n\nShutting down...")
    # Send stop command on exit
    try:
        requests.get(f"{BASE_URL}/motor/all_stop", timeout=0.5)
        print("Motors stopped.")
    except Exception:
        print("Could not send stop command.")
    print("Controller disconnected.")
finally:
    pygame.quit()
