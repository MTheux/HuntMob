# HuntMob runtime capability contract v1.0 — 2026-10-13

## Objective

Give the HuntMob UI one stable contract regardless of whether the device is
provided by Genymotion, an Apple Simulator worker, Corellium, a real-device
cloud or a future HuntMob runtime.

## Contract

| Capability | UI responsibility | Worker responsibility |
|---|---|---|
| Power | start, stop, reboot request | enforce state transition and timeout |
| Display | render and send typed input | produce time-bounded video/input session |
| Apps | upload/install/launch request | validate hash, package and engagement |
| Files | scoped browser | enforce path roots and redact secrets |
| Console | terminal component | allowlisted commands; no raw browser shell |
| Frida | script editor and results | authorized target process and audited session |
| Network capture | timeline and export | capture PCAP and hash immutable evidence |
| Sensors | controlled fixtures | validate camera/location/biometric fixture |
| Snapshots | create/restore request | isolate by engagement and record provenance |
| Port forwarding | declared service mapping | bind only approved interfaces and ports |
| REA static | artifact selection | hash and inspect APK/IPA/native libraries |
| REA dynamic evidence | evidence timeline | ingest logs, PCAP, traces and screenshots |

## Provider independence

The browser never calls a provider directly. A server-side adapter translates
the HuntMob contract to `gmtool`, `simctl`, a provider REST API or a worker RPC.
Provider tokens, SSH keys and VPN material never reach browser storage.

Corellium is an optional adapter and a public behavioral reference, not copied
source code. REA is used on owned or explicitly authorized artifacts and on the
evidence produced by HuntMob workers.

## iOS boundary

HuntMob can be controlled from Windows or Linux, but iOS execution is scheduled
to a Mac worker, licensed virtual-device provider or approved physical-device
farm. The project does not ship Apple firmware or attempt unlicensed macOS/iOS
virtualization on generic PC hardware.
