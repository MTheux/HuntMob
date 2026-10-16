# Virtual SEP v1 — fresh cohort contract, 2026-10-15

The new profile must start from pristine public firmware and nine newly created
backings. An old booted container with Data deleted is unsuitable: APFS copy on
write, snapshots/free extents, xART, and auxiliary namespaces can retain the old
identity state. Existing labs/checkpoints remain preserved and are never inputs
to this preparation script.

## Preparation and review

`scripts/prepare_ios_virtual_profile.py` defaults to a read-only plan:

```text
python3 scripts/prepare_ios_virtual_profile.py --plan --vm-uuid <NEW-CANONICAL-UUID>
```

There are no user-controlled source, target, device, or image path arguments.
The target is exclusively
`~/.huntmob/research/ios-vms/virtual-sep-v1-<UUID>` and must not exist.
`--create-files --authorized-lab` creates only nine new sparse backings and a
public identity manifest; it does not initialize/read the Keychain root.
`--restore-reviewed --authorized-lab` creates a new cohort and performs the
host filesystem restore. It must be invoked only after reviewing this script's
erase command and ownership checks. It cannot resume/reuse an existing target.

The reviewed destructive command template is:

```text
/usr/sbin/asr restore --source <PINNED-PRISTINE-source.dmg> \
  --target <NEW-OWNED-WHOLE-LOOP-DEVICE> \
  --erase --noprompt --SHA256 --puppetstrings
```

Only a device attached by this process from its newly created
`namespace-1.raw` can reach that command. Checks require a new device absent
from the initial inventory; exact `DeviceNode`/identifier/size; whole virtual
Disk Image, non-internal/unmounted metadata; and a unique current
`hdiutil info -plist` association to the exact backing pathname/URI/inode.
Partition paths and raw-device aliases are rejected. The helper rechecks
ownership before erase and before detach. Error cleanup detaches only the
verified owned image, never uses force, and records ambiguous cleanup for
manual review rather than detaching another device.

No restore/attachment/format was executed during implementation. The new
ownership parser has synthetic metadata tests; its strict diskutil metadata
contract still requires validation during the first reviewed attachment.

## Pristine-source evidence

Read-only verification on this host confirmed:

- IPSW SHA256: `706742ed60327a5247c29ccc5bf7e6ce9bbf11dd30a468f8f6fc9da76bdca96d`.
- Build `18A5351d`, unique n104ap `Research Developer Erase Install` identity.
- Archive OS entry `038-44337-083.dmg` and the existing extracted `source.dmg`
  have identical SHA256
  `cae20aff4f69e72b78f80fdaf92f26d1f3dac7890c66ca00d16bb6f3270368dd`.
- Existing converted `source.raw` SHA256:
  `96bebe305f5e0ab41ba61e976e52687646bfa1f189918956069caeda107ee9d6`.
- Its APFS partition SHA384 matches
  `artifacts/validation/ios-x86-image-integrity-v1-2026-10-13.json`.

Mutating preparation rehashes all three pinned files, rejects symlinks/hard
links, and retains/rechecks inode, size, mtime and ctime before/after restore.
Only this unbooted firmware source and newly zero-backed auxiliary stores are
used; no old private Gigalocker, systembag, SSC or Data bytes are copied.
This provenance does not claim that every possible source artifact has been
independently inspected: `private_artifact_absence_checked` remains false until
the separate stock-file/guest staging inspection.

## Space and execution bounds

The main namespace is logically 32 GiB; the other six namespaces and two SEP
stores use the exact pinned sizes from `boot_ios_research.command()`. Files are
new independent inodes, created with `O_EXCL`/`O_NOFOLLOW`, never hard linked.
The directory is mode 0700 and backing/manifest files are 0600.

At least 28 GiB free is required initially: a 20 GiB reserve plus expected
8 GiB restore allocation. ASR is bounded to 900 seconds, an 8 MiB metadata log,
and a 20 GiB free-space floor monitored every 250 ms. The controller process is
terminated on a bound failure and the partial new cohort is retained for
review. These checks do not promise that the maximum logical 32 GiB write fits
in the current free space; allocating beyond the permitted reserve aborts.

The existing x86 companion has a historical tools-ready receipt, but current
read-only checks found no QMP socket/listener and a refused USB socket. It was
not restarted. The host ASR route avoids depending on the earlier companion
restore stall at guest ASR 4%; historical ASR success is not a new restore result.

## Fresh provisioning requirements

Staging/boot are separate from this script. Before their first persistent write:

1. Bind the fresh public VM UUID/manifest to its explicitly created Keychain
   root through the dedicated inherited pipe. Missing lookup must fail closed.
2. Verify stock binaries/firmware hashes; install owned helpers separately.
   No old Data, keybags, protection probes, or Gigalocker may be imported.
3. Require a fresh auxiliary-store cohort and Data absent before initializing
   effaceable/Class D state. Current `prepare_userdata.c` initializes those
   only when `/dev/disk0s1s2` is absent; validate the pinned layout explicitly.
4. Require `MKBKeyBagCreateSystem(NULL, "/mnt2") == 0`. A return of `-4` means
   an existing systembag and must fail this fresh-profile path; never load/map
   an old bag under the new identity.
5. Determine the fresh xART/Gigalocker state dynamically. The existing
   `init_storage.c` checks a hard-coded old Gigalocker UUID; do not transplant
   that existence check as proof of a fresh profile.
6. Keep the original Data Protection verifier and all failures. Create the
   class C test atomically with protection and `O_EXCL`; then verify write,
   fsync, cold restart/read, and absence of the public test marker in raw storage.

The manifest keeps readiness, Data Protection, SpringBoard and IPA gates false.
This is an experimental HuntMob virtual identity, not a physical Apple SEP or
hardware attestation claim.
