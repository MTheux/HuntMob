/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Own authenticated virtual DRAM model. NOT an Apple hardware cipher/KDF. */
#ifdef HUNTMOB_VIRTUAL_MPE_STANDALONE
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <pthread.h>
typedef pthread_mutex_t MPELock;
#define lock_init(x) pthread_mutex_init(x, NULL)
#define lock_take(x) pthread_mutex_lock(x)
#define lock_drop(x) pthread_mutex_unlock(x)
#define lock_destroy(x) pthread_mutex_destroy(x)
#define MPE_NETTLE 1
#else
#include "qemu/osdep.h"
#include "qemu/thread.h"
typedef QemuMutex MPELock;
#define lock_init(x) qemu_mutex_init(x)
#define lock_take(x) qemu_mutex_lock(x)
#define lock_drop(x) qemu_mutex_unlock(x)
#define lock_destroy(x) qemu_mutex_destroy(x)
#ifdef CONFIG_NETTLE
#define MPE_NETTLE 1
#endif
#endif
#include "crypto/huntmob-virtual-mpe.h"
#ifdef MPE_NETTLE
#include <nettle/gcm.h>
#include <nettle/hmac.h>
#include <nettle/version.h>
#endif
#define CONTEXT_SIZE 76u
#define GENERATION_LIMIT UINT32_MAX
#ifdef MPE_NETTLE
static const char kdf_label[] = "HuntMob.OwnMPE.v1/region";
static const char aad_label[] = "HuntMob.OwnMPE.v1/line";
#endif

