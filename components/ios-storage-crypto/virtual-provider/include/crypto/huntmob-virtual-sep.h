/* SPDX-License-Identifier: GPL-2.0-or-later */
/* HuntMob VirtualSEP v1: own virtual identity, NOT Apple SEP reproduction. */
#ifndef QCRYPTO_HUNTMOB_VIRTUAL_SEP_H
#define QCRYPTO_HUNTMOB_VIRTUAL_SEP_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "qapi/error.h"

typedef struct HuntMobVirtualSEP HuntMobVirtualSEP;

/* Machine owns the pointer; SEP/NVMe borrow it. Stop all users before free.
 * Root secret is exactly 32 bytes. Missing/wrong-size root fails closed.
 * No implicit root creation, derived-key host secret or fallback exists.
 */
HuntMobVirtualSEP *huntmob_virtual_sep_new(const char *root_secret_id,
                                         const uint8_t vm_id[16], Error **errp);
void huntmob_virtual_sep_free(HuntMobVirtualSEP *provider);

/* Slots: 0/1 wrapping bank0/1; 2/3 authentication bank0/1. Input is LE32
 * 0x7772616b (wrapping) or 0x6175746b (authentication), then public context28.
 * Wrapping program starts a new candidate. Authentication must follow a
 * derived wrapping slot and match its context. No key bytes are programmed.
 */
bool huntmob_virtual_sep_program(HuntMobVirtualSEP *provider, unsigned slot,
                                 const uint8_t input[32], Error **errp);
/* Exact commit words: 205/245 wrapping bank0/1, 204/244 auth bank0/1. */
bool huntmob_virtual_sep_derive(HuntMobVirtualSEP *provider, uint32_t syncword,
                                Error **errp);
/* Roles4/5 latch derived wrap/auth; coherent pair publishes after both.
 * Role6 validates the same pair only, without inventing another subkey.
 */
bool huntmob_virtual_sep_latch(HuntMobVirtualSEP *provider, unsigned role,
                               unsigned bank, Error **errp);
/* Derived slot cipher operation; keys remain private. Accepts 16/32 bytes,
 * caller IV, AES256-CBC. Does not require KEY latches, only derived slot.
 */
bool huntmob_virtual_sep_slot_crypt(HuntMobVirtualSEP *provider, unsigned slot,
                                   bool encrypt, const uint8_t iv[16],
                                   const uint8_t *input, uint8_t *output,
                                   size_t length, Error **errp);

/* Virtual identity UID KDF, not Apple's algorithm:
 * SP800-108 counter HMAC256, labels HuntMob.VirtualSEP.v1/UID0 or /UID1;
 * context=VMID16||BE32(seed_bits). Encrypt32 with AES256-CBC initial zeroIV,
 * then re-encrypt same32 while carrying CBC IV. count0=>1, cap65536.
 * The caller handles disabled/unseeded hardware status and register clearing.
 */
bool huntmob_virtual_sep_uid_transform(HuntMobVirtualSEP *provider,
                                      unsigned uid_index, uint32_t seed_bits,
                                      uint32_t iterations,
                                      const uint8_t input[32],
                                      uint8_t output[32], Error **errp);

/* Only canonical envelope flags1b140, bank0 are currently supported.
 * Authenticates before raw32 output; returns a generation snapshot for later
 * NVMe epoch checks. No provider lock is held across bus/DMA/AIO/callbacks.
 */
bool huntmob_virtual_sep_unwrap(HuntMobVirtualSEP *provider,
                                const uint8_t envelope[64], uint8_t raw[32],
                                uint64_t *epoch, Error **errp);
uint64_t huntmob_virtual_sep_get_epoch(HuntMobVirtualSEP *provider);
bool huntmob_virtual_sep_is_ready(HuntMobVirtualSEP *provider);
bool huntmob_virtual_sep_epoch_current(HuntMobVirtualSEP *provider, uint64_t epoch);
/* Revoke/reset erase all derived/staged keys and retire leases. VM root
 * remains for fresh deterministic derivations until machine teardown/free.
 */
void huntmob_virtual_sep_revoke(HuntMobVirtualSEP *provider);
#endif
