/* AUTHORIZED TESTING ONLY — deterministic public fixture composition.
 * "backing" and "DMA" below are local byte arrays, never disk/device I/O.
 * The test exercises real QCrypto codec calls outside the lifecycle lock.
 */
#include "qemu/osdep.h"
#include "ans_context_lifecycle.h"
#include "wrapped_reference.h"
#include "context_codec_fixture.h"

static unsigned checks;
static void expect(bool condition)
{
    if (!condition) {
        fprintf(stderr, "Context/codec boundary failed at check %u\n", checks);
        exit(1);
    }
    checks++;
}

static void erase(void *buffer, size_t length)
{
    volatile uint8_t *bytes = buffer;
    while (length--) {
        *bytes++ = 0;
    }
}

typedef struct Snapshot {
    uint8_t pair[64];
} Snapshot;

typedef struct CopyAction {
    const uint8_t *input;
    uint8_t *output;
    unsigned calls;
} CopyAction;

/* These callbacks only perform bounded copies. In particular, no QCrypto
 * allocation, wait, device drain or reentrant lifecycle call occurs here. */
static void snapshot_action(const uint8_t wrap[32], const uint8_t auth[32], void *opaque)
{
    Snapshot *snapshot = opaque;
    memcpy(snapshot->pair, wrap, 32);
    memcpy(snapshot->pair + 32, auth, 32);
}

static void final_copy_action(const uint8_t wrap[32], const uint8_t auth[32], void *opaque)
{
    CopyAction *action = opaque;
    (void)wrap;
    (void)auth;
    memcpy(action->output, action->input, 32);
    action->calls++;
}

static uint64_t publish(HuntMobANSContext *context, const uint8_t wrap[32],
                         const uint8_t auth[32])
{
    uint64_t generation;
    expect(huntmob_ans_context_begin(context, &generation));
    expect(huntmob_ans_context_stage_synthetic_pair(context, generation, wrap, auth));
    expect(huntmob_ans_context_publish(context, generation));
    return generation;
}

static void snapshot(HuntMobANSContext *context, uint64_t generation,
                      HuntMobANSContextLease *lease, Snapshot *copied)
{
    expect(huntmob_ans_context_acquire(context, generation, lease));
    expect(huntmob_ans_context_execute(context, lease, snapshot_action, copied));
}

static bool decode_outside_lock(Snapshot *copied, const uint8_t blob[64],
                                uint8_t raw[32])
{
    Error *error = NULL;
    /* No lock is held here. QCrypto may allocate/free expanded cipher state. */
    int result = huntmob_wrapped_reference_unwrap(copied->pair, copied->pair + 32,
                                                 blob, 64, raw, &error);
    expect((result == 0) == (error == NULL));
    error_free(error);
    erase(copied, sizeof(*copied));
    for (size_t i = 0; i < sizeof(*copied); i++) {
        expect(((const uint8_t *)copied)[i] == 0);
    }
    return result == 0;
}

static void expect_marker(const uint8_t actual[32], const uint8_t marker[32])
{
    expect(memcmp(actual, marker, 32) == 0);
}

