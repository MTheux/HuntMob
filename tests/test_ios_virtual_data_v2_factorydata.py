"""Public temporary directories/C mocks only; no guest mount or private data."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = ROOT / "components/ios-device-lab/provisioning"
SOURCE = PROVISIONING / "prepare_factorydata_virtual_v2.c"


class FactoryDataPublicTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_main_always_unmounts_its_hardware_before_failure_or_checkpoint(self):
        text = SOURCE.read_text()
        main = text[text.index("int main(void) {"):]
        code = r'''
#include <stdio.h>
#include <stdarg.h>
#include <stdbool.h>
#include <string.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
#include <setjmp.h>
#define FACTORY_VM_UUID "public-vm"
#define HUNTMOB_VM_UUID FACTORY_VM_UUID
static jmp_buf done;
static int fault,ids,mounts,unmounts,points,opens,closes,checkpoints,corecalls,errors;
static int virtual_v1_scope(void){return 0;}
static void error_metadata(const char*s,unsigned i,int e){(void)s;(void)i;(void)e;errors++;}
static unsigned test_alarm(unsigned s){(void)s;return 0;}
static mode_t test_umask(mode_t m){(void)m;return 0;}
static int test_lstat(const char*p,struct stat*s){(void)p;memset(s,0,sizeof(*s));s->st_mode=S_IFBLK;return 0;}
static int empty_system_mountpoint(void){points++;return fault==8&&points==2;}
static int command(const char*stage,char*const argv[]){
 if(!strcmp(stage,"mount-hardware")){
  if(strcmp(argv[1],"/dev/disk0s1s4")||strcmp(argv[2],"/mnt6"))return 100;
  mounts++;return fault==1;
 }
 if(strcmp(stage,"unmount-hardware")||strcmp(argv[0],"/sbin/umount")||strcmp(argv[1],"/mnt6"))return 100;
 unmounts++;return fault==7;
}
static int hardware_identity(dev_t*d){ids++;*d=42;return (fault==2&&ids==1)||(fault==5&&ids==2);}
static int test_open(const char*p,int f,...){(void)f;if(strcmp(p,"/mnt6"))return -1;opens++;return fault==3?-1:7;}
static int prepare_factory_ancestry(int fd,dev_t d){if(fd!=7||d!=42)return 100;corecalls++;return fault==4;}
static int test_fsync(int fd){if(fd!=7)return 100;return fault==6?-1:0;}
static int test_close(int fd){if(fd!=7)return 100;closes++;return 0;}
static int test_fprintf(FILE*f,const char*fmt,...){(void)f;if(strstr(fmt,"checkpoint ready"))checkpoints++;return 0;}
static int test_pause(void){longjmp(done,1);}
#define alarm test_alarm
#define umask test_umask
#define lstat test_lstat
#define open test_open
#define fsync test_fsync
#define close test_close
#define fprintf test_fprintf
#define pause test_pause
#define main actual_helper_main
''' + main + r'''
#undef main
static void reset(void){fault=ids=mounts=unmounts=points=opens=closes=checkpoints=corecalls=errors=0;}
int main(void){
 for(int failure=1;failure<=8;failure++){
  reset();fault=failure;
  if(actual_helper_main()!=1||mounts!=1||checkpoints)return 10+failure;
  if(unmounts!=(failure==1?0:1))return 20+failure;
  if(failure==2&&corecalls)return 30;
  if(failure==3&&closes)return 31;
 }
 reset();
 if(!setjmp(done)){actual_helper_main();return 40;}
 if(mounts!=1||unmounts!=1||ids!=2||points!=2||opens!=1||closes!=1||corecalls!=1||checkpoints!=1||errors)return 41;
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="hm-factory-main-public-") as directory:
            source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture"
            source.write_text(code)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_real_metadata_core_creation_idempotency_symlink_mode_and_failure_boundaries(self):
        text = SOURCE.read_text()
        core = text.split("/* BEGIN PUBLIC-TESTABLE DIRECTORY METADATA CORE */", 1)[1].split(
            "/* END PUBLIC-TESTABLE DIRECTORY METADATA CORE */", 1)[0]
        code = r'''
#include <stdbool.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static int chowns,chmods,syncs,errors,fail_chown,fail_sync;
static int public_fstat(int fd,struct stat *s){int r=fstat(fd,s);if(!r){s->st_uid=0;s->st_gid=0;}return r;}
static int public_fchown(int fd,uid_t u,gid_t g){(void)fd;chowns++;if(u||g||fail_chown){errno=EPERM;return -1;}return 0;}
static int public_fchmod(int fd,mode_t m){chmods++;return fchmod(fd,m);}
static int public_fsync(int fd){syncs++;if(fail_sync&&syncs==fail_sync){errno=EIO;return -1;}return fsync(fd);}
static void error_metadata(const char*s,unsigned i,int e){(void)s;(void)i;(void)e;errors++;}
static int silent_log(FILE*f,const char*s,...){(void)f;(void)s;return 0;}
#define fstat public_fstat
#define fchown public_fchown
#define fchmod public_fchmod
#define fsync public_fsync
#define fprintf silent_log
''' + core + r'''
#undef fstat
static int run(const char *path,int wrongdev){int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);struct stat st;if(fd<0||fstat(fd,&st))return 99;
int r=prepare_factory_ancestry(fd,st.st_dev+wrongdev);close(fd);return r;}
static void reset(void){chowns=chmods=syncs=errors=fail_chown=fail_sync=0;}
int main(int argc,char **argv){
if(argc!=2)return 90;umask(0);char p[1024],q[1024];
if(snprintf(p,sizeof(p),"%s/fresh",argv[1])<0||mkdir(p,0755))return 1;
reset();if(run(p,0)||chowns!=5||chmods!=5||syncs!=10||errors)return 2;
reset();if(run(p,0)||chowns||chmods||syncs!=10||errors)return 3;
snprintf(q,sizeof(q),"%s/FactoryData/System/Library",p);if(chmod(q,0700))return 4;
reset();if(run(p,0)!=1||chowns||chmods||errors!=1)return 5;
struct stat st;if(stat(q,&st)||(st.st_mode&07777)!=0700)return 6;
snprintf(p,sizeof(p),"%s/symlink",argv[1]);snprintf(q,sizeof(q),"%s/target",argv[1]);
if(mkdir(p,0755)||mkdir(q,0700))return 7;
char link[1024];snprintf(link,sizeof(link),"%s/FactoryData",p);if(symlink(q,link))return 8;
reset();if(run(p,0)!=1||chowns||chmods||stat(q,&st)||(st.st_mode&07777)!=0700)return 9;
snprintf(p,sizeof(p),"%s/wrongdev",argv[1]);if(mkdir(p,0755))return 10;
reset();if(run(p,1)!=1||errors!=1)return 11;
snprintf(p,sizeof(p),"%s/chown-fail",argv[1]);if(mkdir(p,0755))return 12;
reset();fail_chown=1;if(run(p,0)!=1||chowns!=1||chmods||errors!=1)return 13;
snprintf(p,sizeof(p),"%s/sync-fail",argv[1]);if(mkdir(p,0755))return 14;
reset();fail_sync=1;if(run(p,0)!=1||chowns!=1||chmods!=1||errors!=1)return 15;
snprintf(p,sizeof(p),"%s/file",argv[1]);if(mkdir(p,0755))return 16;
snprintf(q,sizeof(q),"%s/FactoryData",p);int fd=open(q,O_WRONLY|O_CREAT|O_EXCL,0600);if(fd<0)return 17;close(fd);
reset();if(run(p,0)!=1||chowns||chmods||errors!=1)return 18;
return 0;}
'''
        with tempfile.TemporaryDirectory(prefix="hm-factory-public-") as directory:
            source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture"
            source.write_text(code)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(binary), directory], check=True, capture_output=True, timeout=5)

    def test_operational_source_is_hardware_only_and_never_overrides_protection(self):
        source = SOURCE.read_text()
        self.assertIn('"/dev/disk0s1s4"', source)
        self.assertIn('"/mnt6"', source)
        self.assertIn('"A264DAE3-874A-4B57-9FAD-50DDB8E77A47"', source)
        self.assertIn('"9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"', source)
        for token in ("/dev/disk0s1s2", '"/private/var', "MKB", "ClassD", "newfs_apfs", "F_SETPROTECTIONCLASS",
                      "F_GETPROTECTIONCLASS", "O_CREAT", "O_TRUNC", "unlink(", "rmdir("):
            self.assertNotIn(token, source)
        self.assertIn("created && (fchown(child, 0, 0) || fchmod(child, 0755))", source)
        self.assertIn("O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC", source)
        self.assertIn('if (command("unmount-hardware", unmount)) return 1;', source)

    @unittest.skipUnless(shutil.which("xcrun"), "iPhoneOS SDK unavailable")
    def test_native_iphone_compile_without_executing_guest_helper(self):
        sdk = subprocess.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], check=True,
                             capture_output=True, text=True, timeout=30).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="hm-factory-public-iphone-") as directory:
            subprocess.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
                "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"',
                str(SOURCE), "-o", str(Path(directory) / "public-factory-helper")],
                check=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    unittest.main()
