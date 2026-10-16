# Embedded analysis — v1.0 — 2026-10-13

## Implementation

HuntMob 0.2.0 incorporates the official JADX 1.5.5 all-in-one JAR and a packaged
Eclipse Temurin JRE 21.0.11+10. It invokes the internal Java executable directly
with `jadx.cli.JadxCLI`, never an externally installed JADX script. No PATH lookup,
Java bootstrap or network download occurs during analysis. This is incorporation
of third-party compiled technology, not a new decompiler invented by HuntMob.

Official release artifacts and SHA-256 values are pinned in the component manifest.
The builder includes licenses and legal notices, validates archive paths, verifies
archives and generates file integrity metadata. The runtime verifies its platform
and packaged files before analysis. Release wheels contain the UI and native JRE
and carry platform tags so incompatible wheels are rejected by the installer.

The UI checks `/api/analysis/status` and labels the capability “Motor integrado”.
Missing/corrupt bundles fail closed; the client is instructed to reinstall its
HuntMob package rather than install JADX/Java separately. Partial decompilation
continues to be reported honestly.

## Validation and bounds

85 Python tests pass. Direct source and installed macOS ARM64 wheel execution
succeeded with PATH empty and JAVA_HOME pointing to a nonexistent installation.
InsecureBankv2 produced 3668 files and retained its partial status (two errors).

Windows x64 and Linux x64 wheels were assembled with their native JREs, engine,
licenses, integrity manifest and UI; their archive contents were verified. Native
execution on those operating systems has not been verified. Other targets are
pinned but not yet assembled or runtime-validated. Wheels require Python; standalone
desktop installers and the other mobile lab dependencies remain separate work.

Generated binary assets and release artifacts are ignored by source Git. A clean
source checkout must run the release builder; final releases include those assets
and run offline. No code was committed or pushed.
