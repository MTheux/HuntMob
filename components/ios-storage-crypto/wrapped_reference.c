/*
 * AUTHORIZED TESTING ONLY — ISOLATED LAB
 * Pinned AESSEP firmware framing + the current virtual model's AES semantics.
 * Does not implement Apple hardware key derivation or a SEP-to-ANS bridge.
 */
#include "qemu/osdep.h"
#include "crypto/cipher.h"
#include "wrapped_reference.h"

static void erase_temporary(void *buffer, size_t length)
{
    volatile uint8_t *bytes = buffer;
    while (length--) {
        *bytes++ = 0;
    }
}

bool huntmob_wrapped_reference_flags_supported(uint32_t flags)
{
    return flags == HUNTMOB_WRAPPED_REFERENCE_FLAGS ||
           flags == HUNTMOB_WRAPPED_REFERENCE_FLAGS_NATIVE;
}

static uint32_t read_le32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
           (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

static void write_le32(uint8_t *bytes, uint32_t value)
{
    for (size_t i = 0; i < 4; i++) {
        bytes[i] = (uint8_t)(value >> (8 * i));
    }
}

static int aes256_cbc(const uint8_t key[32], const uint8_t *input,
                      uint8_t *output, size_t length, bool encrypt, Error **errp)
{
    uint8_t iv[16] = { 0 };
    QCryptoCipher *cipher = qcrypto_cipher_new(QCRYPTO_CIPHER_ALGO_AES_256,
                                              QCRYPTO_CIPHER_MODE_CBC,
                                              key, 32, errp);
    int result;
    if (!cipher) {
        return -1;
    }
    result = qcrypto_cipher_setiv(cipher, iv, sizeof(iv), errp);
    if (result == 0) {
        result = encrypt ? qcrypto_cipher_encrypt(cipher, input, output,
                                                  length, errp)
                         : qcrypto_cipher_decrypt(cipher, input, output,
                                                  length, errp);
    }
    /* Requires the tested QCrypto/Nettle expanded-context erasure patch. */
    qcrypto_cipher_free(cipher);
    erase_temporary(iv, sizeof(iv));
    return result;
}

static int compute_auth(const uint8_t auth_key[32], const uint8_t encrypted[32],
                        uint32_t flags, uint8_t tag[16], Error **errp)
{
    uint8_t message[48] = { 0 };
    uint8_t encrypted_message[48] = { 0 };
    int result;
    memcpy(message, encrypted, 32);
    write_le32(message + 44, flags);
    result = aes256_cbc(auth_key, message, encrypted_message,
                       sizeof(message), true, errp);
    if (result == 0) {
        memcpy(tag, encrypted_message + 32, 16);
    }
    erase_temporary(message, sizeof(message));
    erase_temporary(encrypted_message, sizeof(encrypted_message));
    return result;
}

int huntmob_wrapped_reference_wrap(const uint8_t wrap_key[32],
                                  const uint8_t auth_key[32],
                                  const uint8_t raw[32], uint32_t flags,
                                  uint8_t output[64], Error **errp)
{
    uint8_t candidate[64] = { 0 };
    int result = -1;
    if (!wrap_key || !auth_key || !raw || !output ||
        !huntmob_wrapped_reference_flags_supported(flags)) {
        error_setg(errp, "Unsupported virtual SEP envelope parameters");
        return -1;
    }
    write_le32(candidate, flags);
    if (aes256_cbc(wrap_key, raw, candidate + 32, 32, true, errp) < 0 ||
        compute_auth(auth_key, candidate + 32, flags, candidate + 16, errp) < 0) {
        goto cleanup;
    }
    memcpy(output, candidate, sizeof(candidate));
    result = 0;
cleanup:
    erase_temporary(candidate, sizeof(candidate));
    return result;
}

int huntmob_wrapped_reference_unwrap(const uint8_t wrap_key[32],
                                    const uint8_t auth_key[32],
                                    const uint8_t *blob, size_t blob_length,
                                    uint8_t output[32], Error **errp)
{
    uint8_t plaintext[32] = { 0 };
    uint8_t tag[16] = { 0 };
    volatile unsigned difference = 0;
    int result = -1;
    if (!wrap_key || !auth_key || !blob || !output || blob_length != 64 ||
        !huntmob_wrapped_reference_flags_supported(read_le32(blob))) {
        error_setg(errp, "Unsupported virtual SEP envelope parameters");
        return -1;
    }
    for (size_t i = 4; i < 16; i++) {
        difference |= blob[i];
    }
    if (difference) {
        error_setg(errp, "Unsupported virtual SEP envelope reserved metadata");
        goto cleanup;
    }
    if (compute_auth(auth_key, blob + 32, read_le32(blob), tag, errp) < 0) {
        goto cleanup;
    }
    /* Fixed-size constant-work comparison: no early exit on tag differences. */
    for (size_t i = 0; i < sizeof(tag); i++) {
        difference |= tag[i] ^ blob[i + 16];
    }
    if (difference) {
        error_setg(errp, "Virtual SEP envelope authentication failed");
        goto cleanup;
    }
    if (aes256_cbc(wrap_key, blob + 32, plaintext, sizeof(plaintext),
                   false, errp) < 0) {
        goto cleanup;
    }
    memcpy(output, plaintext, sizeof(plaintext));
    result = 0;
cleanup:
    erase_temporary(tag, sizeof(tag));
    erase_temporary(plaintext, sizeof(plaintext));
    return result;
}
