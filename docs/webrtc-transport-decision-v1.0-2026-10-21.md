# WebRTC transport decision v1.0 — 2026-10-21

## Decision

Status: **instrument first; WebRTC not enabled**.

HuntMob keeps H.264/WebCodecs for Android and bounded MJPEG for iOS while it
collects comparable telemetry. WebRTC is a candidate transport, not a declared
capability. This avoids adding signaling, ICE/TURN, NAT traversal and another
authentication surface before a measured problem justifies them.

## Baseline now available

Every device session publishes the following under
`channels.stream.telemetry`:

- connection attempts and reconnect count;
- stall count;
- first-frame latency in milliseconds;
- age of the last frame;
- H.264 GOP queue bytes and its hard limit.

The producers fail closed after eight seconds without frames. A stream session
is capped at 30 minutes and the server admits at most four concurrent stream
producers. Reconnect remains client-driven and bounded by the existing browser
policy.

## Pilot gate

A WebRTC proof of concept may start only after representative local, Tailscale
and higher-latency sessions have enough samples to calculate p50/p95. Start the
pilot if at least one condition is observed:

1. p95 first-frame latency exceeds 1.5 seconds;
2. more than 1% of sessions hit the stall watchdog;
3. reconnect success is below 99% within ten seconds;
4. MJPEG bandwidth or CPU prevents the supported device concurrency;
5. interactive latency remains unacceptable despite healthy producer metrics.

## Acceptance criteria

WebRTC must demonstrate, on the same devices and networks:

- lower p95 interaction and first-frame latency;
- no regression in visual correctness or input ownership;
- bounded bitrate, queueing and memory;
- authenticated, session-scoped signaling;
- no public STUN/TURN dependency by default;
- deterministic teardown of peer, tracks, input owner and TURN allocations;
- equivalent evidence capture and sanitized failure receipts;
- fallback to the existing transports when negotiation fails.

## Security gates

- Signaling inherits HuntMob gateway authentication and workspace ownership.
- ICE candidates and private addresses are treated as sensitive diagnostics and
  are not written to client-visible receipts.
- DataChannel input carries the current device/session generation and never
  accepts arbitrary command text.
- TURN credentials, if introduced, are short-lived and remain server-side.
- A successful peer connection does not establish device authorization or DAST
  scope.

## Rollback

WebRTC must ship behind a disabled-by-default capability flag. Rollback removes
the flag and leaves H.264/MJPEG unchanged; no evidence schema migration is
required.

## Primary references

- [W3C WebRTC Recommendation](https://www.w3.org/TR/webrtc/)
- [WebRTC peer connection and signaling](https://webrtc.org/getting-started/peer-connections)
- [MDN WebRTC connectivity and ICE](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Connectivity)
- [RFC 8826 — Security Considerations for WebRTC](https://www.rfc-editor.org/rfc/rfc8826)
