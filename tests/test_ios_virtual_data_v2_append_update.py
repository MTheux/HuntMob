"""Public C dispatch fixtures only. Never runs stock newfs or touches a volume."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = ROOT / "components/ios-device-lab/provisioning"
SOURCE = PROVISIONING / "append_update_virtual_v2.c"


class AppendUpdatePublicTests(unittest.TestCase):
    def compile_run(self, code):
        with tempfile.TemporaryDirectory(prefix="hm-append-update-public-") as directory:
            source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture"
            source.write_text(code)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-I", str(PROVISIONING), str(source), "-o", str(binary)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_exact_append_arguments_reject_user_role_format_flags_and_other_target(self):
        code = r'''#include "append_update_policy_v2.h"
int main(void){
char *argv[]={HUNTMOB_UPDATE_NEWFS,"-A","-o","role=p","-v","Update","/dev/disk0s1",NULL};
if(!huntmob_update_append_arguments(7,argv))return 1;
const char *bad[]={"role=u","role=x","role=h","role=d","role=unknown"};
for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){argv[3]=(char*)bad[i];if(huntmob_update_append_arguments(7,argv))return 2;}
argv[3]="role=p";
for(unsigned i=0;i<7;i++){char *saved=argv[i];argv[i]="-F";if(huntmob_update_append_arguments(7,argv))return 3;argv[i]=saved;}
if(huntmob_update_append_arguments(6,argv)||huntmob_update_append_arguments(8,argv)||huntmob_update_append_arguments(7,NULL))return 4;
argv[7]="-E";if(huntmob_update_append_arguments(7,argv))return 5;
return 0;}'''
        self.compile_run(code)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_main_preflight_and_command_failures_never_checkpoint_or_retry(self):
        text = SOURCE.read_text()
        main = text[text.index("int main(void) {"):]
        code = r'''
#include <stdio.h>
#include <stdarg.h>
#include <sys/types.h>
#include <stdbool.h>
#include <string.h>
#include <setjmp.h>
#include <errno.h>
#include "append_update_policy_v2.h"
#define UPDATE_VM_UUID "public-vm"
#define HUNTMOB_VM_UUID UPDATE_VM_UUID
static jmp_buf done;
static int fault,append_calls,wait_calls,sync_calls,checkpoints,errors;
static int virtual_v1_scope(void){return fault==1;}
static unsigned test_alarm(unsigned n){return n;}
static int block_identity(const char*p,dev_t*d){(void)p;(void)d;return fault==2?-1:1;}
static int existing_slots(dev_t d[5],bool save){(void)save;for(int i=0;i<5;i++)d[i]=100+i;return fault==3;}
static int require_absent(const char*p){return (fault==4&&strstr(p,"s6"))||(fault==5&&strstr(p,"s7"));}
static void failure(const char*s,int e){(void)s;(void)e;errors++;}
static int append_stock_update(char*const argv[]){append_calls++;if(!huntmob_update_append_arguments(7,argv))return 100;return fault==6;}
static int wait_single_new_slot(dev_t d[5]){(void)d;wait_calls++;return fault==7;}
static void test_sync(void){sync_calls++;}
static int test_fprintf(FILE*f,const char*fmt,...){(void)f;if(strstr(fmt,"checkpoint ready"))checkpoints++;return 0;}
static int test_pause(void){longjmp(done,1);}
#define alarm test_alarm
#define sync test_sync
#define fprintf test_fprintf
#define pause test_pause
#define main actual_append_main
''' + main + r'''
#undef main
static void reset(void){fault=append_calls=wait_calls=sync_calls=checkpoints=errors=0;}
int main(void){
for(int f=1;f<=7;f++){reset();fault=f;if(actual_append_main()!=1||checkpoints||sync_calls)return 10+f;
if(append_calls!=(f>=6?1:0)||wait_calls!=(f==7?1:0))return 20+f;}
reset();if(!setjmp(done)){actual_append_main();return 30;}
if(append_calls!=1||wait_calls!=1||sync_calls!=1||checkpoints!=1||errors)return 31;
return 0;}
'''
        self.compile_run(code)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_slot_wait_rejects_extra_alias_changed_missing_and_timeout(self):
        text = SOURCE.read_text()
        slots = text[text.index("static int block_identity("):text.index("static int verify_stock_newfs(")]
        wait = text[text.index("static int wait_single_new_slot("):text.index("int main(void) {")]
        code = r'''
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <errno.h>
static int sixth,seventh,alias,changed,missing,clock_calls,timeout,sleeps;
static int fake_lstat(const char*p,struct stat*s){unsigned slot=0;memset(s,0,sizeof(*s));
if(sscanf(p,"/dev/disk0s1s%u",&slot)!=1)return -1;
if(slot==7&&!seventh){errno=ENOENT;return -1;}
if(slot==6&&!sixth){errno=ENOENT;return -1;}
if((int)slot==missing){errno=ENOENT;return -1;}
s->st_mode=(slot==6&&sixth==2)?S_IFLNK:S_IFBLK;
s->st_rdev=slot+10;if(slot==6&&alias)s->st_rdev=11;if((int)slot==changed)s->st_rdev+=100;return 0;}
static int fake_clock(clockid_t c,struct timespec*t){(void)c;t->tv_nsec=0;t->tv_sec=clock_calls++*(timeout?61:1);return 0;}
static int fake_sleep(unsigned n){(void)n;sleeps++;sixth=1;return 0;}
#define lstat fake_lstat
#define clock_gettime fake_clock
#define usleep fake_sleep
''' + slots + wait + r'''
static void reset(void){sixth=1;seventh=alias=changed=missing=clock_calls=timeout=sleeps=0;errno=0;}
int main(void){dev_t old[5];reset();if(existing_slots(old,true))return 1;
if(wait_single_new_slot(old)||sleeps)return 2;
reset();sixth=0;if(wait_single_new_slot(old)||sleeps!=1)return 3;
reset();seventh=1;if(wait_single_new_slot(old)!=1||errno!=EEXIST||sleeps)return 4;
reset();alias=1;if(wait_single_new_slot(old)!=1||errno!=EINVAL)return 5;
reset();changed=3;if(wait_single_new_slot(old)!=1||errno!=EINVAL)return 6;
reset();missing=4;if(wait_single_new_slot(old)!=1||errno!=ENOENT)return 7;
reset();sixth=2;if(wait_single_new_slot(old)!=1||errno!=EINVAL)return 8;
reset();sixth=0;timeout=1;if(wait_single_new_slot(old)!=1||errno!=ETIMEDOUT||sleeps)return 9;
return 0;}
'''
        self.compile_run(code)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_stock_child_status_and_signal_are_required_not_just_pid(self):
        text = SOURCE.read_text()
        child = text.split("static int append_stock_update(char *const argv[]) {", 1)[1].split(
            "static int wait_single_new_slot", 1)[0]
        code = r'''
#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <signal.h>
#include <errno.h>
#include "append_update_policy_v2.h"
static int pin_bad,mode,forks,waits,errors;
static int verify_stock_newfs(void){return pin_bad;}
static void failure(const char*s,int e){(void)s;(void)e;errors++;}
static pid_t fake_fork(void){forks++;return mode==4?-1:123;}
static pid_t fake_waitpid(pid_t pid,int*s,int opts){(void)opts;waits++;if(mode==1)*s=2<<8;else if(mode==2)*s=SIGKILL;else *s=0;return pid;}
static unsigned fake_alarm(unsigned n){return n;}
static int never_exec(const char*p,char*const argv[]){(void)p;(void)argv;return -1;}
static void never_exit(int n){(void)n;}
#define fork fake_fork
#define waitpid fake_waitpid
#define alarm fake_alarm
#define execv never_exec
#define _exit never_exit
static int append_stock_update(char *const argv[]) {
''' + child + r'''
int main(void){char *argv[]={HUNTMOB_UPDATE_NEWFS,"-A","-o","role=p","-v","Update","/dev/disk0s1",NULL};
for(int m=0;m<=2;m++){mode=m;forks=waits=0;int r=append_stock_update(argv);if((r!=0)!=(m!=0)||forks!=1||waits!=1)return 10+m;}
pin_bad=1;forks=waits=0;if(append_stock_update(argv)!=1||forks||waits)return 20;
pin_bad=0;argv[3]="role=u";if(append_stock_update(argv)!=1||forks||waits)return 21;
argv[3]="role=p";mode=4;forks=waits=0;if(append_stock_update(argv)!=1||forks!=1||waits)return 22;
return 0;}
'''
        self.compile_run(code)

    def test_source_has_only_the_stock_append_route_and_no_mount_or_keys(self):
        text = SOURCE.read_text()
        self.assertIn('"8dbd1aa6abbfbae8d0797e35b518441172f2a1e3b8bb6cb3f8f9186aa7dfe997"', text)
        self.assertIn('"-A", "-o", "role=p", "-v", "Update", "/dev/disk0s1"', text)
        self.assertIn("alarm(60)", text)
        self.assertIn("alarm(150)", text)
        for token in ("MKB", "ClassD", "mount_apfs", "umount", "role=d", "role=u", '"-E"', '"-P"', '"-F"',
                      "O_CREAT", "O_TRUNC", '"/private/var', '"/mnt2"'):
            self.assertNotIn(token, text)

    @unittest.skipUnless(shutil.which("xcrun"), "iPhoneOS SDK unavailable")
    def test_iphone_sdk_build_only_never_executes_the_append_tool(self):
        sdk = subprocess.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], check=True,
                             capture_output=True, text=True, timeout=30).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="hm-update-public-iphone-") as directory:
            subprocess.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
                "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"',
                str(SOURCE), "-o", str(Path(directory) / "public-append-helper")],
                check=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    unittest.main()
