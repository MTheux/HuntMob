/* Current virtual SEP framing only; Apple hardware key equivalence unproven. */
#ifndef HUNTMOB_WRAPPED_REFERENCE_H
#define HUNTMOB_WRAPPED_REFERENCE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "qapi/error.h"

#define HUNTMOB_WRAPPED_REFERENCE_FLAGS UINT32_C(0x1b140)
#define HUNTMOB_WRAPPED_REFERENCE_FLAGS_NATIVE UINT32_C(0x1b040)

/* Envelope authentication and DATA cipher support are separate contracts. */
bool huntmob_wrapped_reference_flags_supported(uint32_t flags);
#define HUNTMOB_WRAPPED_REFERENCE_RAW_BYTES 32u
#define HUNTMOB_WRAPPED_REFERENCE_BLOB_BYTES 64u

/* Public/synthetic context inputs only until a real SEP bridge is validated.
 * Both functions leave output untouched on every failure. The unwrap function
 * authenticates the framing before decrypting or exposing any raw key bytes.
 * The caller owns and must erase input/output key material when no longer used.
 */
int huntmob_wrapped_reference_wrap(const uint8_t wrap_key[32],
                                  const uint8_t auth_key[32],
                                  const uint8_t raw[32], uint32_t flags,
                                  uint8_t output[64], Error **errp);
int huntmob_wrapped_reference_unwrap(const uint8_t wrap_key[32],
                                    const uint8_t auth_key[32],
                                    const uint8_t *blob, size_t blob_length,
                                    uint8_t output[32], Error **errp);
#endif
