# Blackboard publisher timestamps

Goal: Record Bullet App blackboard MsgPack payloads unchanged while preserving a publisher-provided Unix nanosecond MCAP publish timestamp.

Implementation: Accept three-frame `[topic, eight-byte little-endian unsigned timestamp, payload]` on ordinary channels alongside legacy two-frame input. Keep bagger receive time as MCAP log time, use the header as publish time, and never decode the payload. Reject malformed framing and headers under the existing receiver failure policy. Update the example channels and documentation.

Verification: The bagger suite passed (78 tests), covering exact payload and timestamp round trip, legacy input, and malformed frames. The wheel built. A live two-process App-to-bagger smoke run recorded ten messages with distinct MCAP publish/log times.

Scope: SHM image handling stays unchanged. This supersedes the raw-MAVLink-packet assumptions in `mavlink-publish-timestamps.md`.

Status: Implemented and verified. Implementation commit: Pending (repository has no Git history).
