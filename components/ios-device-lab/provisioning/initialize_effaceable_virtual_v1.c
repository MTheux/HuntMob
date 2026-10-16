/* AUTHORIZED TESTING ONLY — OWN FRESH VIRTUAL RAMDISK PROFILE.
 * Host must gate the exact owned cohort and all-zero fresh namespace6 before
 * launch. No device argument, SEP/MKB/ClassD, lockers, keys or filesystem
 * creation. The stock SecureRoot check is neither changed nor bypassed. */
#include "virtual_v1_scope.h"
#include <dlfcn.h>
#include <mach/mach.h>
#include <sys/mount.h>
#include <sys/wait.h>

static int online_preloaded_controller(void) {
    /* Original restore tool's explicit preloaded-firmware path. It does not
     * validate Apple ANS firmware on this own virtual-controller model. The
     * host requires the vendor namespace-format denial before this runs. */
    pid_t pid=fork();
    if(pid<0) return 1;
    if(pid==0) {
        alarm(15);
        char *const args[]={"/usr/bin/nvmefwupdater","--nvme","enable-skip",NULL};
        execv(args[0],args);
        _exit(127);
    }
    int status=0;
    while(waitpid(pid,&status,0)<0) if(errno!=EINTR) return 1;
    fprintf(stderr,"HuntMob: preloaded NVMe online exit=%d signal=%d\n",
            WIFEXITED(status)?WEXITSTATUS(status):-1,WIFSIGNALED(status)?WTERMSIG(status):0);
    return !WIFEXITED(status)||WEXITSTATUS(status)!=0;
}

typedef int (*ScalarCall)(unsigned,unsigned,const uint64_t *,unsigned,uint64_t *,unsigned *);
/* Matching diagnostics only: public class names and bounded object counts.
 * No registry properties, paths, key/locker bytes or formatting calls. Count
 * is capped at64; every returned object and iterator is released. */
