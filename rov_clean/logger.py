# logger.py
import time, sys

log_buffer = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    log_buffer.append(entry)
    if len(log_buffer) > 300:
        log_buffer.pop(0)
    sys.__stdout__.write(entry + "\n")
