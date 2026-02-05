# motors.py
import time
import threading
import RPi.GPIO as GPIO
from gpiozero import PWMOutputDevice
from logger import log
from config import (motor_pins, MOTOR_GROUPS, MAX_ACTIVE_GROUPS, GROUP_STAGGER_S,
                    MIN_ACTIVATE_INTERVAL_S, THRUST_MIX, VERTICAL_MIX,
                    BIDIRECTIONAL_PINS, PWM_CONFIG, pwm_state)


class MotorController:
    """Legacy on/off motor controller for manual button control."""

    def __init__(self):
        self.status = {p: 0 for p in motor_pins}
        self.active = set()
        self.lock = threading.Lock()
        self.last_time = 0.0

    def toggle(self, name):
        now = time.time()
        pins = MOTOR_GROUPS[name]
        with self.lock:
            turn_on = any(self.status[p] == 0 for p in pins)
            if turn_on:
                if len(self.active) >= MAX_ACTIVE_GROUPS:
                    return "denied"
                if now - self.last_time < MIN_ACTIVATE_INTERVAL_S:
                    return "wait"
                for p in pins:
                    self.status[p] = 1
                    GPIO.output(p, GPIO.HIGH)
                    log(f"[MOTOR] {name} ON motor {p}")
                    time.sleep(GROUP_STAGGER_S)
                self.active.add(name)
                self.last_time = now
                return "on"
            else:
                for p in pins:
                    self.status[p] = 0
                    GPIO.output(p, GPIO.LOW)
                self.active.discard(name)
                log(f"[MOTOR] {name} OFF")
                return "off"


