/* Public-fixture-only bounded allocation shim; not used in engine builds. */
#ifndef HUNTMOB_MPE_BENCH_ALLOCATOR_H
#define HUNTMOB_MPE_BENCH_ALLOCATOR_H
#include <stddef.h>
void *mpe_bench_malloc(size_t size);
void *mpe_bench_calloc(size_t count, size_t size);
void mpe_bench_free(void *pointer);
#endif
