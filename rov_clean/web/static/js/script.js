// === E-STOP STATE ===
let estopLocked = false;

// Poll E-stop state from server to keep UI in sync
async function pollEstopStatus() {
  try {
    let r = await fetch('/motor/estop_status', { cache: "no-store" });
    let data = await r.json();
    estopLocked = data.estop_locked;
    updateEstopUI();
  } catch (e) {
    // Silently fail — covered by heartbeat
  }
}

function updateEstopUI() {
  const btn = document.getElementById('estopBtn');
  if (estopLocked) {
    btn.textContent = 'E-STOP ACTIVE — Click to Release';
    btn.classList.add('estop-active');
  } else {
    btn.textContent = 'ALL STOP';
    btn.classList.remove('estop-active');
  }
}

function emergencyStop() {
  if (estopLocked) {
    // If already locked, clicking releases it
    fetch('/motor/estop_release', { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          estopLocked = false;
          updateEstopUI();
          // Flash green to confirm release
          document.body.style.boxShadow = 'inset 0 0 60px rgba(0, 255, 0, 0.4)';
          setTimeout(() => { document.body.style.boxShadow = 'none'; }, 300);
        }
      })
      .catch(console.error);
  } else {
    // Engage E-stop
    fetch('/motor/all_stop')
      .then(r => r.json())
      .then(d => {
        estopLocked = true;
        updateEstopUI();
        // Flash red to confirm
        document.body.style.boxShadow = 'inset 0 0 100px rgba(255, 0, 0, 0.5)';
        setTimeout(() => { document.body.style.boxShadow = 'none'; }, 300);
      })
      .catch(console.error);
  }
}

setInterval(pollEstopStatus, 500);

// === PWM THRUSTER STATUS ===
async function pollPWMStatus() {
  try {
    let r = await fetch('/motor/pwm_status', { cache: "no-store" });
    let data = await r.json();

    // Update horizontal thruster displays by pin
    for (let pin in data.duties) {
      updateThrusterDisplay(pin, data.duties[pin]);
    }

    // Update vertical thrust indicators (descend/ascend)
    updateThrusterDisplay('descend', data.descend || 0);
    updateThrusterDisplay('ascend', data.ascend || 0);

    // Update control mode indicator
    const modeEl = document.getElementById('control-mode');
    if (modeEl) {
      modeEl.textContent = `Mode: ${data.control_mode.toUpperCase()}`;
      modeEl.classList.remove('pwm', 'manual');
      modeEl.classList.add(data.control_mode);
    }

  } catch (e) {
    console.error("PWM status fetch failed", e);
  }
}

function updateThrusterDisplay(pin, duty) {
  const fill = document.getElementById(`fill-${pin}`);
  const value = document.getElementById(`duty-${pin}`);

  if (!fill || !value) return;

  const percent = Math.round(duty * 100);
  fill.style.width = `${percent}%`;
  value.textContent = `${percent}%`;

  // Color coding based on intensity
  fill.classList.remove('medium', 'high');
  if (percent > 75) {
    fill.classList.add('high');
  } else if (percent > 40) {
    fill.classList.add('medium');
  }
}

// Poll PWM status at 10Hz for smooth updates
setInterval(pollPWMStatus, 100);

// === BUTTON FUNCTIONS ===
function toggleMotor(name){
  fetch(`/motor/${name}`)
    .then(r => r.json())
    .then(d => console.log("Motor:", d))
    .catch(console.error);
}

function calibrateDepth(){
  fetch('/cal_depth').then(r => r.text());
}

function calibrateHorizon(){
  fetch('/cal_horizon').then(r => r.text());
}

function zeroIMU(){
  fetch('/zero_imu').then(r => r.text());
}

function toggleLED(){
  fetch('/toggle_led').then(r => r.text());
}

// === RECORDING FUNCTIONS ===
let isRecording = false;

