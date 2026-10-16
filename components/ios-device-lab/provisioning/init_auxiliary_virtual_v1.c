/* AUTHORIZED TESTING ONLY — ISOLATED LAB.
 * Fresh auxiliary APFS volumes only. Never initializes SEP/MKB or returns
 * success for the stock Data Protection task. */
#include "virtual_v1_scope.h"
#include <sys/wait.h>
static int block_present(const char *path) {
    struct stat info;
    if(lstat(path,&info)==0) return S_ISBLK(info.st_mode)?1:-1;
    return errno==ENOENT?0:-1;
}
static int format(const char *role,const char *name,int step) {
    pid_t pid=fork();
    if(pid<0) return 1;
    if(pid==0) {
        alarm(45);
        char *args[]={"/System/Library/Filesystems/apfs.fs/newfs_apfs","-A","-o",
                      (char *)role,"-v",(char *)name,"/dev/disk0s1",NULL};
        execv(args[0],args);_exit(127);
    }
    int status=0;
    while(waitpid(pid,&status,0)<0) if(errno!=EINTR) return 1;
    fprintf(stderr,"HuntMob virtual v1: auxiliary step=%d status=%d\n",step,
            WIFEXITED(status)?WEXITSTATUS(status):-1);
    return !WIFEXITED(status)||WEXITSTATUS(status)!=0;
}
static int wait_block(const char *path) {
    for(int i=0;i<30;i++) {
        int state=block_present(path);
        if(state==1) return 0;
        if(state<0) return 1;
        usleep(100000);
    }
    return 1;
}
int main(void) {
    alarm(180);
    if(virtual_v1_scope()||block_present("/dev/disk0s1s2")!=1||
       block_present("/dev/disk0s1s3")!=0||block_present("/dev/disk0s1s4")!=0||
       block_present("/dev/disk0s1s5")!=0) {
        fprintf(stderr,"HuntMob virtual v1: auxiliary preflight rejected\n");return 1;
    }
    if(format("role=x","xART",1)||wait_block("/dev/disk0s1s3")||
       format("role=h","Hardware",2)||wait_block("/dev/disk0s1s4")||
       format("role=b","Preboot",3)||wait_block("/dev/disk0s1s5")) return 1;
    sync();
    fprintf(stderr,"HuntMob: provisioning checkpoint ready; virtual v1 auxiliary volumes prepared\n");
    for(;;) pause();
}
