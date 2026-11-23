# Record MSP RC commands

Register `control/msp_rc` on the existing App telemetry endpoint as an ordinary schema-free channel. Store the version-1 MsgPack envelope unchanged with the supplied send-time header as MCAP publish time and Bagger receive time as MCAP log time. Verify configuration registration and readback; no Bagger parser or transport change is needed.

Status: Implemented; 86 Bagger tests passed.
