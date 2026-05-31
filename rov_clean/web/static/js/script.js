// === DEAD RECKONING STATE ===
let drState = { x: 0, y: 0, vx: 0, vy: 0, trail: [], lastTime: null };

// === FERROUS ANOMALY PINS ===
const ferrousPins = [];       // {x, y, strength} in world-frame metres
const PIN_THRESHOLD_UT = 5.0; // µT deviation to drop a pin
const PIN_DEBOUNCE_S   = 3.0; // minimum seconds between pins
const PIN_MIN_DIST_M   = 0.3; // minimum metres moved before a new pin
let _lastPinTime = 0;
let _lastPinX    = null;
let _lastPinY    = null;

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
  fetch('/toggle_led')
    .then(r => r.json())
    .then(d => {
      const btn = document.getElementById('ledBtn');
      if (d.led_on) {
        btn.classList.add('led-on');
        btn.textContent = 'LED ON';
      } else {
        btn.classList.remove('led-on');
        btn.textContent = 'Toggle LED';
      }
    })
    .catch(console.error);
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
let headingHoldEnabled = false;
let positionHoldEnabled = false;

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
        btn.textContent = 'ON';
        statusEl.textContent = `Holding: ${data.status.target_depth.toFixed(1)} ft`;
      } else {
        statusEl.textContent = data.error || 'Failed';
      }
    } else {
      // Disable depth hold
      let r = await fetch('/depth_hold/disable', { method: 'POST' });
      depthHoldEnabled = false;
      btn.classList.remove('active');
      btn.textContent = 'OFF';
      statusEl.textContent = '';
    }
  } catch (e) {
    console.error("Depth hold error:", e);
    statusEl.textContent = 'Error';
  }
}

async function goToDepth() {
  const input = document.getElementById('targetDepthInput');
  const depth = parseFloat(input.value);
  if (isNaN(depth) || depth < 0) {
    input.style.borderColor = '#f00';
    setTimeout(() => { input.style.borderColor = ''; }, 1000);
    return;
  }

  try {
    let r = await fetch('/depth_hold/enable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_depth: depth })
    });
    let data = await r.json();
    if (data.success) {
      depthHoldEnabled = true;
      const btn = document.getElementById('depthHoldBtn');
      btn.classList.add('active');
      btn.textContent = 'ON';
      const statusEl = document.getElementById('depthHoldStatus');
      statusEl.textContent = `Target: ${data.status.target_depth.toFixed(1)} ft`;
    } else {
      const statusEl = document.getElementById('depthHoldStatus');
      statusEl.textContent = data.error || 'Failed';
    }
  } catch (e) {
    console.error("Go-to-depth error:", e);
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
      btn.textContent = 'ON';
      statusEl.textContent = `Target: ${data.target_depth.toFixed(1)} ft | Error: ${data.error.toFixed(2)} ft`;
    } else {
      btn.classList.remove('active');
      btn.textContent = 'OFF';
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

// === HEADING HOLD FUNCTIONS ===
async function toggleHeadingHold() {
  const btn = document.getElementById('headingHoldBtn');
  const statusEl = document.getElementById('headingHoldStatus');
  try {
    if (!headingHoldEnabled) {
      let r = await fetch('/heading_hold/enable', { method: 'POST' });
      let data = await r.json();
      if (data.success) {
        headingHoldEnabled = true;
        btn.classList.add('active');
        btn.textContent = 'ON';
        statusEl.textContent = `Holding: ${data.status.target_heading.toFixed(0)}°`;
      } else {
        statusEl.textContent = data.error || 'Failed';
      }
    } else {
      await fetch('/heading_hold/disable', { method: 'POST' });
      headingHoldEnabled = false;
      btn.classList.remove('active');
      btn.textContent = 'OFF';
      statusEl.textContent = '';
    }
  } catch (e) {
    console.error("Heading hold error:", e);
    statusEl.textContent = 'Error';
  }
}

async function updateHeadingPID() {
  const kp = parseFloat(document.getElementById('headingKp').value);
  const ki = parseFloat(document.getElementById('headingKi').value);
  const kd = parseFloat(document.getElementById('headingKd').value);
  try {
    let r = await fetch('/heading_hold/tune', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kp, ki, kd })
    });
    let data = await r.json();
    if (!data.success) alert("Heading PID error: " + (data.error || "unknown"));
  } catch (e) {
    console.error("Heading PID tune error:", e);
  }
}

