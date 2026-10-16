/* Owned virtual SEP v1: dynamic fresh Gigalocker and unchanged stock verifier. */
#include "virtual_v1_scope.h"
#include <dirent.h>
#include <sys/wait.h>
static int stock_utility(const char *option, const char *input) {
    /* Cold TCG SEP boot exceeded the former 60s child deadline. Keep the
     * command bounded; report only its fixed option and process status. */
    fprintf(stderr,"HuntMob virtual v1: stock step %s start\n",option);
    pid_t pid=fork();
    if(pid<0) return 1;
    if(pid==0) { alarm(!strcmp(option,"--restore+art")?150:60); char *args[]={"/usr/libexec/seputil",(char *)option,(char *)input,NULL}; execv(args[0],args); _exit(127); }
    int status=0;
    while(waitpid(pid,&status,0)<0) if(errno!=EINTR) return 1;
    fprintf(stderr,"HuntMob virtual v1: stock step %s exit=%d signal=%d\n",option,
            WIFEXITED(status)?WEXITSTATUS(status):-1,WIFSIGNALED(status)?WTERMSIG(status):0);
    return !WIFEXITED(status)||WEXITSTATUS(status)!=0;
}
/* Inspect names/type only. Never read, export or hash Gigalocker contents. */
static int inspect_lockers(char *name,struct stat *identity) {
    DIR *directory=opendir("/private/xarts");
    if(!directory) return -1;
    struct dirent *entry; int count=0;
    while((entry=readdir(directory))) {
        size_t n=strlen(entry->d_name);
        if(n<3||strcmp(entry->d_name+n-3,".gl")) continue;
        struct stat info;
        if(n!=39||fstatat(dirfd(directory),entry->d_name,&info,AT_SYMLINK_NOFOLLOW)||!S_ISREG(info.st_mode)) {count=-1;break;}
        if(name) memcpy(name,entry->d_name,n+1);
        if(identity) *identity=info;
        count++;
    }
    closedir(directory);
    return count;
}
static int locker_count(void) {return inspect_lockers(NULL,NULL);}
static int restore_locker_register(int lockers) {
    char before_name[40]={0},after_name[40]={0},alias[64]={0};
    struct stat before={0},after={0},private_dir={0},alias_dir={0};
    ssize_t n=readlink("/mnt7",alias,sizeof(alias)-1);
    if(n<0||(size_t)n>=sizeof(alias)-1||strcmp(alias,"/private/xarts")||
       stat("/mnt7",&alias_dir)||stat("/private/xarts",&private_dir)||
       !S_ISDIR(private_dir.st_mode)||private_dir.st_dev!=alias_dir.st_dev||
       private_dir.st_ino!=alias_dir.st_ino) return 1;
    if(lockers==1&&(inspect_lockers(before_name,&before)!=1||before.st_size<6*1024*1024)) return 1;
    /* The stock utility creates only when missing, then registers the path
     * through selector44 even for an existing file. Registration is per boot. */
    if(stock_utility("--gigalocker-init",NULL)||inspect_lockers(after_name,&after)!=1) return 1;
    if(lockers==1&&(strcmp(before_name,after_name)||before.st_dev!=after.st_dev||
       before.st_ino!=after.st_ino||before.st_size!=after.st_size)) {
        fprintf(stderr,"HuntMob virtual v1: existing Gigalocker identity changed\n");return 1;
    }
    fprintf(stderr,"HuntMob virtual v1: stock Gigalocker registered for this boot\n");
    return 0;
}
static int marker_present(const char *path) {
    struct stat info;
    if(lstat(path,&info)==0) return S_ISREG(info.st_mode)?1:-1;
    return errno==ENOENT?0:-1;
}
int main(int argc,char **argv) {
    alarm(300);
    if(virtual_v1_scope()) {fprintf(stderr,"HuntMob virtual v1: scope rejected\n");return 1;}
    int restoring=marker_present("/usr/libexec/huntmob-restore-sep.img4");
    int preparing=marker_present("/usr/libexec/huntmob-prepare-data");
    int lockers=locker_count();
    if(restoring<0||preparing<0||lockers<0) return 1;
    if(restoring) {
        if(lockers>1||preparing) {fprintf(stderr,"HuntMob virtual v1: fresh restore state rejected\n");return 1;}
        if(lockers==1) {
            fprintf(stderr,"HuntMob virtual v1: resuming same-profile restore with existing Gigalocker\n");
        }
        if(restore_locker_register(lockers)) return 1;
        if(stock_utility("--restore+art","/usr/libexec/huntmob-restore-sep.img4")||
           stock_utility("--erase",NULL)||stock_utility("--commit-hash","--erase")||
           stock_utility("--new-nonce",NULL)||stock_utility("--gigalocker-shutdown",NULL)) return 1;
        sync();
        fprintf(stderr,"HuntMob: provisioning checkpoint ready; virtual v1 stock SEP restore prepared\n");
        for(;;) pause();
    }
    if(lockers!=1) {fprintf(stderr,"HuntMob virtual v1: persisted Gigalocker unavailable\n");return 1;}
    char **args=calloc((size_t)(argc>0?argc:1)+1,sizeof(char *));
    if(!args) return 1;
    args[0]="/usr/libexec/init_data_protection";
    for(int i=1;i<argc;i++) args[i]=argv[i];
    fprintf(stderr,"HuntMob: invoking stock Data Protection verifier\n");
    pid_t pid=fork();
    if(pid<0) {free(args);return 1;}
    if(pid==0) {execv("/usr/libexec/huntmob-original/init_data_protection",args);_exit(127);}
    int status=0;
    while(waitpid(pid,&status,0)<0) if(errno!=EINTR) {free(args);return 1;}
    free(args);
    if(!WIFEXITED(status)||WEXITSTATUS(status)!=0) {fprintf(stderr,"HuntMob virtual v1: stock verifier failed\n");return 1;}
    if(preparing) {
        char *prepare[]={"/usr/libexec/huntmob-prepare-userdata",NULL};
        execv(prepare[0],prepare);return 1;
    }
    return 0;
}
