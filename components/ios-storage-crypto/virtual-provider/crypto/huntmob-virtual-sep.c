/* SPDX-License-Identifier: GPL-2.0-or-later */
/* HuntMob VirtualSEP v1 is a documented virtual identity, NOT Apple's KDF.
 * The owning machine must opt in and provide a protected per-VM root.
 * No guest-visible getter, derived-key secret substitution or fallback.
 */
#include "qemu/osdep.h"
#include "qemu/thread.h"
#include "qemu/bswap.h"
#include "crypto/cipher.h"
#include "crypto/hmac.h"
#include "crypto/secret.h"
#include "crypto/apple-ans-wrapped.h"
#include "crypto/huntmob-virtual-sep.h"

typedef struct VirtualBank {
    uint8_t input[2][32];
    uint8_t key[2][32];
    bool programmed[2];
    bool derived[2];
    unsigned latched;
    bool ready;
} VirtualBank;

struct HuntMobVirtualSEP {
    QemuMutex lock;
    uint8_t root[32];
    uint8_t vm_id[16];
    VirtualBank bank[2];
    uint64_t epoch;
    bool exhausted;
};

static void erase(void *buffer, size_t length)
{
    volatile uint8_t *bytes = buffer;
    while (length--) {
        *bytes++ = 0;
    }
}

static bool failure(Error **errp)
{
    error_setg(errp, "Virtual SEP v1 operation unavailable or incoherent");
    return false;
}

static bool advance_locked(HuntMobVirtualSEP *provider)
{
    if (provider->exhausted || provider->epoch == UINT64_MAX) {
        erase(provider->bank, sizeof(provider->bank));
        provider->exhausted = true;
        return false;
    }
    provider->epoch++;
    return true;
}

/* SP800-108 counter-mode HMAC-SHA256, one 256-bit block, r=32:
 * HMAC(K, BE32(1) || ASCII Label || 00 || Context || BE32(256)).
 * Prefix/labels/context are public; root-derived material is never logged.
 */
static bool kdf(const uint8_t root[32], const char *label,
                 const uint8_t *context, size_t context_length,
                 uint8_t output[32], Error **errp)
{
    uint8_t one[4], bits[4], separator = 0;
    uint8_t candidate[32] = { 0 };
    uint8_t *result = candidate;
    size_t result_length = sizeof(candidate);
    struct iovec input[5] = {
        { .iov_base = one, .iov_len = sizeof(one) },
        { .iov_base = (void *)label, .iov_len = strlen(label) },
        { .iov_base = &separator, .iov_len = 1 },
        { .iov_base = (void *)context, .iov_len = context_length },
        { .iov_base = bits, .iov_len = sizeof(bits) },
    };
    QCryptoHmac *hmac;
    bool valid;
    stl_be_p(one, 1);
    stl_be_p(bits, 256);
    hmac = qcrypto_hmac_new(QCRYPTO_HASH_ALGO_SHA256, root, 32, errp);
    if (!hmac) {
        return false;
    }
    valid = qcrypto_hmac_bytesv(hmac, input, G_N_ELEMENTS(input), &result,
                                &result_length, errp) == 0;
    if (valid) {
        memcpy(output, candidate, sizeof(candidate));
    }
    /* The accompanying Nettle-HMAC erasure patch is required. */
    qcrypto_hmac_free(hmac);
    erase(candidate, sizeof(candidate));
    return valid;
}

static bool cbc(const uint8_t key[32], const uint8_t iv[16], bool encrypt,
                 const uint8_t *input, uint8_t *output, size_t length,
                 Error **errp)
{
    QCryptoCipher *cipher = qcrypto_cipher_new(QCRYPTO_CIPHER_ALGO_AES_256,
                                              QCRYPTO_CIPHER_MODE_CBC,
                                              key, 32, errp);
    bool valid = false;
    if (!cipher) {
        return false;
    }
    if (qcrypto_cipher_setiv(cipher, iv, 16, errp) == 0) {
        valid = (encrypt ? qcrypto_cipher_encrypt(cipher, input, output, length, errp)
                         : qcrypto_cipher_decrypt(cipher, input, output, length, errp)) == 0;
    }
    qcrypto_cipher_free(cipher);
    return valid;
}

