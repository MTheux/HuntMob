/* Standalone SYNTHETIC lifecycle component, not a validated SEP provider. */
#ifndef HUNTMOB_ANS_CONTEXT_LIFECYCLE_H
#define HUNTMOB_ANS_CONTEXT_LIFECYCLE_H
#include <stdbool.h>
#include <stdint.h>

typedef struct HuntMobANSContext HuntMobANSContext;
typedef struct HuntMobANSContextLease {
    HuntMobANSContext *owner;
    uint64_t generation;
    bool active;
} HuntMobANSContextLease;

typedef struct HuntMobANSContextStatus {
    uint64_t generation;
    bool ready;
    bool staged;
    bool exhausted;
} HuntMobANSContextStatus;

/* Callbacks run under the context mutex. They must be short, nonblocking,
 * nonreentrant and must not allocate, wait, drain devices, invoke completion
 * callbacks, call this API, or retain key pointers. A bounded immediate async
 * submission or bounded memory copy is allowed; completion/drain are separate.
 * Acquire BQL/AioContext before entering this API, never in a callback.
 */
typedef void (*HuntMobANSContextAction)(const uint8_t wrap_key[32],
                                      const uint8_t auth_key[32], void *opaque);

/* Only a public synthetic fixture may be staged in this standalone component.
 * No host secret substitution, KEY register binding or hardware claim exists.
 */
HuntMobANSContext *huntmob_ans_context_new(void);
/* Returns false while any owned lease exists. Stop/join external callers
 * before destroying; successful destruction invalidates the context pointer.
 */
bool huntmob_ans_context_destroy(HuntMobANSContext *context);
bool huntmob_ans_context_begin(HuntMobANSContext *context, uint64_t *generation);
bool huntmob_ans_context_stage_synthetic_pair(HuntMobANSContext *context,
                                            uint64_t generation,
                                            const uint8_t wrap_key[32],
                                            const uint8_t auth_key[32]);
bool huntmob_ans_context_publish(HuntMobANSContext *context, uint64_t generation);
/* Both revoke and reset invalidate staged/published pairs and old leases.
 * They are distinct entry points for caller lifecycle intent; neither drains
 * previously submitted I/O or removes bytes already committed to storage.
 */
bool huntmob_ans_context_revoke(HuntMobANSContext *context);
bool huntmob_ans_context_reset(HuntMobANSContext *context);
HuntMobANSContextStatus huntmob_ans_context_status(HuntMobANSContext *context);
/* A lease is owned and must not be copied. Initialize it to zero, release it
 * exactly once, and keep its owner alive. No key bytes are exported in a lease.
 */
bool huntmob_ans_context_acquire(HuntMobANSContext *context, uint64_t generation,
                                HuntMobANSContextLease *lease);
bool huntmob_ans_context_release(HuntMobANSContextLease *lease);
/* Check and action are one mutex-protected operation: revoke cannot interleave.
 * A stale lease never runs the callback. This does not authorize later work
 * after this call returns; protect final read-DMA and submission separately.
 */
bool huntmob_ans_context_execute(HuntMobANSContext *context,
                                const HuntMobANSContextLease *lease,
                                HuntMobANSContextAction action, void *opaque);

#ifdef HUNTMOB_ANS_CONTEXT_TESTING
/* Unit harness only; absent from normal builds. Only an empty context is valid. */
bool huntmob_ans_context_test_seed_generation(HuntMobANSContext *context,
                                             uint64_t generation);
#endif
#endif