async function pollHeadingHoldStatus() {
  try {
    let r = await fetch('/heading_hold/status', { cache: "no-store" });
    let data = await r.json();
    const btn = document.getElementById('headingHoldBtn');
    const statusEl = document.getElementById('headingHoldStatus');
    headingHoldEnabled = data.enabled;
    if (data.enabled) {
      btn.classList.add('active');
      btn.textContent = 'ON';
      statusEl.textContent = `Target: ${data.target_heading.toFixed(0)}° | Err: ${data.error.toFixed(1)}°`;
    } else {
      btn.classList.remove('active');
      btn.textContent = 'OFF';
    }
    const activeEl = document.activeElement;
    const kpEl = document.getElementById('headingKp');
    const kiEl = document.getElementById('headingKi');
    const kdEl = document.getElementById('headingKd');
    if (activeEl !== kpEl) kpEl.value = data.kp;
    if (activeEl !== kiEl) kiEl.value = data.ki;
    if (activeEl !== kdEl) kdEl.value = data.kd;
  } catch (e) { /* silently ignore */ }
}
setInterval(pollHeadingHoldStatus, 500);

// === POSITION HOLD FUNCTIONS ===
async function togglePositionHold() {
  const btn = document.getElementById('positionHoldBtn');
  const statusEl = document.getElementById('positionHoldStatus');
  try {
    if (!positionHoldEnabled) {
      let r = await fetch('/position_hold/enable', { method: 'POST' });
      let data = await r.json();
      if (data.success) {
        positionHoldEnabled = true;
        btn.classList.add('active');
        btn.textContent = 'Release';
        statusEl.textContent = 'Station keeping active';
      } else {
        statusEl.textContent = data.error || 'Failed';
      }
    } else {
      await fetch('/position_hold/disable', { method: 'POST' });
      positionHoldEnabled = false;
      btn.classList.remove('active');
      btn.textContent = 'Station Keep';
      statusEl.textContent = '';
    }
  } catch (e) {
    console.error("Position hold error:", e);
    statusEl.textContent = 'Error';
  }
}

async function pollPositionHoldStatus() {
  try {
    let r = await fetch('/position_hold/status', { cache: "no-store" });
    let data = await r.json();
    const btn = document.getElementById('positionHoldBtn');
    const statusEl = document.getElementById('positionHoldStatus');
    positionHoldEnabled = data.enabled;
    if (data.enabled) {
      btn.classList.add('active');
      btn.textContent = 'Release';
      statusEl.textContent = `Vx:${data.dr_vx.toFixed(2)} Vy:${data.dr_vy.toFixed(2)} m/s`;
    } else {
      btn.classList.remove('active');
      btn.textContent = 'Station Keep';
    }
  } catch (e) { /* silently ignore */ }
}
setInterval(pollPositionHoldStatus, 500);

// === MAGNETOMETER CALIBRATION ===
let _magCalActive = false;
async function toggleMagCal() {
  const btn = document.getElementById('magCalBtn');
  const statusEl = document.getElementById('magCalStatus');
  if (!_magCalActive) {
    await fetch('/mag_cal/start', { method: 'POST' });
    _magCalActive = true;
    btn.classList.add('active');
    btn.textContent = 'Finish Cal';
    statusEl.textContent = 'Rotating... collecting samples';
    _pollMagCalSamples();
  } else {
    let r = await fetch('/mag_cal/finish', { method: 'POST' });
    let data = await r.json();
    _magCalActive = false;
    btn.classList.remove('active');
    btn.textContent = 'Mag Cal';
    if (data.success) {
      const hi = data.hard_iron.map(v => v.toFixed(1)).join(', ');
      statusEl.textContent = `Done! Hard iron: [${hi}]`;
    } else {
      statusEl.textContent = data.error || 'Failed';
    }
  }
}

