# Integrated proxy — v1.0 — 2026-10-13

HuntMob starts a headless mitmdump capture worker instead of mitmweb. No web UI
listener or external browser URL is created. The listener binds to host loopback;
the owned emulator uses 10.0.2.2 to reach it. Flow output is quiet; the existing
redacted capture addon supplies the HuntMob Proxy inspector directly.

The frontend updates its internal inspector based on managed capture, without
expecting a web_url. The previous HuntMob-owned mitmweb process was stopped and
replaced with the new capture worker. Port 8081 no longer listens.

Validation: capture started through the HuntMob UI; Android sent a controlled
HTTP request via the loopback proxy to a temporary local fixture, received 200,
and the flow appeared in the internal inspector. The browser remained on 8090.
92 Python tests passed; JavaScript syntax and diff checks passed. HTTPS trust/CA
configuration was not changed or tested. Changes are local, not committed/pushed;
earlier release artifacts require rebuilding before distribution.