typedef struct MPERecord {
    uint8_t ciphertext[64];
    uint8_t tag[16];
    uint64_t generation;
} MPERecord;
typedef struct MPERegion {
    uint8_t *cache;
    size_t capacity, length, lines;
    uint64_t base;
    bool configured, active, faulted;
    MPERecord *records;
    uint64_t *expected;
    uint8_t context[CONTEXT_SIZE];
#ifdef MPE_NETTLE
    struct gcm_aes256_ctx cipher;
#endif
} MPERegion;
struct HuntMobVirtualMPE {
    MPELock lock;
    uint8_t vm_id[16], salt[32], input[2][32];
    uint64_t epoch, generation;
    bool staged[2], latched[2], revoked;
    MPERegion region[HUNTMOB_MPE_REGIONS];
};
static void erase(void *buffer, size_t length)
{
    volatile uint8_t *p = buffer;
    while (length--) { *p++ = 0; }
}
#ifdef MPE_NETTLE
static void be32(uint8_t *out, uint32_t value)
{
    for (unsigned i = 0; i < 4; i++) { out[i] = value >> (24 - i * 8); }
}
static void be64(uint8_t *out, uint64_t value)
{
    for (unsigned i = 0; i < 8; i++) { out[i] = value >> (56 - i * 8); }
}
#endif
static bool both_locked(HuntMobVirtualMPE *m)
{
    return !m->revoked && m->latched[0] && m->latched[1];
}
static bool range_ok(size_t maximum, size_t offset, size_t length)
{
    return length && offset <= maximum && length <= maximum - offset;
}
static void region_erase(MPERegion *r)
{
    if (r->cache) { erase(r->cache, r->capacity); }
    if (r->records) { erase(r->records, r->lines * sizeof(*r->records)); free(r->records); }
    if (r->expected) { erase(r->expected, r->lines * sizeof(*r->expected)); free(r->expected); }
    erase(r, sizeof(*r));
}
static void fault_region(MPERegion *r)
{
    r->faulted = true;
    if (r->cache) { erase(r->cache, r->capacity); }
#ifdef MPE_NETTLE
    erase(&r->cipher, sizeof(r->cipher));
#endif
}
static void revoke_locked(HuntMobVirtualMPE *m)
{
    for (unsigned i = 0; i < HUNTMOB_MPE_REGIONS; i++) { region_erase(&m->region[i]); }
    erase(m->input, sizeof(m->input));
    erase(m->salt, sizeof(m->salt));
    erase(m->staged, sizeof(m->staged));
    erase(m->latched, sizeof(m->latched));
    m->generation = 0;
    m->revoked = true;
}
#ifdef MPE_NETTLE
static void make_context(HuntMobVirtualMPE *m, unsigned id, MPERegion *r)
{
    memcpy(r->context, m->vm_id, 16);
    memcpy(r->context + 16, m->salt, 32);
    be64(r->context + 48, m->epoch);
    be32(r->context + 56, id);
    be64(r->context + 60, r->base);
    be64(r->context + 68, r->length);
}
static void derive(HuntMobVirtualMPE *m, MPERegion *r)
{
    struct hmac_sha256_ctx hmac;
    uint8_t root[64], key[32], counter[4], bits[4], separator = 0;
    memcpy(root, m->input, 64);
    be32(counter, 1); be32(bits, 256);
    hmac_sha256_set_key(&hmac, sizeof(root), root);
    hmac_sha256_update(&hmac, sizeof(counter), counter);
    hmac_sha256_update(&hmac, sizeof(kdf_label) - 1, (const uint8_t *)kdf_label);
    hmac_sha256_update(&hmac, 1, &separator);
    hmac_sha256_update(&hmac, sizeof(r->context), r->context);
    hmac_sha256_update(&hmac, sizeof(bits), bits);
#if NETTLE_VERSION_MAJOR >= 4
    hmac_sha256_digest(&hmac, key);
#else
    hmac_sha256_digest(&hmac, sizeof(key), key);
#endif
    gcm_aes256_set_key(&r->cipher, key);
    erase(root, sizeof(root)); erase(key, sizeof(key)); erase(&hmac, sizeof(hmac));
}
static void mpe_line_crypt(MPERegion *r, size_t line, uint64_t generation, bool encrypt,
                  const uint8_t input[64], uint8_t output[64], uint8_t tag[16])
{
    uint8_t nonce[12], aad[128];
    size_t n = sizeof(aad_label) - 1;
    be32(nonce, line); be64(nonce + 4, generation);
    memcpy(aad, aad_label, n); aad[n++] = 0;
    memcpy(aad + n, r->context, sizeof(r->context)); n += sizeof(r->context);
    be32(aad + n, line); n += 4;
    be64(aad + n, generation); n += 8;
    be32(aad + n, HUNTMOB_MPE_LINE_SIZE); n += 4;
    gcm_aes256_set_iv(&r->cipher, sizeof(nonce), nonce);
    gcm_aes256_update(&r->cipher, n, aad);
    if (encrypt) { gcm_aes256_encrypt(&r->cipher, 64, output, input); }
    else { gcm_aes256_decrypt(&r->cipher, 64, output, input); }
#if NETTLE_VERSION_MAJOR >= 4
    gcm_aes256_digest(&r->cipher, tag);
#else
    gcm_aes256_digest(&r->cipher, 16, tag);
#endif
    erase(nonce, sizeof(nonce)); erase(aad, sizeof(aad));
}
static bool decrypt_line(MPERegion *r, size_t index, uint8_t output[64])
{
    MPERecord *record = &r->records[index];
    uint8_t tag[16], difference = 0;
    if (!record->generation || record->generation != r->expected[index]) { fault_region(r); return false; }
    mpe_line_crypt(r, index, record->generation, false, record->ciphertext, output, tag);
    for (unsigned i = 0; i < sizeof(tag); i++) { difference |= tag[i] ^ record->tag[i]; }
    erase(tag, sizeof(tag));
    if (difference) { erase(output, 64); fault_region(r); return false; }
    return true;
}
#endif
HuntMobVirtualMPE *huntmob_virtual_mpe_new(const uint8_t vm_id[16],
                                         const uint8_t salt[32], uint64_t epoch)
{
#ifdef MPE_NETTLE
    HuntMobVirtualMPE *m;
    if (!vm_id || !salt || !epoch) { return NULL; }
    m = calloc(1, sizeof(*m));
    if (!m) { return NULL; }
    lock_init(&m->lock);
    memcpy(m->vm_id, vm_id, 16); memcpy(m->salt, salt, 32); m->epoch = epoch;
    return m;
#else
    (void)vm_id; (void)salt; (void)epoch;
    return NULL;
#endif
}
void huntmob_virtual_mpe_reset(HuntMobVirtualMPE *m)
{
    if (!m) { return; }
    lock_take(&m->lock); revoke_locked(m); lock_drop(&m->lock);
}
void huntmob_virtual_mpe_free(HuntMobVirtualMPE *m)
{
    if (!m) { return; }
    huntmob_virtual_mpe_reset(m); lock_destroy(&m->lock); erase(m, sizeof(*m)); free(m);
}
bool huntmob_virtual_mpe_stage_key(HuntMobVirtualMPE *m, unsigned slot, const uint8_t input[32])
{
    bool valid = false;
    if (!m || slot > 1 || !input) { return false; }
    lock_take(&m->lock);
    if (!m->revoked && !m->staged[slot] && (!slot || m->latched[0])) {
        memcpy(m->input[slot], input, 32); m->staged[slot] = true; valid = true;
    }
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_latch_key(HuntMobVirtualMPE *m, unsigned slot)
{
    bool valid = false;
    if (!m || slot > 1) { return false; }
    lock_take(&m->lock);
    if (!m->revoked && m->staged[slot] && !m->latched[slot] && (!slot || m->latched[0])) {
        m->latched[slot] = true; valid = true;
    }
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_both_latched(HuntMobVirtualMPE *m)
{
    bool result;
    if (!m) { return false; }
    lock_take(&m->lock); result = both_locked(m); lock_drop(&m->lock); return result;
}
bool huntmob_virtual_mpe_regions_bound(HuntMobVirtualMPE *m)
{
    bool result;
    if (!m) { return false; }
    lock_take(&m->lock);
    result = !m->revoked && m->region[0].cache && m->region[1].cache;
    lock_drop(&m->lock); return result;
}
bool huntmob_virtual_mpe_bind_region(HuntMobVirtualMPE *m, unsigned id,
                                     size_t capacity, uint8_t *cache)
{
    bool valid = false;
    uintptr_t start = (uintptr_t)cache;
    if (!m || id >= HUNTMOB_MPE_REGIONS || !cache || !capacity || capacity % 64 ||
        capacity > HUNTMOB_MPE_MAX_REGION || start > UINTPTR_MAX - capacity) { return false; }
    lock_take(&m->lock);
    MPERegion *r = &m->region[id], *other = &m->region[id ^ 1];
    uintptr_t other_start = (uintptr_t)other->cache;
    if (!m->revoked && !r->cache && (!other->cache ||
        start + capacity <= other_start || other_start + other->capacity <= start)) {
        r->cache = cache; r->capacity = capacity; valid = true;
    }
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_configure_region(HuntMobVirtualMPE *m, unsigned id,
                                          uint64_t base, size_t length)
{
    bool valid = false;
    if (!m || id >= HUNTMOB_MPE_REGIONS || !length || length % 64 || base % 64 ||
        base > UINT64_MAX - length) { return false; }
    lock_take(&m->lock);
    MPERegion *r = &m->region[id], *other = &m->region[id ^ 1];
    if (both_locked(m) && r->cache && !r->configured && length <= r->capacity &&
        (!other->configured || base + length <= other->base || other->base + other->length <= base)) {
        r->base = base; r->length = length; r->lines = length / 64;
        r->configured = true; valid = true;
    }
    lock_drop(&m->lock); return valid;
}
size_t huntmob_virtual_mpe_region_length(HuntMobVirtualMPE *m, unsigned id)
{
    size_t length;
    if (!m || id >= HUNTMOB_MPE_REGIONS) { return 0; }
    lock_take(&m->lock); length = m->revoked ? 0 : m->region[id].length;
    lock_drop(&m->lock); return length;
}
bool huntmob_virtual_mpe_is_configured(HuntMobVirtualMPE *m, unsigned id)
{
    bool valid;
    if (!m || id >= HUNTMOB_MPE_REGIONS) { return false; }
    lock_take(&m->lock); valid = !m->revoked && m->region[id].configured;
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_is_active(HuntMobVirtualMPE *m, unsigned id)
{
    bool valid;
    if (!m || id >= HUNTMOB_MPE_REGIONS) { return false; }
    lock_take(&m->lock); valid = !m->revoked && m->region[id].active && !m->region[id].faulted;
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_initialize_region(HuntMobVirtualMPE *m, unsigned id)
{
    bool valid = false;
    if (!m || id >= HUNTMOB_MPE_REGIONS) { return false; }
    lock_take(&m->lock);
#ifdef MPE_NETTLE
    MPERegion *r = &m->region[id];
    if (both_locked(m) && r->configured && !r->active && !r->faulted && !r->records &&
        r->lines <= GENERATION_LIMIT - m->generation) {
        r->records = calloc(r->lines, sizeof(*r->records));
        r->expected = calloc(r->lines, sizeof(*r->expected));
        if (!r->records || !r->expected) {
            free(r->records); free(r->expected); r->records = NULL; r->expected = NULL;
        } else {
            make_context(m, id, r); derive(m, r);
            for (size_t i = 0; i < r->lines; i++) {
                MPERecord *record = &r->records[i];
                record->generation = ++m->generation; r->expected[i] = record->generation;
                mpe_line_crypt(r, i, record->generation, true, r->cache + i * 64,
                      record->ciphertext, record->tag);
            }
            erase(r->cache + r->length, r->capacity - r->length);
            r->active = true; valid = true;
        }
    }
#endif
    lock_drop(&m->lock); return valid;
}
/* Caller locks. A failed authentication never copies speculative plaintext. */
static bool read_locked(HuntMobVirtualMPE *m, unsigned id, size_t offset,
                         uint8_t *output, size_t length, bool external)
{
    MPERegion *r = &m->region[id];
    if (m->revoked || r->faulted || !r->cache) { return false; }
    if (!range_ok(r->configured ? r->length : r->capacity, offset, length)) {
        if (r->active) { fault_region(r); }
        return false;
    }
    if (!r->active) {
        if (external) { return false; }
        memcpy(output, r->cache + offset, length); return true;
    }
#ifdef MPE_NETTLE
    if (length > HUNTMOB_MPE_MAX_TRANSFER) { fault_region(r); return false; }
    size_t first = offset / 64, last = (offset + length - 1) / 64;
    size_t lines = last - first + 1;
    uint8_t *plain = malloc(lines * 64);
    if (!plain) { fault_region(r); return false; }
    bool valid = true;
    for (size_t i = 0; i < lines; i++) {
        if (!decrypt_line(r, first + i, plain + i * 64)) { valid = false; break; }
    }
    if (valid) {
        if (!external) { memcpy(output, plain + offset % 64, length); }
        else {
            for (size_t done = 0; done < length;) {
                size_t at = offset + done, take = 64 - at % 64;
                if (take > length - done) { take = length - done; }
                memcpy(output + done, r->records[at / 64].ciphertext + at % 64, take); done += take;
            }
        }
    }
    erase(plain, lines * 64); free(plain); return valid;
#else
    return false;
#endif
}
static bool read_api(HuntMobVirtualMPE *m, unsigned id, size_t offset,
                       uint8_t *output, size_t length, bool external)
{
    bool valid;
    if (!m || id >= HUNTMOB_MPE_REGIONS || !output) { return false; }
    lock_take(&m->lock); valid = read_locked(m, id, offset, output, length, external);
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_private_read(HuntMobVirtualMPE *m, unsigned id,
                                      size_t offset, uint8_t *output, size_t length)
{
    return read_api(m, id, offset, output, length, false);
}
bool huntmob_virtual_mpe_external_read(HuntMobVirtualMPE *m, unsigned id,
                                       size_t offset, uint8_t *output, size_t length)
{
    return read_api(m, id, offset, output, length, true);
}
bool huntmob_virtual_mpe_private_write(HuntMobVirtualMPE *m, unsigned id,
                                       size_t offset, const uint8_t *input, size_t length)
{
    bool valid = false;
    if (!m || id >= HUNTMOB_MPE_REGIONS || !input) { return false; }
    lock_take(&m->lock);
    MPERegion *r = &m->region[id];
    if (m->revoked || r->faulted || !r->cache) { goto done; }
    if (!range_ok(r->configured ? r->length : r->capacity, offset, length)) {
        if (r->active) { fault_region(r); }
        goto done;
    }
    if (!r->active) { memmove(r->cache + offset, input, length); valid = true; goto done; }
#ifdef MPE_NETTLE
    if (length > HUNTMOB_MPE_MAX_TRANSFER) { fault_region(r); goto done; }
    size_t first = offset / 64, last = (offset + length - 1) / 64;
    size_t lines = last - first + 1;
    if (lines > GENERATION_LIMIT - m->generation) { fault_region(r); goto done; }
    uint8_t *plain = malloc(lines * 64);
    MPERecord *candidate = malloc(lines * sizeof(*candidate));
    if (!plain || !candidate) { free(plain); free(candidate); fault_region(r); goto done; }
    for (size_t i = 0; i < lines; i++) {
        if (!decrypt_line(r, first + i, plain + i * 64)) { goto failed; }
    }
    memmove(plain + offset % 64, input, length);
    for (size_t i = 0; i < lines; i++) {
        candidate[i].generation = m->generation + i + 1;
        mpe_line_crypt(r, first + i, candidate[i].generation, true, plain + i * 64,
              candidate[i].ciphertext, candidate[i].tag);
    }
    /* All possible failure/validation points precede this publication. */
    for (size_t i = 0; i < lines; i++) {
        r->records[first + i] = candidate[i];
        r->expected[first + i] = candidate[i].generation;
    }
    m->generation += lines;
    memcpy(r->cache + first * 64, plain, lines * 64); valid = true;
failed:
    erase(plain, lines * 64); erase(candidate, lines * sizeof(*candidate)); free(plain); free(candidate);
#endif
done:
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_external_write(HuntMobVirtualMPE *m, unsigned id,
                                        size_t offset, const uint8_t *input, size_t length)
{
    (void)m; (void)id; (void)offset; (void)input; (void)length;
    return false;
}
#ifdef HUNTMOB_VIRTUAL_MPE_TESTING
bool huntmob_virtual_mpe_test_record(HuntMobVirtualMPE *m, unsigned id, size_t line,
                                    uint8_t c[64], uint8_t tag[16], uint64_t *generation)
{
    bool valid = false;
    if (!m || id >= 2 || !c || !tag || !generation) { return false; }
    lock_take(&m->lock);
    MPERegion *r = &m->region[id];
    if (!m->revoked && r->active && line < r->lines) {
        memcpy(c, r->records[line].ciphertext, 64); memcpy(tag, r->records[line].tag, 16);
        *generation = r->records[line].generation; valid = true;
    }
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_test_replace(HuntMobVirtualMPE *m, unsigned id, size_t line,
                                     const uint8_t c[64], const uint8_t tag[16], uint64_t generation)
{
    bool valid = false;
    if (!m || id >= 2 || !c || !tag) { return false; }
    lock_take(&m->lock);
    MPERegion *r = &m->region[id];
    if (!m->revoked && r->active && line < r->lines) {
        memcpy(r->records[line].ciphertext, c, 64); memcpy(r->records[line].tag, tag, 16);
        r->records[line].generation = generation; valid = true;
    }
    lock_drop(&m->lock); return valid;
}
bool huntmob_virtual_mpe_test_counter(HuntMobVirtualMPE *m, uint64_t value)
{
    if (!m || value > GENERATION_LIMIT) { return false; }
    lock_take(&m->lock);
    bool valid = !m->revoked && value >= m->generation;
    if (valid) { m->generation = value; }
    lock_drop(&m->lock); return valid;
}
#endif
