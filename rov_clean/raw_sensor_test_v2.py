import time
import board

i2c = board.I2C()

ps = None
try:
    import adafruit_lps28
    ps = adafruit_lps28.LPS28(i2c)
    print("Pressure sensor: OK")
except Exception as e:
    print(f"Pressure sensor: NOT FOUND ({e})")

imu = None
try:
    import qwiic_lsm6dso
    imu = qwiic_lsm6dso.QwiicLSM6DSO()
    if imu.connected:
        imu.begin()
        print("IMU: OK")
    else:
        imu = None
        print("IMU: NOT CONNECTED")
except Exception as e:
    imu = None
    print(f"IMU: FAILED ({e})")

mag = None
try:
    import adafruit_mmc56x3
    mag = adafruit_mmc56x3.MMC5603(i2c)
    print("Magnetometer: OK")
except Exception as e:
    print(f"Magnetometer: NOT FOUND ({e})")

print("--- starting read loop ---")
for i in range(60):
    line = f"[{i:02d}]"
    if ps is not None:
        try:
            line += f"  press={ps.pressure:.2f}hPa temp={ps.temperature:.2f}C"
        except Exception as e:
            line += f"  press=ERR({e})"
    if imu is not None:
        try:
            ax, ay, az = imu.read_float_accel_all()
            gx, gy, gz = imu.read_float_gyro_all()
            line += f"  accel=({ax:+.3f},{ay:+.3f},{az:+.3f})g gyro=({gx:+.2f},{gy:+.2f},{gz:+.2f})dps"
        except Exception as e:
            line += f"  imu=ERR({e})"
    if mag is not None:
        try:
            mx, my, mz = mag.magnetic
            line += f"  mag=({mx:+.1f},{my:+.1f},{mz:+.1f})"
        except Exception as e:
            line += f"  mag=ERR({e})"
    print(line)
    time.sleep(0.05)