async function toggleRecording() {
  const btn = document.getElementById('recordBtn');
  const statusEl = document.getElementById('recordingStatus');

  try {
    if (!isRecording) {
      // Start recording
      let r = await fetch('/recording/start', { method: 'POST' });
      let data = await r.json();
      if (data.success) {
        isRecording = true;
        btn.classList.add('recording');
        btn.textContent = 'Stop';
        statusEl.textContent = `Recording: ${data.filename}`;
        // Flash screen green
        document.body.style.boxShadow = 'inset 0 0 50px rgba(0, 255, 0, 0.3)';
        setTimeout(() => { document.body.style.boxShadow = 'none'; }, 200);
      }
    } else {
      // Stop recording
      let r = await fetch('/recording/stop', { method: 'POST' });
      let data = await r.json();
      isRecording = false;
      btn.classList.remove('recording');
      btn.textContent = 'Record';
      statusEl.textContent = data.filename ? `Saved: ${data.filename}` : '';
    }
  } catch (e) {
    console.error("Recording error:", e);
    statusEl.textContent = 'Error';
  }
}

// Poll recording status to update elapsed time
async function pollRecordingStatus() {
  if (!isRecording) return;
  try {
    let r = await fetch('/recording/status', { cache: "no-store" });
    let data = await r.json();
    const statusEl = document.getElementById('recordingStatus');
    if (data.recording) {
      const mins = Math.floor(data.elapsed_seconds / 60);
      const secs = Math.floor(data.elapsed_seconds % 60);
      statusEl.textContent = `Recording: ${mins}:${secs.toString().padStart(2, '0')}`;
    }
  } catch (e) {
    console.error("Recording status error:", e);
  }
}
setInterval(pollRecordingStatus, 1000);

// === STILL CAPTURE (uses separate #captureStatus element) ===
async function captureImage() {
  const btn = document.getElementById('captureBtn');
  const captureEl = document.getElementById('captureStatus');
  btn.disabled = true;
  btn.textContent = 'Capturing...';

  try {
    // Flash screen white to indicate capture
    document.body.style.boxShadow = 'inset 0 0 100px rgba(255, 255, 255, 0.8)';
    setTimeout(() => { document.body.style.boxShadow = 'none'; }, 150);

    let r = await fetch('/capture_image', { method: 'POST' });
    let data = await r.json();

    if (data.success) {
      captureEl.textContent = `Captured: ${data.filename}`;
      setTimeout(() => {
        if (captureEl.textContent.startsWith('Captured:')) {
          captureEl.textContent = '';
        }
      }, 3000);
    } else {
      captureEl.textContent = `Capture failed: ${data.error || 'unknown'}`;
    }
  } catch (e) {
    console.error("Capture error:", e);
    captureEl.textContent = 'Capture error';
  }

  btn.disabled = false;
  btn.textContent = 'Capture';
}

// === DEPTH HOLD FUNCTIONS ===
let depthHoldEnabled = false;

async function toggleDepthHold() {
  const btn = document.getElementById('depthHoldBtn');
  const statusEl = document.getElementById('depthHoldStatus');

  try {
    if (!depthHoldEnabled) {
      // Enable depth hold
      let r = await fetch('/depth_hold/enable', { method: 'POST' });
      let data = await r.json();
      if (data.success) {
        depthHoldEnabled = true;
        btn.classList.add('active');
        btn.textContent = 'Release';
        statusEl.textContent = `Holding: ${data.status.target_depth.toFixed(1)} ft`;
      } else {
        statusEl.textContent = data.error || 'Failed';
      }
    } else {
      // Disable depth hold
      let r = await fetch('/depth_hold/disable', { method: 'POST' });
      depthHoldEnabled = false;
      btn.classList.remove('active');
      btn.textContent = 'Depth Hold';
      statusEl.textContent = '';
    }
  } catch (e) {
    console.error("Depth hold error:", e);
    statusEl.textContent = 'Error';
  }
}

