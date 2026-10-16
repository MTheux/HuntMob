/* Native public-fixture tests only: never opens firmware, VM, or storage. */
#include "qemu/osdep.h"
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#include "ans_context_lifecycle.h"

static unsigned checks;
static void expect(bool condition)
{
    if (!condition) {
        fprintf(stderr, "Context lifecycle selftest failed at check %u\n", checks);
        exit(1);
    }
    checks++;
}

static void count_action(const uint8_t wrap[32], const uint8_t auth[32], void *opaque)
{
    unsigned *count = opaque;
    (void)wrap;
    (void)auth;
    (*count)++;
}

static bool prepare(HuntMobANSContext *context, uint64_t *generation)
{
    uint8_t wrap[32], auth[32];
    if (!huntmob_ans_context_begin(context, generation)) {
        return false;
    }
    for (size_t i = 0; i < sizeof(wrap); i++) {
        wrap[i] = (uint8_t)(*generation >> ((i % 8) * 8));
        auth[i] = (uint8_t)~wrap[i];
    }
    return huntmob_ans_context_stage_synthetic_pair(context, *generation, wrap, auth) &&
           huntmob_ans_context_publish(context, *generation);
}

typedef struct Race {
    HuntMobANSContext *context;
    atomic_bool done;
    atomic_bool bad;
    uint64_t expected;
    unsigned callbacks;
} Race;

static void coherence_action(const uint8_t wrap[32], const uint8_t auth[32], void *opaque)
{
    Race *race = opaque;
    for (size_t i = 0; i < 32; i++) {
        uint8_t expected = (uint8_t)(race->expected >> ((i % 8) * 8));
        if (wrap[i] != expected || auth[i] != (uint8_t)~expected) {
            atomic_store(&race->bad, true);
        }
    }
    race->callbacks++;
}

static void *publish_thread(void *opaque)
{
    Race *race = opaque;
    uint64_t generation;
    for (unsigned i = 0; i < 5000; i++) {
        if (!prepare(race->context, &generation)) {
            atomic_store(&race->bad, true);
            break;
        }
        if (i % 10 == 0) {
            sched_yield();
        }
    }
    atomic_store(&race->done, true);
    return NULL;
}

static void *acquire_thread(void *opaque)
{
    Race *race = opaque;
    do {
        HuntMobANSContextStatus status = huntmob_ans_context_status(race->context);
        HuntMobANSContextLease lease = { 0 };
        if (huntmob_ans_context_acquire(race->context, status.generation, &lease)) {
            race->expected = lease.generation;
            huntmob_ans_context_execute(race->context, &lease, coherence_action, race);
            if (!huntmob_ans_context_release(&lease)) {
                atomic_store(&race->bad, true);
            }
        }
    } while (!atomic_load(&race->done));
    return NULL;
}

typedef struct Ordering {
    HuntMobANSContext *context;
    atomic_bool entered;
    atomic_bool attempted;
    atomic_bool copied;
    atomic_bool revoked;
    atomic_bool violation;
    bool overlapped;
} Ordering;

static void ordered_action(const uint8_t wrap[32], const uint8_t auth[32], void *opaque)
{
    Ordering *ordering = opaque;
    volatile unsigned work = 0;
    (void)wrap;
    (void)auth;
    atomic_store(&ordering->entered, true);
    /* Bounded CPU work exposes overlap; no waits, allocation or I/O inside
     * the callback. This is a scheduling probe, not a production DMA model. */
    for (unsigned i = 0; i < 10000000; i++) {
        work ^= i;
    }
    (void)work;
    ordering->overlapped = atomic_load(&ordering->attempted);
    if (atomic_load(&ordering->revoked)) {
        atomic_store(&ordering->violation, true);
    }
    atomic_store(&ordering->copied, true);
}

static void *revoke_thread(void *opaque)
{
    Ordering *ordering = opaque;
    while (!atomic_load(&ordering->entered)) {
        sched_yield();
    }
    atomic_store(&ordering->attempted, true);
    if (!huntmob_ans_context_revoke(ordering->context) ||
        !atomic_load(&ordering->copied)) {
        atomic_store(&ordering->violation, true);
    }
    atomic_store(&ordering->revoked, true);
    return NULL;
}

