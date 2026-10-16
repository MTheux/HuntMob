# OwnMPE v1 — experimental, 2026-10-15

This is HuntMob's authenticated volatile-memory model, not Apple's MPE cipher,
UID derivation, attestation, or proof of native iOS readiness. The exact framing,
limits and memory-owner obligations are in [contract-v1.json](contract-v1.json).

Two separately staged/latched 32-byte inputs form one 64-byte SP800-108 HMAC
root. VM identity, fresh boot salt, epoch, region and physical range bind the
AES-GCM key. Each64-byte line has a full16-byte authentication tag and a unique
nonce containing its index and trusted monotonic write generation. Inputs with
duplicated halves do not imply extra entropy. No key getter is exported.

Initialization encrypts all active lines before exposing ciphertext. Active
partial writes authenticate every touched old line and stage all replacements
before committing. Failed authentication or active invalid access faults the
region, wipes the full borrowed plaintext cache and expanded keys, and leaves
caller output untouched. The owner must then fault mappings and flush all ROMD
and translated-code state before the SEP CPU resumes. Successful writes also
require code-cache invalidation. Ordinary shared-RAM aliases cannot satisfy this
contract because direct stores bypass the cryptographic core.

Reset revokes the object permanently and wipes caches, keys, ciphertext, tags
and generation maps. Reuse requires a new core with fresh salt and epoch.
ROM control200 preserving key latches is not this destructive reset. Live migration is unsupported and separately blocked by the owning integration.
This core adds no generic QMP/debugger guard and does not claim complete dump
blocking. The SEP-only ROMD cache is outside the ordinary AP/system-memory
view; host-admin/debug access, including inspection of SEP CPU registers, may
expose private data and remains trusted. Host memory and the emulator process
are also trusted. No persistent antirollback is claimed.

Run only synthetic public fixtures:

```sh
python3 components/ios-storage-crypto/virtual-mpe/build_selftest.py \
  --authorized-synthetic-selftest
```

The standalone C checks exercise state, bounds, RMW, rejection, corruption,
exhaustion and cache erasure. Python independently derives keys with HMAC and
checks ciphertext/tags using `cryptography` AESGCM, including cross-line,
region, profile, salt, epoch and physical-range transplantation. Test-only record
injection is absent from production engine builds. These tests do not execute
firmware, bind live guest RAM, validate MMIO or instruction fetch, or establish
SpringBoard, Data Protection or IPA execution.
