# Feature Implementation Plan

## Overview

Three new features for the ROV control system:
1. Video recording with telemetry overlay
2. Still picture capture at maximum resolution
3. Depth hold using PID control

---

## Feature 1: Video Recording with Telemetry Overlay

### Goal
Record video with telemetry data (depth, pitch, roll, heading, temperature) burned into the video for post-mission playback.

### Implementation Approach

**Backend Changes (`camera_module.py`):**
- Add video recording state management (recording flag, output file)
- Use OpenCV VideoWriter to encode H.264 video
- Overlay telemetry text onto each frame before writing
- Continue streaming to web while recording

**New Routes (`routes.py`):**
- `POST /recording/start` - Start recording, creates timestamped file
- `POST /recording/stop` - Stop recording, finalize video file
- `GET /recording/status` - Returns recording state and current filename

**Storage:**
- Save to `rov_clean/recordings/` directory
- Filename format: `ROV_YYYY-MM-DD_HH-MM-SS.mp4`

**Frontend Changes:**
- Add "Record" toggle button (red when recording)
- Show recording indicator and elapsed time

### Technical Details

```python
# Telemetry overlay format (burned into video):
# Top-left corner:
#   Depth: 12.3 ft
#   Pitch: -5.2°  Roll: 2.1°
#   Heading: 127°
#   Water: 62.1°F
# Bottom-right: timestamp
```

**Dependencies:** OpenCV (`cv2`) for video encoding

---

## Feature 2: Still Picture Capture

### Goal
Capture high-resolution still images using the full capability of the Raspberry Pi Camera Module v3.

### Camera Module v3 Specs
- **Max still resolution:** 4608 x 2592 (11.9 MP)
- **Sensor:** Sony IMX708

### Implementation Approach

**Backend Changes (`camera_module.py`):**
- Add separate capture function for stills at max resolution
- Temporarily pause video stream during capture (user requested)
- Save image with timestamp and depth metadata

**New Route (`routes.py`):**
- `POST /capture_image` - Capture still, returns filename
- `GET /images/<filename>` - Serve captured images

**Storage:**
- Save to `rov_clean/images/` directory
- Filename format: `ROV_YYYY-MM-DD_HH-MM-SS_depth-XX.Xft.jpg`
- JPEG quality: 95%

**Frontend Changes:**
- Add "Capture" button
- Flash screen briefly to indicate capture
- Show notification with image filename

### Technical Details

```python
# Capture sequence:
1. Pause video stream generator
2. Reconfigure camera for max resolution still
3. Capture image to file
4. Reconfigure camera back to video mode
5. Resume video stream
# Expected pause duration: ~1-2 seconds
```

---

## Feature 3: Depth Hold (PID Control)

### Goal
Automatically maintain a target depth using the descend/ascend thrusters with a PID controller.

### Control Loop Design

```
                    ┌─────────────┐
  Target Depth ──>  │             │
                    │  PID        │──> Descend/Ascend Motor Commands
  Current Depth ──> │  Controller │
  (from LPS28)      │             │
                    └─────────────┘
```

### Implementation Approach

**New Module (`depth_hold.py`):**
```python
class DepthHoldController:
    def __init__(self, kp=0.5, ki=0.1, kd=0.2):
        self.kp = kp          # Proportional gain
        self.ki = ki          # Integral gain
        self.kd = kd          # Derivative gain
        self.target_depth = 0.0
        self.enabled = False
        self.integral = 0.0
        self.last_error = 0.0

    def set_target(self, depth_ft):
        """Set target depth and reset integral"""

    def update(self, current_depth):
        """Calculate PID output, returns (descend, ascend) tuple"""

    def enable(self):
        """Enable depth hold at current depth"""

    def disable(self):
        """Disable depth hold, return to manual control"""
```

**PID Output Mapping:**
- Positive error (too shallow) → Increase `descend` value
- Negative error (too deep) → Increase `ascend` value
- Output clamped to 0.0 - 1.0 range

**Integration Options:**

**Option A: ROV-side (Recommended)**
- Run PID loop in background thread on Pi
- Automatically overrides descend/ascend from controller when enabled
- Controller can still control surge/sway/yaw while depth is held
- More responsive (no network latency)

**Option B: PC-side**
- Run PID in winconpi5.py
- Requires continuous sensor polling from PC
- Higher latency, less reliable

**New Routes (`routes.py`):**
- `POST /depth_hold/enable` - Enable at current depth
- `POST /depth_hold/disable` - Return to manual
- `POST /depth_hold/set_target` - Set specific target depth
- `GET /depth_hold/status` - Returns enabled state, target, current depth
- `POST /depth_hold/tune` - Adjust PID gains (optional)

**Frontend Changes:**
- Add "Depth Hold" toggle button
- Show target depth when enabled
- Visual indicator (lock icon or color change)
- Optional: depth target adjustment (+/- buttons or slider)

### Safety Considerations
- Disable depth hold on emergency stop
- Limit maximum motor output (e.g., 80%) to prevent aggressive corrections
- Add deadband around target (e.g., ±0.1 ft) to prevent oscillation
- Timeout if depth changes too rapidly (possible sensor error)

### PID Tuning Starting Values
Based on typical underwater ROV characteristics:
- **Kp = 0.5** - Proportional response
- **Ki = 0.1** - Integral to eliminate steady-state error
- **Kd = 0.2** - Derivative to dampen oscillations
- **Update rate:** 20 Hz (50ms interval)
- **Deadband:** ±0.1 ft

---

## File Changes Summary

### New Files
| File | Purpose |
|------|---------|
| `rov_clean/depth_hold.py` | PID controller for depth hold |
| `rov_clean/recordings/` | Directory for recorded videos |
| `rov_clean/images/` | Directory for captured images |

### Modified Files
| File | Changes |
|------|---------|
| `camera_module.py` | Add recording and still capture functions |
| `routes.py` | Add routes for recording, capture, depth hold |
| `index.html` | Add Record, Capture, Depth Hold buttons |
| `script.js` | Add button handlers and status polling |
| `style.css` | Style new buttons and indicators |
| `motors.py` | Integration point for depth hold output |

---

## Implementation Order

1. **Still Picture Capture** (simplest, standalone)
   - Modify camera_module.py
   - Add /capture_image route
   - Add frontend button

2. **Video Recording** (builds on camera knowledge)
   - Add recording functions to camera_module.py
   - Add start/stop routes
   - Add frontend controls

3. **Depth Hold PID** (most complex, needs testing)
   - Create depth_hold.py module
   - Add routes
   - Integrate with motor controller
   - Add frontend controls
   - Tune PID gains through testing

---

## Questions/Decisions Needed

1. **Video format:** H.264 (smaller) or MJPEG (simpler but larger)?
2. **Depth hold activation:** Hold current depth on button press, or allow setting specific target?
3. **PID tuning:** Hardcoded initial values or expose tuning UI?
4. **Recording storage:** Local only or option to download via web?
