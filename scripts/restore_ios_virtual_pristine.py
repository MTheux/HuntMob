#!/usr/bin/env python3
"""Initialize only a never-booted VirtualSEP-v1 cohort from pristine public APFS.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Rebuild GPT for the emulated 4096-byte
sectors; never copy historical Data, keybags, SEP backing or entire 512B GPT.
This is a direct pristine-filesystem copy, not a successful ASR invocation.
"""
import argparse
import hashlib
import json
import os
import struct
import uuid
import zlib
from pathlib import Path

import prepare_ios_virtual_profile as p

BLOCK = 4096
PARTITION_OFFSET = 17408
PARTITION_BYTES = 7695577088
APFS_TYPE = uuid.UUID('7c3457ef-0000-11aa-aa11-00306543ecac')


def gpt(size, vm_id):
    p.require(size % BLOCK == 0 and size // BLOCK > 20, 'Invalid disk size')
    count = size // BLOCK
    disk_id = uuid.uuid5(uuid.UUID(vm_id), 'HuntMob.VirtualSEP.v1/disk')
    part_id = uuid.uuid5(uuid.UUID(vm_id), 'HuntMob.VirtualSEP.v1/apfs')
    entries = bytearray(128 * 128)
    struct.pack_into('<16s16sQQQ72s', entries, 0, APFS_TYPE.bytes_le,
                     part_id.bytes_le, 6, count - 6, 0, 'HuntMob iOS'.encode('utf-16le'))
    entries_crc = zlib.crc32(entries)
    def header(current, alternate, entries_lba):
        value = bytearray(BLOCK)
        struct.pack_into('<8sIIIIQQQQ16sQIII', value, 0, b'EFI PART',
                         0x10000, 92, 0, 0, current, alternate, 6, count - 6,
                         disk_id.bytes_le, entries_lba, 128, 128, entries_crc)
        struct.pack_into('<I', value, 16, zlib.crc32(value[:92]))
        return bytes(value)
    pmbr = bytearray(BLOCK)
    struct.pack_into('<B3sB3sII', pmbr, 446, 0, b'\0\2\0', 0xee,
                     b'\xff\xff\xff', 1, min(count - 1, 0xffffffff))
    pmbr[510:512] = b'\x55\xaa'
    return {0: bytes(pmbr), BLOCK: header(1, count - 1, 2),
            2 * BLOCK: bytes(entries), (count - 5) * BLOCK: bytes(entries),
            (count - 1) * BLOCK: header(count - 1, 1, count - 5)}


def verify_gpt(fd, size):
    count = size // BLOCK
    for offset in (BLOCK, (count - 1) * BLOCK):
        value = bytearray(os.pread(fd, BLOCK, offset))
        fields = struct.unpack_from('<8sIIIIQQQQ16sQIII', value)
        p.require(fields[0] == b'EFI PART' and fields[2] == 92, 'GPT header mismatch')
        original = fields[3]
        struct.pack_into('<I', value, 16, 0)
        p.require(zlib.crc32(value[:92]) == original, 'GPT header CRC mismatch')
        entries = os.pread(fd, fields[11] * fields[12], fields[10] * BLOCK)
        p.require(zlib.crc32(entries) == fields[13], 'GPT entry CRC mismatch')
        partition = struct.unpack_from('<16s16sQQQ72s', entries)
        p.require(partition[0] == APFS_TYPE.bytes_le and partition[2:4] == (6, count - 6),
                  'GPT partition geometry differs')
        p.require(not any(entries[128:]), 'Unexpected extra partition')
    p.require(os.pread(fd, 2, 510) == b'\x55\xaa', 'Protective MBR missing')


def restore(vm_id):
    p.require(str(uuid.UUID(vm_id)) == vm_id, 'Canonical UUID required')
    p.check_parent()
    target = p.VM_ROOT / ('virtual-sep-v1-' + vm_id)
    p.require(not target.is_symlink(), 'Symlink target refused')
    manifest_path = target / 'virtual-profile.json'
    p.require(not manifest_path.is_symlink() and manifest_path.stat().st_size <= 65536,
              'Invalid profile manifest')
    m = json.loads(manifest_path.read_text())
    p.require(m.get('schema') == 'huntmob.virtual-sep-profile.v1' and m.get('vm_uuid') == vm_id and
              m.get('old_cohort_cloned') is False and m.get('root_provisioned') is False and
              m.get('restore_completed') is False and m.get('state') in
              {'preparation-failed', 'new-sparse-cohort'} and not m.get('firmware_components_staged'),
              'Only the new never-booted unprovisioned cohort can be initialized')
    for name in p.SIZES:
        p.require(p.fingerprint(target / name) == m['backings'][name], 'Backing identity changed')
        if name != 'namespace-1.raw':
            p.require(not any((target / name).read_bytes()), 'Auxiliary identity store is not empty')
    image = target / 'namespace-1.raw'
    p.require(all(p.image_path(e['image-path']).resolve() != image.resolve()
                  for e in p.image_inventory() if e.get('image-path')), 'New image is still attached')
    sources = p.validate_sources()
    p.require(sources == m['sources'], 'Pristine source provenance changed')
    p.require(p.shutil.disk_usage(p.VM_ROOT).free >= p.MIN_START_FREE, 'Insufficient copy headroom')
    source_fd = os.open(p.SOURCE_RAW, os.O_RDONLY | os.O_NOFOLLOW)
    destination_fd = os.open(image, os.O_RDWR | os.O_NOFOLLOW)
    try:
        opened = os.fstat(destination_fd)
        identity = m['backings']['namespace-1.raw']
        p.require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_nlink) ==
                  (identity['device'], identity['inode'], identity['bytes'], 1),
                  'Opened target does not match the owned manifest')
        source_header = os.pread(source_fd, 92, 512)
        p.require(source_header[:8] == b'EFI PART', 'Pristine source GPT absent')
        source_entries_lba = struct.unpack_from('<Q', source_header, 72)[0]
        source_partition = os.pread(source_fd, 128, source_entries_lba * 512)
        typ, _, start, end = struct.unpack_from('<16s16sQQ', source_partition)
        p.require(typ == APFS_TYPE.bytes_le and start * 512 == PARTITION_OFFSET and
                  (end - start + 1) * 512 == PARTITION_BYTES, 'Source APFS geometry changed')
        superblock = os.pread(source_fd, BLOCK, PARTITION_OFFSET)
        p.require(superblock[32:36] == b'NXSB' and struct.unpack_from('<I', superblock, 36)[0] == BLOCK,
                  'Source is not the expected public 4K APFS container')
        m.update(state='copying-pristine-public-apfs', restore_method='pristine-apfs-partition-copy-v1',
                 asr_completed_successfully=False)
        p.write_manifest(target, m)
        # No key was ever associated with this cohort. Drop partial failed-ASR
        # metadata in this same newly created inode, never a historical image.
        os.ftruncate(destination_fd, 0)
        os.ftruncate(destination_fd, identity['bytes'])
        for offset, value in gpt(identity['bytes'], vm_id).items():
            p.require(os.pwrite(destination_fd, value, offset) == len(value), 'Short GPT write')
        source_hash = hashlib.sha256()
        for offset in range(0, PARTITION_BYTES, 1024 * 1024):
            p.require(p.shutil.disk_usage(p.VM_ROOT).free >= p.MIN_RUNNING_FREE, '20 GiB reserve reached')
            data = os.pread(source_fd, min(1024 * 1024, PARTITION_BYTES - offset), PARTITION_OFFSET + offset)
            p.require(bool(data), 'Short pristine source read')
            source_hash.update(data)
            p.require(os.pwrite(destination_fd, data, 6 * BLOCK + offset) == len(data), 'Short APFS write')
        os.fsync(destination_fd)
        verify_gpt(destination_fd, identity['bytes'])
        copied_hash = hashlib.sha256()
        for offset in range(0, PARTITION_BYTES, 1024 * 1024):
            data = os.pread(destination_fd, min(1024 * 1024, PARTITION_BYTES - offset), 6 * BLOCK + offset)
            p.require(bool(data), 'Short APFS readback')
            copied_hash.update(data)
        p.require(copied_hash.digest() == source_hash.digest(), 'Public filesystem readback differs')
        p.require(p.fingerprint(image) == identity, 'Target identity changed during copy')
        p.require(p.fingerprint(p.SOURCE_RAW, source=True) == {key: sources[str(p.SOURCE_RAW)][key]
                  for key in ('device', 'inode', 'bytes', 'links', 'mtime_ns', 'ctime_ns')}, 'Source changed during copy')
        m.update(state='pristine-filesystem-restored', restore_completed=True,
                 owned_device_detached=True, gpt_sector_bytes=BLOCK, gpt_crc_verified=True,
                 public_apfs_partition_sha256=source_hash.hexdigest(),
                 public_apfs_bytes=PARTITION_BYTES, public_apfs_readback_matches=True,
                 filesystem_capacity_expansion_validated=False, private_artifact_absence_checked=False)
        p.write_manifest(target, m)
        return m
    except BaseException as error:
        m.update(state='preparation-failed', restore_completed=False, failure_type=type(error).__name__)
        p.write_manifest(target, m)
        raise
    finally:
        os.close(destination_fd)
        os.close(source_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--vm-uuid', required=True)
    args = parser.parse_args()
    result = restore(args.vm_uuid)
    print(json.dumps({key: result[key] for key in ('state', 'restore_method', 'public_apfs_readback_matches', 'ready')}))


if __name__ == '__main__':
    main()
