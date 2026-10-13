# HuntMob session face recognition v1.0 — 2026-10-13

## Dependency

- Project: `@vladmandic/human`
- Version: `3.3.6` (pinned)
- License: MIT
- Upstream: <https://github.com/vladmandic/human>

Human was selected over the older `face-api.js` because it provides an active,
unified browser pipeline for face detection, embeddings, anti-spoof and liveness
signals. Model and runtime files are currently loaded from pinned/public upstream
URLs; production packaging should vendor and hash them for offline operation.

## Privacy boundary

The browser asks for camera access only after an explicit click. Enrollment stores
one numeric embedding in JavaScript memory. Closing the fixture stops camera tracks,
clears the overlay and drops the embedding. HuntMob does not use localStorage,
IndexedDB or a server endpoint for biometric data.

## Assurance limitation

This is a pentest fixture, not certified biometric authentication. The `0.5`
similarity threshold follows the upstream FaceRes demo configuration and requires
calibration against the actual camera population. Anti-spoof and liveness outputs
raise test quality but do not establish resistance against presentation attacks.
