/* Standard XTS reference only. No Apple key wrapping or MMIO ABI implied. */
#ifndef HUNTMOB_XTS_REFERENCE_H
#define HUNTMOB_XTS_REFERENCE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "qapi/error.h"

/* Key order is the STANDARD/QEMU order: K1 data, K2 tweak. */
int huntmob_xts128_unit(const uint8_t key[32], const uint8_t tweak[16],
                       const uint8_t *input, uint8_t *output, size_t length,
                       bool encrypt, Error **errp);
/* Fixed 4096-byte data units; first_unit is NOT assumed to be a guest LBA. */
int huntmob_xts128_units(const uint8_t key[32], uint64_t first_unit,
                        const uint8_t *input, uint8_t *output, size_t length,
                        bool encrypt, Error **errp);
#endif
