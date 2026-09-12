import time
import board
import adafruit_lps28
import qwiic_lsm6dso

i2c = board.I2C()
ps = adafruit_lps28.LPS28(i2c)

imu = qwiic_lsm6dso.QwiicLSM6DSO()
print("IMU connected:", imu.connected)
imu.begin()

for i in range(60):
    ax, ay, az = imu.read_float_accel_all()
    gx, gy, gz = imu.read_float_gyro_all()
    t = imu.read_temp_c()
    p = ps.pressure
    pt = ps.temperature
    print(f"[{i:02d}] accel=({ax:+.3f},{ay:+.3f},{az:+.3f}) g  "
          f"gyro=({gx:+.2f},{gy:+.2f},{gz:+.2f}) dps  "
          f"imu_temp={t:.2f}C  press={p:.2f}hPa  press_temp={pt:.2f}C")
    time.sleep(0.3)
