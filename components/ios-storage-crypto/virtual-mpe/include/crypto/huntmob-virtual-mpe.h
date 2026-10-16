/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Own VirtualMPE-v1: not Apple's MPE cipher, KDF or attestation. */
#ifndef QCRYPTO_HUNTMOB_VIRTUAL_MPE_H
#define QCRYPTO_HUNTMOB_VIRTUAL_MPE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define HUNTMOB_MPE_LINE_SIZE 64u
#define HUNTMOB_MPE_REGIONS 2u
#define HUNTMOB_MPE_MAX_REGION (128u * 1024u * 1024u)
#define HUNTMOB_MPE_MAX_TRANSFER (1024u * 1024u)
typedef struct HuntMobVirtualMPE HuntMobVirtualMPE;
/* salt must be fresh cryptographic randomness for EACH object. epoch nonzero.
 * Machine owns object. No root/key getter. Callers must not log inputs. */
HuntMobVirtualMPE *huntmob_virtual_mpe_new(const uint8_t vm_id[16],
                                         const uint8_t boot_salt[32], uint64_t epoch);
/* Free/reset must precede releasing borrowed cache memory. Destructive reset
 * revokes this object permanently; create a fresh object+salt for next epoch.
 * ROM control200 preserving latches is NOT a destructive reset. */
void huntmob_virtual_mpe_reset(HuntMobVirtualMPE *mpe);
void huntmob_virtual_mpe_free(HuntMobVirtualMPE *mpe);
/* Both slots form ONE 64-byte KDF root. Stage then latch EACH, in order0/1.
 * No restaging/re-latching accepted. A bad input never publishes readiness. */
bool huntmob_virtual_mpe_stage_key(HuntMobVirtualMPE *mpe, unsigned slot,
                                   const uint8_t input[32]);
bool huntmob_virtual_mpe_latch_key(HuntMobVirtualMPE *mpe, unsigned slot);
bool huntmob_virtual_mpe_both_latched(HuntMobVirtualMPE *mpe);
bool huntmob_virtual_mpe_regions_bound(HuntMobVirtualMPE *mpe);
size_t huntmob_virtual_mpe_region_length(HuntMobVirtualMPE *mpe, unsigned region);
/* Borrow a private ROMD plaintext cache before boot. No external alias may
 * reference it. capacity must be64-aligned, <=128MiB.
 * Entire capacity is wiped by reset. Preconfiguration private reads/writes
 * are permitted, external reads are denied. */
bool huntmob_virtual_mpe_bind_region(HuntMobVirtualMPE *mpe, unsigned region,
                                     size_t capacity, uint8_t *private_cache);
/* Fixed active prefix length, multiple64, <= bound capacity. Both keys must
 * be latched. Configuration is immutable; initialize encrypts EVERY line
 * before atomic publication. Caller publishes ROMD/map-ready only on true. */
bool huntmob_virtual_mpe_configure_region(HuntMobVirtualMPE *mpe, unsigned region,
                                          uint64_t physical_base, size_t active_length);
bool huntmob_virtual_mpe_initialize_region(HuntMobVirtualMPE *mpe, unsigned region);
bool huntmob_virtual_mpe_is_configured(HuntMobVirtualMPE *mpe, unsigned region);
bool huntmob_virtual_mpe_is_active(HuntMobVirtualMPE *mpe, unsigned region);
/* Active operations authenticate complete touched lines before output/mutation.
 * Write atomicity covers the entire request, <=1MiB active transfer. No mutex
 * is held across bus/DMA callbacks (core never invokes any). ROMD owner must
 * flush_rom_device changed bytes after successful private_write. On any false
 * active bus operation, revoke/fault and flush ROMD/TB before resuming SEP;
 * authentication/malformed active access/counter exhaustion permanently faults
 * that region, wiping its ENTIRE cache and expanded keys before false. Owner
 * must flush the ENTIRE capacity/TB on false. Limit ROMD to active_length;
 * direct reads/fetch outside that prefix must fault, not expose cache tail. */
bool huntmob_virtual_mpe_private_write(HuntMobVirtualMPE *mpe, unsigned region,
                                       size_t offset, const uint8_t *input, size_t length);
bool huntmob_virtual_mpe_private_read(HuntMobVirtualMPE *mpe, unsigned region,
                                      size_t offset, uint8_t *output, size_t length);
bool huntmob_virtual_mpe_external_read(HuntMobVirtualMPE *mpe, unsigned region,
                                       size_t offset, uint8_t *output, size_t length);
/* External writes are unsupported: always false, with no mutation. */
bool huntmob_virtual_mpe_external_write(HuntMobVirtualMPE *mpe, unsigned region,
                                        size_t offset, const uint8_t *input, size_t length);
#ifdef HUNTMOB_VIRTUAL_MPE_TESTING
/* Public-fixture test-only ABI, never present in engine builds. No key getter. */
bool huntmob_virtual_mpe_test_record(HuntMobVirtualMPE *, unsigned, size_t,
                                    uint8_t ciphertext[64], uint8_t tag[16], uint64_t *generation);
bool huntmob_virtual_mpe_test_replace(HuntMobVirtualMPE *, unsigned, size_t,
                                     const uint8_t ciphertext[64], const uint8_t tag[16], uint64_t generation);
bool huntmob_virtual_mpe_test_counter(HuntMobVirtualMPE *, uint64_t generation);
#endif
#endif
