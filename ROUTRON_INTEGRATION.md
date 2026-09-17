# Pi_Ray Autonomy + Routron Integration Plan

**Status:** planning — nothing in this document is implemented yet.
**Last updated:** 2026-09-17
**Companion doc:** Routron's `PROJECT_STATUS.txt` carries a matching dated
entry noting this plan exists; Routron's own code is not expected to
change because of this work (see "Explicit non-changes" below).

This is a living document — update it in place as work happens. Move an
item from "planned" to "done" with a short dated note rather than deleting
it, the same convention Routron's own `PROJECT_STATUS.txt` uses.

---

## 1. Why this exists

Two things came out of a planning discussion before any code was written:

1. Pi_Ray is the testbed for Routron's edge-AI resilience story (chaos
   testing, a deterministic policy gate, a tamper-evident ledger, replay).
   Routron already ships a real deployment config for this vehicle
   (`config.pi_ray.yaml` in the Routron repo) and a runbook section
   (`HOW_TO_RUN.txt` PART 10) describing an LLM advisor button in
   `rov_clean` — but that advisor code does not exist in this repo yet.
2. A manually-triggered "ask a question" button produces, at best, a
   handful of LLM queries per session. Routron's strongest sales evidence
   — proving the policy gate holds and the ledger stays intact through a
   simulated comms dropout — needs a *continuous* stream of queries across
   a whole run, not a few clicks. The way to get that stream, and to make
   it a genuinely autonomous vehicle rather than a chatbot bolted onto a
   manually-driven ROV, is to give the ROV a bounded mission it runs on
   its own.

This document is the plan for that: what becomes autonomous, what
deliberately does not, how it talks to Routron, and what has to be true on
the hardware before it's safe to run unattended.

---

## 2. Current baseline (as of 2026-09-17)

What already exists in `rov_clean`:

- Manual control path: `winconpi5.py` (Windows joystick client) → Flask
  routes in `routes.py` → `motors.py`, at 20Hz.
- Deterministic hold controllers already implemented: `depth_hold.py`,
  `heading_hold.py`, `position_hold.py`, backed by `dead_reckoning.py` and
  the sensor fusion in `sensors.py` (Madgwick-filtered roll/pitch/yaw,
  depth, water temp, a magnetometer anomaly baseline, `leak_detected`).
- Telemetry logging (`telemetry_logger.py`) to CSV, already running
  independently of any LLM code.

What does not exist yet:

- `llm_advisor.py` — referenced in Routron's `HOW_TO_RUN.txt` PART 10 and
  in `config.pi_ray.yaml`'s comments, but not present in this repo. This
  plan treats building it as one of the concrete work items below, not as
  something already done.
- Any mission/autonomy layer above the existing hold controllers.
- Any obstacle-avoidance sensor (sonar/DVL). Position awareness is IMU
  dead reckoning only, which drifts over time.

Known hardware constraints from `components.txt`, relevant to running
anything unattended:

- The vertical (ascend/descend) thruster is driven by two single-direction
  MOSFET boards, one wired reversed, relying on the inactive board's
  diodes to block the reverse current path — not a true H-bridge. Flagged
  in `components.txt` as a known issue needing a hardware fix.
- Brownout risk under motor inrush is currently mitigated only in
  software (a 0.05 duty/update ramp rate); the hardware mitigations listed
  in `components.txt` (separate Pi BEC, capacitors, heavier wire gauge)
  are still TBD.

---

## 3. Architectural principle: two loops, never merged

- **Control loop (existing, deterministic, unchanged by this plan).**
  `depth_hold.py` / `heading_hold.py` / `position_hold.py` / `motors.py`.
  Reads sensors, computes PID output, writes thruster PWM, at 20Hz. No
  LLM, no Routron, no network dependency, ever.
- **Mission / advisory loop (new).** Decides *what* the vehicle should be
  doing — picks setpoints, sequences them into a mission, narrates
  telemetry, and asks Routron for judgment calls on anomalies. This is the
  only layer that talks to an LLM or to Routron.

