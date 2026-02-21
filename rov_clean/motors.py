# motors.py
import time
import threading
import math
import RPi.GPIO as GPIO
from gpiozero import PWMOutputDevice
from logger import log
from config import (motor_pins, horizontal_pins, descend_pins, ascend_pins,
                    MOTOR_GROUPS, MAX_ACTIVE_GROUPS, GROUP_STAGGER_S,
                    MIN_ACTIVATE_INTERVAL_S, THRUST_MIX, DESCEND_MIX, ASCEND_MIX,
                    PWM_CONFIG, pwm_state)


class MotorController:
    """Legacy on/off motor controller for manual button control."""

    # Pins that actually exist on the Pi (exclude placeholders)
    REAL_PINS = horizontal_pins + descend_pins

    def __init__(self):
        self.status = {p: 0 for p in motor_pins}
        self.active = set()
        self.lock = threading.Lock()
        self.last_time = 0.0

    def toggle(self, name):
        now = time.time()
        pins = MOTOR_GROUPS[name]
        # Filter to only real pins (skip placeholder pins like 1, 2)
        real_pins = [p for p in pins if p in self.REAL_PINS]
        if not real_pins:
            log(f"[MOTOR] {name} has no real pins configured yet")
            return "denied"

        with self.lock:
            turn_on = any(self.status[p] == 0 for p in real_pins)
            if turn_on:
                if len(self.active) >= MAX_ACTIVE_GROUPS:
                    return "denied"
                if now - self.last_time < MIN_ACTIVATE_INTERVAL_S:
                    return "wait"
                # Collect pins to update
                pins_to_update = []
                for p in real_pins:
                    self.status[p] = 1
                    pins_to_update.append(p)
                self.active.add(name)
                self.last_time = now

            else:
                pins_to_update = []
                for p in real_pins:
                    self.status[p] = 0
                    pins_to_update.append(p)
                self.active.discard(name)

        # Perform GPIO operations OUTSIDE lock to prevent blocking
        if turn_on:
            for p in pins_to_update:
                try:
                    GPIO.output(p, GPIO.HIGH)
                    log(f"[MOTOR] {name} ON motor {p}")
                except Exception as e:
                    log(f"[MOTOR] GPIO error pin {p}: {e}")
                time.sleep(GROUP_STAGGER_S)
            return "on"
        else:
            for p in pins_to_update:
                try:
                    GPIO.output(p, GPIO.LOW)
                except Exception as e:
                    log(f"[MOTOR] GPIO error pin {p}: {e}")
            log(f"[MOTOR] {name} OFF")
            return "off"


