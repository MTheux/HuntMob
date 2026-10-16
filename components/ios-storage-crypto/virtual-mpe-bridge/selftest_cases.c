static void setup(AppleSEPState*s,HuntMobVirtualMPEMemory*m){memset(s,0,sizeof(*s));memset(m,0,sizeof(*m));m->ready=true;m->cores[0].bound=true;s->virtual_mpe_memory=m;}
static void pair(AppleSEPState*s){uint8_t input[32];for(unsigned i=0;i<32;i++)input[i]=0x31+i;expect(sep_virtual_mpe_stage(s,0,input));expect(sep_virtual_mpe_write(s,0x80,0,4));expect(sep_virtual_mpe_stage(s,1,input));expect(sep_virtual_mpe_write(s,0x80,0x100,4));}
static void configure(AppleSEPState*s){expect(sep_virtual_mpe_write(s,0x300,0x40000,4));expect(sep_virtual_mpe_write(s,0x318,0x40030,4));expect(sep_virtual_mpe_write(s,0x310,16,4));}
static void init_valid(AppleSEPState*s,unsigned r){unsigned base=r?0x420:0x400;uint64_t len=huntmob_virtual_mpe_memory_region_length(s->virtual_mpe_memory,r);expect(sep_virtual_mpe_write(s,base,0,4));expect(sep_virtual_mpe_write(s,base+8,(len>>9)-1,4));expect(sep_virtual_mpe_write(s,base+0x10,1,4));expect(sep_virtual_mpe_write(s,base+0x10,0,4));expect(sep_virtual_mpe_write(s,base,0,4));expect(sep_virtual_mpe_write(s,base+8,0,4));expect(sep_virtual_mpe_write(s,base+0x14,1,4));}
int main(void){struct rlimit core={0,0};setrlimit(RLIMIT_CORE,&core);AppleSEPState*s=g_new0(AppleSEPState,1);HuntMobVirtualMPEMemory m;uint8_t input[32];for(unsigned i=0;i<32;i++)input[i]=0x31+i;
 setup(s,&m);sep_virtual_mpe_bridge_reset(s);expect(m.resets==0);pair(s);configure(s);expect(m.configurations==1&&m.base==0x10000000&&m.lengths[0]==16384&&m.second==0x1000c000);expect(!huntmob_virtual_mpe_is_active(huntmob_virtual_mpe_memory_core(&m),0));init_valid(s,0);init_valid(s,1);expect(m.initialized[0]==1&&m.initialized[1]==1);expect(sep_virtual_mpe_write(s,0x414,1,4));expect(m.initialized[0]==1);expect(sep_virtual_mpe_write(s,0x310,16,4));expect(m.configurations==1);unsigned oldepoch=m.epoch;sep_virtual_mpe_bridge_reset(s);expect(m.epoch==oldepoch+1&&!s->virtual_mpe_configured&&!s->virtual_mpe_faulted);pair(s);expect(huntmob_virtual_mpe_both_latched(huntmob_virtual_mpe_memory_core(&m)));
 setup(s,&m);m.ready=false;expect(!sep_virtual_mpe_stage(s,0,input));expect(s->virtual_mpe_faulted&&m.resets==1);expect(!sep_virtual_mpe_write(s,0x80,0,4)&&m.resets==1);
 setup(s,&m);expect(!sep_virtual_mpe_write(s,0x80,0,4));expect(s->virtual_mpe_faulted);
 setup(s,&m);pair(s);expect(!sep_virtual_mpe_write(s,0x310,16,4));expect(m.configurations==0);
 setup(s,&m);pair(s);expect(sep_virtual_mpe_write(s,0x318,0x40030,4));expect(sep_virtual_mpe_write(s,0x310,0,4));expect(m.lengths[0]==0&&m.lengths[1]==32768);expect(!sep_virtual_mpe_write(s,0x410,1,4));
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x414,1,4));expect(m.initialized[0]==0);
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x408,30,4));expect(m.initialized[0]==0);
 setup(s,&m);pair(s);configure(s);expect(sep_virtual_mpe_write(s,0x408,31,4));expect(sep_virtual_mpe_write(s,0x410,1,4));expect(!sep_virtual_mpe_write(s,0x408,0,4));
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x318,0x40040,4));
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x200,1,4));
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x80,0x400,4));
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x408,31,8));
 setup(s,&m);pair(s);configure(s);expect(!sep_virtual_mpe_write(s,0x508,0,4));
 setup(s,&m);last_control_value=99;expect(!sep_virtual_mpe_write(s,0x404,0x12345678,4));expect(last_control_value==0);
 setup(s,&m);last_control_value=99;expect(!sep_virtual_mpe_write(s,0x400,0x123456789ULL,8));expect(last_control_value==0);
 setup(s,&m);m.ready=false;expect(sep_virtual_mpe_write(s,0x180,1,4));expect(!s->virtual_mpe_started&&!s->virtual_mpe_faulted&&!s->virtual_mpe_configured&&m.resets==0);expect(ldl_le_p(&s->misc1_regs[0x180])==0);
 s->virtual_mpe_faulted=true;expect(sep_virtual_mpe_write(s,0x180,UINT64_C(0x100000001),8));expect(ldq_le_p(&s->misc1_regs[0x180])==UINT64_C(0x100000000));expect(s->virtual_mpe_faulted&&m.resets==0&&!s->virtual_mpe_configured);
 g_free(s);printf("{\"checks\":%u,\"bridge_functions_exact\":true,\"core_and_memory_mocked\":true,\"real_crypto_validated\":false,\"engine_mmio_validated\":false}\n",checks);return 0;}
