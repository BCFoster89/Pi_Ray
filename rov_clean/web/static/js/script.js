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

// === EMERGENCY STOP ===
function emergencyStop() {
  fetch('/motor/all_stop')
    .then(r => r.json())
    .then(d => {
      console.log("Emergency stop:", d);
      // Flash screen to confirm
      document.body.style.boxShadow = 'inset 0 0 100px rgba(255, 0, 0, 0.5)';
      setTimeout(() => {
        document.body.style.boxShadow = 'none';
      }, 300);
    })
    .catch(console.error);
}

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

// === STATUS HEARTBEAT ===
async function heartbeatLoop(){
  let btn = document.getElementById("statusBtn");
  try {
    let r = await fetch('/heartbeat', { cache: "no-store" });
    if (r.ok){
      btn.textContent = "Pi Status: OK";
      btn.classList.remove("lost");
      btn.classList.add("ok");
    } else throw new Error("bad response");
  } catch {
    btn.textContent = "Pi Status: LOST";
    btn.classList.remove("ok");
    btn.classList.add("lost");
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

    // update telemetry card
   // Replace your existing telemetry section with this:
const telemetryEl = document.getElementById("telemetry");

// Updated displayOrder to match sensors.py keys
const displayOrder = [
  { key: 'depth_ft', label: 'Depth', unit: 'ft' },
  { key: 'pitch', label: 'Pitch', unit: '°' },
  { key: 'roll', label: 'Roll', unit: '°' },
  { key: 'yaw', label: 'Heading', unit: '°' }, // Using 'yaw' for heading
  { key: 'temperature_f', label: 'Water', unit: '°F' }, // Matches python 'temperature_f'
  { key: 'imu_temp_f', label: 'Internal', unit: '°F' }  // Matches python 'imu_temp_f'
];

telemetryEl.textContent = displayOrder
  .map(item => {
    const val = sensor[item.key];
    // Format the number to 1 decimal place if it exists
    const displayVal = (typeof val === 'number') ? val.toFixed(1) : (val || '0.0');
    return `${item.label.padEnd(8)}: ${displayVal} ${item.unit}`;
  })
  .join('\n');

    //below repalced with above
    //document.getElementById("telemetry").textContent =
      //JSON.stringify(sensor, null, 2);

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
  let cy = canvas.height/2;

  // Horizon with roll & pitch
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((-sensor.roll || 0) * Math.PI/180);
  let pitchOffset = (sensor.pitch || 0) * 5; // scale
  ctx.strokeStyle = "#ff0";
  ctx.beginPath();
  ctx.moveTo(-300, pitchOffset);
  ctx.lineTo(300, pitchOffset);
  ctx.stroke();

  // Pitch ladder
  ctx.font = "14px Segoe UI";
  ctx.fillStyle = "#ff0";
  for(let p=-20;p<=20;p+=5){
    let offset = (p - (sensor.pitch||0)) * 5;
    ctx.beginPath();
    ctx.moveTo(-40, offset);
    ctx.lineTo(40, offset);
    ctx.stroke();
    ctx.fillText(p+"°", 50, offset+5);
  }
  ctx.restore();

// Heading tape top-center
  let heading = sensor.yaw || 0;
  ctx.fillStyle = "#ff0";
  ctx.font = "bold 16px Arial";
  ctx.textAlign = "center";
  
  // 1. Draw the actual digital readout in the center
  ctx.fillText(`${Math.round((heading + 360) % 360)}°`, cx, 25);

  // 2. Setup the tape
  let spacing = 5; // pixels per degree
  let snapHeading = Math.floor(heading / 10) * 10; // The nearest 10° mark
  
  ctx.beginPath();
  // We draw 9 marks to the left and 9 to the right of our "snapped" heading
  for (let i = -90; i <= 90; i += 10) {
    let mark = snapHeading + i;
    
    // Calculate position: (The mark position) - (exact heading)
    // This creates the smooth sliding effect
    let x = cx + (mark - heading) * spacing;
    
    // Wrap the number for display (0-359)
    let displayMark = (mark + 360) % 360;

    // Draw the tick mark
    ctx.moveTo(x, 45);
    ctx.lineTo(x, 55);
    ctx.stroke();

    // 3. Draw the Label (Cardinal or Number)
    const getCardinal = (d) => {
      const directions = {0:"N", 45:"NE", 90:"E", 135:"SE", 180:"S", 225:"SW", 270:"W", 315:"NW"};
      return directions[d] !== undefined ? directions[d] : d;
    };

    let label = getCardinal(displayMark);
    ctx.font = (typeof label === "string") ? "bold 16px Arial" : "12px Arial";
    ctx.fillText(label, x, 70);
  }

  // 4. Draw a "Lubber Line" (the center pointer)
  ctx.strokeStyle = "#f00"; // Red pointer
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx, 40);
  ctx.lineTo(cx, 60);
  ctx.stroke();
  ctx.lineWidth = 1; // Reset for other drawings
  ctx.strokeStyle = "#ff0"; // Reset to yellow

  // Depth bottom-right
  ctx.fillStyle = "#ff0";
  ctx.font = "bold 20px Arial"; // This sets the size to 30 pixels and makes it bold
  ctx.textAlign = "left";
  ctx.fillText(`Depth: ${(sensor.depth_ft||0).toFixed(1)} ft`, 20, 40);
  
  // Roll & Pitch bottom-left
  ctx.fillStyle = "#ff0";
  ctx.font = "bold 16px Arial"; // This sets the size to 30 pixels and makes it bold
  ctx.textAlign = "left";
  ctx.fillText(`Pitch: ${(sensor.pitch||0).toFixed(1)}°`, 20, canvas.height-40);
  ctx.fillText(`Roll: ${(sensor.roll||0).toFixed(1)}°`, 20, canvas.height-20);
}
