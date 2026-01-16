import io, time
from flask import Response
from picamera2 import Picamera2

def init_camera():
    cam = Picamera2()
    vc = cam.create_video_configuration(main={"size":(1280,720)}, controls={"FrameRate":30})
    cam.configure(vc)
    cam.start()
    return cam

def video_feed(cam):
    def gen():
        stream = io.BytesIO()
        while True:
            try:
                cam.capture_file(stream, format="jpeg")
                stream.seek(0); frame = stream.read()
                stream.seek(0); stream.truncate()
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                time.sleep(1/30)
            except:
                time.sleep(1)
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    print("[TEST] Starting camera preview...")
    cam = init_camera()
    from flask import Flask
    app = Flask(__name__)

    @app.route('/video')
    def vid():
        return video_feed(cam)

    app.run(host="0.0.0.0", port=5001)