async function _pollMagCalSamples() {
  if (!_magCalActive) return;
  try {
    let r = await fetch('/mag_cal/status', { cache: "no-store" });
    let data = await r.json();
    const statusEl = document.getElementById('magCalStatus');
    if (statusEl && data.collecting) {
      statusEl.textContent = `Collecting: ${data.sample_count} samples (need ≥50)`;
      setTimeout(_pollMagCalSamples, 500);
    }
  } catch (e) {}
}

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

    // draw HUD and attitude canvas
    drawHUD(sensor);

    // update depth card
    const depthEl = document.getElementById('depthDisplay');
    if (depthEl) depthEl.textContent = (sensor.depth_ft || 0).toFixed(1) + ' ft';

    // update ferrous anomaly bar
    const anomaly = sensor.mag_anomaly || 0;
    const ferrousFill = document.getElementById('ferrousFill');
    const ferrousVal  = document.getElementById('ferrousVal');
    if (ferrousFill && ferrousVal) {
      const fillPct = Math.min(100, (anomaly / 15.0) * 100);
      ferrousFill.style.width = fillPct + '%';
      ferrousFill.style.backgroundColor = anomaly > 10 ? '#f44' : anomaly > 5 ? '#fa0' : '#4af';
      ferrousVal.textContent = anomaly.toFixed(1) + 'µT';
    }

    // drop DR map pin at significant magnetic anomaly positions
    const now = Date.now() / 1000;
    const px = sensor.dr_x ?? null;
    const py = sensor.dr_y ?? null;
    if (anomaly >= PIN_THRESHOLD_UT && px !== null && py !== null) {
      const dtPin   = now - _lastPinTime;
      const dxPin   = _lastPinX === null ? Infinity : Math.abs(px - _lastPinX);
      const dyPin   = _lastPinY === null ? Infinity : Math.abs(py - _lastPinY);
      const distPin = Math.sqrt(dxPin * dxPin + dyPin * dyPin);
      if (dtPin > PIN_DEBOUNCE_S || distPin > PIN_MIN_DIST_M) {
        ferrousPins.push({ x: px, y: py, strength: anomaly });
        _lastPinTime = now;
        _lastPinX = px;
        _lastPinY = py;
      }
    }

    // dead reckoning update and map draw
    updateDeadReckoning(sensor);
    drawDRMap(sensor);

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

// === ARTIFICIAL HORIZON (drawn on #ahCanvas card) ===
function drawAH(sensor) {
  const canvas = document.getElementById("ahCanvas");
  if (!canvas) return;
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const ahX = canvas.width / 2;
  const ahY = canvas.height / 2;
  const ahRadius = Math.min(canvas.width, canvas.height) / 2 - 6;
  const pitchScale = 8;

  ctx.save();
  ctx.beginPath();
  ctx.arc(ahX, ahY, ahRadius, 0, Math.PI * 2);
  ctx.clip();

  ctx.translate(ahX, ahY);
  ctx.rotate((-sensor.roll || 0) * Math.PI / 180);

  const pitchOffset = (sensor.pitch || 0) * pitchScale;

  ctx.fillStyle = "#1a4a7a";
  ctx.fillRect(-ahRadius * 2, -ahRadius * 2 + pitchOffset, ahRadius * 4, ahRadius * 2);
  ctx.fillStyle = "#5a3a1a";
  ctx.fillRect(-ahRadius * 2, pitchOffset, ahRadius * 4, ahRadius * 2);

  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-ahRadius * 2, pitchOffset);
  ctx.lineTo(ahRadius * 2, pitchOffset);
  ctx.stroke();

  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1;
  ctx.font = "8px Arial";
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  for (let p = -10; p <= 10; p += 2) {
    if (p === 0) continue;
    const offset = pitchOffset - p * pitchScale;
    const lineWidth = (p % 4 === 0) ? 24 : 12;
    ctx.beginPath();
    ctx.moveTo(-lineWidth / 2, offset);
    ctx.lineTo(lineWidth / 2, offset);
    ctx.stroke();
    if (p % 4 === 0) {
      ctx.fillText(Math.abs(p) + "", lineWidth / 2 + 6, offset + 3);
    }
  }
  ctx.restore();

  // Aircraft reference symbol
  ctx.strokeStyle = "#fa0";
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(ahX - 25, ahY); ctx.lineTo(ahX - 10, ahY); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(ahX + 10, ahY); ctx.lineTo(ahX + 25, ahY); ctx.stroke();
  ctx.beginPath(); ctx.arc(ahX, ahY, 3, 0, Math.PI * 2); ctx.stroke();

  // Circle border
  ctx.strokeStyle = "#888";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(ahX, ahY, ahRadius, 0, Math.PI * 2);
  ctx.stroke();

  // Roll tick marks
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1;
  for (let r = -10; r <= 10; r += 2) {
    ctx.save();
    ctx.translate(ahX, ahY);
    ctx.rotate(r * Math.PI / 180);
    const tickLen = (r % 4 === 0) ? 8 : 4;
    ctx.beginPath();
    ctx.moveTo(0, -ahRadius - 2);
    ctx.lineTo(0, -ahRadius - 2 - tickLen);
    ctx.stroke();
    ctx.restore();
  }

  // Roll pointer
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
}