int main(int argc, char **argv)
{
    HuntMobANSContext *context, *other;
    HuntMobANSContextStatus status;
    HuntMobANSContextLease lease = { 0 }, fresh = { 0 };
    uint64_t generation, newer;
    uint8_t wrap[32] = { 0 }, auth[32] = { 0 };
    unsigned called = 0;
    pthread_t writer, reader, revoker;
    if (argc != 2 || strcmp(argv[1], "--authorized-synthetic-selftest")) {
        return 2;
    }
    context = huntmob_ans_context_new();
    other = huntmob_ans_context_new();
    status = huntmob_ans_context_status(context);
    expect(!status.ready && !status.staged && status.generation == 0);
    expect(!huntmob_ans_context_acquire(context, 0, &lease));
    expect(!huntmob_ans_context_stage_synthetic_pair(context, 0, wrap, auth));
    expect(!huntmob_ans_context_publish(context, 0));
    expect(huntmob_ans_context_begin(context, &generation));
    expect(!huntmob_ans_context_publish(context, generation));
    expect(huntmob_ans_context_stage_synthetic_pair(context, generation, wrap, auth));
    expect(!huntmob_ans_context_acquire(context, generation, &lease));
    expect(huntmob_ans_context_publish(context, generation));
    expect(!huntmob_ans_context_stage_synthetic_pair(context, generation, wrap, auth));
    expect(huntmob_ans_context_acquire(context, generation, &lease));
    expect(!huntmob_ans_context_acquire(context, generation, &lease));
    expect(!huntmob_ans_context_destroy(context));
    expect(!huntmob_ans_context_execute(other, &lease, count_action, &called));
    expect(called == 0);
    expect(huntmob_ans_context_execute(context, &lease, count_action, &called));
    expect(called == 1);
    expect(huntmob_ans_context_begin(context, &newer) && newer > generation);
    expect(!huntmob_ans_context_execute(context, &lease, count_action, &called));
    expect(!huntmob_ans_context_stage_synthetic_pair(context, generation, wrap, auth));
    expect(!huntmob_ans_context_publish(context, generation));
    expect(!huntmob_ans_context_acquire(context, newer, &fresh));
    expect(huntmob_ans_context_release(&lease));
    expect(!huntmob_ans_context_release(&lease));
    expect(huntmob_ans_context_stage_synthetic_pair(context, newer, wrap, auth));
    expect(huntmob_ans_context_revoke(context));
    expect(!huntmob_ans_context_publish(context, newer));
    expect(prepare(context, &generation));
    expect(huntmob_ans_context_acquire(context, generation, &lease));
    expect(huntmob_ans_context_reset(context));
    expect(!huntmob_ans_context_execute(context, &lease, count_action, &called));
    expect(huntmob_ans_context_release(&lease));
    expect(huntmob_ans_context_destroy(context));
    expect(huntmob_ans_context_destroy(other));

    Race race = { .context = huntmob_ans_context_new() };
    expect(prepare(race.context, &generation));
    expect(pthread_create(&reader, NULL, acquire_thread, &race) == 0);
    expect(pthread_create(&writer, NULL, publish_thread, &race) == 0);
    expect(pthread_join(writer, NULL) == 0);
    expect(pthread_join(reader, NULL) == 0);
    expect(!atomic_load(&race.bad) && race.callbacks > 0);
    expect(huntmob_ans_context_destroy(race.context));

    Ordering ordering = { .context = huntmob_ans_context_new() };
    expect(prepare(ordering.context, &generation));
    expect(huntmob_ans_context_acquire(ordering.context, generation, &lease));
    expect(pthread_create(&revoker, NULL, revoke_thread, &ordering) == 0);
    expect(huntmob_ans_context_execute(ordering.context, &lease, ordered_action, &ordering));
    expect(pthread_join(revoker, NULL) == 0);
    expect(ordering.overlapped && !atomic_load(&ordering.violation));
    expect(!huntmob_ans_context_execute(ordering.context, &lease, count_action, &called));
    expect(huntmob_ans_context_release(&lease));
    expect(huntmob_ans_context_destroy(ordering.context));

    context = huntmob_ans_context_new();
    expect(huntmob_ans_context_test_seed_generation(context, UINT64_MAX - 1));
    expect(prepare(context, &generation) && generation == UINT64_MAX);
    expect(huntmob_ans_context_acquire(context, generation, &lease));
    expect(!huntmob_ans_context_revoke(context));
    status = huntmob_ans_context_status(context);
    expect(status.exhausted && !status.ready && !status.staged);
    expect(!huntmob_ans_context_execute(context, &lease, count_action, &called));
    expect(!huntmob_ans_context_reset(context));
    expect(!huntmob_ans_context_begin(context, &newer));
    expect(huntmob_ans_context_release(&lease));
    expect(huntmob_ans_context_destroy(context));
    printf("{\"checks\":%u,\"publication_cycles\":5000,"
           "\"coherent_callbacks\":%u,\"mixed_generation_detected\":false,"
           "\"revoke_overlapped_callback\":true,\"callback_before_revoke\":true,"
           "\"overflow_permanently_closed\":true,\"reset_revokes_lease\":true,"
           "\"controller_connected\":false,\"hardware_provider_validated\":false,"
           "\"native_ios_ready\":false}\n", checks, race.callbacks);
    return 0;
}