static void service_counts(void *(*matching)(const char *),
                           int (*find_all)(unsigned,void *,unsigned *),
                           unsigned (*next)(unsigned),int (*release)(unsigned)) {
    static const char *const classes[]={"IOPlatformExpertDevice","IONVMeEffaceableDevice",
                                        "AppleEffaceableBlockDevice","AppleEffaceableStorage"};
    for(unsigned i=0;i<sizeof(classes)/sizeof(classes[0]);i++) {
        unsigned iterator=0,count=0;
        void *filter=matching(classes[i]);
        /* A null filter must not turn this into an unscoped registry query. */
        int status=filter?find_all(0,filter,&iterator):-1;
        if(!status&&iterator) {
            while(count<64) {
                unsigned object=next(iterator);
                if(!object) break;
                release(object);
                count++;
            }
        }
        if(iterator) release(iterator);
        fprintf(stderr,"HuntMob: trusted effaceable class=%s status=%x count=%u\n",
                classes[i],status,count);
    }
}
static int query(ScalarCall call,unsigned connection,const char *phase,int *formatted) {
    uint64_t value=UINT64_MAX;
    unsigned count=1;
    int status=call(connection,3,NULL,0,&value,&count);
    /* Metadata only. Never log keys, lockers, buffers or opaque properties. */
    fprintf(stderr,"HuntMob: trusted effaceable %s status=%x count=%u formatted=%llu\n",
            phase,status,count,(unsigned long long)value);
    if(status||count!=1||value>1) return 1;
    *formatted=(int)value;
    return 0;
}
int main(void) {
    alarm(45);
    struct statfs root;
    struct stat info;
    int scope=virtual_v1_scope(),root_status=statfs("/",&root);
    if(!root_status) fprintf(stderr,"HuntMob: trusted effaceable root scope=%d type=%s from=%s on=%s rootfs=%d\n",
            scope,root.f_fstypename,root.f_mntfromname,root.f_mntonname,!!(root.f_flags&MNT_ROOTFS));
    struct stat root_info,md_info;
    int device_status=stat("/",&root_info)||lstat("/dev/md0",&md_info);
    int root_is_md0=!device_status&&S_ISBLK(md_info.st_mode)&&root_info.st_dev==md_info.st_rdev;
    fprintf(stderr,"HuntMob: trusted effaceable root device-is-md0=%d\n",root_is_md0);
    /* This kernel reports f_mntfromname='root_device' even for md0. Compare
     * the actual filesystem device to the exact kernel md0 block device;
     * never change the reported name or the platform SecureRoot policy. */
    if(scope||root_status||!(root.f_flags&MNT_ROOTFS)||!root_is_md0||
       strcmp(root.f_mntonname,"/")||strcmp(root.f_fstypename,"hfs")||
       (strcmp(root.f_mntfromname,"md0")&&strcmp(root.f_mntfromname,"/dev/md0")&&
        strcmp(root.f_mntfromname,"root_device"))) {
        fprintf(stderr,"HuntMob: trusted effaceable RAMdisk scope rejected\n");return 1;
    }
    if(lstat("/dev/disk0s1s2",&info)==0||errno!=ENOENT) {
        fprintf(stderr,"HuntMob: trusted effaceable requires absent Data slot\n");return 1;
    }
    if(online_preloaded_controller()) return 1;
    /* The public restore root contains the versioned install name used by
     * restored_external; unlike normal System, it has no top-level alias. */
    void *library=dlopen("/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit",RTLD_NOW|RTLD_LOCAL);
    if(!library) { fprintf(stderr,"HuntMob: trusted effaceable IOKit unavailable\n");return 1; }
    void *(*matching)(const char *)=dlsym(library,"IOServiceMatching");
    int (*find_all)(unsigned,void *,unsigned *)=dlsym(library,"IOServiceGetMatchingServices");
    unsigned (*next)(unsigned)=dlsym(library,"IOIteratorNext");
    int (*open_service)(unsigned,unsigned,unsigned,unsigned *)=dlsym(library,"IOServiceOpen");
    ScalarCall call=dlsym(library,"IOConnectCallScalarMethod");
    int (*close_service)(unsigned)=dlsym(library,"IOServiceClose");
    int (*release)(unsigned)=dlsym(library,"IOObjectRelease");
    if(!matching||!find_all||!next||!open_service||!call||!close_service||!release) {
        fprintf(stderr,"HuntMob: trusted effaceable IOKit ABI unavailable\n");return 1;
    }
    unsigned iterator=0,connection=0;
    int status=0;
    /* LaunchDaemons may start before asynchronous namespace publication. This
     * wait only repeats matching queries; the formatting call remains once. */
    for(unsigned attempt=0;attempt<200;attempt++) {
        status=find_all(0,matching("AppleEffaceableStorage"),&iterator);
        if(status||iterator) break;
        usleep(100000);
    }
    if(status||!iterator) {
        fprintf(stderr,"HuntMob: trusted effaceable matching failed status=%x\n",status);
        if(iterator) release(iterator);
        if(!status) service_counts(matching,find_all,next,release);
        dlclose(library);
        return 1;
    }
    if(lstat("/dev/disk0s1s2",&info)==0||errno!=ENOENT) {
        release(iterator);
        fprintf(stderr,"HuntMob: trusted effaceable Data appeared during matching\n");return 1;
    }
    unsigned service=next(iterator),extra=next(iterator);
    release(iterator);
    if(!service||extra) {
        if(service) release(service);
        if(extra) release(extra);
        fprintf(stderr,"HuntMob: trusted effaceable service not unique\n");return 1;
    }
    status=open_service(service,mach_task_self(),0,&connection);
    release(service);
    fprintf(stderr,"HuntMob: trusted effaceable open status=%x\n",status);
    if(status) return 1;
    int formatted=0,result=1;
    if(query(call,connection,"before",&formatted)) goto done;
    if(!formatted) {
        status=call(connection,4,NULL,0,NULL,NULL);
        fprintf(stderr,"HuntMob: trusted effaceable stock format status=%x\n",status);
        if(status) goto done;
        /* Selector4 can return zero without formatting. Re-query the SAME
         * connection and require the actual stock boolean to become one. */
        if(query(call,connection,"after",&formatted)||!formatted) goto done;
    }
    result=0;
done:
    status=close_service(connection);
    dlclose(library);
    if(result||status) return 1;
    sync();
    fprintf(stderr,"HuntMob: provisioning checkpoint ready; trusted effaceable formatted=1\n");
    alarm(0);
    for(;;) pause();
}