HuntMobVirtualSEP *huntmob_virtual_sep_new(const char *root_secret_id,
                                         const uint8_t vm_id[16], Error **errp)
{
    uint8_t *root = NULL;
    size_t length = 0;
    Error *local = NULL;
    HuntMobVirtualSEP *provider = NULL;
    if (!root_secret_id || !vm_id ||
        !qcrypto_hmac_supports(QCRYPTO_HASH_ALGO_SHA256) ||
        qcrypto_secret_lookup(root_secret_id, &root, &length, &local) < 0 ||
        length != 32) {
        failure(errp);
        goto cleanup;
    }
    provider = g_new0(HuntMobVirtualSEP, 1);
    qemu_mutex_init(&provider->lock);
    memcpy(provider->root, root, 32);
    memcpy(provider->vm_id, vm_id, 16);
    provider->epoch = 1;
cleanup:
    if (root) {
        erase(root, length);
        g_free(root);
    }
    error_free(local);
    return provider;
}

void huntmob_virtual_sep_free(HuntMobVirtualSEP *provider)
{
    if (provider) {
        /* Owner has stopped/joined every borrowing device/thread. */
        qemu_mutex_destroy(&provider->lock);
        erase(provider, sizeof(*provider));
        g_free(provider);
    }
}

bool huntmob_virtual_sep_program(HuntMobVirtualSEP *provider, unsigned slot,
                                 const uint8_t input[32], Error **errp)
{
    bool valid;
    unsigned bank = slot & 1, role = slot >> 1;
    VirtualBank *state;
    if (!provider || slot > 3 || !input) {
        return failure(errp);
    }
    qemu_mutex_lock(&provider->lock);
    state = &provider->bank[bank];
    valid = advance_locked(provider);
    if (!role) {
        erase(state, sizeof(*state));
    } else {
        erase(state->key[1], sizeof(state->key[1]));
        state->programmed[1] = false;
        state->derived[1] = false;
        state->ready = false;
        state->latched = 0;
    }
    valid = valid && ldl_le_p(input) == (role ? 0x6175746bU : 0x7772616bU) &&
            (!role || (state->derived[0] &&
                       !memcmp(state->input[0] + 4, input + 4, 28)));
    if (valid) {
        memcpy(state->input[role], input, 32);
        state->programmed[role] = true;
    } else {
        erase(state, sizeof(*state));
    }
    qemu_mutex_unlock(&provider->lock);
    return valid || failure(errp);
}

bool huntmob_virtual_sep_derive(HuntMobVirtualSEP *provider, uint32_t syncword,
                                Error **errp)
{
    uint8_t root[32] = { 0 }, context[45] = { 0 }, candidate[32] = { 0 };
    uint64_t epoch;
    unsigned slot, bank, role;
    bool valid;
    VirtualBank *state;
    if (!provider) {
        return failure(errp);
    }
    switch (syncword) {
    case 0x205: slot = 0; break;
    case 0x245: slot = 1; break;
    case 0x204: slot = 2; break;
    case 0x244: slot = 3; break;
    default: return failure(errp);
    }
    bank = slot & 1;
    role = slot >> 1;
    qemu_mutex_lock(&provider->lock);
    state = &provider->bank[bank];
    valid = !provider->exhausted && state->programmed[role];
    epoch = provider->epoch;
    if (valid) {
        memcpy(root, provider->root, 32);
        memcpy(context, provider->vm_id, 16);
        context[16] = bank;
        memcpy(context + 17, state->input[role] + 4, 28);
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
        goto cleanup;
    }
    if (!kdf(root, role ? "HuntMob.VirtualSEP.v1/inline-auth" :
                         "HuntMob.VirtualSEP.v1/inline-wrap",
              context, sizeof(context), candidate, errp)) {
        valid = false;
        goto cleanup;
    }
    qemu_mutex_lock(&provider->lock);
    valid = !provider->exhausted && provider->epoch == epoch &&
            state->programmed[role];
    if (valid) {
        memcpy(state->key[role], candidate, 32);
        state->derived[role] = true;
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
    }
cleanup:
    erase(root, sizeof(root));
    erase(candidate, sizeof(candidate));
    erase(context, sizeof(context));
    return valid;
}

