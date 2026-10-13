# Genymotion REA analysis v1.0 — 2026-10-13

## Scope

Passive, local, read-only inspection of `/Applications/Genymotion.app`. No
virtual device was started and no network target was contacted.

## Confirmed evidence

- Genymotion Desktop: `3.10.0`, revision `20260331-81a66429d0`.
- Main `genymotion` and `gmtool` executables: Mach-O `x86_64`.
- Runtime composition: QEMU, VirtualBox integration, ADB/AAPT and Qt/QML.
- REA provider: `rea-artifact-graph` v1.
- Evidence ID: `ev_022e8c6a6d73ecf8cd75c19077e482fd5ae25cef0c43d6e53adf1e25cfec6cad`.
- Inspection ID: `ai_25f2fe9f70f620d19897140a5ce34ad8c956657756139911c25f6e13c6df959d`.
- Manifest ID: `agm_f19d18120d0709a4814a395ccf5e6c5e13fc750128a6abfe830b0813aace4dc7`.
- Graph: 1,654 nodes, 3,018 occurrences and 2,794 edges.

## Integration decision

HuntMob uses the supported `gmtool` surface as the Android runtime adapter.
REA analyzes authorized app/runtime artifacts and evidence; it does not replace
the hypervisor. Device creation, start, mutation and deletion remain behind the
engagement and human-approval gates.

## Limitations

- Static inspection does not establish runtime performance or compatibility.
- The x86_64 binaries may require translation on Apple Silicon; benchmark it
  with a disposable device before treating this as a production constraint.
- No Genymotion virtual device existed during this inspection.
