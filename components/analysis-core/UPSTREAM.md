# HuntMob embedded analysis core

HuntMob incorporates the compiled JADX decompilation engine (1.5.5) and an
Eclipse Temurin Java runtime (21.0.11+10) into its platform distribution.
JADX is third-party technology, not a newly invented HuntMob decompiler.

Sources:
- https://github.com/skylot/jadx/tree/v1.5.5 — Apache-2.0
- https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.11%2B10
  — runtime includes its upstream legal directory and notices.

`manifest.json` pins official artifact URLs and SHA-256 checksums for macOS,
Linux and Windows, on x64 and aarch64. The release builder verifies downloaded
archives, materializes files safely and records an integrity manifest for each
bundle. Original engine and Java runtime license files are included in releases.

Runtime clients invoke only the packaged Java executable and engine JAR. They do
not search PATH, invoke a system JADX script, download engines or install Java.
Generated binary assets are release inputs, excluded from source Git; they are
included as package data in the final platform wheel.
