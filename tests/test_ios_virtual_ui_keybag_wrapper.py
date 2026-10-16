"""Execute real C control flow against public mocks; no live processes/volumes."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = ROOT / "components/ios-device-lab/provisioning"
SOURCE = PROVISIONING / "keybagd_ui_process_observer_v2.c"
SOURCE_SHA = "7e25f2b61831d92111d67db767ffeb2728e738cd5e63296c1b5e614549dfd696"


class UIKeybagWrapperPublicTests(unittest.TestCase):
    def compile_run(self, code):
        with tempfile.TemporaryDirectory(prefix="hm-ui-keybag-public-") as directory:
            source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture"
            source.write_text(code)
            result = subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-I", str(PROVISIONING), str(source), "-o", str(binary)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_wrapper_source_is_exact_reviewed_artifact(self):
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), SOURCE_SHA)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_main_preserves_stock_status_and_only_spawns_confirmed_owned_sampler(self):
        text = SOURCE.read_text()
        status = text[text.index("static int stock_status("):text.index("int main(")]
        main = text[text.index("int main("):]
        self.compile_run(r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdbool.h>
#include <errno.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <setjmp.h>
#include "post_keybag_sequence_v2.h"
#define STOCK_KEYBAGD "/usr/libexec/huntmob-original/keybagd"
#define STOCK_KEYBAGD_SHA256 "4cd2506d4f47a150da3748887127eca0420051d3095bf6dd1470f35805920cf6"
#define OBSERVER "/usr/libexec/huntmob-ui-process-observer"
#define HUNTMOB_EXPECTED_OBSERVER_SHA256 "public-signed-observer-hash"
static jmp_buf jumped;
static int fault,status_value,forks,waits,execs,scope_calls,data_calls,stock_checks,observer_checks;
static int group_calls,getgroup_calls,kills,kill_pid,kill_sig,alarm_100,alarm_90,alarm_130,alarm_zero;
static int enable_calls,post_failed,spawn_failed,group_failed,spawned,exec_kind,exit_value,signal_calls;
static char **initial_argv;
static int virtual_v1_scope(void){scope_calls++;return (fault==1&&scope_calls==1)||(fault==2&&scope_calls==2);}
static int verify_program(const char*p,const char*h){
 if(!strcmp(p,STOCK_KEYBAGD)){stock_checks++;if(strcmp(h,STOCK_KEYBAGD_SHA256))abort();return fault==3;}
 if(strcmp(p,OBSERVER)||strcmp(h,HUNTMOB_EXPECTED_OBSERVER_SHA256))abort();observer_checks++;return fault==4;}
static int enable_alarm(void){enable_calls++;return fault==5;}
static int data_identity(void){data_calls++;return (fault==6&&data_calls==1)||(fault==7&&data_calls==2);}
static unsigned fake_alarm(unsigned n){if(!n)alarm_zero++;else if(n==100)alarm_100++;else if(n==90)alarm_90++;else if(n==130)alarm_130++;else abort();return 0;}
static pid_t fake_fork(void){forks++;if((fault==8&&forks==1)||(fault==9&&forks==2))return -1;
 if((fault==10&&forks==1)||(fault==11&&forks==2))return 0;return 1000+forks;}
static pid_t fake_waitpid(pid_t child,int*s,int options){waits++;if(options||child!=1001+(group_failed?1:0))abort();
 if(fault==12&&waits==1){errno=EINTR;return -1;}if(fault==13){errno=ECHILD;return -1;}*s=status_value;return child;}
static int fake_execv(const char*p,char *const args[]){execs++;
 if(!strcmp(p,OBSERVER)){if(strcmp(args[0],"huntmob-ui-process-observer")||strcmp(args[1],"--metadata-only")||args[2])abort();exec_kind=3;}
 else if(!strcmp(p,STOCK_KEYBAGD)){if(args==initial_argv)exec_kind=1;
 else {if(strcmp(args[0],"keybagd")||strcmp(args[1],"--init")||args[2])abort();exec_kind=2;}}
 else abort();return -1;}
static void fake_exit(int value){exit_value=value;longjmp(jumped,1);}
static int fake_setpgid(pid_t pid,pid_t group){group_calls++;if(pid!=group||(pid!=0&&pid!=1002))abort();
 if(fault==14){errno=EPERM;return -1;}if(fault==15){errno=EACCES;return -1;}return 0;}
static pid_t fake_getpgid(pid_t pid){getgroup_calls++;if(pid!=1002)abort();return fault==16?999:1002;}
static int fake_kill(pid_t pid,int sig){kills++;kill_pid=pid;kill_sig=sig;return 0;}
static pid_t fake_getpid(void){return 4242;}
static void (*fake_signal(int sig,void(*handler)(int)))(int){signal_calls++;if(sig!=SIGTERM||handler!=SIG_DFL)abort();return SIG_DFL;}
static int fake_fprintf(FILE*f,const char*format,...){(void)f;
 if(strstr(format,"wrapper-post-init-guard-failed"))post_failed++;
 if(strstr(format,"observer-spawn-failed"))spawn_failed++;
 if(strstr(format,"observer-group-failed"))group_failed++;
 if(strstr(format,"observer-spawned"))spawned++;
 return 1;}
#define alarm fake_alarm
#define fork fake_fork
#define waitpid fake_waitpid
#define execv fake_execv
#define _exit fake_exit
#define setpgid fake_setpgid
#define getpgid fake_getpgid
#define kill fake_kill
#define getpid fake_getpid
#define signal fake_signal
#define fprintf fake_fprintf
#define main actual_main
''' + status + main + r'''
#undef main
static void reset(void){fault=status_value=forks=waits=execs=scope_calls=data_calls=stock_checks=observer_checks=0;
 group_calls=getgroup_calls=kills=kill_pid=kill_sig=alarm_100=alarm_90=alarm_130=alarm_zero=0;
 enable_calls=post_failed=spawn_failed=group_failed=spawned=exec_kind=exit_value=signal_calls=0;}
int main(void){char *daemon[]={"/usr/libexec/keybagd","-t","15",NULL};char *init[]={"keybagd","--init",NULL};
 reset();initial_argv=daemon;if(actual_main(3,daemon)!=127||execs!=1||exec_kind!=1||forks||observer_checks||enable_calls||alarm_zero!=1||alarm_100)return 1;
 reset();initial_argv=init;if(actual_main(2,init)||forks!=2||waits!=1||observer_checks!=1||group_calls!=1||getgroup_calls!=1||spawned!=1||alarm_zero!=1||kills)return 2;
 for(int code=1;code<=125;code+=31){reset();status_value=code<<8;if(actual_main(2,init)!=code||forks!=1||observer_checks||group_calls||spawned)return 3;}
 reset();status_value=SIGTERM;if(actual_main(2,init)!=128+SIGTERM||forks!=1||observer_checks||kills!=1||kill_pid!=4242||kill_sig!=SIGTERM||signal_calls!=1)return 4;
 for(int bad=1;bad<=16;bad++){
 if(bad==10||bad==11)continue;reset();fault=bad;int result=actual_main(2,init);
 if(bad==2||bad==4||bad==7){if(result||post_failed!=1||forks!=1||spawned||kills)return 10+bad;}
 else if(bad==9){if(result||spawn_failed!=1||spawned||kills)return 30;}
 else if(bad==14||bad==16){if(result||group_failed!=1||kills!=1||kill_pid!=1002||kill_sig!=SIGKILL||waits!=2||alarm_zero!=1||spawned)return 31;}
 else if(bad==15){if(result||spawned!=1||kills||getgroup_calls!=1)return 32;}
 else if(bad==12){if(result||waits!=2||spawned!=1)return 33;}
 else if(result!=125||observer_checks||spawned)return 40+bad;
 }
 reset();fault=10;if(!setjmp(jumped)){actual_main(2,init);return 60;}
 if(exit_value!=127||exec_kind!=2||alarm_90!=1||observer_checks||waits)return 61;
 reset();fault=11;if(!setjmp(jumped)){actual_main(2,init);return 62;}
 if(exit_value!=127||exec_kind!=3||alarm_130!=1||enable_calls!=2||group_calls!=1||getgroup_calls)return 63;
 reset();char *bad[]={"keybagd","--init","extra",NULL};if(actual_main(3,bad)!=125||forks||execs||observer_checks)return 64;
 return 0;}
''')

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_alarm_setup_resets_ignored_handler_and_unblocks_inherited_mask(self):
        text = SOURCE.read_text()
        function = text[text.index("static int enable_alarm("):text.index("static int data_identity(")]
        self.compile_run(r'''
#include <signal.h>
#include <string.h>
static int fault,calls,default_reset,unblocked,added;
static int fake_empty(sigset_t*s){memset(s,0,sizeof(*s));calls++;return fault==calls;}
static int fake_action(int sig,const struct sigaction*a,struct sigaction*old){calls++;
 if(sig!=SIGALRM||a->sa_handler!=SIG_DFL||old)return 1;default_reset++;return fault==calls;}
static int fake_add(sigset_t*s,int sig){(void)s;calls++;if(sig!=SIGALRM)return 1;added++;return fault==calls;}
static int fake_mask(int how,const sigset_t*s,sigset_t*old){calls++;if(how!=SIG_UNBLOCK||!s||old)return 1;unblocked++;return fault==calls;}
#undef sigemptyset
#define sigemptyset fake_empty
#define sigaction(a,b,c) fake_action(a,b,c)
#undef sigaddset
#define sigaddset fake_add
#define sigprocmask fake_mask
''' + function + r'''
int main(void){if(enable_alarm()||calls!=5||default_reset!=1||unblocked!=1||added!=1)return 1;
 for(int bad=1;bad<=5;bad++){fault=bad;calls=default_reset=unblocked=added=0;if(!enable_alarm()||calls!=bad)return 10+bad;}
 return 0;}
''')

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_program_owner_exception_requires_exact_readonly_system_and_never_relaxes_stock(self):
        text = SOURCE.read_text()
        functions = text[text.index("static int readonly_system_identity(void);"):text.index("static int enable_alarm(")]
        self.compile_run(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <uuid/uuid.h>
#define OBSERVER "/usr/libexec/huntmob-ui-process-observer"
#define STOCK_KEYBAGD "/usr/libexec/huntmob-original/keybagd"
#define CC_SHA256_DIGEST_LENGTH 32
struct fake_hash {int count;};
typedef struct fake_hash CC_SHA256_CTX;
typedef unsigned CC_LONG;
static int fault,owner,read_calls,ro_calls,hash_calls,closed;
static int fake_open(const char*p,int flags){if(strcmp(p,OBSERVER)&&strcmp(p,STOCK_KEYBAGD))abort();
 if(flags!=(O_RDONLY|O_NOFOLLOW|O_CLOEXEC))abort();return 8;}
static int fake_fstat(int fd,struct stat*s){if(fd!=8)abort();memset(s,0,sizeof(*s));s->st_mode=S_IFREG|0755;s->st_nlink=1;
 s->st_uid=owner;s->st_size=1;s->st_dev=3;s->st_ino=42;s->st_mtime=7;s->st_ctime=8;
 if(fault==10)s->st_mode|=0020;if(fault==11)s->st_nlink=2;return 0;}
static int fake_lstat(const char*p,struct stat*s){(void)p;fake_fstat(8,s);if(fault==12)s->st_ino++;return 0;}
static ssize_t fake_read(int fd,void*buffer,size_t size){if(fd!=8||size!=8192)abort();if(read_calls++)return 0;*(char*)buffer='x';return 1;}
static int fake_close(int fd){if(fd!=8)abort();closed++;return 0;}
static int fake_init(CC_SHA256_CTX*c){c->count=0;hash_calls++;return 1;}
static int fake_update(CC_SHA256_CTX*c,const void*p,CC_LONG size){(void)p;c->count+=(int)size;return 1;}
static int fake_final(unsigned char*out,CC_SHA256_CTX*c){if(c->count!=1)abort();memset(out,fault==13?1:0,32);return 1;}
static int fake_statfs(const char*p,struct statfs*s){if(strcmp(p,"/"))abort();ro_calls++;memset(s,0,sizeof(*s));
 strcpy(s->f_fstypename,fault==1?"hfs":"apfs");strcpy(s->f_mntonname,fault==2?"/other":"/");
 strcpy(s->f_mntfromname,fault==3?"/dev/disk0s1s2":"/dev/disk0s1s1");s->f_flags=fault==4?0:MNT_RDONLY;return fault==5;}
static int fake_uuid_parse(const char*value,unsigned char*out){if(strcmp(value,"5133F48D-5D9E-499B-A8BA-45E692E36FD9"))abort();
 memset(out,1,16);return fault==6;}
static int fake_getattr(const char*p,struct attrlist*a,void*buffer,size_t size,unsigned long options){
 if(strcmp(p,"/")||a->bitmapcount!=ATTR_BIT_MAP_COUNT||a->volattr!=(ATTR_VOL_INFO|ATTR_VOL_UUID)||size!=20||options)abort();
 uint32_t length=fault==8?19:20;memcpy(buffer,&length,4);memset((char*)buffer+4,fault==9?2:1,16);return fault==7;}
#define open fake_open
#define fstat fake_fstat
#define lstat fake_lstat
#define read fake_read
#define close fake_close
#define CC_SHA256_Init fake_init
#define CC_SHA256_Update fake_update
#define CC_SHA256_Final fake_final
#define statfs(a,b) fake_statfs(a,b)
#define uuid_parse fake_uuid_parse
#define getattrlist fake_getattr
''' + functions + r'''
static void reset(void){fault=read_calls=ro_calls=hash_calls=closed=0;owner=501;}
int main(void){const char *zero="0000000000000000000000000000000000000000000000000000000000000000";
 reset();if(verify_program(OBSERVER,zero)||ro_calls!=1||hash_calls!=1||closed!=1)return 1;
 reset();if(!verify_program(STOCK_KEYBAGD,zero)||ro_calls||hash_calls||closed!=1)return 2;
 reset();owner=0;if(verify_program(STOCK_KEYBAGD,zero)||ro_calls||closed!=1)return 3;
 reset();owner=0;if(verify_program(OBSERVER,zero)||ro_calls)return 4;
 for(int bad=1;bad<=13;bad++){reset();fault=bad;if(!verify_program(OBSERVER,zero)||closed!=1)return 10+bad;
 if(bad<=9&&hash_calls)return 30+bad;}
 return 0;}
''')

    @unittest.skipUnless(shutil.which("xcrun"), "Apple SDK unavailable")
    def test_actual_frozen_wrapper_compiles_for_iphoneos_ios14(self):
        sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True, timeout=30).strip()
        with tempfile.TemporaryDirectory(prefix="hm-ui-keybag-ios-build-") as directory:
            result = subprocess.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
                "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"',
                '-DHUNTMOB_EXPECTED_DATA_UUID="2F4BDE84-276C-414B-839A-2B2E996C1BF6"',
                '-DHUNTMOB_EXPECTED_OBSERVER_SHA256="' + "0" * 64 + '"',
                "-c", str(SOURCE), "-o", str(Path(directory) / "wrapper.o")], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