// === HUD DRAWING ===
function drawHUD(sensor){
  let canvas = document.getElementById("overlay");
  let ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;

  ctx.clearRect(0,0,canvas.width,canvas.height);
  let cx = canvas.width/2;

  // Draw artificial horizon on its own card canvas
  drawAH(sensor);

  // === HEADING TAPE (top-center) ===
  let heading = sensor.yaw || 0;
  // Server already sends [0, 360) — just round to integer
  let headingDisplay = Math.round(heading % 360);

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

}

// === DEAD RECKONING ===
function updateDeadReckoning(sensor) {
  // Prefer server-side DR (quaternion-accurate, 20Hz) if available
  if (typeof sensor.dr_x === 'number' && typeof sensor.dr_y === 'number') {
    drState.x  = sensor.dr_x;
    drState.y  = sensor.dr_y;
    drState.vx = sensor.dr_vx || 0;
    drState.vy = sensor.dr_vy || 0;
    drState.trail.push({ x: drState.x, y: drState.y });
    if (drState.trail.length > 500) drState.trail.shift();
    return;
  }

  // ── Client-side fallback (used when server DR unavailable) ──
  const now = performance.now() / 1000;
  if (drState.lastTime === null) { drState.lastTime = now; return; }
  const dt = now - drState.lastTime;
  drState.lastTime = now;
  if (dt <= 0 || dt > 1) return;

  const damping   = parseFloat(document.getElementById('drDamping').value)   || 0.95;
  const deadzone  = parseFloat(document.getElementById('drDeadzone').value)  || 0.05;
  const accelScale = parseFloat(document.getElementById('drAccelScale').value) || 1.0;

  const pitch = (sensor.pitch || 0) * Math.PI / 180;
  const roll  = (sensor.roll  || 0) * Math.PI / 180;
  const yaw   = (sensor.yaw   || 0) * Math.PI / 180;

  let ax_body = (sensor.accel_x || 0) + Math.sin(pitch) * 9.81;
  let ay_body = (sensor.accel_y || 0) - Math.sin(roll) * Math.cos(pitch) * 9.81;
  if (Math.abs(ax_body) < deadzone) ax_body = 0;
  if (Math.abs(ay_body) < deadzone) ay_body = 0;
  ax_body *= accelScale;
  ay_body *= accelScale;

  const ax_world = ax_body * Math.cos(yaw) - ay_body * Math.sin(yaw);
  const ay_world = ax_body * Math.sin(yaw) + ay_body * Math.cos(yaw);

  drState.vx = (drState.vx + ax_world * dt) * damping;
  drState.vy = (drState.vy + ay_world * dt) * damping;
  drState.x += drState.vx * dt;
  drState.y += drState.vy * dt;

  drState.trail.push({ x: drState.x, y: drState.y });
  if (drState.trail.length > 500) drState.trail.shift();
}

