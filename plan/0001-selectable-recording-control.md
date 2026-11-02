# Selectable recording control

## Goal
Add an explicit recorder-only ZMQ mode for application/MAVLink-controlled MCAP
recording, preserving the existing Godot/physics default and interactive CLI.

## Implementation and interfaces
--control-mode recording selects recording/state input and recording/status
confirmation. Default --control-mode simulation retains ControlledRecorder.
Readiness marks installed subscriptions; files open only on running state.
Fresh identities/sequences, closed-session protection, duplicate idempotency,
3-second silence closure and finalize-before-idle status are enforced. Errors
propagate to process failure and cannot be acknowledged as successful closure.
The launcher stops the recorder last. No raw physical-camera image publisher,
commits, pushes or application/flight lifecycle changes are included.

## Status
Implemented; 92 recorder tests and fresh installed roundtrip passed. Not committed.

## Implementation commit
Pending

## Verification results
- 20 bringup tests passed: configuration/dry-run, process startup/failure/signals,
  readiness timeout, partial startup and log-thread failure cleanup, real local
  MAVLink/ZMQ/MCAP roundtrip, Godot isolation and pending-command shutdown ACK.
- 173 application tests, 92 recorder tests, 182 shared-message tests and 8
  workspace tests passed (475 total). Existing simulation recording, reload and
  parameter handling remain covered by their regression suites.
- Tested new recording error paths: bad/stale/reordered messages, confirmation
  timeout, disk-open failure, writer failure, silence timeout, duplicate commands,
  closed-session protection and a fresh Start after recorder closure.
- Built /tmp/bullet-bringup-bundle-final with eight local runtime wheels plus
  locked third-party wheels (113 MB, Linux x86_64 / Python 3.12 build host).
  Installed offline into /tmp/bullet-bringup-installed and ran from /tmp with
  PYTHONPATH and display variables unset. Installed MAVLink start/stop/readback
  and pending-command shutdown passed. All eight local packages resolve from
  that venv; no simulator, Qt viewer or pytest packages are installed there.
- MAVLink/Godot dry-runs validated without creating logs or recordings. Existing
  dependency versions are preserved; uv lock --check and changed-file whitespace
  checks passed. No real camera capture or flight actuation was performed.
- Applied exception-risk-review to thread/socket/process cleanup. Fixed partial
  log-thread startup cleanup, worker-error finalization reporting, pending ACKs
  on app shutdown and restarting a previously closed recording session.
- New bringup repository is initialized on main; no commits, remotes, pushes or
  systemd services were added. Process logs/build wheels are outside source or
  ignored. Test-owned child processes were terminated.

Verification logs: /tmp/bringup-*-final.log; installed check:
/tmp/bringup-installed-final.log. Local sources and wheel payloads were compared.