class PWMMotorController:
    """PWM-based motor controller for proportional vectored thrust control."""

    def __init__(self):
        self.lock = threading.Lock()
        self.pwm_devices = {}
        self.current_duties = {p: 0.0 for p in motor_pins}
        self.target_duties = {p: 0.0 for p in motor_pins}
        self.last_command_time = 0.0
        self.initialized = False

        # Configuration
        self.frequency = PWM_CONFIG['frequency']
        self.deadband = PWM_CONFIG['deadband']
        self.ramp_rate = PWM_CONFIG['ramp_rate']
        self.stagger_delay = PWM_CONFIG['stagger_delay']
        self.watchdog_timeout = PWM_CONFIG['watchdog_timeout']

    def initialize(self):
        """Initialize PWM devices. Called lazily on first use."""
        if self.initialized:
            return

        with self.lock:
            if self.initialized:
                return

            log("[PWM] Initializing PWM motor controller...")

            # Clean up GPIO before initializing gpiozero PWM
            for p in motor_pins:
                GPIO.output(p, GPIO.LOW)

            # Initialize PWM devices for each motor
            for pin in motor_pins:
                try:
                    self.pwm_devices[pin] = PWMOutputDevice(
                        pin,
                        active_high=True,
                        initial_value=0,
                        frequency=self.frequency
                    )
                    log(f"[PWM] Motor pin {pin} initialized")
                except Exception as e:
                    log(f"[PWM] Failed to initialize pin {pin}: {e}")

            self.initialized = True
            log("[PWM] PWM motor controller ready")

    def apply_deadband(self, value):
        """Apply deadband to input value."""
        if abs(value) < self.deadband:
            return 0.0
        # Rescale so deadband edge maps to 0
        sign = 1.0 if value > 0 else -1.0
        return sign * (abs(value) - self.deadband) / (1.0 - self.deadband)

    def calculate_motor_duties(self, surge, sway, yaw, heave):
        """
        Calculate PWM duty cycles for all motors based on thrust vector.

        Args:
            surge: -1.0 to +1.0 (forward/back)
            sway:  -1.0 to +1.0 (strafe left/right)
            yaw:   -1.0 to +1.0 (rotate left/right)
            heave: -1.0 to +1.0 (descend/ascend)

        Returns:
            dict of {pin: duty_cycle} where duty_cycle is 0.0-1.0
        """
        duties = {}

        # Horizontal thrusters (unidirectional - only positive duty cycle)
        for pin, (s_mix, w_mix, y_mix) in THRUST_MIX.items():
            # Calculate raw thrust contribution
            raw = surge * s_mix + sway * w_mix + yaw * y_mix
            # Unidirectional motors: clamp to 0-1 range
            # Negative values mean "this motor doesn't contribute in this direction"
            duties[pin] = max(0.0, min(1.0, raw))

        # Vertical thrusters (bidirectional)
        for pin, h_mix in VERTICAL_MIX.items():
            raw = heave * h_mix
            if pin in BIDIRECTIONAL_PINS:
                # Bidirectional: map -1..+1 to 0..1 (0.5 = neutral/off)
                # Actually, for simplicity with ESC, we'll use:
                # positive heave = motor on at that duty
                # negative heave = motor on at abs(duty) but ESC reverses
                # For now, we'll just use absolute value since the ESC handles direction
                duties[pin] = min(1.0, abs(raw))
            else:
                duties[pin] = max(0.0, min(1.0, raw))

        return duties

    def smooth_duty(self, pin, target):
        """Apply rate limiting for smooth transitions."""
        current = self.current_duties[pin]
        delta = target - current

        # Apply rate limiting
        if abs(delta) > self.ramp_rate:
            delta = self.ramp_rate if delta > 0 else -self.ramp_rate

        return current + delta

    def set_thrust_vector(self, surge, sway, yaw, heave):
        """
        Set the thrust vector for the ROV.

        Args:
            surge: -1.0 to +1.0 (forward/back from left stick Y)
            sway:  -1.0 to +1.0 (strafe from left stick X)
            yaw:   -1.0 to +1.0 (rotation from right stick X)
            heave: -1.0 to +1.0 (dive/ascend from triggers)

        Returns:
            dict of current duty cycles
        """
        self.initialize()

        # Apply deadband to inputs
        surge = self.apply_deadband(surge)
        sway = self.apply_deadband(sway)
        yaw = self.apply_deadband(yaw)
        heave = self.apply_deadband(heave)

        # Calculate target duty cycles
        target_duties = self.calculate_motor_duties(surge, sway, yaw, heave)

        with self.lock:
            self.last_command_time = time.time()

            # Apply smoothing and update motors with stagger delay
            for pin in motor_pins:
                target = target_duties.get(pin, 0.0)
                smoothed = self.smooth_duty(pin, target)

                # Only update if changed significantly
                if abs(smoothed - self.current_duties[pin]) > 0.01:
                    self.current_duties[pin] = smoothed
                    if pin in self.pwm_devices:
                        self.pwm_devices[pin].value = smoothed
                    time.sleep(self.stagger_delay)

            # Update shared state
            pwm_state['duties'] = self.current_duties.copy()
            pwm_state['active'] = any(d > 0 for d in self.current_duties.values())
            pwm_state['last_update'] = self.last_command_time
            pwm_state['control_mode'] = 'pwm'

        return self.current_duties.copy()

    def emergency_stop(self):
        """Immediately stop all motors."""
        self.initialize()

        with self.lock:
            log("[PWM] EMERGENCY STOP")
            for pin in motor_pins:
                self.current_duties[pin] = 0.0
                self.target_duties[pin] = 0.0
                if pin in self.pwm_devices:
                    self.pwm_devices[pin].value = 0.0

            # Update shared state
            pwm_state['duties'] = {p: 0.0 for p in motor_pins}
            pwm_state['active'] = False
            pwm_state['last_update'] = time.time()

    def check_watchdog(self):
        """Check if watchdog has timed out. Call periodically."""
        if self.last_command_time > 0:
            elapsed = time.time() - self.last_command_time
            if elapsed > self.watchdog_timeout:
                if any(d > 0 for d in self.current_duties.values()):
                    log(f"[PWM] Watchdog timeout ({elapsed:.2f}s) - stopping motors")
                    self.emergency_stop()
                    return True
        return False

    def get_status(self):
        """Get current PWM status."""
        with self.lock:
            return {
                'duties': self.current_duties.copy(),
                'active': any(d > 0 for d in self.current_duties.values()),
                'last_update': self.last_command_time,
                'control_mode': pwm_state['control_mode']
            }

    def cleanup(self):
        """Clean up PWM devices."""
        with self.lock:
            for pin, device in self.pwm_devices.items():
                try:
                    device.value = 0
                    device.close()
                except:
                    pass
            self.pwm_devices.clear()
            self.initialized = False
            log("[PWM] Cleanup complete")


# Singleton controller instances
motor = MotorController()
pwm_motor = PWMMotorController()
