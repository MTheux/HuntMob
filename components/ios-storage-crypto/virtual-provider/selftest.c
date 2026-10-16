/* Public deterministic provider test. Only QCryptoSecret lookup is mocked;
 * actual QCrypto HMAC/AES and provider implementation are linked unchanged.
 * No engine, device, guest, host keychain, VM backing or real root is opened.
 */
#include "qemu/osdep.h"
#include "qemu/bswap.h"
#include "crypto/secret.h"
#include "crypto/hmac.h"
#include "crypto/huntmob-virtual-sep.h"
#include "provider_fixture.h"

static unsigned checks;
static void expect(bool condition)
{
    if (!condition) {
        fprintf(stderr, "Virtual provider fixture failed at check %u\n", checks);
        exit(1);
    }
    checks++;
}

int qcrypto_secret_lookup(const char *id, uint8_t **data, size_t *length, Error **errp)
{
    if (!strcmp(id, "public-root-a") || !strcmp(id, "public-root-b")) {
        *length = 32;
        *data = g_memdup2(!strcmp(id, "public-root-a") ? fixture_root_a : fixture_root_b, 32);
        return 0;
    }
    if (!strcmp(id, "wrong-size-root")) {
        *length = 64;
        *data = g_malloc0(64);
        return 0;
    }
    error_setg(errp, "Public fixture secret unavailable");
    return -1;
}

static void failed(Error **error)
{
    expect(*error != NULL);
    error_free(*error);
    *error = NULL;
}

static void input(uint8_t bytes[32], bool auth, const uint8_t context[28])
{
    stl_le_p(bytes, auth ? 0x6175746bU : 0x7772616bU);
    memcpy(bytes + 4, context, 28);
}

static void derive_pair(HuntMobVirtualSEP *provider, unsigned bank,
                         const uint8_t context[28], bool publish)
{
    uint8_t bytes[32];
    Error *error = NULL;
    input(bytes, false, context);
    expect(huntmob_virtual_sep_program(provider, bank, bytes, &error));
    expect(huntmob_virtual_sep_derive(provider, bank ? 0x245 : 0x205, &error));
    input(bytes, true, context);
    expect(huntmob_virtual_sep_program(provider, bank + 2, bytes, &error));
    expect(huntmob_virtual_sep_derive(provider, bank ? 0x244 : 0x204, &error));
    if (publish) {
        expect(huntmob_virtual_sep_latch(provider, 4, bank, &error));
        expect(huntmob_virtual_sep_latch(provider, 5, bank, &error));
    }
    expect(error == NULL);
}

static void produce_blob(HuntMobVirtualSEP *provider, unsigned bank, uint8_t blob[64])
{
    uint8_t intermediate[32], zero[16] = { 0 }, metadata[16] = { 0 };
    Error *error = NULL;
    memset(blob, 0, 64);
    stl_le_p(blob, 0x1b140);
    stl_le_p(metadata + 12, 0x1b140);
    expect(huntmob_virtual_sep_slot_crypt(provider, bank, true, zero,
            fixture_raw, blob + 32, 32, &error));
    expect(huntmob_virtual_sep_slot_crypt(provider, bank + 2, true, zero,
            blob + 32, intermediate, 32, &error));
    expect(huntmob_virtual_sep_slot_crypt(provider, bank + 2, true, intermediate + 16,
            metadata, blob + 16, 16, &error));
    expect(error == NULL);
}

