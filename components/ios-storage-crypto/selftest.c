/* Public IEEE vectors and synthetic keys only. No guest/VM/file inputs. */
#include "qemu/osdep.h"
#include <nettle/sha2.h>
#include <nettle/version.h>
#include "xts_reference.h"

static bool rejected(const uint8_t key[32], uint64_t unit, size_t length)
{
    uint8_t in[8192] = { 0 }, out[8192], expected[8192];
    Error *error = NULL;
    memset(out, 0xa5, sizeof(out));
    memcpy(expected, out, sizeof(out));
    int result = huntmob_xts128_units(key, unit, in, out, length, true, &error);
    bool ok = result < 0 && error && !memcmp(out, expected, sizeof(out));
    error_free(error);
    return ok;
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--authorized-synthetic-selftest")) {
        fprintf(stderr, "Use --authorized-synthetic-selftest; accepts no guest input.\n");
        return 2;
    }
    uint8_t key[32], tweak[16] = { 0 }, plaintext[32], ciphertext[32], roundtrip[32];
    const uint8_t expected[32] = {
        0xc4,0x54,0x18,0x5e,0x6a,0x16,0x93,0x6e,0x39,0x33,0x40,0x38,0xac,0xef,0x83,0x8b,
        0xfb,0x18,0x6f,0xff,0x74,0x80,0xad,0xc4,0x28,0x93,0x82,0xec,0xd6,0xd3,0x94,0xf0
    };
    memset(key, 0x11, 16); memset(key + 16, 0x22, 16);
    memset(tweak, 0x33, 5); memset(plaintext, 0x44, sizeof(plaintext));
    Error *error = NULL;
    bool ieee = huntmob_xts128_unit(key, tweak, plaintext, ciphertext, 32, true, &error) == 0 &&
                !memcmp(ciphertext, expected, 32) &&
                huntmob_xts128_unit(key, tweak, ciphertext, roundtrip, 32, false, &error) == 0 &&
                !memcmp(roundtrip, plaintext, 32);
    error_free(error); error = NULL;
    uint8_t in[8192], out[8192] = { 0 }, clear[8192] = { 0 }, digest[32];
    const uint8_t expected_digest[32] = {
        0x64,0x2d,0x02,0x8e,0xc0,0xd0,0x2b,0xe8,0xd4,0x6b,0xd0,0xf6,0x37,0xb3,0x55,0xb6,
        0x02,0x5b,0x24,0x52,0x92,0x52,0xee,0x2b,0x64,0x65,0xdf,0x30,0x59,0x44,0xa9,0xa4
    };
    for (size_t i = 0; i < 32; i++) key[i] = i;
    for (size_t i = 0; i < sizeof(in); i++) in[i] = (i * 17 + 3) & 255;
    bool fixed = huntmob_xts128_units(key, UINT64_C(0x123456789a), in, out,
                                    sizeof(in), true, &error) == 0;
    struct sha256_ctx hash;
    sha256_init(&hash); sha256_update(&hash, sizeof(out), out);
#if NETTLE_VERSION_MAJOR >= 4
    sha256_digest(&hash, digest);
#else
    sha256_digest(&hash, 32, digest);
#endif
    fixed &= !memcmp(digest, expected_digest, 32);
    fixed &= huntmob_xts128_units(key, UINT64_C(0x123456789a), out, clear,
                                 sizeof(out), false, &error) == 0 && !memcmp(clear, in, sizeof(in));
    error_free(error); error = NULL;
    bool limits = rejected(key, 0, 0) && rejected(key, 0, 4095) &&
                  rejected(key, 0, 1024 * 1024 + 4096) &&
                  rejected(NULL, 0, 4096) && rejected(key, UINT64_MAX, 8192);
    uint8_t duplicate[32] = { 0 };
    bool halves = rejected(duplicate, 0, 4096);
    printf("{\"version\":1,\"actual_qemu_cipher_linked\":true,"
           "\"ieee_1619_kat\":%s,\"two_4096_units_match_independent_reference\":%s,"
           "\"invalid_parameters_preserve_output\":%s,\"duplicate_halves_rejected\":%s,"
           "\"guest_firmware_executed\":false,\"hardware_abi_validated\":false,"
           "\"wrapped_key_support\":false,\"ready\":false}\n",
           ieee ? "true" : "false", fixed ? "true" : "false",
           limits ? "true" : "false", halves ? "true" : "false");
    return ieee && fixed && limits && halves ? 0 : 1;
}
