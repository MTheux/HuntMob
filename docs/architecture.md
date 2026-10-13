# Architecture v0.1

HuntBox Mob separates orchestration from runtime implementation:

1. **Control plane** validates the engagement and action allowlist.
2. **Runtime adapters** manage Genymotion, Apple Simulator or vPhone.
3. **Analysis providers** send authorized APK/IPA artifacts to REA/Ghidra.
4. **Evidence store** persists immutable hashes, receipts and sanitized output.

The initial milestone is discovery-only. Device mutation and application
installation remain blocked until their approval and receipt contracts exist.

