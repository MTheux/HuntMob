"""Execute only the real shim main with synthetic callbacks; no stock exec/I/O."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = ROOT / "components/ios-device-lab/provisioning"


class ActualShimDispatchPublicFixture(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_actual_main_isolates_daemon_init_reject_and_failure_routes(self):
        source = (PROVISIONING / "verify_post_keybag_data_v2.c").read_text()
        # Compile the exact current dispatch, replacing ALL operational callees
        # with local public stubs. Neither actual stock/probe functions nor the
        # iOS scope/body are linked into this host test.
        main = source[source.index("int main(int argc, char **argv) {"):]
        harness = r'''
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <setjmp.h>
#include "post_keybag_sequence_v2.h"
#define HUNTMOB_POST_KEYBAG_PATH_SHIM_V2 1
#define HUNTMOB_EXPECTED_CANARY_SHA256 "public-placeholder-not-evaluated"
#define STOCK_KEYBAGD "/usr/libexec/huntmob-original/keybagd"
struct verifier {unsigned char expected_digest[32];const char *result;};
static jmp_buf done;
static int scope_bad,pin_bad,fail_step,count,init_calls,probe_calls,exec_calls,checkpoint_calls;
static unsigned alarms[4],alarm_count;
static char order[8];
static char *const *expected_argv;
static int virtual_v1_scope(void){return scope_bad;}
static int verify_stock(void){return pin_bad;}
static int parse_digest(const char*h,unsigned char*d){(void)h;(void)d;return 0;}
static int data_identity(void*p){(void)p;order[count++]='I';return count==fail_step;}
static int stock_init(void*p){(void)p;init_calls++;order[count++]='S';return count==fail_step;}
static int read_probe(void*p){probe_calls++;order[count++]='P';((struct verifier*)p)->result="public";return count==fail_step;}
static unsigned fixture_alarm(unsigned n){alarms[alarm_count++]=n;return 0;}
static int fixture_execv(const char*path,char*const argv[]){
 if(strcmp(path,STOCK_KEYBAGD)||argv!=expected_argv)exec_calls=100;else exec_calls++;
 return -1; /* Always simulate exec failure. Never call host exec. */
}
static int fixture_fprintf(FILE*f,const char*format,...){(void)f;if(strstr(format,"checkpoint ready"))checkpoint_calls++;return 0;}
static int fixture_pause(void){longjmp(done,1);}
#define alarm fixture_alarm
#define execv fixture_execv
#define fprintf fixture_fprintf
#define pause fixture_pause
#define main tested_shim_main
''' + main + r'''
#undef main
static void reset(void){scope_bad=pin_bad=fail_step=count=init_calls=probe_calls=exec_calls=checkpoint_calls=0;alarm_count=0;memset(order,0,sizeof(order));}
int main(void){
 char *daemon[]={"/usr/libexec/keybagd","-t","15",NULL};
 char *init[]={"keybagd","--init",NULL};
 char *wrong[]={"keybagd","-t","15",NULL};
 reset();expected_argv=daemon;
 if(tested_shim_main(3,daemon)!=1||exec_calls!=1||count||init_calls||probe_calls||checkpoint_calls||
    alarm_count!=2||alarms[0]!=180||alarms[1]!=0)return 1;
 reset();expected_argv=daemon;pin_bad=1;
 if(tested_shim_main(3,daemon)!=1||exec_calls||count||init_calls||probe_calls||checkpoint_calls||alarm_count!=1)return 2;
 reset();expected_argv=daemon;scope_bad=1;
 if(tested_shim_main(3,daemon)!=1||exec_calls||count||checkpoint_calls)return 3;
 reset();expected_argv=wrong;
 if(tested_shim_main(3,wrong)!=1||exec_calls||count||init_calls||probe_calls||checkpoint_calls)return 4;
 for(int fail=1;fail<=4;fail++){
  reset();expected_argv=init;fail_step=fail;
  if(tested_shim_main(2,init)!=1||exec_calls||count!=fail||memcmp(order,"ISIP",(size_t)count)||checkpoint_calls)return 10+fail;
 }
 reset();expected_argv=init;
 if(!setjmp(done)){tested_shim_main(2,init);return 20;}
 if(exec_calls||count!=4||memcmp(order,"ISIP",4)||init_calls!=1||probe_calls!=1||checkpoint_calls!=1||
    alarm_count!=1||alarms[0]!=180)return 21;
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="hm-shim-dispatch-public-") as directory:
            fixture = Path(directory) / "dispatch.c"
            executable = Path(directory) / "dispatch"
            fixture.write_text(harness)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-I", str(PROVISIONING), str(fixture), "-o", str(executable)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
