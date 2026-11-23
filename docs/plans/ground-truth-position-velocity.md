# Record physics ground truth

Subscribed to `analysis/physics/ground_truth` on TCP port 5555 in the sample
configuration. The existing three-frame receiver preserves JSON payloads as
opaque bytes and uses the Unix-nanosecond header for MCAP publish time. The
pipeline timestamp round-trip test and full pipeline suite pass (18 tests).
