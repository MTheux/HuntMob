/* Authorized synthetic lifecycle checks only; no firmware, guest or disk input. */
#include "qemu/osdep.h"
#include "crypto/cipher.h"
#include "qapi/error.h"
#include <nettle/sha2.h>
#include <nettle/version.h>

void *huntmob_probe_malloc0(size_t bytes);
void *huntmob_probe_malloc0_n(size_t count, size_t size);
void huntmob_probe_free(void *pointer);

static void *live_allocation;
static size_t live_bytes;
static unsigned allocations, releases, zero_releases, tracking_errors;

void *huntmob_probe_malloc0(size_t bytes)
{
    if (live_allocation || !bytes) {
        tracking_errors++;
        abort();
    }
    live_allocation = g_malloc0(bytes);
    live_bytes = bytes;
    allocations++;
    return live_allocation;
}

void *huntmob_probe_malloc0_n(size_t count, size_t size)
{
    if (!size || count > SIZE_MAX / size) {
        tracking_errors++;
        abort();
    }
    return huntmob_probe_malloc0(count * size);
}

void huntmob_probe_free(void *pointer)
{
    if (!pointer) {
        return;
    }
    if (pointer != live_allocation || !live_bytes) {
        tracking_errors++;
        abort();
    }
    const volatile uint8_t *bytes = pointer;
    uint8_t residue = 0;
    for (size_t index = 0; index < live_bytes; index++) {
        residue |= bytes[index];
    }
    zero_releases += residue == 0;
    releases++;
    live_allocation = NULL;
    live_bytes = 0;
    g_free(pointer); /* The allocation is released only after the live scan. */
}

static bool unsupported_mode(QCryptoCipherAlgo algorithm, QCryptoCipherMode mode)
{
#ifdef CONFIG_CRYPTO_SM4
    if (algorithm == QCRYPTO_CIPHER_ALGO_SM4) {
        return mode != QCRYPTO_CIPHER_MODE_ECB;
    }
#endif
    return mode == QCRYPTO_CIPHER_MODE_XTS &&
           (algorithm == QCRYPTO_CIPHER_ALGO_DES ||
            algorithm == QCRYPTO_CIPHER_ALGO_3DES ||
            algorithm == QCRYPTO_CIPHER_ALGO_CAST5_128);
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--authorized-synthetic-selftest")) {
        return 2;
    }
    const QCryptoCipherAlgo algorithms[] = {
        QCRYPTO_CIPHER_ALGO_DES, QCRYPTO_CIPHER_ALGO_3DES,
        QCRYPTO_CIPHER_ALGO_AES_128, QCRYPTO_CIPHER_ALGO_AES_192,
        QCRYPTO_CIPHER_ALGO_AES_256, QCRYPTO_CIPHER_ALGO_CAST5_128,
        QCRYPTO_CIPHER_ALGO_SERPENT_128, QCRYPTO_CIPHER_ALGO_SERPENT_192,
        QCRYPTO_CIPHER_ALGO_SERPENT_256, QCRYPTO_CIPHER_ALGO_TWOFISH_128,
        QCRYPTO_CIPHER_ALGO_TWOFISH_192, QCRYPTO_CIPHER_ALGO_TWOFISH_256,
#ifdef CONFIG_CRYPTO_SM4
        QCRYPTO_CIPHER_ALGO_SM4,
#endif
    };
    const QCryptoCipherMode modes[] = {
        QCRYPTO_CIPHER_MODE_ECB, QCRYPTO_CIPHER_MODE_CBC,
        QCRYPTO_CIPHER_MODE_CTR, QCRYPTO_CIPHER_MODE_XTS,
    };
    struct sha256_ctx matrix;
    sha256_init(&matrix);
    unsigned tested = 0, rejected_modes = 0, rejected_lengths = 0;
    uint8_t key[64], iv[16], clear[64], encrypted[64], decrypted[64];
    for (size_t index = 0; index < sizeof(key); index++) {
        key[index] = (index * 17 + 3) & 255;
        clear[index] = (index * 29 + 5) & 255;
    }
    memset(iv, 0x63, sizeof(iv));
    for (size_t a = 0; a < G_N_ELEMENTS(algorithms); a++) {
        for (size_t m = 0; m < G_N_ELEMENTS(modes); m++) {
            QCryptoCipherAlgo algorithm = algorithms[a];
            QCryptoCipherMode mode = modes[m];
            size_t key_len = qcrypto_cipher_get_key_len(algorithm) *
                             (mode == QCRYPTO_CIPHER_MODE_XTS ? 2 : 1);
            size_t iv_len = qcrypto_cipher_get_iv_len(algorithm, mode);
            Error *error = NULL;
            QCryptoCipher *cipher = qcrypto_cipher_new(algorithm, mode, key,
                                                       key_len, &error);
            if (unsupported_mode(algorithm, mode)) {
                if (cipher || !error) {
                    return 1;
                }
                error_free(error);
                rejected_modes++;
                continue;
            }
            if (!cipher || error) {
                return 1;
            }
            if ((iv_len && qcrypto_cipher_setiv(cipher, iv, iv_len, &error)) ||
                qcrypto_cipher_encrypt(cipher, clear, encrypted, sizeof(clear), &error) ||
                (iv_len && qcrypto_cipher_setiv(cipher, iv, iv_len, &error)) ||
                qcrypto_cipher_decrypt(cipher, encrypted, decrypted, sizeof(clear), &error) ||
                error || memcmp(clear, decrypted, sizeof(clear))) {
                return 1;
            }
            sha256_update(&matrix, sizeof(encrypted), encrypted);
            qcrypto_cipher_free(cipher);
            tested++;
            /* Also destroy initialized key/tweak schedules and IV before I/O. */
            cipher = qcrypto_cipher_new(algorithm, mode, key, key_len, &error);
            if (!cipher || (iv_len && qcrypto_cipher_setiv(cipher, iv, iv_len, &error))) {
                return 1;
            }
            qcrypto_cipher_free(cipher);
            /* Error-return paths must retain a destructible, erasable object. */
            cipher = qcrypto_cipher_new(algorithm, mode, key, key_len, &error);
            if (!cipher || qcrypto_cipher_encrypt(cipher, clear, encrypted,
                                                   sizeof(clear) - 1, &error) != -1 || !error) {
                return 1;
            }
            error_free(error);
            qcrypto_cipher_free(cipher);
            rejected_lengths++;
        }
    }
    uint8_t digest[32];
#if NETTLE_VERSION_MAJOR >= 4
    sha256_digest(&matrix, digest);
#else
    sha256_digest(&matrix, sizeof(digest), digest);
#endif
    printf("{\"version\":1,\"algorithm_mode_pairs\":%u,\"unsupported_modes_rejected\":%u,"
           "\"invalid_length_contexts_released\":%u,\"allocations\":%u,\"releases\":%u,"
           "\"zero_before_release\":%u,\"tracking_errors\":%u,\"all_contexts_wiped\":%s,"
           "\"ciphertext_matrix_sha256\":\"", tested, rejected_modes, rejected_lengths,
           allocations, releases, zero_releases, tracking_errors,
           zero_releases == releases ? "true" : "false");
    for (size_t index = 0; index < sizeof(digest); index++) {
        printf("%02x", digest[index]);
    }
    printf("\",\"guest_executed\":false,\"wrapped_abi_validated\":false,\"ready\":false}\n");
    return !tested || tracking_errors || live_allocation || allocations != releases;
}
