# Preserve publisher timestamps for opaque MAVLink packets

Goal: Record Bullet App's original MAVLink wire packets without parsing them, using App publication time for MCAP `publish_time` and bagger receive time for MCAP `log_time`.

The App will send a ZMQ multipart message with three frames: `[topic, header, payload]`. `topic` is the configured exact UTF-8 topic; `header` is `struct.pack('<Q', time.time_ns())`, an eight-byte little-endian UTC Unix nanosecond timestamp written immediately before publication; `payload` is the original MAVLink packet and must be stored unchanged.

Implementation steps:
1. Accept both legacy `[topic, payload]` and new `[topic, header, payload]` messages on ordinary, non-SHM channels. Reject any other frame count or a header whose length is not eight bytes. Decode only the timestamp header, not the payload.
2. Carry separate receive and publish timestamps through the bounded queue. Set MCAP `log_time` to the bagger's local `time.time_ns()` at reception and `publish_time` to the header value. For legacy messages, use receive time for both. Preserve existing topic matching, payload bytes, ordering, and shutdown behavior.
3. Update the sample configuration for `telemetry/heartbeat`, `telemetry/attitude`, `telemetry/vfr_hud`, and `telemetry/timesync` at `tcp://127.0.0.1:5557`; document App's opt-in publisher command and the wire format. The bagger remains independent of MAVLink and Bullet App packages.

Verification: Real ZMQ-to-MCAP round trip with a binary packet whose bytes are unchanged; assert distinct exact `publish_time` and receive-based `log_time`. Cover legacy two-frame input, invalid frame counts and header lengths, and the complete bagger test suite.

Scope/defaults: SHM image handling is unchanged. Publisher and bagger use UTC Unix nanoseconds. No implementation has been performed by saving this plan.

Status: Superseded by `blackboard-publish-timestamps.md`, which records decoded blackboard MsgPack with the same timestamp envelope. Implementation commit: Pending.
