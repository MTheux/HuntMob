/* AUTHORIZED TESTING ONLY — PUBLIC SYNTHETIC FIXTURES. No real root/guest. */
#include "crypto/huntmob-virtual-mpe.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static unsigned checks;
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stderr,"public fixture failed line %u\n",__LINE__); exit(1); } } while (0)
static HuntMobVirtualMPE *ready(uint8_t a[256],uint8_t b[256])
{
    uint8_t vm[16],salt[32],key0[32],key1[32];
    for(unsigned i=0;i<16;i++)vm[i]=i;
    for(unsigned i=0;i<32;i++){salt[i]=32+i;key0[i]=64+i;key1[i]=96+i;}
    HuntMobVirtualMPE *m=huntmob_virtual_mpe_new(vm,salt,1);
    CHECK(m);CHECK(huntmob_virtual_mpe_bind_region(m,0,256,a));
    CHECK(huntmob_virtual_mpe_bind_region(m,1,256,b));
    CHECK(huntmob_virtual_mpe_regions_bound(m));
    CHECK(!huntmob_virtual_mpe_latch_key(m,0));
    CHECK(!huntmob_virtual_mpe_stage_key(m,1,key1));
    CHECK(huntmob_virtual_mpe_stage_key(m,0,key0));CHECK(huntmob_virtual_mpe_latch_key(m,0));
    CHECK(!huntmob_virtual_mpe_configure_region(m,0,0x100000,256));
    CHECK(huntmob_virtual_mpe_stage_key(m,1,key1));CHECK(huntmob_virtual_mpe_latch_key(m,1));
    CHECK(huntmob_virtual_mpe_both_latched(m));CHECK(!huntmob_virtual_mpe_stage_key(m,0,key0));
    CHECK(!huntmob_virtual_mpe_configure_region(m,0,0x100000,0));
    CHECK(huntmob_virtual_mpe_configure_region(m,0,0x100000,256));
    CHECK(!huntmob_virtual_mpe_configure_region(m,1,0x100040,256));
    CHECK(huntmob_virtual_mpe_configure_region(m,1,0x200000,256));
    uint8_t out[128];memset(out,0xa7,sizeof(out));
    CHECK(!huntmob_virtual_mpe_external_read(m,0,0,out,sizeof(out)));CHECK(out[0]==0xa7);
    CHECK(huntmob_virtual_mpe_private_write(m,0,61,(const uint8_t *)"public-cross-line",17));
    CHECK(huntmob_virtual_mpe_initialize_region(m,0));CHECK(huntmob_virtual_mpe_initialize_region(m,1));
    CHECK(!huntmob_virtual_mpe_initialize_region(m,0));
    return m;
}
int main(void)
{
    uint8_t a[256]={0},b[256]={0},out[256],cipher[256],snapshot[256],c[64],tag[16];uint64_t gen;
    HuntMobVirtualMPE *m=ready(a,b);
    CHECK(huntmob_virtual_mpe_is_active(m,0));
    CHECK(huntmob_virtual_mpe_private_read(m,0,0,out,256));CHECK(!memcmp(out,a,256));
    CHECK(huntmob_virtual_mpe_external_read(m,0,0,cipher,256));CHECK(memcmp(cipher,a,256));
    memcpy(snapshot,cipher,256);
    CHECK(!huntmob_virtual_mpe_external_write(m,0,0,(const uint8_t *)"denied",6));
    CHECK(huntmob_virtual_mpe_external_read(m,0,0,cipher,256));CHECK(!memcmp(snapshot,cipher,256));
    CHECK(huntmob_virtual_mpe_private_write(m,0,63,(const uint8_t *)"NEW",3));
    CHECK(huntmob_virtual_mpe_private_read(m,0,63,out,3));CHECK(!memcmp(out,"NEW",3));
    CHECK(huntmob_virtual_mpe_test_record(m,0,0,c,tag,&gen));
    CHECK(huntmob_virtual_mpe_test_counter(m,UINT32_MAX));memcpy(snapshot,a,256);
    CHECK(!huntmob_virtual_mpe_private_write(m,0,3,(const uint8_t *)"x",1));CHECK(!huntmob_virtual_mpe_is_active(m,0));
    CHECK(!huntmob_virtual_mpe_private_write(m,0,255,(const uint8_t *)"zz",2));
    huntmob_virtual_mpe_reset(m);
    CHECK(!huntmob_virtual_mpe_is_active(m,0));CHECK(!huntmob_virtual_mpe_regions_bound(m));
    for(unsigned i=0;i<256;i++){CHECK(a[i]==0);CHECK(b[i]==0);}
    CHECK(!huntmob_virtual_mpe_stage_key(m,0,c));huntmob_virtual_mpe_free(m);
    for(unsigned kind=0;kind<3;kind++){
        memset(a,0,256);memset(b,0,256);m=ready(a,b);
        CHECK(huntmob_virtual_mpe_test_record(m,0,0,c,tag,&gen));
        if(kind==0)c[17]^=1;else if(kind==1)tag[3]^=1;else gen++;
        CHECK(huntmob_virtual_mpe_test_replace(m,0,0,c,tag,gen));
        memset(out,0xa7,256);memcpy(snapshot,a,256);
        CHECK(!huntmob_virtual_mpe_private_write(m,0,63,(const uint8_t *)"xx",2));
        CHECK(!huntmob_virtual_mpe_is_active(m,0));
        for(unsigned j=0;j<256;j++)CHECK(a[j]==0);
        CHECK(!huntmob_virtual_mpe_private_read(m,0,0,out,128));CHECK(out[0]==0xa7&&out[127]==0xa7);
        huntmob_virtual_mpe_free(m);
    }
    printf("{\"public_fixture_checks\":%u,\"native_ready\":false,\"apple_cipher_validated\":false}\n",checks);
    return 0;
}