**Non-goal, stated explicitly:** LLM output never becomes a thruster
command directly, and Routron never sits in the actuation path. This
matches Routron's own scope rule (advisory path only, never safety-
critical actuation, no ML-derived signal as a policy predicate — see
Routron's `HOW_TO_RUN.txt`, "Scope, Safety, and Terminology"). It is also
the stronger sales position: the pitch is an autonomy stack where an AI
fault can be detected and isolated without being coupled into actuation,
which is the literal ask in the AFWERX runtime-assured-autonomy topic
`GO_TO_MARKET.md` already cites. A demo where an LLM's output drives a
thruster would undercut that claim on our own showcase vehicle.

---

## 4. What actually becomes autonomous

**Mission sequencer** — a new layer that:

- Holds an ordered list of "legs": target depth, target heading, hold
  duration, optional camera action.
- Hands each leg's setpoint to the existing hold controllers, which
  already know how to reach and hold it deterministically.
- Advances through legs into a bounded pattern (a grid/lawnmower search
  at a held depth, or a loiter/station-keep pattern), using
  `dead_reckoning.py` for enough position awareness to make it a real
  pattern rather than a blind timer.

**Explicitly bounded scope** — no GPS waypoint navigation (no GPS
underwater) and no obstacle-avoiding navigation (no sonar/DVL on the parts
list). The mission is time/heading/depth-limited and pre-authorized, run
in a known-clear test area. This is a deliberate, honest scope choice, not
a placeholder for something bigger — see "Open questions" for what would
change that.

**Two categories of Routron-routed query per leg**, matching the ladders
already defined in `config.pi_ray.yaml`:

1. **Leg-transition narration** — low priority → local rung first
   (`low_priority_ladder: [0, 1]`). Continuous, cheap, works fully
   offline. This is the query stream's backbone.
2. **Anomaly-triggered correlation** — high priority → cloud rung first
   (`high_priority_ladder: [1, 0]`), falling back to local automatically.
   Triggered off signals `sensors.py` already computes: `leak_detected`,
   a `mag_anomaly` spike relative to `mag_baseline`, or a fast roll/pitch
   change. No new sensor code needed — just thresholds in the mission
   layer.

---

## 5. Human/policy gating for consequential decisions

Any LLM recommendation that would change mission behavior (abort the leg,
ascend early, hold position) is never executed directly. It goes through
Routron's existing `require_approval` policy action:

- **Comms available:** held for operator approval via the dashboard /
  `POST /approvals/{token}`, same as any other Routron deployment.
- **Comms degraded, no operator reachable:** a declared, deterministic
  default fires instead — e.g. hold current position, or begin a scripted
  ascent — recorded in the ledger as a policy decision, not a hang or an
  unbounded timeout.

This is what turns "reversionary protocol" from a phrase in
`GO_TO_MARKET.md`'s AFWERX summary into something an evaluator can watch
happen on real hardware.

---

## 6. Hardware prerequisites (before an unattended autonomous run)

- [ ] Raspberry Pi 3 → Pi 5 upgrade (needed to run local inference at all
      with useful headroom).
- [ ] Fix the vertical thruster ascend/descend driver — replace the dual
      single-direction MOSFET boards with a proper H-bridge (L298N,
      DRV8833, TB6612) or add the isolation diodes `components.txt`
      suggests. A depth-hold mission cycles this thruster far more than
      manual driving has to date; this is the actuator most likely to be
      stressed by autonomy.
- [ ] Harden brownout mitigation in hardware (separate 5V/3A BEC for the
      Pi, capacitors across each motor driver board, ≥16 AWG motor supply
      wiring) — sustained autonomous thruster cycling is a harder test of
      this than intermittent manual joystick input has been.
- [ ] Confirm `position_hold.py` / `heading_hold.py` accept an externally
      supplied target setpoint the same way `depth_hold.py` is designed
      to. Assumed true by naming/pattern, **not yet verified by reading
      the code** — do this before designing the sequencer's API.
