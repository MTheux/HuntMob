"""Public C fixtures; never queries a live process, device, VM or keybag."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = ROOT / "components/ios-device-lab/provisioning"
SOURCE = PROVISIONING / "observe_ui_processes_v2.c"


class UIProcessObserverPublicTests(unittest.TestCase):
    def compile_run(self, code):
        with tempfile.TemporaryDirectory(prefix="hm-ui-process-public-") as directory:
            source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture"
            source.write_text(code)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-I", str(PROVISIONING), str(source), "-o", str(binary)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_exact_comm_allowlist_never_propagates_process_strings(self):
        self.compile_run(r'''
#include "ui_process_observer_policy_v2.h"
int main(void) {
const char *good[]={"SpringBoard","backboardd","runningboardd"};
for(int i=0;i<3;i++)if(hm_ui_select(good[i],strlen(good[i])+1)!=(enum hm_ui_label)(i+1))return 1;
const char *bad[]={"SpringBoard.evil","SpringBoardX","springboard","backboardd\n","runningboardd-extra","","sshd"};
for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++)if(hm_ui_select(bad[i],strlen(bad[i])+1))return 2;
char raw[16];memset(raw,'X',sizeof(raw));memcpy(raw,"SpringBoard",11);
if(hm_ui_select(raw,sizeof(raw))||hm_ui_select("SpringBoard",11)||hm_ui_select(NULL,1)||hm_ui_select("",0))return 3;
if(hm_ui_static_label(HM_UI_NONE)||hm_ui_static_label((enum hm_ui_label)99))return 4;
return 0;}
''')

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_real_policy_bounded_sampling_absence_and_failure_boundaries(self):
        self.compile_run(r'''
#include "ui_process_observer_policy_v2.h"
struct fixture {uint64_t now;unsigned snapshots,waits,emitted;int fault;};
static int clock_ms(void *p,uint64_t *now){struct fixture*f=p;if(f->fault==1)return 1;*now=f->now;return 0;}
static int wait_ms(void*p,uint64_t until){struct fixture*f=p;f->waits++;if(f->fault==2)return 1;
 if(f->fault!=3)f->now=until;if(f->fault==4)f->now=HM_UI_MAX_DURATION_MS;return 0;}
static int snapshot(void*p,struct hm_ui_row*r,size_t*n){struct fixture*f=p;f->snapshots++;
 if(f->fault==5)return 1;*n=f->fault==6?4:3;
 for(unsigned i=0;i<3;i++)r[i]=(struct hm_ui_row){(enum hm_ui_label)(i+1),100+(int)i,2};
 if(f->fault==7)r[1].label=HM_UI_SPRINGBOARD;if(f->fault==8)r[0].pid=0;
 if(f->fault==9)r[0].status=0;if(f->fault==10)r[0].status=8;
 if(f->fault==11)r[0].label=(enum hm_ui_label)99;if(f->fault==12)*n=0;
 if(f->fault==13)f->now=HM_UI_MAX_DURATION_MS;if(f->fault==14&&f->snapshots>1)f->now=0;return 0;}
static int emit(void*p,unsigned sample,const struct hm_ui_row*r){struct fixture*f=p;
 if(sample>=24||!hm_ui_static_label(r->label))return 1;f->emitted++;return f->fault==15;}
int main(void){struct fixture f={0};struct hm_ui_operations o={&f,snapshot,clock_ms,wait_ms,emit};
 if(hm_ui_observe(&o)||f.snapshots!=24||f.waits!=23||f.emitted!=72||f.now!=115000)return 1;
 for(int bad=1;bad<=15;bad++){if(bad==12)continue;memset(&f,0,sizeof(f));f.fault=bad;
 if(hm_ui_observe(&o)!=1||f.snapshots>24||f.emitted>72)return 10+bad;}
 memset(&f,0,sizeof(f));f.fault=12;if(hm_ui_observe(&o)||f.snapshots!=24||f.emitted)return 30;
 memset(&f,0,sizeof(f));f.now=UINT64_MAX;if(hm_ui_observe(&o)!=1||f.snapshots)return 31;
 if(hm_ui_observe(NULL)!=1)return 32;o.emit=NULL;if(hm_ui_observe(&o)!=1)return 33;
 return 0;}
''')

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_snapshot_exact_mib_size_and_filter_fail_closed(self):
        text = SOURCE.read_text()
        native = text[text.index("struct native_ui_context"):text.index("static int native_clock(")]
        self.compile_run(r'''
#include <errno.h>
#include <stdlib.h>
#include "ui_process_observer_policy_v2.h"
#define CTL_KERN 1
#define KERN_PROC 14
#define KERN_PROC_ALL 0
struct extern_proc { char p_comm[17]; int p_pid; int p_stat; };
struct kinfo_proc {struct extern_proc kp_proc;};
static unsigned calls;static int fault;
static int fake_sysctl(int*m,unsigned n,void*out,size_t*size,void*newp,size_t newlen){
 calls++;if(n!=4||m[0]!=CTL_KERN||m[1]!=KERN_PROC||m[2]!=KERN_PROC_ALL||m[3]||newp||newlen)return 1;
 if(fault==1)return 1;
 if(!out){*size=fault==2?HM_UI_MAX_BUFFER+1:sizeof(struct kinfo_proc)*4;return 0;}
 if(*size!=HM_UI_MAX_BUFFER)return 1;if(fault==3)return 1;
 struct kinfo_proc *p=out;memset(p,0,sizeof(*p)*4);
 const char *names[]={"SpringBoard","backboardd","runningboardd","private-secret"};
 for(unsigned i=0;i<4;i++){strcpy(p[i].kp_proc.p_comm,names[i]);p[i].kp_proc.p_pid=100+(int)i;p[i].kp_proc.p_stat=2;}
 if(fault==4)strcpy(p[3].kp_proc.p_comm,"SpringBoard");
 *size=fault==5?HM_UI_MAX_BUFFER+1:sizeof(*p)*4+(fault==6?1:0);return 0;}
#define sysctl fake_sysctl
''' + native + r'''
int main(void){struct native_ui_context c={malloc(HM_UI_MAX_BUFFER)};struct hm_ui_row rows[3];size_t n;
 if(!c.buffer)return 1;if(native_snapshot(&c,rows,&n)||n!=3||calls!=2)return 2;
 for(unsigned i=0;i<3;i++)if(rows[i].label!=(enum hm_ui_label)(i+1)||rows[i].pid!=100+(int)i)return 3;
 for(int bad=1;bad<=6;bad++){fault=bad;calls=0;if(!native_snapshot(&c,rows,&n))return 10+bad;
 if(calls>(bad<=2?1u:2u))return 20+bad;}
 free(c.buffer);return 0;}
''')

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_main_exact_arguments_scope_alarm_and_memory_cleanup(self):
        text = SOURCE.read_text()
        main = text[text.index("int main(int argc, char *argv[]) {"):]
        self.compile_run(r'''
#include <stdlib.h>
#include <stdio.h>
#include "ui_process_observer_policy_v2.h"
#define HUNTMOB_VM_UUID "public-vm"
#define UI_OBSERVER_VM_UUID "public-vm"
struct native_ui_context {void *buffer;};
static unsigned armed,cancelled,allocated,freed,observed,scope_calls;static int fault;
static unsigned fake_alarm(unsigned n){if(n==130)armed++;else if(!n)cancelled++;else abort();return 0;}
static unsigned fake_getuid(void){return fault==1?501:0;}
static int virtual_v1_scope(void){scope_calls++;return fault==2;}
static void *fake_malloc(size_t n){allocated++;if(n!=HM_UI_MAX_BUFFER)abort();return fault==3?NULL:malloc(n);}
static void fake_free(void *p){freed++;free(p);}
static int native_snapshot(void*p,struct hm_ui_row*r,size_t*n){(void)p;(void)r;(void)n;return 0;}
static int native_clock(void*p,uint64_t*t){(void)p;(void)t;return 0;}
static int native_wait(void*p,uint64_t t){(void)p;(void)t;return 0;}
static int native_emit(void*p,unsigned s,const struct hm_ui_row*r){(void)p;(void)s;(void)r;return 0;}
static int fake_observe(const struct hm_ui_operations*o){if(!o->context)abort();observed++;return fault==4;}
#define alarm fake_alarm
#define getuid fake_getuid
#define malloc fake_malloc
#define free fake_free
#define hm_ui_observe fake_observe
#define main actual_observer_main
''' + main + r'''
#undef main
static void reset(void){armed=cancelled=allocated=freed=observed=scope_calls=0;fault=0;}
int main(void){char *argv[]={"huntmob-ui-process-observer","--metadata-only",NULL,NULL};
reset();if(actual_observer_main(2,argv)||armed!=1||cancelled!=1||allocated!=1||freed!=1||observed!=1)return 1;
for(int bad=1;bad<=4;bad++){reset();fault=bad;if(actual_observer_main(2,argv)!=1||armed!=1||cancelled||observed>(bad==4?1u:0u))return 10+bad;
if(freed!=(bad==4?1u:0u))return 20+bad;}
for(int bad=0;bad<5;bad++){reset();char *saved;
 if(bad==0){if(actual_observer_main(1,argv)!=1)return 30;}
 if(bad==1){saved=argv[0];argv[0]="other";if(actual_observer_main(2,argv)!=1)return 31;argv[0]=saved;}
 if(bad==2){saved=argv[1];argv[1]="--read-all";if(actual_observer_main(2,argv)!=1)return 32;argv[1]=saved;}
 if(bad==3){argv[2]="extra";if(actual_observer_main(2,argv)!=1)return 33;argv[2]=NULL;}
 if(bad==4&&actual_observer_main(2,NULL)!=1)return 34;
 if(allocated||observed||scope_calls)return 40+bad;}
return 0;}
''')

    @unittest.skipUnless(shutil.which("xcrun"), "Apple SDK unavailable")
    def test_actual_source_compiles_for_iphoneos_ios14(self):
        sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True, timeout=30).strip()
        with tempfile.TemporaryDirectory(prefix="hm-ui-process-ios-build-") as directory:
            subprocess.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
                "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"',
                "-c", str(SOURCE), "-o", str(Path(directory) / "observer.o")], check=True, capture_output=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
