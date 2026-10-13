# HuntMob clean-room Android runtime v0.1 — 2026-10-13

## Decision

HuntMob owns the Android runtime. Genymotion is a behavioral reference only and
is not installed, invoked or redistributed by a HuntMob worker.

## Clean-room boundary

REA may record externally observable states, inputs, outputs and public file
formats from an authorized local reference installation. Implementation work
uses AOSP, QEMU and documented Android interfaces. Proprietary binaries, disk
images, protocols, assets and decompiled source are excluded.

## Runtime stack

```text
HuntMob Control Plane
        |
  typed Worker RPC
        |
HuntMob Android Worker
  |-- QEMU + HVF/KVM/WHPX
  |-- HuntMob AOSP system image
  |-- ADB bridge
  |-- WebRTC display/input gateway
  |-- virtual biometric HAL
  |-- virtual camera HAL
  |-- GPS/sensor/baseband fixtures
  `-- evidence and snapshot service
```

## Biometric contract

The owned biometric HAL must expose fingerprint enrollment plus deterministic
`recognized`, `unrecognized`, `dirty`, `partial`, `insufficient` and `too-fast`
events. Every injection is scoped to a device and engagement, requires an
approved action, and emits an immutable receipt. Face recognition remains a
separate camera-driven fixture and is never reported as Android fingerprint
authentication.

## Current evidence

- ADB is installed independently on the current Mac.
- No independent QEMU executable or HuntMob AOSP image is installed.
- Therefore the owned runtime is `build-required`; no Genymotion fallback is
  allowed.

## Next implementation slice

1. Pin and build the AOSP image plus biometric/camera HAL modules.
2. Package QEMU per worker OS and verify HVF, KVM and WHPX separately.
3. Implement typed power/display/fixture RPCs and receipts.
4. Add disposable-device integration tests for enrollment and all six outcomes.

## Container execution

The lifecycle observed in the reference product maps cleanly to an immutable
base image plus a writable per-instance overlay: select a hardware recipe,
resolve the Android base image, create the data disk, allocate ports, boot,
wait for ADB and publish display/fixture services.

On bare-metal Linux, HuntMob packages that worker in Docker and passes
`/dev/kvm` into the container. Docker provides isolation and distribution while
KVM performs hardware virtualization. On macOS and Windows the worker remains
native to preserve HVF/WHPX acceleration; only the control plane may run in
Docker. Docker Desktop is not treated as a portable KVM layer.

The Compose manifest is intentionally not runnable until CI publishes a signed
HuntMob worker image and the AOSP pipeline produces a verified base image. This
prevents an implicit fallback to a third-party emulator image.
