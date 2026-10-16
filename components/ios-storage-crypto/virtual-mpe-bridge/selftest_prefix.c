/* Exact bridge functions; memory/core and BQL are mocked. Public fixtures only. */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/bswap.h"
#include <sys/resource.h>
typedef uint64_t hwaddr;
typedef struct HuntMobVirtualMPE { bool staged[2], latched[2], bound, active[2]; unsigned id; } HuntMobVirtualMPE;
typedef struct HuntMobVirtualMPEMemory { HuntMobVirtualMPE cores[32]; unsigned epoch; bool ready; uint64_t lengths[2], base, second; unsigned configurations, initialized[2], resets; } HuntMobVirtualMPEMemory;
typedef struct AppleSEPVirtualMPEInit { uint32_t first_sector,last_sector,control;bool started,pending_finish,finished; } AppleSEPVirtualMPEInit;
typedef struct AppleSEPState { HuntMobVirtualMPEMemory *virtual_mpe_memory; uint32_t virtual_mpe_primary_base_kib,virtual_mpe_primary_length_kib,virtual_mpe_secondary_base_kib;bool virtual_mpe_primary_base_written,virtual_mpe_secondary_base_written,virtual_mpe_configured,virtual_mpe_started,virtual_mpe_faulted;AppleSEPVirtualMPEInit virtual_mpe_init[2];uint8_t misc1_regs[0x40000]; } AppleSEPState;
static unsigned checks;
static uint64_t last_control_value;
static void expect(bool b){if(!b){fprintf(stderr,"bridge check %u failed\n",checks);exit(1);}checks++;}
static bool bql_locked(void){return true;}
static void trace_apple_sep_virtual_mpe_control(const char*a,uint64_t r,uint64_t v,bool ok){if(!strcmp(a,"control"))last_control_value=v;(void)r;(void)ok;}
static HuntMobVirtualMPE *huntmob_virtual_mpe_memory_core(HuntMobVirtualMPEMemory*m){return &m->cores[m->epoch];}
static void huntmob_virtual_mpe_memory_reset(HuntMobVirtualMPEMemory*m){expect(m->epoch<31);m->epoch++;m->cores[m->epoch].id=m->epoch;m->cores[m->epoch].bound=true;m->resets++;}
static bool huntmob_virtual_mpe_memory_consumer_ready(HuntMobVirtualMPEMemory*m){return m->ready;}
static bool huntmob_virtual_mpe_regions_bound(HuntMobVirtualMPE*c){return c->bound;}
static bool huntmob_virtual_mpe_stage_key(HuntMobVirtualMPE*c,unsigned slot,const uint8_t in[32]){if(slot>1||c->staged[slot]||(slot==1&&!c->latched[0]))return false;expect(in[0]==0x31&&in[31]==0x50);c->staged[slot]=true;return true;}
static bool huntmob_virtual_mpe_latch_key(HuntMobVirtualMPE*c,unsigned slot){if(slot>1||!c->staged[slot]||c->latched[slot])return false;c->latched[slot]=true;return true;}
static bool huntmob_virtual_mpe_both_latched(HuntMobVirtualMPE*c){return c->latched[0]&&c->latched[1];}
static bool huntmob_virtual_mpe_is_active(HuntMobVirtualMPE*c,unsigned r){return c->active[r];}
static bool huntmob_virtual_mpe_memory_configure(HuntMobVirtualMPEMemory*m,uint64_t base,uint64_t length,uint64_t secondary,bool enabled,Error**errp){(void)errp;m->configurations++;m->base=base;m->lengths[0]=length;m->second=secondary;m->lengths[1]=enabled?32768:0;return true;}
static uint64_t huntmob_virtual_mpe_memory_region_length(HuntMobVirtualMPEMemory*m,unsigned r){return m->lengths[r];}
static bool huntmob_virtual_mpe_memory_initialize_region(HuntMobVirtualMPEMemory*m,unsigned r,Error**errp){(void)errp;m->initialized[r]++;huntmob_virtual_mpe_memory_core(m)->active[r]=true;return true;}