int main(int argc, char **argv)
{
    HuntMobANSContext *context;
    HuntMobANSContextLease old = { 0 }, fresh = { 0 };
    Snapshot copied = { 0 };
    uint8_t raw[32], dma[32], backing[32], marker[32], corrupted[64];
    uint64_t generation;
    CopyAction submit = { .input = raw, .output = backing };
    CopyAction deliver = { .input = raw, .output = dma };
    if (argc != 2 || strcmp(argv[1], "--authorized-synthetic-selftest")) {
        return 2;
    }
    memset(marker, 0xa5, sizeof(marker));
    context = huntmob_ans_context_new();

    /* Valid first generation: snapshot, real codec, then separately fenced
     * mock submission and final memory delivery using the same owned lease. */
    generation = publish(context, fixture_wrap_a, fixture_auth_a);
    snapshot(context, generation, &old, &copied);
    expect(decode_outside_lock(&copied, fixture_blob_a, raw));
    expect(memcmp(raw, fixture_raw_a, sizeof(raw)) == 0);
    memcpy(backing, marker, 32);
    memcpy(dma, marker, 32);
    expect(huntmob_ans_context_execute(context, &old, final_copy_action, &submit));
    expect(huntmob_ans_context_execute(context, &old, final_copy_action, &deliver));
    expect(submit.calls == 1 && deliver.calls == 1);
    expect(memcmp(backing, fixture_raw_a, 32) == 0);
    expect(memcmp(dma, fixture_raw_a, 32) == 0);
    expect(huntmob_ans_context_release(&old));
    erase(raw, sizeof(raw));

    /* Deterministic revoke AFTER successful unwrap and BEFORE submission. */
    snapshot(context, generation, &old, &copied);
    expect(decode_outside_lock(&copied, fixture_blob_a, raw));
    memcpy(backing, marker, 32);
    memcpy(dma, marker, 32);
    expect(huntmob_ans_context_revoke(context));
    expect(!huntmob_ans_context_execute(context, &old, final_copy_action, &submit));
    expect(!huntmob_ans_context_execute(context, &old, final_copy_action, &deliver));
    expect(submit.calls == 1 && deliver.calls == 1);
    expect_marker(backing, marker);
    expect_marker(dma, marker);
    erase(raw, sizeof(raw));

    /* A complete distinct pair is published. The old lease must stay stale;
     * it cannot obtain either the new pair or permission to perform a copy. */
    generation = publish(context, fixture_wrap_b, fixture_auth_b);
    memset(&copied, 0xa5, sizeof(copied));
    expect(!huntmob_ans_context_execute(context, &old, snapshot_action, &copied));
    for (size_t i = 0; i < sizeof(copied); i++) {
        expect(((const uint8_t *)&copied)[i] == 0xa5);
    }
    expect(!huntmob_ans_context_execute(context, &old, final_copy_action, &submit));
    expect_marker(backing, marker);
    expect(huntmob_ans_context_release(&old));
    snapshot(context, generation, &fresh, &copied);
    memcpy(raw, marker, 32);
    expect(!decode_outside_lock(&copied, fixture_blob_a, raw));
    expect_marker(raw, marker); /* Wrong-generation envelope never decrypts. */
    expect(huntmob_ans_context_execute(context, &fresh, snapshot_action, &copied));
    expect(decode_outside_lock(&copied, fixture_blob_b, raw));
    expect(memcmp(raw, fixture_raw_b, 32) == 0);
    expect(huntmob_ans_context_execute(context, &fresh, final_copy_action, &submit));
    expect(memcmp(backing, fixture_raw_b, 32) == 0);
    expect(submit.calls == 2);
    expect(huntmob_ans_context_release(&fresh));
    erase(raw, sizeof(raw));

    /* Read boundary: completed decode may have produced a valid raw key, but
     * revocation before final DMA prevents delivery. No mock backing write is
     * performed by a read, and no already-submitted write is "rolled back". */
    snapshot(context, generation, &fresh, &copied);
    expect(decode_outside_lock(&copied, fixture_blob_b, raw));
    memcpy(backing, marker, 32);
    memcpy(dma, marker, 32);
    expect(huntmob_ans_context_revoke(context));
    expect(!huntmob_ans_context_execute(context, &fresh, final_copy_action, &deliver));
    expect(deliver.calls == 1);
    expect_marker(backing, marker);
    expect_marker(dma, marker);
    expect(huntmob_ans_context_release(&fresh));
    erase(raw, sizeof(raw));

    /* Reset is separately tested at the same final-DMA boundary. */
    generation = publish(context, fixture_wrap_a, fixture_auth_a);
    snapshot(context, generation, &fresh, &copied);
    expect(decode_outside_lock(&copied, fixture_blob_a, raw));
    expect(huntmob_ans_context_reset(context));
    expect(!huntmob_ans_context_execute(context, &fresh, final_copy_action, &deliver));
    expect(deliver.calls == 1);
    expect_marker(backing, marker);
    expect_marker(dma, marker);
    expect(huntmob_ans_context_release(&fresh));
    erase(raw, sizeof(raw));

    /* Authentication failure with a current lease: the caller never attempts
     * final submission/DMA when decode fails. Sentinels remain untouched. */
    generation = publish(context, fixture_wrap_a, fixture_auth_a);
    snapshot(context, generation, &fresh, &copied);
    memcpy(corrupted, fixture_blob_a, 64);
    corrupted[16] ^= 1;
    memcpy(raw, marker, 32);
    bool decoded = decode_outside_lock(&copied, corrupted, raw);
    expect(!decoded);
    if (decoded) {
        huntmob_ans_context_execute(context, &fresh, final_copy_action, &submit);
        huntmob_ans_context_execute(context, &fresh, final_copy_action, &deliver);
    }
    expect(submit.calls == 2 && deliver.calls == 1);
    expect_marker(raw, marker);
    expect_marker(backing, marker);
    expect_marker(dma, marker);
    expect(huntmob_ans_context_release(&fresh));
    erase(raw, sizeof(raw));
    erase(corrupted, sizeof(corrupted));
    expect(huntmob_ans_context_destroy(context));
    printf("{\"checks\":%u,\"valid_pair_a_roundtrip\":true,"
           "\"distinct_pair_b_decode\":true,\"snapshot_erased_after_codec\":true,"
           "\"revoke_before_submission_blocks_callback\":true,"
           "\"revoke_before_read_dma_blocks_callback\":true,"
           "\"reset_before_read_dma_blocks_callback\":true,"
           "\"old_lease_rejected_after_pair_change\":true,"
           "\"old_envelope_rejected_by_distinct_pair\":true,"
           "\"bad_mac_never_reaches_final_callbacks\":true,"
           "\"rejected_path_sentinels_unchanged\":true,"
           "\"mock_submission_calls\":%u,\"mock_dma_calls\":%u,"
           "\"controller_connected\":false,\"sep_provider_validated\":false,"
           "\"native_ios_ready\":false}\n", checks, submit.calls, deliver.calls);
    return 0;
}
