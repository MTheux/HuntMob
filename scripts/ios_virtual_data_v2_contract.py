"""Own DATA-v2 cohort contract. Metadata only; never handles root key bytes."""
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

import prepare_ios_virtual_profile as preparation

PROJECT = Path(__file__).resolve().parents[1]
VM_ROOT = preparation.VM_ROOT
CANDIDATE = preparation.RESEARCH / "ios-engine-diagnostics-20261014"
SCHEMA = "huntmob.virtual-sep-data-profile.v2"
IDENTITY_SCHEMA = "huntmob.virtual-sep-profile.v1"
KDF_ID = "huntmob.virtual-sep-kdf.v1"
PREFIX = "virtual-sep-data-v2-"
PROFILE = {
    "id": "huntmob.virtual-data.v2", "version": 2,
    "formats": ["0x0001b040", "0x0001b140"],
    "algorithm": "AES-128-XTS", "key_bytes": 32, "data_unit_bytes": 4096,
    "unit_encoding": "LE64||zero64",
    "machine_property": "huntmob-virtual-data-profile=v2",
    "hardware_equivalent": False,
}
require = preparation.require


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate manifest key")
        result[key] = value
    return result


def read_metadata(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 1024 * 1024,
            "Expected bounded independent metadata file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), "Metadata changed while opening")
        with os.fdopen(fd, "r", closefd=False) as stream:
            value = json.load(stream, object_pairs_hook=unique_object)
        require(isinstance(value, dict), "Metadata object required")
        after = os.fstat(fd)
        require((after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns), "Metadata changed while reading")
        current = path.lstat()
        require((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "Metadata pathname changed while reading")
        return value
    finally:
        os.close(fd)


def target_for(vm_id):
    parsed = uuid.UUID(vm_id)
    require(str(parsed) == vm_id and parsed.version == 4, "A new canonical UUIDv4 is required")
    return VM_ROOT / (PREFIX + vm_id)


def require_new_identity(vm_id):
    target = target_for(vm_id)
    require(not target.exists() and not target.is_symlink(), "DATA-v2 destination already exists")
    for path in VM_ROOT.iterdir():
        require(not (path.name.endswith(vm_id)), "VM UUID already belongs to another cohort")
        metadata = path / "virtual-profile.json"
        if path.is_dir() and not path.is_symlink() and metadata.exists():
            record = read_metadata(metadata)
            require(record.get("vm_uuid") != vm_id and record.get("keychain_account") != vm_id,
                    "VM identity/account was already used")
    return target


def validate_manifest(target, manifest=None, *, owned_launch_lock=None):
    require(target.is_dir() and not target.is_symlink(), "Independent DATA-v2 directory required")
    value = manifest if manifest is not None else read_metadata(target / "virtual-profile.json")
    require(target == target_for(value.get("vm_uuid", "")), "DATA-v2 path/UUID mismatch")
    require(value.get("schema") == SCHEMA and value.get("identity_schema") == IDENTITY_SCHEMA and
            value.get("data_profile") == PROFILE and value.get("kdf_id") == KDF_ID and
            value.get("data_profile_sha256") == canonical_hash(PROFILE), "Wrong identity or DATA contract")
    require(value.get("keychain_service") == "HuntMob.VirtualSEP.v1" and
            value.get("keychain_account") == value["vm_uuid"], "Root account binding differs")
    require(value.get("old_cohort_cloned") is False and value.get("ready") is False and
            value.get("apple_sep_equivalent") is False and value.get("native_ready") is False,
            "A research cohort must remain unpromoted and independently created")
    require(set(value.get("backings", {})) == set(preparation.SIZES), "Exact nine backing files required")
    identities = set()
    for name, size in preparation.SIZES.items():
        observed = preparation.fingerprint(target / name)
        require(observed == value["backings"][name] and observed["bytes"] == size,
                "Backing identity/geometry changed")
        identity = (observed["device"], observed["inode"])
        require(identity not in identities, "Backing identities alias")
        identities.add(identity)
    # A copy/symlink/hardlink of a historical identity store is never accepted.
    for sibling in VM_ROOT.iterdir():
        if sibling == target or not sibling.is_dir() or sibling.is_symlink():
            continue
        for name in preparation.SIZES:
            candidate = sibling / name
            if candidate.exists() and not candidate.is_symlink():
                info = candidate.stat()
                require((info.st_dev, info.st_ino) not in identities, "Historical backing alias refused")
    socket = target / "qmp.sock"
    require(not socket.exists() and not socket.is_symlink(), "A VM may be active; refuse concurrent operation")
    lock = target / ".data-v2-launch.lock"
    if lock.exists() or lock.is_symlink():
        require(owned_launch_lock is not None, "A DATA-v2 launch is active or unresolved; refuse host access")
        opened = os.fstat(owned_launch_lock)
        actual = lock.lstat()
        require(stat.S_ISREG(actual.st_mode) and actual.st_nlink == 1 and actual.st_uid == os.getuid() and
                stat.S_IMODE(actual.st_mode) == 0o600 and
                (actual.st_dev, actual.st_ino) == (opened.st_dev, opened.st_ino),
                "Only the launcher's existing exclusive lock descriptor is accepted")
    else:
        require(owned_launch_lock is None, "Owned launch lock disappeared")
    binding = value.get("engine_binding", {})
    require(isinstance(binding, dict) and all(re.fullmatch(r"[0-9a-f]{64}", str(binding.get(key, "")))
            for key in ("binary_sha256", "build_receipt_sha256", "reviewed_sources_sha256", "data_v2_patch_sha256")),
            "Engine/source/contract fingerprints are mandatory")
    sources = binding.get("reviewed_source_sha256", {})
    require(isinstance(sources, dict) and sources and canonical_hash(sources) == binding["reviewed_sources_sha256"],
            "Reviewed source map fingerprint mismatch")
    require(all(isinstance(key, str) and not Path(key).is_absolute() and ".." not in Path(key).parts and
                re.fullmatch(r"[0-9a-f]{64}", str(value)) for key, value in sources.items()),
            "Invalid reviewed source map")
    return value


def engine_binding(expected_binary_sha256):
    """Bind the reviewed compiled artifact. No engine process is executed."""
    from build_ios_research_engine import PATCHES, require_data_protection, reviewed_sources
    require(re.fullmatch(r"[0-9a-f]{64}", expected_binary_sha256 or ""), "Exact reviewed engine SHA256 required")
    receipt_path = CANDIDATE / "build-receipt.json"
    receipt = read_metadata(receipt_path)
    binary = CANDIDATE / "build/qemu-system-aarch64"
    observed, _ = preparation.digest(binary)
    require(receipt.get("state") == "compiled" and receipt.get("ready") is False and
            receipt.get("virtual_sep_default_enabled") is False and
            observed == expected_binary_sha256 == receipt.get("binary_sha256"), "Engine receipt/hash differs")
    require_data_protection(CANDIDATE / "source")
    sources = reviewed_sources(CANDIDATE / "source", PATCHES)
    require(sources == receipt.get("reviewed_source_sha256"), "Reviewed source binding changed")
    patch = PROJECT / "components/ios-engine/ans-own-data-v2-profile.patch"
    patch_sha, _ = preparation.digest(patch)
    require(any(str(path).endswith("ans-own-data-v2-profile.patch") for path in PATCHES),
            "DATA-v2 patch is not in the reviewed build recipe")
    require(receipt.get("patch_sha256", {}).get(patch.name) == patch_sha,
            "Compiled receipt does not bind the DATA-v2 patch")
    machine = (CANDIDATE / "source/hw/arm/apple-silicon/t8030.c").read_text()
    require('"huntmob-virtual-data-profile"' in machine and "virtual_data_v2" in machine,
            "Reviewed engine lacks the explicit DATA-v2 machine property")
    receipt_sha, _ = preparation.digest(receipt_path)
    return {"binary_sha256": observed, "build_receipt_sha256": receipt_sha,
            "reviewed_source_sha256": sources, "reviewed_sources_sha256": canonical_hash(sources),
            "data_v2_patch_sha256": patch_sha}


def verify_engine(manifest):
    observed = engine_binding(manifest["engine_binding"]["binary_sha256"])
    require(observed == manifest["engine_binding"], "Cohort cannot silently rebind its engine or source")
    return CANDIDATE / "build/qemu-system-aarch64"


def plan(vm_id, action):
    return {"schema": "huntmob.virtual-sep-data-plan.v2", "read_only": True,
            "target": str(target_for(vm_id)), "action": action, "data_profile": PROFILE,
            "identity_schema": IDENTITY_SCHEMA, "kdf_id": KDF_ID,
            "keychain_service": "HuntMob.VirtualSEP.v1", "keychain_account": vm_id,
            "root_accessed": False, "root_in_python": False, "vm_started": False,
            "v1_cohort_reused": False, "ready": False, "native_ready": False,
            "remaining_adapters": ["DATA-v2 auxiliary APFS staging", "DATA-v2 trusted effaceable ramdisk staging"]}