int main(int argc, char **argv)
{
    HuntMobVirtualSEP *a, *b, *again, *other;
    Error *error = NULL;
    uint8_t blob[64], raw[32], marker[32], bytes[32], changed[64], uid[32];
    uint64_t epoch = 0;
    if (argc != 2 || strcmp(argv[1], "--authorized-synthetic-selftest")) {
        return 2;
    }
    memset(marker, 0xa5, 32);
    /* Exercise every digest adapter changed for Nettle4, with independent
     * Python/OpenSSL HMAC vectors, not just provider SHA256. */
    struct {
        QCryptoHashAlgo algorithm;
        const uint8_t *expected;
        size_t length;
    } mac_cases[] = {
        { QCRYPTO_HASH_ALGO_MD5, fixture_hmac_md5, sizeof(fixture_hmac_md5) },
        { QCRYPTO_HASH_ALGO_SHA1, fixture_hmac_sha1, sizeof(fixture_hmac_sha1) },
        { QCRYPTO_HASH_ALGO_SHA224, fixture_hmac_sha224, sizeof(fixture_hmac_sha224) },
        { QCRYPTO_HASH_ALGO_SHA256, fixture_hmac_sha256, sizeof(fixture_hmac_sha256) },
        { QCRYPTO_HASH_ALGO_SHA384, fixture_hmac_sha384, sizeof(fixture_hmac_sha384) },
        { QCRYPTO_HASH_ALGO_SHA512, fixture_hmac_sha512, sizeof(fixture_hmac_sha512) },
        { QCRYPTO_HASH_ALGO_RIPEMD160, fixture_hmac_ripemd160, sizeof(fixture_hmac_ripemd160) },
#ifdef CONFIG_CRYPTO_SM3
        { QCRYPTO_HASH_ALGO_SM3, fixture_hmac_sm3, sizeof(fixture_hmac_sm3) },
#endif
    };
    for (size_t i = 0; i < G_N_ELEMENTS(mac_cases); i++) {
        uint8_t result[64], *pointer = result;
        size_t length = mac_cases[i].length;
        QCryptoHmac *mac = qcrypto_hmac_new(mac_cases[i].algorithm,
                                           fixture_root_a, 32, &error);
        expect(mac != NULL && error == NULL);
        expect(qcrypto_hmac_bytes(mac, (const char *)fixture_context, 28,
                                  &pointer, &length, &error) == 0);
        expect(length == mac_cases[i].length &&
               memcmp(result, mac_cases[i].expected, length) == 0);
        qcrypto_hmac_free(mac);
    }
    expect(!huntmob_virtual_sep_new("missing-root", fixture_vm_id, &error));
    failed(&error);
    expect(!huntmob_virtual_sep_new("wrong-size-root", fixture_vm_id, &error));
    failed(&error);
    expect(!huntmob_virtual_sep_new(NULL, fixture_vm_id, &error));
    failed(&error);
    a = huntmob_virtual_sep_new("public-root-a", fixture_vm_id, &error);
    b = huntmob_virtual_sep_new("public-root-b", fixture_vm_id, &error);
    again = huntmob_virtual_sep_new("public-root-a", fixture_vm_id, &error);
    other = huntmob_virtual_sep_new("public-root-a", fixture_other_vm_id, &error);
    expect(a && b && again && other && !error);
    expect(!huntmob_virtual_sep_is_ready(a));
    memcpy(raw, marker, 32);
    expect(!huntmob_virtual_sep_unwrap(a, fixture_blob_a, raw, &epoch, &error));
    failed(&error);
    expect(memcmp(raw, marker, 32) == 0 && epoch == 0);
    derive_pair(a, 0, fixture_context, false);
    produce_blob(a, 0, blob);
    expect(memcmp(blob, fixture_blob_a, 64) == 0);
    expect(!huntmob_virtual_sep_is_ready(a));
    expect(huntmob_virtual_sep_latch(a, 6, 0, &error));
    expect(!huntmob_virtual_sep_is_ready(a));
    expect(huntmob_virtual_sep_latch(a, 4, 0, &error));
    expect(!huntmob_virtual_sep_is_ready(a));
    expect(huntmob_virtual_sep_latch(a, 5, 0, &error));
    expect(huntmob_virtual_sep_is_ready(a));
    expect(huntmob_virtual_sep_unwrap(a, blob, raw, &epoch, &error));
    expect(memcmp(raw, fixture_raw, 32) == 0);
    expect(huntmob_virtual_sep_epoch_current(a, epoch));
    derive_pair(b, 0, fixture_context, true);
    produce_blob(b, 0, changed);
    expect(memcmp(changed, fixture_blob_b, 64) == 0 && memcmp(blob, changed, 64));
    memcpy(raw, marker, 32);
    expect(!huntmob_virtual_sep_unwrap(b, blob, raw, &epoch, &error));
    failed(&error);
    expect(memcmp(raw, marker, 32) == 0);
    derive_pair(again, 0, fixture_context, true);
    produce_blob(again, 0, changed);
    expect(memcmp(changed, blob, 64) == 0); /* Stable root/VMID across new objects. */
    derive_pair(other, 0, fixture_context, true);
    produce_blob(other, 0, changed);
    expect(memcmp(changed, fixture_other_vm_blob, 64) == 0 && memcmp(changed, blob, 64));

    expect(huntmob_virtual_sep_uid_transform(a, 0, 0x11223344, 0, fixture_raw, uid, &error));
    expect(memcmp(uid, fixture_uid0_count1, 32) == 0);
    expect(huntmob_virtual_sep_uid_transform(a, 0, 0x11223344, 1, fixture_raw, uid, &error));
    expect(memcmp(uid, fixture_uid0_count1, 32) == 0);
    expect(huntmob_virtual_sep_uid_transform(a, 0, 0x11223344, 2, fixture_raw, uid, &error));
    expect(memcmp(uid, fixture_uid0_count2, 32) == 0);
    expect(huntmob_virtual_sep_uid_transform(a, 1, 0x11223344, 1, fixture_raw, uid, &error));
    expect(memcmp(uid, fixture_uid1_count1, 32) == 0);
    memcpy(uid, marker, 32);
    expect(!huntmob_virtual_sep_uid_transform(a, 0, 0x11223344, 65537, fixture_raw, uid, &error));
    failed(&error);
    expect(memcmp(uid, marker, 32) == 0);

    epoch = huntmob_virtual_sep_get_epoch(a);
    derive_pair(a, 1, fixture_context, true);
    expect(huntmob_virtual_sep_is_ready(a)); /* Secondary setup preserves primary. */
    expect(!huntmob_virtual_sep_epoch_current(a, epoch));
    expect(huntmob_virtual_sep_unwrap(a, blob, raw, &epoch, &error));
    expect(memcmp(raw, fixture_raw, 32) == 0);
    huntmob_virtual_sep_revoke(a);
    expect(!huntmob_virtual_sep_is_ready(a));
    expect(!huntmob_virtual_sep_epoch_current(a, epoch));
    memcpy(raw, marker, 32);
    expect(!huntmob_virtual_sep_unwrap(a, blob, raw, &epoch, &error));
    failed(&error);
    expect(memcmp(raw, marker, 32) == 0);
    expect(!huntmob_virtual_sep_slot_crypt(a, 0, true, marker, marker, raw, 32, &error));
    failed(&error);
    expect(memcmp(raw, marker, 32) == 0);
    expect(huntmob_virtual_sep_uid_transform(a, 0, 0x11223344, 1, fixture_raw, uid, &error));
    expect(memcmp(uid, fixture_uid0_count1, 32) == 0); /* Root survives revoke. */

    input(bytes, false, fixture_context);
    expect(huntmob_virtual_sep_program(a, 0, bytes, &error));
    expect(huntmob_virtual_sep_derive(a, 0x205, &error));
    input(bytes, true, fixture_context);
    bytes[4] ^= 1;
    expect(!huntmob_virtual_sep_program(a, 2, bytes, &error));
    failed(&error);
    expect(!huntmob_virtual_sep_latch(a, 4, 0, &error));
    failed(&error);
    expect(!huntmob_virtual_sep_is_ready(a));
    derive_pair(a, 0, fixture_context, true);
    memcpy(changed, blob, 64);
    changed[16] ^= 1;
    expect(!huntmob_virtual_sep_unwrap(a, changed, raw, &epoch, &error));
    failed(&error);
    expect(memcmp(raw, marker, 32) == 0);
    expect(error == NULL);
    huntmob_virtual_sep_free(a);
    huntmob_virtual_sep_free(b);
    huntmob_virtual_sep_free(again);
    huntmob_virtual_sep_free(other);
    printf("{\"checks\":%u,\"hmac_digest_adapters_tested\":%zu,"
           "\"private_derived_pair_frame_matches_oracle\":true,"
           "\"uid_counter_kdf_cbc_matches_oracle\":true,\"wrong_root_rejected\":true,"
           "\"mixed_context_rejected\":true,\"latches_required\":true,"
           "\"secondary_setup_preserves_primary\":true,\"revoke_retires_epoch\":true,"
           "\"missing_root_no_fallback\":true,\"secret_lookup_mocked\":true,"
           "\"controller_connected\":false,\"apple_hardware_equivalent\":false,"
           "\"native_ios_ready\":false}\n", checks, G_N_ELEMENTS(mac_cases));
    return 0;
}
