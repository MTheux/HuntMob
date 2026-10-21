# Expo Device Hub infrastructure review v1.0 — 2026-10-21

## Outcome

Expo Device Hub is a useful architectural reference for HuntMob's device plane.
The strongest reusable ideas are its provider-neutral client contract, explicit
capability advertisement, independent lifecycle/stream/input state, bounded
streaming sessions and stale-session protection. HuntMob adapts these ideas to
its authorization and evidence model; no Expo source code was copied.

Reference reviewed: `expo/expo-device-hub` at commit
`2dbd92873b6ce44722cb0d283c70bd2684172c63` (MIT root license).

## Implemented in this slice

1. `huntmob.device-inventory/v1` and `huntmob.device-session/v1` normalize
   Android and iOS identity, lifecycle, channels and capabilities.
2. Stream, input and settings state are independent. Device boot no longer
   implies that video or input is ready.
3. Each relay publishes a generation. Browser input carries that generation;
   delayed input from a stopped/restarted session fails closed.
4. Discovery is isolated per device. One unavailable worker produces a
   sanitized `device_discovery_failed` diagnostic without hiding healthy
   devices or leaking the underlying exception.
5. Capabilities are explicit and platform-specific. iOS Simulator does not
   advertise Android root or Frida capability.

## Next high-value adaptations

| Priority | Expo pattern | HuntMob application | Gate |
|---|---|---|---|
| P1 | Atomic screenshot publication plus failure receipt | Write evidence to a temporary path, hash it, rename atomically and persist a sanitized failure receipt | EvidenceStore review |
| P1 | Stream telemetry and stall watchdog | Track first-frame latency, last-frame age, reconnect count and decoder failures per device | Metrics contract |
| P1 | Session-scoped cleanup | Central session owner closes video, input, proxy and analysis handles together | Lifecycle integration tests |
| P2 | Typed capability modules | Load device controls only when their capability is declared and healthy | UI capability routing |
| P2 | Bounded recording/upload queues | Apply byte, duration and concurrency budgets to evidence capture | Storage policy |
| P3 | WebRTC transport | Evaluate only after the current H.264/MJPEG paths have telemetry; WebRTC adds signaling and TURN operational cost | Architecture decision record |

## Security review by the six engines

- Business Logic — Confirmed: lifecycle and input remain fixed verbs; the new
  contract does not expose arbitrary provider commands.
- IDOR/Authorization — Confirmed: workspace/device ownership remains checked on
  every action; generation is an additional freshness gate, not authorization.
- Authentication/Session — Confirmed: stale input is rejected after relay
  restart. Generation is not a secret and must not replace gateway auth.
- Data Exposure — Confirmed: discovery errors are returned as stable codes;
  worker exception text is not exposed.
- Injection/Input Validation — Confirmed: no shell or provider expression was
  added. Existing typed input validation remains the sink boundary.
- Configuration/Infrastructure — Confirmed locally: device discovery now
  degrades per device and advertises honest channel state. Physical devices and
  remote workers were not exercised in this validation.

## Limitations

This review validated source and local automated tests. It does not establish
Docker/KVM boot, Windows device execution, physical iOS behavior, WebRTC
viability or deployed runtime behavior.