bool huntmob_virtual_sep_latch(HuntMobVirtualSEP *provider, unsigned role,
                               unsigned bank, Error **errp)
{
    bool valid;
    VirtualBank *state;
    if (!provider || bank > 1 || role < 4 || role > 6) {
        return failure(errp);
    }
    qemu_mutex_lock(&provider->lock);
    state = &provider->bank[bank];
    valid = !provider->exhausted && state->derived[0] && state->derived[1] &&
            !memcmp(state->input[0] + 4, state->input[1] + 4, 28);
    if (valid && role != 6) {
        state->latched |= 1U << (role - 4);
        state->ready = state->latched == 3;
    } else if (!valid) {
        erase(state, sizeof(*state));
        advance_locked(provider);
    }
    qemu_mutex_unlock(&provider->lock);
    return valid || failure(errp);
}

bool huntmob_virtual_sep_slot_crypt(HuntMobVirtualSEP *provider, unsigned slot,
                                   bool encrypt, const uint8_t iv[16],
                                   const uint8_t *input, uint8_t *output,
                                   size_t length, Error **errp)
{
    uint8_t key[32] = { 0 }, candidate[32] = { 0 };
    uint64_t epoch;
    bool valid;
    VirtualBank *state;
    unsigned bank = slot & 1, role = slot >> 1;
    if (!provider || slot > 3 || !iv || !input || !output ||
        (length != 16 && length != 32)) {
        return failure(errp);
    }
    qemu_mutex_lock(&provider->lock);
    state = &provider->bank[bank];
    valid = !provider->exhausted && state->derived[role];
    epoch = provider->epoch;
    if (valid) {
        memcpy(key, state->key[role], 32);
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
        goto cleanup;
    }
    if (!cbc(key, iv, encrypt, input, candidate, length, errp)) {
        valid = false;
        goto cleanup;
    }
    qemu_mutex_lock(&provider->lock);
    valid = !provider->exhausted && provider->epoch == epoch && state->derived[role];
    if (valid) {
        memcpy(output, candidate, length);
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
    }
cleanup:
    erase(key, sizeof(key));
    erase(candidate, sizeof(candidate));
    return valid;
}

bool huntmob_virtual_sep_uid_transform(HuntMobVirtualSEP *provider,
                                      unsigned uid_index, uint32_t seed_bits,
                                      uint32_t iterations,
                                      const uint8_t input[32],
                                      uint8_t output[32], Error **errp)
{
    uint8_t root[32] = { 0 }, context[20] = { 0 }, key[32] = { 0 };
    uint8_t candidate[32] = { 0 }, iv[16] = { 0 };
    QCryptoCipher *cipher = NULL;
    uint64_t epoch;
    bool valid;
    if (!provider || uid_index > 1 || iterations > 65536 || !input || !output) {
        return failure(errp);
    }
    qemu_mutex_lock(&provider->lock);
    valid = !provider->exhausted;
    epoch = provider->epoch;
    if (valid) {
        memcpy(root, provider->root, 32);
        memcpy(context, provider->vm_id, 16);
        stl_be_p(context + 16, seed_bits);
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
        goto cleanup;
    }
    if (!kdf(root, uid_index ? "HuntMob.VirtualSEP.v1/UID1" :
                              "HuntMob.VirtualSEP.v1/UID0",
              context, sizeof(context), key, errp)) {
        valid = false;
        goto cleanup;
    }
    cipher = qcrypto_cipher_new(QCRYPTO_CIPHER_ALGO_AES_256,
                                QCRYPTO_CIPHER_MODE_CBC, key, 32, errp);
    if (!cipher || qcrypto_cipher_setiv(cipher, iv, 16, errp) < 0) {
        valid = false;
        goto cleanup;
    }
    memcpy(candidate, input, 32);
    for (uint32_t count = iterations ? iterations : 1; count; count--) {
        if (qcrypto_cipher_encrypt(cipher, candidate, candidate, 32, errp) < 0) {
            valid = false;
            goto cleanup;
        }
    }
    qemu_mutex_lock(&provider->lock);
    valid = !provider->exhausted && provider->epoch == epoch;
    if (valid) {
        memcpy(output, candidate, 32);
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
    }
cleanup:
    qcrypto_cipher_free(cipher);
    erase(root, sizeof(root));
    erase(context, sizeof(context));
    erase(key, sizeof(key));
    erase(candidate, sizeof(candidate));
    erase(iv, sizeof(iv));
    return valid;
}

