/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Own VirtualMPE-v1 memory consumer; not Apple's MPE or hardware attestation. */
#ifndef HW_ARM_HUNTMOB_VIRTUAL_MPE_MEMORY_H
#define HW_ARM_HUNTMOB_VIRTUAL_MPE_MEMORY_H
#include "qemu/typedefs.h"
#include "crypto/huntmob-virtual-mpe.h"
#define TYPE_HUNTMOB_VIRTUAL_MPE_MEMORY "huntmob-virtual-mpe-memory"
typedef struct HuntMobVirtualMPEMemory HuntMobVirtualMPEMemory;
/* Internal machine-only factory. Strong QOM child of parent, no public QOM
 * key/config properties. Generates fresh private boot salt itself. */
HuntMobVirtualMPEMemory *huntmob_virtual_mpe_memory_new(Object *parent,
                                                       const uint8_t vm_id[16],
                                                       Error **errp);
/* Borrowed pointer can change after full reset. Never cache it across calls. */
HuntMobVirtualMPE *huntmob_virtual_mpe_memory_core(HuntMobVirtualMPEMemory *m);
bool huntmob_virtual_mpe_memory_attach_sep(HuntMobVirtualMPEMemory *m,
                                           MemoryRegion *sep_cpu_memory,
                                           Error **errp);
/* Host bootstrap only, before guest execution. TZ offset is relative to DRAM,
 * not an absolute physical address. Covers ENTIRE carveout externally. */
bool huntmob_virtual_mpe_memory_set_tz(HuntMobVirtualMPEMemory *m,
                                       uint64_t dram_base, uint64_t tz_offset,
                                       uint64_t tz_size, Error **errp);
bool huntmob_virtual_mpe_memory_consumer_ready(HuntMobVirtualMPEMemory *m);
/* Proven ROM KiB fields converted by bridge; offsets remain DRAM-relative.
 * secondary_enabled is explicit, so a missing318 is not offset zero. */
bool huntmob_virtual_mpe_memory_configure(HuntMobVirtualMPEMemory *m,
                                          uint64_t primary_offset,
                                          uint64_t primary_length,
                                          uint64_t secondary_offset,
                                          bool secondary_enabled,
                                          Error **errp);
bool huntmob_virtual_mpe_memory_initialize_region(HuntMobVirtualMPEMemory *m,
                                                  unsigned region, Error **errp);
uint64_t huntmob_virtual_mpe_memory_region_length(HuntMobVirtualMPEMemory *m,
                                                  unsigned region);
/* Full SEP/machine reset only. Retires old object, wipes caches and renews
 * salt/epoch. AESS200 is NOT a caller. Failure leaves the consumer unavailable. */
void huntmob_virtual_mpe_memory_reset(HuntMobVirtualMPEMemory *m);
#endif
