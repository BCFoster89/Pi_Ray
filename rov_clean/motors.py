import time, threading
import RPi.GPIO as GPIO
from logger import log
from config import motor_pins, MOTOR_GROUPS, MAX_ACTIVE_GROUPS, GROUP_STAGGER_S, MIN_ACTIVATE_INTERVAL_S

class MotorController:
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

motor = MotorController()

if __name__ == "__main__":
    log("Motor debug mode")
    print("Toggling 'x' group:", motor.toggle('x'))
    time.sleep(1)
    print("Toggling 'x' group:", motor.toggle('x'))