function drawDRMap(sensor) {
  const canvas = document.getElementById('drMapCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  // Set actual pixel size to match CSS size
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;

  const w = canvas.width;
  const h = canvas.height;

  // Dark background
  ctx.fillStyle = '#0a1020';
  ctx.fillRect(0, 0, w, h);

  // Compute bounding box of trail + current position
  let minX = drState.x, maxX = drState.x;
  let minY = drState.y, maxY = drState.y;
  for (const pt of drState.trail) {
    if (pt.x < minX) minX = pt.x;
    if (pt.x > maxX) maxX = pt.x;
    if (pt.y < minY) minY = pt.y;
    if (pt.y > maxY) maxY = pt.y;
  }

  // Minimum 2m view in each axis, add margin
  const margin = 0.5;
  const rangeX = Math.max(maxX - minX + margin * 2, 2);
  const rangeY = Math.max(maxY - minY + margin * 2, 2);
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;

  // Uniform scale (fit both axes, leave padding)
  const pad = 20;
  const scaleX = (w - pad * 2) / rangeX;
  const scaleY = (h - pad * 2) / rangeY;
  const scale = Math.min(scaleX, scaleY);

  // Map world coords to canvas coords
  function toCanvas(wx, wy) {
    return {
      cx: w / 2 + (wx - centerX) * scale,
      cy: h / 2 - (wy - centerY) * scale  // flip Y so +Y is up
    };
  }

  // Draw grid
  ctx.strokeStyle = 'rgba(0, 255, 255, 0.1)';
  ctx.lineWidth = 1;
  const gridStep = gridInterval(rangeX, rangeY);
  const gridMinX = Math.floor((centerX - rangeX / 2) / gridStep) * gridStep;
  const gridMaxX = Math.ceil((centerX + rangeX / 2) / gridStep) * gridStep;
  const gridMinY = Math.floor((centerY - rangeY / 2) / gridStep) * gridStep;
  const gridMaxY = Math.ceil((centerY + rangeY / 2) / gridStep) * gridStep;

  for (let gx = gridMinX; gx <= gridMaxX; gx += gridStep) {
    const p = toCanvas(gx, 0);
    ctx.beginPath();
    ctx.moveTo(p.cx, 0);
    ctx.lineTo(p.cx, h);
    ctx.stroke();
  }
  for (let gy = gridMinY; gy <= gridMaxY; gy += gridStep) {
    const p = toCanvas(0, gy);
    ctx.beginPath();
    ctx.moveTo(0, p.cy);
    ctx.lineTo(w, p.cy);
    ctx.stroke();
  }

  // Draw trail as cyan polyline
  if (drState.trail.length > 1) {
    ctx.strokeStyle = '#0ff';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    const p0 = toCanvas(drState.trail[0].x, drState.trail[0].y);
    ctx.moveTo(p0.cx, p0.cy);
    for (let i = 1; i < drState.trail.length; i++) {
      const p = toCanvas(drState.trail[i].x, drState.trail[i].y);
      ctx.lineTo(p.cx, p.cy);
    }
    ctx.stroke();
  }

  // Draw ferrous anomaly pins (red/orange diamonds)
  for (const pin of ferrousPins) {
    const p = toCanvas(pin.x, pin.y);
    const s = Math.min(7, 4 + pin.strength / 5);
    ctx.save();
    ctx.translate(p.cx, p.cy);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = pin.strength > 10 ? '#f44' : '#fa0';
    ctx.fillRect(-s / 2, -s / 2, s, s);
    ctx.restore();
  }

  // Draw current position dot
  const cur = toCanvas(drState.x, drState.y);
  ctx.fillStyle = '#0f0';
  ctx.beginPath();
  ctx.arc(cur.cx, cur.cy, 4, 0, Math.PI * 2);
  ctx.fill();

  // Draw heading arrow
  const yaw = (sensor.yaw || 0) * Math.PI / 180;
  const arrowLen = 12;
  const ax = cur.cx + Math.sin(yaw) * arrowLen;
  const ay = cur.cy - Math.cos(yaw) * arrowLen;
  ctx.strokeStyle = '#fa0';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cur.cx, cur.cy);
  ctx.lineTo(ax, ay);
  ctx.stroke();
  // Arrowhead
  const headLen = 4;
  const headAngle = Math.atan2(ay - cur.cy, ax - cur.cx);
  ctx.beginPath();
  ctx.moveTo(ax, ay);
  ctx.lineTo(ax - headLen * Math.cos(headAngle - 0.5), ay - headLen * Math.sin(headAngle - 0.5));
  ctx.moveTo(ax, ay);
  ctx.lineTo(ax - headLen * Math.cos(headAngle + 0.5), ay - headLen * Math.sin(headAngle + 0.5));
  ctx.stroke();

  // Scale bar (bottom-left)
  const scaleBarWorld = gridStep;
  const scaleBarPx = scaleBarWorld * scale;
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(8, h - 10);
  ctx.lineTo(8 + scaleBarPx, h - 10);
  ctx.stroke();
  // End ticks
  ctx.beginPath();
  ctx.moveTo(8, h - 14);
  ctx.lineTo(8, h - 6);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(8 + scaleBarPx, h - 14);
  ctx.lineTo(8 + scaleBarPx, h - 6);
  ctx.stroke();
  ctx.fillStyle = '#fff';
  ctx.font = '9px Arial';
  ctx.textAlign = 'left';
  ctx.fillText(`${scaleBarWorld.toFixed(scaleBarWorld >= 1 ? 0 : 1)}m`, 8, h - 16);

  // Coordinate display (bottom-right)
  ctx.fillStyle = '#8cf';
  ctx.font = '9px Courier New';
  ctx.textAlign = 'right';
  ctx.fillText(`x:${drState.x.toFixed(1)}m y:${drState.y.toFixed(1)}m`, w - 6, h - 6);
}