- [ ] Pick and bound a safe test area/pattern (known-clear pool or
      confined water) given there is no obstacle-avoidance sensor.

## 7. Software work (Pi_Ray side)

- [ ] Build `llm_advisor.py` — the file Routron's docs already reference
      but that doesn't exist here yet. Formats current `sensor_data` into
      the telemetry system-prompt format `config.pi_ray.yaml` expects,
      sends it to Routron's `/v1/chat/completions` with the right
      priority/complexity so it lands on the intended ladder.
- [ ] Build the mission sequencer (new module, e.g. `mission.py`) — a
      state machine over a list of legs, driving `depth_hold` /
      `heading_hold` / `position_hold` setpoints, calling `llm_advisor` at
      leg transitions and anomaly triggers.
- [ ] Wire anomaly triggers off the existing `sensor_data` fields
      (`leak_detected`, `mag_anomaly` vs. `mag_baseline`, roll/pitch
      delta) — thresholds live in the mission layer, no new sensor code.
- [ ] Wire consequential recommendations through Routron's
      `require_approval` flow; implement the declared safe-default
      behavior for the no-approval-reachable case.
- [ ] Extend `telemetry_logger.py` / `dive_logs` to record mission-leg
      transitions alongside the existing telemetry CSV, so a post-dive
      report can line the mission timeline up against Routron's ledger.
- [ ] Add mission start/stop/status routes to `routes.py`, mirroring the
      existing pattern used by depth hold's routes.

---

## 8. Demo / validation plan

1. Run a scripted multi-leg mission fully connected — confirm the
   sequencer, hold controllers, and local/cloud narration all work
   end to end.
2. Repeat with `routron chaos --drop-link` (or physically leaving Wi-Fi
   range) triggered mid-mission — confirm the high-priority ladder fails
   over to local, or a policy fires `safe_response` / the
   `require_approval` no-response default, instead of hanging.
3. Surface and run `routron ledger verify` and `routron replay <seq>`
   against the dropout decision(s) — this is the artifact for the sales
   pitch and the SBIR evidence packet `GO_TO_MARKET.md` describes.
4. Keep the recording (video + ledger export + `dive_logs`) as a reusable
   demo asset.

---

## 9. Open questions

- Exact interface of `position_hold.py` / `heading_hold.py` — confirm
  before finalizing the mission sequencer's API.
- What counts as "anomalous enough" to escalate to cloud and/or require
  approval — needs real-world tuning on actual sensor noise, not
  guessable up front.
- Local model choice on Pi 5 — stick with `smollm:135m` or move to
  something slightly larger now that Pi 5 has more headroom than the Pi 3
  Routron's `PROJECT_STATUS.txt` hardware findings were measured on?
  Revisit once the Pi 5 is in hand.
- Where the mission sequencer lives — inside `rov_clean`'s Flask process
  (matching the existing hold-controller pattern) or as a separate
  process. Current lean is inside `rov_clean`; revisit if it gets
  unwieldy.
- Whether a real obstacle-avoidance sensor (e.g. a Blue Robotics Ping
  sonar) ever gets added — out of scope for this plan, but the thing that
  would eventually let "bounded scripted pattern" grow into something
  closer to real navigation.

---

## 10. Explicit non-changes

No changes are planned to Routron's core code (`router_engine.py`,
`routron/policy.py`, `routron/chaos/`, the ledger schema). Everything in
this plan is designed against Routron's current, shipped surface —
priority ladders, the `require_approval` policy action, `routron chaos`,
`routron ledger verify`/`replay` — all already present in
`config.pi_ray.yaml` and the Routron codebase. If implementation surfaces
a real gap (for example, an approval-timeout default the policy grammar
can't express yet), it gets recorded here, and a matching dated entry goes
into Routron's `PROJECT_STATUS.txt` — not a silent workaround.

---

## Changelog

- **2026-09-17** — Initial plan drafted from a design discussion. Nothing
  implemented yet.
