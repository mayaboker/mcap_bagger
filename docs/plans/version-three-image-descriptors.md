# Version 3 image descriptors

## Goal

Accept the renderer's version 3 shared-memory image notifications so recording does not stop with `invalid image descriptor fields`.

## Implementation

- Extend descriptor validation to allow the pose header, drone ID, and optional host capture timestamp used by version 3.
- Keep strict version-specific field checks and existing SHM identity, layout, and sequence validation.
- Add end-to-end image receiver and malformed descriptor regression tests.

## Interfaces

The MCAP bagger accepts version 3 image notifications on its existing image topic and endpoint. Recording configuration and MCAP payload format are unchanged.

## Verification

The focused pipeline and registration tests passed (36 tests). A temporary CLI
recording against the live renderer captured 28 version 3 images and finalized
an MCAP file. The full suite had two unrelated failures: the demo test tried to
bind live renderer port 5556, and the writer-failure test observed a concurrent
`queue input is closed` error instead of its injected disk error.

## Scope and status

Status: Complete. The bagger remains standalone and does not import the renderer
or simulation protocol packages.
