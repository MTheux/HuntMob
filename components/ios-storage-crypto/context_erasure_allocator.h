/* Synthetic instrumentation for the cipher translation unit only.
 * The normal GLib allocator is called by the harness, after inspection while
 * its allocation is still live. No freed-memory inspection is performed. */
#ifndef HUNTMOB_CONTEXT_ERASURE_ALLOCATOR_H
#define HUNTMOB_CONTEXT_ERASURE_ALLOCATOR_H
#include "qemu/osdep.h"
void *huntmob_probe_malloc0(size_t bytes);
void *huntmob_probe_malloc0_n(size_t count, size_t size);
void huntmob_probe_free(void *pointer);
#define g_malloc0 huntmob_probe_malloc0
#define g_malloc0_n huntmob_probe_malloc0_n
#define g_free huntmob_probe_free
#endif
