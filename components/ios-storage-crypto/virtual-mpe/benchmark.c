/* AUTHORIZED TESTING ONLY — PUBLIC SYNTHETIC FIXTURES.
 * Frozen core timing only: not guest CPU, boot time or UI performance. */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "crypto/huntmob-virtual-mpe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <time.h>
#include <sys/resource.h>
#include "benchmark_allocator.h"
#define MIB (1024u * 1024u)
static size_t allocation_live,allocation_peak;
typedef union AllocationHeader { size_t size; max_align_t alignment; } AllocationHeader;
void *mpe_bench_malloc(size_t size) {
    if(size>512u*MIB-sizeof(AllocationHeader)||allocation_live>512u*MIB-size-sizeof(AllocationHeader))return NULL;
    AllocationHeader *h=malloc(sizeof(*h)+size);if(!h)return NULL;
    h->size=size;allocation_live+=size+sizeof(*h);if(allocation_live>allocation_peak)allocation_peak=allocation_live;return h+1;
}
void *mpe_bench_calloc(size_t count,size_t size) {
    if(size&&count>SIZE_MAX/size)return NULL;
    void *p=mpe_bench_malloc(count*size);if(p)memset(p,0,count*size);return p;
}
void mpe_bench_free(void *pointer) {
    if(!pointer)return;AllocationHeader *h=(AllocationHeader *)pointer-1;
    allocation_live-=h->size+sizeof(*h);free(h);
}
static double wall(void) {
    struct timespec t;
    if(clock_gettime(CLOCK_MONOTONIC,&t))exit(2);
    return t.tv_sec+t.tv_nsec/1e9;
}
static double cpu(void) {
    struct rusage r;
    if(getrusage(RUSAGE_SELF,&r))exit(2);
    return r.ru_utime.tv_sec+r.ru_utime.tv_usec/1e6+r.ru_stime.tv_sec+r.ru_stime.tv_usec/1e6;
}
static size_t peak(void) {
    struct rusage r;if(getrusage(RUSAGE_SELF,&r))exit(2);
#ifdef __APPLE__
    return (size_t)r.ru_maxrss;
#else
    return (size_t)r.ru_maxrss*1024u;
#endif
}
#define require(ok) do { if(!(ok)) { fprintf(stderr,"Public benchmark failed closed line=%u\n",__LINE__);exit(2); } } while(0)
int main(void) {
    alarm(28);
    uint8_t vm[16],salt[32],input0[32],input1[32],zero[8]={0};
    for(unsigned i=0;i<16;i++){vm[i]=i;input0[i]=input0[i+16]=64+i;input1[i]=input1[i+16]=96+i;}
    for(unsigned i=0;i<32;i++)salt[i]=32+i;
    uint8_t *primary=mpe_bench_malloc(32u*MIB),*secondary=mpe_bench_malloc(84u*MIB);
    require(primary&&secondary);
    memset(primary,0xa5,32u*MIB);memset(secondary,0x5a,84u*MIB);
    HuntMobVirtualMPE *m=huntmob_virtual_mpe_new(vm,salt,1);require(m!=NULL);
    require(huntmob_virtual_mpe_bind_region(m,0,32u*MIB,primary));
    require(huntmob_virtual_mpe_bind_region(m,1,84u*MIB,secondary));
    require(huntmob_virtual_mpe_stage_key(m,0,input0));require(huntmob_virtual_mpe_latch_key(m,0));
    require(huntmob_virtual_mpe_stage_key(m,1,input1));require(huntmob_virtual_mpe_latch_key(m,1));
    require(huntmob_virtual_mpe_configure_region(m,0,0x110000000,32u*MIB));
    require(huntmob_virtual_mpe_configure_region(m,1,0x120000000,84u*MIB));
    double w=wall(),c=cpu();require(huntmob_virtual_mpe_initialize_region(m,0));
    double init0w=wall()-w,init0c=cpu()-c;
    w=wall();c=cpu();require(huntmob_virtual_mpe_initialize_region(m,1));
    double init1w=wall()-w,init1c=cpu()-c;
    w=wall();c=cpu();
    for(size_t offset=0;offset<MIB;offset+=8)require(huntmob_virtual_mpe_private_write(m,0,offset,zero,8));
    double writesw=wall()-w,writesc=cpu()-c;
    for(size_t i=0;i<MIB;i++)require(primary[i]==0);
    require(primary[MIB]==0xa5&&secondary[0]==0x5a);
    uint8_t readback[64];require(huntmob_virtual_mpe_private_read(m,0,0,readback,64));
    for(unsigned i=0;i<64;i++)require(readback[i]==0);
    size_t rss=peak();require(rss<512u*MIB);
    printf("{\"primary_init_bytes\":%u,\"primary_init_wall_s\":%.9f,\"primary_init_cpu_s\":%.9f,"
           "\"secondary_init_bytes\":%u,\"secondary_init_wall_s\":%.9f,\"secondary_init_cpu_s\":%.9f,"
           "\"write_unit_bytes\":8,\"write_total_bytes\":%u,\"write_calls\":%u,"
           "\"write_wall_s\":%.9f,\"write_cpu_s\":%.9f,\"max_rss_bytes\":%zu,\"tracked_heap_peak_bytes\":%zu,"
           "\"public_pattern_readback_passed\":true,\"native_ready\":false}\n",
           32u*MIB,init0w,init0c,84u*MIB,init1w,init1c,MIB,MIB/8,writesw,writesc,rss,allocation_peak);
    huntmob_virtual_mpe_free(m);mpe_bench_free(primary);mpe_bench_free(secondary);require(allocation_live==0);alarm(0);return 0;
}