class PWMMotorController:
    """PWM-based motor controller for proportional vectored thrust control."""

    # Pins that actually exist on the Pi (exclude placeholders like 1, 2)
    REAL_PINS = horizontal_pins + descend_pins

    def __init__(self):
        self.lock = threading.Lock()
        self.pwm_devices = {}
        self.current_duties = {p: 0.0 for p in motor_pins}
        self.target_duties = {p: 0.0 for p in motor_pins}
        self.last_command_time = 0.0
        self.initialized = False

        # Track vertical thrust input values for UI display
        self.descend_value = 0.0
        self.ascend_value = 0.0

        # Configuration
        self.frequency = PWM_CONFIG['frequency']
        self.deadband = PWM_CONFIG['deadband']
        self.ramp_rate = PWM_CONFIG['ramp_rate']
        self.stagger_delay = PWM_CONFIG['stagger_delay']
        self.watchdog_timeout = PWM_CONFIG['watchdog_timeout']

        # Start watchdog thread
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        log("[PWM] Watchdog thread started")

    def _watchdog_loop(self):
        """Background thread that checks for motor command timeout."""
        while self._watchdog_running:
            try:
                self.check_watchdog()
            except Exception as e:
                log(f"[PWM] Watchdog error: {e}")
            time.sleep(0.1)  # Check every 100ms

    def initialize(self):
        """Initialize PWM devices. Called lazily on first use."""
        if self.initialized:
            return

        with self.lock:
            if self.initialized:
                return

            log("[PWM] Initializing PWM motor controller...")

            # Clean up GPIO before initializing gpiozero PWM (only real pins)
            for p in self.REAL_PINS:
                try:
                    GPIO.output(p, GPIO.LOW)
                except:
                    pass

            # Initialize PWM devices for each real motor pin (skip placeholders)
            for pin in self.REAL_PINS:
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

    def calculate_motor_duties(self, surge, sway, yaw, descend, ascend):
        """
        Calculate PWM duty cycles for all motors based on thrust vector.

        Args:
            surge:   0.0 to 1.0 (forward) or -1.0 to 0.0 (back)
            sway:    -1.0 to +1.0 (strafe left/right)
            yaw:     -1.0 to +1.0 (rotate left/right)
            descend: 0.0 to 1.0 (left trigger - descend intensity)
            ascend:  0.0 to 1.0 (right trigger - ascend intensity)

        Returns:
            dict of {pin: duty_cycle} where duty_cycle is 0.0-1.0
        """
        duties = {}

        # Horizontal thrusters (unidirectional - only positive duty cycle)
        # Only surge/sway/yaw affect these - NOT descend/ascend
        for pin, (s_mix, w_mix, y_mix) in THRUST_MIX.items():
            # Calculate raw thrust contribution
            raw = surge * s_mix + sway * w_mix + yaw * y_mix
            # Unidirectional motors: clamp to 0-1 range
            # Negative values mean "this motor doesn't contribute in this direction"
            duties[pin] = max(0.0, min(1.0, raw))

        # Descend motors (left trigger) - pins 6, 20
        for pin, mix in DESCEND_MIX.items():
            duties[pin] = max(0.0, min(1.0, descend * mix))

        # Ascend motors (right trigger) - pins 1, 2 (placeholders)
        for pin, mix in ASCEND_MIX.items():
            duties[pin] = max(0.0, min(1.0, ascend * mix))

        return duties

    def smooth_duty(self, pin, target):
        """Apply rate limiting for smooth transitions."""
        current = self.current_duties[pin]
        delta = target - current

        # Apply rate limiting
        if abs(delta) > self.ramp_rate:
            delta = self.ramp_rate if delta > 0 else -self.ramp_rate

        return current + delta

    def set_thrust_vector(self, surge, sway, yaw, descend, ascend):
        """
        Set the thrust vector for the ROV.

        Args:
            surge:   -1.0 to +1.0 (forward/back from left stick Y)
            sway:    -1.0 to +1.0 (strafe from left stick X)
            yaw:     -1.0 to +1.0 (rotation from right stick X)
            descend: 0.0 to 1.0 (left trigger - descend intensity)
            ascend:  0.0 to 1.0 (right trigger - ascend intensity)

        Returns:
            dict of current duty cycles
        """
        self.initialize()

        # Apply deadband to inputs
        surge = self.apply_deadband(surge)
        sway = self.apply_deadband(sway)
        yaw = self.apply_deadband(yaw)
        descend = self.apply_deadband(descend)
        ascend = self.apply_deadband(ascend)

        # Calculate target duty cycles
        target_duties = self.calculate_motor_duties(surge, sway, yaw, descend, ascend)

        # Collect updates to apply (minimize time holding lock)
        updates_to_apply = []

        with self.lock:
            self.last_command_time = time.time()

            # Store vertical thrust values for UI display
            self.descend_value = descend
            self.ascend_value = ascend

            # Calculate smoothed values and collect updates (only real pins)
            for pin in self.REAL_PINS:
                target = target_duties.get(pin, 0.0)
                smoothed = self.smooth_duty(pin, target)

                # Only update if changed significantly
                if abs(smoothed - self.current_duties[pin]) > 0.01:
                    self.current_duties[pin] = smoothed
                    if pin in self.pwm_devices:
                        updates_to_apply.append((pin, smoothed))

            # Update shared state (include all pins for UI display)
            pwm_state['duties'] = self.current_duties.copy()
            pwm_state['active'] = any(d > 0 for d in self.current_duties.values())
            pwm_state['last_update'] = self.last_command_time
            pwm_state['control_mode'] = 'pwm'
            result = self.current_duties.copy()

        # Apply PWM updates OUTSIDE lock with stagger delay
        for pin, value in updates_to_apply:
            try:
                self.pwm_devices[pin].value = value
            except Exception as e:
                log(f"[PWM] Error setting pin {pin}: {e}")
            if len(updates_to_apply) > 1:
                time.sleep(self.stagger_delay)

        return result

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

            # Reset vertical thrust values
            self.descend_value = 0.0
            self.ascend_value = 0.0

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
                'descend': self.descend_value,
                'ascend': self.ascend_value,
                'active': any(d > 0 for d in self.current_duties.values()),
                'last_update': self.last_command_time,
                'control_mode': pwm_state['control_mode']
            }

    def cleanup(self):
        """Clean up PWM devices."""
        # Stop watchdog thread FIRST to prevent deadlock
        self._watchdog_running = False
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=0.5)
            log("[PWM] Watchdog thread stopped")

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