function gridInterval(rangeX, rangeY) {
  const maxRange = Math.max(rangeX, rangeY);
  if (maxRange <= 2) return 0.5;
  if (maxRange <= 5) return 1;
  if (maxRange <= 20) return 2;
  if (maxRange <= 50) return 5;
  return 10;
}

function resetDR() {
  drState.x = 0;
  drState.y = 0;
  drState.vx = 0;
  drState.vy = 0;
  drState.trail = [];
  drState.lastTime = null;
  // Also reset server-side DR
  fetch('/dr/reset', { method: 'POST' }).catch(() => {});
}

// === CAMERA FOCUS CONTROL ===
function setFocusMode(mode) {
  const payload = { mode };
  if (mode === 0) {
    payload.lens_position = parseFloat(document.getElementById('lensPosition').value);
  }
  fetch('/camera/focus', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        updateFocusUI(mode);
      } else {
        console.error("Focus error:", d.error);
      }
    })
    .catch(console.error);
}

function updateLensPosition(value) {
  const display = document.getElementById('lensPositionValue');
  display.textContent = parseFloat(value).toFixed(1);
  fetch('/camera/focus', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 0, lens_position: parseFloat(value) })
  }).catch(console.error);
}

function updateFocusUI(mode) {
  // Update active button
  document.getElementById('focusBtnAuto').classList.toggle('active', mode === 2);
  document.getElementById('focusBtnManual').classList.toggle('active', mode === 0);
  document.getElementById('focusBtnOnce').classList.toggle('active', mode === 1);
  // Show/hide lens position slider
  document.getElementById('lensPositionRow').style.display = (mode === 0) ? 'flex' : 'none';
}

// Wire up lens position slider
document.addEventListener('DOMContentLoaded', function() {
  const slider = document.getElementById('lensPosition');
  if (slider) {
    slider.addEventListener('input', function() {
      updateLensPosition(this.value);
    });
  }
});

// === INFO MODAL ===
function showInfo() {
  document.getElementById('infoModal').style.display = 'flex';
}

function closeInfo() {
  document.getElementById('infoModal').style.display = 'none';
}

function closeInfoOnOverlay(event) {
  if (event.target === document.getElementById('infoModal')) {
    closeInfo();
  }
}
