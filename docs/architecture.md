# HuntMob architecture v0.2

HuntMob separates orchestration from runtime implementation:

1. **Control plane** validates the engagement and action allowlist.
2. **Runtime adapters** manage Genymotion, Apple Simulator or vPhone.
3. **Analysis providers** send authorized APK/IPA artifacts to REA/Ghidra.
4. **Evidence store** persists immutable hashes, receipts and sanitized output.

## Cross-platform iOS execution

The controller and browser UI may run on macOS, Windows or Linux. The iOS
runtime is scheduled onto one of these workers:

1. Apple Simulator worker on an authorized Mac for ordinary app testing.
2. Corellium cloud/private/appliance for privileged security analysis.
3. An approved real-device cloud or owned device farm for hardware behavior.

```text
Windows / Linux / macOS browser
             |
       HuntMob control plane
             |
       VPN/Tailscale + TLS
             |
   +---------+----------+----------------+
   |                    |                |
Mac worker         Corellium worker   Real device cloud
Simulator          privileged iOS    camera/biometrics
```

The control plane never exposes `simctl`, SSH or provider credentials directly
to the browser. Workers accept typed, allowlisted jobs, validate the engagement,
and return a time-bounded stream plus immutable evidence receipts.

The current milestone remains discovery and routing only. Provisioning, remote
streaming and application installation stay blocked until authentication,
approval, isolation and receipt contracts are implemented.