async function updatePIDGains() {
  const kp = parseFloat(document.getElementById('pidKp').value);
  const ki = parseFloat(document.getElementById('pidKi').value);
  const kd = parseFloat(document.getElementById('pidKd').value);

  try {
    let r = await fetch('/depth_hold/tune', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kp, ki, kd })
    });
    let data = await r.json();
    if (data.success) {
      console.log("PID gains updated:", data.status);
    } else {
      alert("PID error: " + (data.error || "unknown"));
    }
  } catch (e) {
    console.error("PID tune error:", e);
  }
}

// Poll depth hold status
async function pollDepthHoldStatus() {
  try {
    let r = await fetch('/depth_hold/status', { cache: "no-store" });
    let data = await r.json();

    const btn = document.getElementById('depthHoldBtn');
    const statusEl = document.getElementById('depthHoldStatus');

    // Sync state with server
    depthHoldEnabled = data.enabled;

    if (data.enabled) {
      btn.classList.add('active');
      btn.textContent = 'Release';
      statusEl.textContent = `Target: ${data.target_depth.toFixed(1)} ft | Error: ${data.error.toFixed(2)} ft`;
    } else {
      btn.classList.remove('active');
      btn.textContent = 'Depth Hold';
    }

    // Only update PID input fields if they are NOT currently focused
    const activeEl = document.activeElement;
    const kpEl = document.getElementById('pidKp');
    const kiEl = document.getElementById('pidKi');
    const kdEl = document.getElementById('pidKd');
    if (activeEl !== kpEl) kpEl.value = data.kp;
    if (activeEl !== kiEl) kiEl.value = data.ki;
    if (activeEl !== kdEl) kdEl.value = data.kd;

  } catch (e) {
    // Silently fail - server might not support depth hold yet
  }
}
setInterval(pollDepthHoldStatus, 500);

// === STATUS HEARTBEAT + LATENCY ===
async function heartbeatLoop(){
  let btn = document.getElementById("statusBtn");
  const latencyEl = document.getElementById("latencyIndicator");
  const t0 = performance.now();
  try {
    let r = await fetch('/heartbeat', { cache: "no-store" });
    const latency = Math.round(performance.now() - t0);
    if (r.ok){
      btn.textContent = "Pi Status: OK";
      btn.classList.remove("lost");
      btn.classList.add("ok");
      // Update latency display
      latencyEl.textContent = `${latency}ms`;
      latencyEl.classList.remove('warn', 'bad');
      if (latency > 200) latencyEl.classList.add('bad');
      else if (latency > 80) latencyEl.classList.add('warn');
    } else throw new Error("bad response");
  } catch {
    btn.textContent = "Pi Status: LOST";
    btn.classList.remove("ok");
    btn.classList.add("lost");
    latencyEl.textContent = "LOST";
    latencyEl.classList.add('bad');
  }
  setTimeout(heartbeatLoop, 2000);
}
heartbeatLoop();

// === TELEMETRY + OVERLAY ===
async function updateOverlay() {
  try {
    let r = await fetch('/status', { cache: "no-store" });
    let data = await r.json();
    let sensor = data.sensor;

    // draw HUD
    drawHUD(sensor);

    // update telemetry card — heading displayed as integer (aviation convention)
    const telemetryEl = document.getElementById("telemetry");

    const displayOrder = [
      { key: 'depth_ft', label: 'Depth', unit: 'ft', decimals: 1 },
      { key: 'pitch', label: 'Pitch', unit: '\u00B0', decimals: 1 },
      { key: 'roll', label: 'Roll', unit: '\u00B0', decimals: 1 },
      { key: 'yaw', label: 'Heading', unit: '\u00B0', decimals: 0 },
      { key: 'temperature_f', label: 'Water', unit: '\u00B0F', decimals: 1 },
      { key: 'imu_temp_f', label: 'Internal', unit: '\u00B0F', decimals: 1 }
    ];

    telemetryEl.textContent = displayOrder
      .map(item => {
        const val = sensor[item.key];
        const displayVal = (typeof val === 'number') ? val.toFixed(item.decimals) : (val || '0.0');
        return `${item.label.padEnd(8)}: ${displayVal} ${item.unit}`;
      })
      .join('\n');

    // Update leak indicator
    const leakBtn = document.getElementById('leakBtn');
    if (leakBtn) {
      if (sensor.leak_detected) {
        leakBtn.textContent = 'LEAK!';
        leakBtn.classList.remove('leak-ok');
        leakBtn.classList.add('leak-detected');
      } else {
        leakBtn.textContent = 'HULL: OK';
        leakBtn.classList.remove('leak-detected');
        leakBtn.classList.add('leak-ok');
      }
    }

    // Update sensor status indicator
    const sensorEl = document.getElementById('sensorStatus');
    if (sensorEl) {
      if (sensor.sensor_ok) {
        sensorEl.textContent = 'SENSORS: OK';
        sensorEl.classList.remove('offline');
      } else {
        sensorEl.textContent = 'SENSORS: OFFLINE';
        sensorEl.classList.add('offline');
      }
    }

  } catch (e) {
    console.warn("Telemetry fetch failed", e);
  }
  setTimeout(updateOverlay, 200);
}
updateOverlay();

