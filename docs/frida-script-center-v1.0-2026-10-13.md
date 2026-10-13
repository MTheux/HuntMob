# HuntMob Frida Script Center v1.0 — 2026-10-13

## Reference and provenance

The interaction model was informed by `z3n70/Frida-Script-Runner`, reviewed at
its public `main` branch on 2026-10-13. The upstream repository is MIT licensed.
HuntMob does not copy its runtime, bundled Frida binaries or unreviewed scripts.

## Adopted product patterns

- Discover installed applications and select a package or bundle identifier.
- Search a script catalog and combine multiple scripts into one job.
- Spawn the authorized app, attach Frida and stream output in the workbench.
- Integrate JADX/Ghidra/REA context when preparing app-specific instrumentation.

## HuntMob safety differences

- Package IDs are validated and must equal the engagement allowlist.
- The browser cannot provide arbitrary CLI flags, paths or shell fragments.
- Scripts are catalog entries with provenance, version and future SHA-256 lock.
- Observe-only scripts are distinct from scripts that modify application behavior.
- Active scripts require human approval and every run requires a receipt.
- Execution happens only in the isolated worker, never in the web process.

## Current status

The catalog, UI selection, package validation and worker job contract are
implemented. Device discovery and actual Frida process execution are not yet
wired to the Worker API.
