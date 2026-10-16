/* AUTHORIZED TESTING ONLY — isolated public/synthetic context lifecycle.
 * No Apple derivation, SEP hardware bridge, host-secret fallback or VM binding.
 */
#include "qemu/osdep.h"
#include "qemu/thread.h"
#include "ans_context_lifecycle.h"

struct HuntMobANSContext {
    QemuMutex lock;
    uint64_t generation;
    size_t leases;
    uint8_t pair[64];
    bool ready;
    bool staging;
    bool staged;
    bool exhausted;
};

static void wipe(void *buffer, size_t length)
{
    volatile uint8_t *bytes = buffer;
    while (length--) {
        *bytes++ = 0;
    }
}

static bool invalidate_locked(HuntMobANSContext *context, bool staging)
{
    wipe(context->pair, sizeof(context->pair));
    context->ready = false;
    context->staged = false;
    context->staging = false;
    if (context->exhausted || context->generation == UINT64_MAX) {
        context->exhausted = true;
        return false;
    }
    context->generation++;
    context->staging = staging;
    return true;
}

HuntMobANSContext *huntmob_ans_context_new(void)
{
    HuntMobANSContext *context = g_new0(HuntMobANSContext, 1);
    qemu_mutex_init(&context->lock);
    return context;
}

bool huntmob_ans_context_destroy(HuntMobANSContext *context)
{
    if (!context) {
        return true;
    }
    qemu_mutex_lock(&context->lock);
    if (context->leases) {
        qemu_mutex_unlock(&context->lock);
        return false;
    }
    wipe(context->pair, sizeof(context->pair));
    qemu_mutex_unlock(&context->lock);
    qemu_mutex_destroy(&context->lock);
    wipe(context, sizeof(*context));
    g_free(context);
    return true;
}

bool huntmob_ans_context_begin(HuntMobANSContext *context, uint64_t *generation)
{
    bool valid;
    if (!context || !generation) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = invalidate_locked(context, true);
    if (valid) {
        *generation = context->generation;
    }
    qemu_mutex_unlock(&context->lock);
    return valid;
}

bool huntmob_ans_context_stage_synthetic_pair(HuntMobANSContext *context,
                                            uint64_t generation,
                                            const uint8_t wrap_key[32],
                                            const uint8_t auth_key[32])
{
    bool valid;
    if (!context || !wrap_key || !auth_key) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = context->generation == generation && context->staging &&
            !context->exhausted;
    if (valid) {
        wipe(context->pair, sizeof(context->pair));
        memcpy(context->pair, wrap_key, 32);
        memcpy(context->pair + 32, auth_key, 32);
        context->staged = true;
    }
    qemu_mutex_unlock(&context->lock);
    return valid;
}

bool huntmob_ans_context_publish(HuntMobANSContext *context, uint64_t generation)
{
    bool valid;
    if (!context) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = context->generation == generation && context->staging &&
            context->staged && !context->exhausted;
    if (valid) {
        context->ready = true;
        context->staging = false;
    }
    qemu_mutex_unlock(&context->lock);
    return valid;
}

static bool invalidate(HuntMobANSContext *context)
{
    bool valid;
    if (!context) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = invalidate_locked(context, false);
    qemu_mutex_unlock(&context->lock);
    return valid;
}

bool huntmob_ans_context_revoke(HuntMobANSContext *context)
{
    return invalidate(context);
}

bool huntmob_ans_context_reset(HuntMobANSContext *context)
{
    return invalidate(context);
}

HuntMobANSContextStatus huntmob_ans_context_status(HuntMobANSContext *context)
{
    HuntMobANSContextStatus status = { 0 };
    if (!context) {
        return status;
    }
    qemu_mutex_lock(&context->lock);
    status.generation = context->generation;
    status.ready = context->ready;
    status.staged = context->staged;
    status.exhausted = context->exhausted;
    qemu_mutex_unlock(&context->lock);
    return status;
}

bool huntmob_ans_context_acquire(HuntMobANSContext *context, uint64_t generation,
                                HuntMobANSContextLease *lease)
{
    bool valid;
    if (!context || !lease || lease->active) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = context->ready && !context->exhausted &&
            context->generation == generation && context->leases < SIZE_MAX;
    if (valid) {
        lease->owner = context;
        lease->generation = generation;
        lease->active = true;
        context->leases++;
    }
    qemu_mutex_unlock(&context->lock);
    return valid;
}

bool huntmob_ans_context_release(HuntMobANSContextLease *lease)
{
    HuntMobANSContext *context;
    if (!lease || !lease->active || !lease->owner) {
        return false;
    }
    context = lease->owner;
    qemu_mutex_lock(&context->lock);
    assert(context->leases > 0);
    context->leases--;
    wipe(lease, sizeof(*lease));
    qemu_mutex_unlock(&context->lock);
    return true;
}

bool huntmob_ans_context_execute(HuntMobANSContext *context,
                                const HuntMobANSContextLease *lease,
                                HuntMobANSContextAction action, void *opaque)
{
    bool valid;
    if (!context || !lease || !action) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = lease->active && lease->owner == context && context->ready &&
            !context->exhausted && lease->generation == context->generation;
    if (valid) {
        action(context->pair, context->pair + 32, opaque);
    }
    qemu_mutex_unlock(&context->lock);
    return valid;
}

#ifdef HUNTMOB_ANS_CONTEXT_TESTING
bool huntmob_ans_context_test_seed_generation(HuntMobANSContext *context,
                                             uint64_t generation)
{
    bool valid;
    if (!context) {
        return false;
    }
    qemu_mutex_lock(&context->lock);
    valid = !context->ready && !context->staged && !context->staging &&
            !context->leases && !context->exhausted;
    if (valid) {
        context->generation = generation;
    }
    qemu_mutex_unlock(&context->lock);
    return valid;
}
#endif
