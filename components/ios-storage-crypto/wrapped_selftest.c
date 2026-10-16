/* Offline public fixtures only. No firmware, devices, backings, or live keys. */
#include "qemu/osdep.h"
#include "wrapped_reference.h"
#include "wrapped_fixture.h"

static unsigned checks;

static void expect(bool condition)
{
    if (!condition) {
        fprintf(stderr, "Wrapped reference selftest failed at check %u\n", checks);
        exit(1);
    }
    checks++;
}

static void reject_blob(const uint8_t *blob, size_t length,
                         const uint8_t *auth_key)
{
    uint8_t output[32];
    uint8_t marker[32];
    Error *error = NULL;
    memset(marker, 0xa5, sizeof(marker));
    memcpy(output, marker, sizeof(output));
    expect(huntmob_wrapped_reference_unwrap(fixture_wrap_key, auth_key, blob,
                                            length, output, &error) < 0);
    expect(error != NULL);
    error_free(error);
    expect(memcmp(output, marker, sizeof(output)) == 0);
}

static void variant(uint32_t flags, const uint8_t expected[64])
{
    uint8_t blob[64], raw[32], changed[64], wrong_key[32];
    Error *error = NULL;
    expect(huntmob_wrapped_reference_flags_supported(flags));
    expect(huntmob_wrapped_reference_wrap(fixture_wrap_key, fixture_auth_key,
                                          fixture_raw, flags, blob, &error) == 0);
    expect(error == NULL);
    expect(memcmp(blob, expected, sizeof(blob)) == 0);
    expect(huntmob_wrapped_reference_unwrap(fixture_wrap_key, fixture_auth_key,
                                            expected, 64, raw, &error) == 0);
    expect(error == NULL);
    expect(memcmp(raw, fixture_raw, sizeof(raw)) == 0);
    /* Every byte position, including flags/reserved/tag/both CBC blocks. */
    for (size_t i = 0; i < 64; i++) {
        memcpy(changed, expected, sizeof(changed));
        changed[i] ^= 1;
        reject_blob(changed, sizeof(changed), fixture_auth_key);
    }
    /* Explicitly cross to the other allowlisted format WITHOUT re-MAC. */
    memcpy(changed, expected, sizeof(changed));
    changed[1] ^= 1;
    reject_blob(changed, sizeof(changed), fixture_auth_key);
    for (size_t length = 0; length < 64; length++) {
        reject_blob(expected, length, fixture_auth_key);
    }
    reject_blob(expected, 65, fixture_auth_key);
    memset(wrong_key, 0, sizeof(wrong_key));
    reject_blob(expected, 64, wrong_key);
    for (size_t i = 0; i < 32; i++) {
        wrong_key[i] = fixture_auth_key[31 - i];
    }
    reject_blob(expected, 64, wrong_key);
    reject_blob(NULL, 64, fixture_auth_key);
    reject_blob(expected, 64, NULL);
    /* Overlap commits only after authentication; failure markers above remain
     * untouched even when the framing fails before any decrypt operation. */
    memcpy(changed, expected, sizeof(changed));
    expect(huntmob_wrapped_reference_unwrap(fixture_wrap_key, fixture_auth_key,
                                            changed, sizeof(changed), changed,
                                            &error) == 0);
    expect(memcmp(changed, fixture_raw, sizeof(raw)) == 0);
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--authorized-synthetic-selftest")) {
        return 2;
    }
    variant(HUNTMOB_WRAPPED_REFERENCE_FLAGS, fixture_expected_blob);
    variant(HUNTMOB_WRAPPED_REFERENCE_FLAGS_NATIVE, fixture_expected_native_blob);
    expect(memcmp(fixture_expected_blob + 32, fixture_expected_native_blob + 32, 32) == 0);
    expect(memcmp(fixture_expected_blob + 16, fixture_expected_native_blob + 16, 16) != 0);
    for (size_t i = 0; i < G_N_ELEMENTS(fixture_unknown_flags); i++) {
        uint8_t output[64], marker[64];
        Error *error = NULL;
        expect(!huntmob_wrapped_reference_flags_supported(fixture_unknown_flags[i]));
        /* These fixtures carry the independently computed VALID MAC for their
         * exact unsupported word. An allowlist failure must still reject. */
        reject_blob(fixture_unknown_blobs[i], 64, fixture_auth_key);
        memset(marker, 0xa5, sizeof(marker));
        memcpy(output, marker, sizeof(output));
        expect(huntmob_wrapped_reference_wrap(fixture_wrap_key, fixture_auth_key,
                                              fixture_raw, fixture_unknown_flags[i],
                                              output, &error) < 0);
        expect(error != NULL);
        error_free(error);
        expect(memcmp(output, marker, sizeof(marker)) == 0);
    }
    printf("{\"checks\":%u,\"reference_passed\":true,"
           "\"both_exact_formats_validated\":true,"
           "\"both_cross_flips_without_remac_rejected\":true,"
           "\"tampered_byte_positions_per_format\":64,"
           "\"valid_MAC_unknown_formats_rejected\":true,"
           "\"output_unchanged_on_rejection\":true,"
           "\"DATA_cipher_semantics_validated\":false,"
           "\"hardware_equivalence_validated\":false,"
           "\"sep_to_ans_bridge_validated\":false,"
           "\"native_ios_ready\":false}\n", checks);
    return 0;
}