// === LOGS ===
async function updateLogs() {
  try {
    let r = await fetch('/logs', { cache: "no-store" });
    let text = await r.text();
    const logsEl = document.getElementById("logs");
    const logsCard = document.getElementById("logsCard");

    // Clean up <br> tags and show last 20 lines
    logsEl.textContent = text.split("<br>").slice(-20).join("\n");

    // AUTO-SCROLL: This pushes the view to the bottom
    logsCard.scrollTop = logsCard.scrollHeight;

  } catch (e) {
    console.warn("Log fetch failed", e);
  }
  setTimeout(updateLogs, 1000);
}
updateLogs();

// === HUD DRAWING ===
function drawHUD(sensor){
  let canvas = document.getElementById("overlay");
  let ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;

  ctx.clearRect(0,0,canvas.width,canvas.height);
  let cx = canvas.width/2;

  // === ARTIFICIAL HORIZON (small circle, top-left) ===
  const ahRadius = 50;  // 100px diameter circle
  const ahX = 80;       // center X position
  const ahY = 120;      // center Y position
  const pitchScale = 8; // pixels per degree of pitch

  ctx.save();

  // Create circular clipping region
  ctx.beginPath();
  ctx.arc(ahX, ahY, ahRadius, 0, Math.PI * 2);
  ctx.clip();

  // Translate to circle center and apply roll rotation
  ctx.translate(ahX, ahY);
  ctx.rotate((-sensor.roll || 0) * Math.PI / 180);

  // Calculate pitch offset
  let pitchOffset = (sensor.pitch || 0) * pitchScale;

  // Draw sky (blue) - large rectangle above horizon
  ctx.fillStyle = "#1a4a7a";
  ctx.fillRect(-ahRadius * 2, -ahRadius * 2 + pitchOffset, ahRadius * 4, ahRadius * 2);

  // Draw ground (brown) - large rectangle below horizon
  ctx.fillStyle = "#5a3a1a";
  ctx.fillRect(-ahRadius * 2, pitchOffset, ahRadius * 4, ahRadius * 2);

  // Draw horizon line
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-ahRadius * 2, pitchOffset);
  ctx.lineTo(ahRadius * 2, pitchOffset);
  ctx.stroke();

  // Draw pitch ladder lines (every 2 degrees)
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1;
  ctx.font = "8px Arial";
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  for (let p = -10; p <= 10; p += 2) {
    if (p === 0) continue;
    let offset = pitchOffset - p * pitchScale;
    let lineWidth = (p % 4 === 0) ? 24 : 12;
    ctx.beginPath();
    ctx.moveTo(-lineWidth / 2, offset);
    ctx.lineTo(lineWidth / 2, offset);
    ctx.stroke();
    if (p % 4 === 0) {
      ctx.fillText(Math.abs(p) + "", lineWidth / 2 + 6, offset + 3);
    }
  }

  ctx.restore();

  // Draw fixed aircraft reference symbol (center of circle, not rotated)
  ctx.strokeStyle = "#fa0";
  ctx.lineWidth = 2;
  // Left wing
  ctx.beginPath();
  ctx.moveTo(ahX - 25, ahY);
  ctx.lineTo(ahX - 10, ahY);
  ctx.stroke();
  // Right wing
  ctx.beginPath();
  ctx.moveTo(ahX + 10, ahY);
  ctx.lineTo(ahX + 25, ahY);
  ctx.stroke();
  // Center dot
  ctx.beginPath();
  ctx.arc(ahX, ahY, 3, 0, Math.PI * 2);
  ctx.stroke();

  // Draw circle border
  ctx.strokeStyle = "#888";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(ahX, ahY, ahRadius, 0, Math.PI * 2);
  ctx.stroke();

  // Draw roll indicator tick marks
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1;
  for (let r = -10; r <= 10; r += 2) {
    ctx.save();
    ctx.translate(ahX, ahY);
    ctx.rotate(r * Math.PI / 180);
    let tickLen = (r % 4 === 0) ? 8 : 4;
    ctx.beginPath();
    ctx.moveTo(0, -ahRadius - 2);
    ctx.lineTo(0, -ahRadius - 2 - tickLen);
    ctx.stroke();
    ctx.restore();
  }

  // Roll pointer (rotates with roll)
  ctx.save();
  ctx.translate(ahX, ahY);
  ctx.rotate((-sensor.roll || 0) * Math.PI / 180);
  ctx.fillStyle = "#fa0";
  ctx.beginPath();
  ctx.moveTo(0, -ahRadius - 2);
  ctx.lineTo(-3, -ahRadius - 8);
  ctx.lineTo(3, -ahRadius - 8);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // === HEADING TAPE (top-center) ===
  let heading = sensor.yaw || 0;
  // Normalize heading to 0-359 for display (integer, aviation convention)
  let headingDisplay = Math.round(((heading % 360) + 360) % 360);

  ctx.fillStyle = "#ff0";
  ctx.font = "bold 16px Arial";
  ctx.textAlign = "center";

  // Digital readout (integer heading)
  ctx.fillText(`${headingDisplay}\u00B0`, cx, 25);

  // Heading tape
  let spacing = 5; // pixels per degree
  let snapHeading = Math.floor(heading / 10) * 10;

  ctx.beginPath();
  ctx.strokeStyle = "#ff0";
  ctx.lineWidth = 1;
  for (let i = -90; i <= 90; i += 10) {
    let mark = snapHeading + i;
    let x = cx + (mark - heading) * spacing;
    let displayMark = ((mark % 360) + 360) % 360;

    // Draw the tick mark
    ctx.moveTo(x, 45);
    ctx.lineTo(x, 55);
    ctx.stroke();

    // Label (cardinal or number)
    const getCardinal = (d) => {
      const directions = {0:"N", 45:"NE", 90:"E", 135:"SE", 180:"S", 225:"SW", 270:"W", 315:"NW"};
      return directions[d] !== undefined ? directions[d] : d;
    };

    let label = getCardinal(displayMark);
    ctx.font = (typeof label === "string") ? "bold 16px Arial" : "12px Arial";
    ctx.fillText(label, x, 70);
  }

  // Lubber line (center pointer)
  ctx.strokeStyle = "#f00";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx, 40);
  ctx.lineTo(cx, 60);
  ctx.stroke();
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#ff0";

  // === DEPTH DISPLAY (below artificial horizon to avoid overlap with heading tape) ===
  ctx.fillStyle = "#ff0";
  ctx.font = "bold 18px Arial";
  ctx.textAlign = "left";
  // Position below the artificial horizon circle (ahY + ahRadius + margin)
  ctx.fillText(`Depth: ${(sensor.depth_ft||0).toFixed(1)} ft`, 20, ahY + ahRadius + 30);
}
