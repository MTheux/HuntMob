# HuntMob workbench UI decision ledger v1.0 — 2026-10-13

## Design brief

Designing a mobile pentest workbench for authorized security operators on web.
Goal: run a device and inspect the same app without changing tools or context.
Tone: dense, technical, controlled and unmistakably HuntBox.
Main risk: turning a security lab into an unsafe raw shell or a decorative dashboard.

## Reference lock

- Primary: existing HuntBox/Draxen UI; preserve near-black canvas, Barlow/neutral
  sans hierarchy, JetBrains-like mono metadata and `#E7274A` action red.
- Product structure: Genymotion device inventory and direct device management.
- Workbench structure: IDE file tree, editor and persistent tabs for technical tools.
- Red is reserved for primary action, current selection and security attention.
- No gradients in UI chrome, no soft rounded card grid, no decorative imagery.
- Device display is the visual anchor; reverse engineering remains visible beside it.

## Decision ledger

| Decision | Source | Role | Why |
|---|---|---|---|
| Black/graphite canvas | HuntBox UI | application chrome | brand continuity |
| `#E7274A` | HuntBox tokens | action and selection | keeps semantic discipline |
| Device list at left | Genymotion | runtime navigation | familiar device workflow |
| Device + RE split | user brief and IDE pattern | primary workspace | removes tool switching |
| Mono for hashes/code | developer-tool craft | technical content | improves scanning |
| Webcam consent dialog | privacy/accessibility craft | fixture control | no silent capture |
| Tabs for REA/Frida/Proxy/Evidence | capability contract | context switch | unified but not crowded |