bool huntmob_virtual_sep_unwrap(HuntMobVirtualSEP *provider,
                                const uint8_t envelope[64], uint8_t raw[32],
                                uint64_t *epoch, Error **errp)
{
    uint8_t pair[64] = { 0 }, candidate[32] = { 0 };
    uint64_t snapshot;
    bool valid;
    if (!provider || !envelope || !raw || !epoch) {
        return failure(errp);
    }
    qemu_mutex_lock(&provider->lock);
    valid = !provider->exhausted && provider->bank[0].ready;
    snapshot = provider->epoch;
    if (valid) {
        memcpy(pair, provider->bank[0].key[0], 32);
        memcpy(pair + 32, provider->bank[0].key[1], 32);
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
        goto cleanup;
    }
    if (huntmob_wrapped_reference_unwrap(pair, pair + 32, envelope, 64,
                                        candidate, errp) < 0) {
        valid = false;
        goto cleanup;
    }
    qemu_mutex_lock(&provider->lock);
    valid = !provider->exhausted && provider->bank[0].ready &&
            provider->epoch == snapshot;
    if (valid) {
        memcpy(raw, candidate, 32);
        *epoch = snapshot;
    }
    qemu_mutex_unlock(&provider->lock);
    if (!valid) {
        failure(errp);
    }
cleanup:
    erase(pair, sizeof(pair));
    erase(candidate, sizeof(candidate));
    return valid;
}

uint64_t huntmob_virtual_sep_get_epoch(HuntMobVirtualSEP *provider)
{
    uint64_t epoch = 0;
    if (provider) {
        qemu_mutex_lock(&provider->lock);
        epoch = provider->epoch;
        qemu_mutex_unlock(&provider->lock);
    }
    return epoch;
}

bool huntmob_virtual_sep_epoch_current(HuntMobVirtualSEP *provider, uint64_t epoch)
{
    bool valid = false;
    if (provider) {
        qemu_mutex_lock(&provider->lock);
        valid = !provider->exhausted && provider->bank[0].ready &&
                provider->epoch == epoch;
        qemu_mutex_unlock(&provider->lock);
    }
    return valid;
}

bool huntmob_virtual_sep_is_ready(HuntMobVirtualSEP *provider)
{
    bool ready = false;
    if (provider) {
        qemu_mutex_lock(&provider->lock);
        ready = !provider->exhausted && provider->bank[0].ready;
        qemu_mutex_unlock(&provider->lock);
    }
    return ready;
}

void huntmob_virtual_sep_revoke(HuntMobVirtualSEP *provider)
{
    if (provider) {
        qemu_mutex_lock(&provider->lock);
        erase(provider->bank, sizeof(provider->bank));
        advance_locked(provider);
        qemu_mutex_unlock(&provider->lock);
    }
}
