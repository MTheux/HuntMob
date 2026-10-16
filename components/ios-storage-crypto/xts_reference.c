/*
 * AUTHORIZED TESTING ONLY — ISOLATED LAB
 * Purpose: standard AES-128-XTS data transformation for synthetic fixtures.
 * Does not implement Apple wrapped keys, SEP handoff, or a guest device.
 */
#include "qemu/osdep.h"
#include "crypto/cipher.h"
#include "xts_reference.h"

#define UNIT_BYTES 4096u
#define REQUEST_LIMIT (1024u * 1024u)

static void clear_temporary(uint8_t *buffer, size_t length)
{
    volatile uint8_t *bytes = buffer;
    while (length--) {
        *bytes++ = 0;
    }
}

static bool valid_key(const uint8_t *key)
{
    unsigned different = 0;
    if (!key) {
        return false;
    }
    for (size_t i = 0; i < 16; i++) {
        different |= key[i] ^ key[i + 16];
    }
    return different != 0;
}

static int transform(QCryptoCipher *cipher, const uint8_t tweak[16],
                     const uint8_t *input, uint8_t *output, size_t length,
                     bool encrypt, Error **errp)
{
    if (qcrypto_cipher_setiv(cipher, tweak, 16, errp) < 0) {
        return -1;
    }
    return encrypt ? qcrypto_cipher_encrypt(cipher, input, output, length, errp)
                   : qcrypto_cipher_decrypt(cipher, input, output, length, errp);
}

int huntmob_xts128_unit(const uint8_t key[32], const uint8_t tweak[16],
                       const uint8_t *input, uint8_t *output, size_t length,
                       bool encrypt, Error **errp)
{
    QCryptoCipher *cipher;
    uint8_t *temporary;
    int result;
    if (!valid_key(key) || !tweak || !input || !output || length < 16 ||
        length > UNIT_BYTES || length % 16) {
        error_setg(errp, "Invalid standard XTS unit parameters");
        return -1;
    }
    cipher = qcrypto_cipher_new(QCRYPTO_CIPHER_ALGO_AES_128,
                                QCRYPTO_CIPHER_MODE_XTS, key, 32, errp);
    if (!cipher) {
        return -1;
    }
    temporary = g_malloc(length);
    result = transform(cipher, tweak, input, temporary, length, encrypt, errp);
    if (result == 0) {
        memcpy(output, temporary, length);
    }
    clear_temporary(temporary, length);
    g_free(temporary);
    qcrypto_cipher_free(cipher);
    return result;
}

int huntmob_xts128_units(const uint8_t key[32], uint64_t first_unit,
                        const uint8_t *input, uint8_t *output, size_t length,
                        bool encrypt, Error **errp)
{
    QCryptoCipher *cipher;
    uint8_t *temporary;
    size_t count;
    int result = 0;
    if (!valid_key(key) || !input || !output || !length ||
        length > REQUEST_LIMIT || length % UNIT_BYTES) {
        error_setg(errp, "Invalid fixed-unit XTS request parameters");
        return -1;
    }
    count = length / UNIT_BYTES;
    if (count - 1 > UINT64_MAX - first_unit) {
        error_setg(errp, "XTS data-unit sequence overflow");
        return -1;
    }
    cipher = qcrypto_cipher_new(QCRYPTO_CIPHER_ALGO_AES_128,
                                QCRYPTO_CIPHER_MODE_XTS, key, 32, errp);
    if (!cipher) {
        return -1;
    }
    temporary = g_malloc(length);
    for (size_t index = 0; index < count; index++) {
        uint64_t unit = first_unit + index;
        uint8_t tweak[16] = { 0 };
        /* Explicit IEEE data-unit sequence encoding, independent of host. */
        for (size_t byte = 0; byte < 8; byte++) {
            tweak[byte] = (uint8_t)(unit >> (byte * 8));
        }
        result = transform(cipher, tweak, input + index * UNIT_BYTES,
                           temporary + index * UNIT_BYTES, UNIT_BYTES,
                           encrypt, errp);
        if (result < 0) {
            break;
        }
    }
    if (result == 0) {
        memcpy(output, temporary, length);
    }
    clear_temporary(temporary, length);
    g_free(temporary);
    qcrypto_cipher_free(cipher);
    return result;
}
