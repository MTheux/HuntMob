/* Fresh Data ONLY: no existing bag association, class downgrade or old Data reuse. */
#include "virtual_v1_scope.h"
#include <dlfcn.h>
#include <mach/mach.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <sys/attr.h>
#include <uuid/uuid.h>
#ifndef HUNTMOB_EFFACEABLE_OBSERVE_ONLY
#define HUNTMOB_EFFACEABLE_OBSERVE_ONLY 0
#endif
#ifndef HUNTMOB_RESUME_CREATED_DATA
#define HUNTMOB_RESUME_CREATED_DATA 0
#endif
#if HUNTMOB_RESUME_CREATED_DATA && !defined(HUNTMOB_EXPECTED_DATA_UUID)
#error Resuming Data requires the exact newly created volume UUID.
#endif
#if HUNTMOB_RESUME_CREATED_DATA && HUNTMOB_EFFACEABLE_OBSERVE_ONLY
#error Resume and observer modes are mutually exclusive.
#endif
/* Normal disk boot must not format effaceable storage. The stock selector can
 * return zero even when SecureRoot rejects the operation. Query the actual
 * state; initialization belongs in the trusted restore environment. */
static int query_effaceable(const char *phase, int *is_formatted) {
    void *library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!library) return 1;
    void *(*matching)(const char *) = dlsym(library, "IOServiceMatching");
    unsigned (*find)(unsigned, void *) = dlsym(library, "IOServiceGetMatchingService");
    int (*open_service)(unsigned, unsigned, unsigned, unsigned *) = dlsym(library, "IOServiceOpen");
    int (*call)(unsigned, unsigned, const uint64_t *, unsigned, uint64_t *, unsigned *) = dlsym(library, "IOConnectCallScalarMethod");
    int (*close_service)(unsigned) = dlsym(library, "IOServiceClose");
    int (*release)(unsigned) = dlsym(library, "IOObjectRelease");
    int (*registry_id)(unsigned, uint64_t *) = dlsym(library, "IORegistryEntryGetRegistryEntryID");
    int (*registry_path)(unsigned, const char *, char *) = dlsym(library, "IORegistryEntryGetPath");
    if (!matching || !find || !open_service || !call || !close_service || !release ||
        !registry_id || !registry_path) return 1;
    unsigned service = find(0, matching("AppleEffaceableStorage")), connection = 0;
    if (!service) { fprintf(stderr, "HuntMob: effaceable service missing\n"); return 1; }
    uint64_t identity = 0; char path[512] = {0};
    int id_status = registry_id(service, &identity);
    int path_status = registry_path(service, "IOService", path);
    if (id_status || path_status || !memchr(path, 0, sizeof(path))) {
        release(service); return 1;
    }
    fprintf(stderr, "HuntMob: effaceable %s registry=%llu path=%s\n", phase,
            (unsigned long long)identity, path);
    int result = open_service(service, mach_task_self(), 0, &connection);
    release(service);
    if (result) { fprintf(stderr, "HuntMob: effaceable open rejected (%x)\n", result); return 1; }
    uint64_t formatted = 0; unsigned count = 1;
    result = call(connection, 3, NULL, 0, &formatted, &count);
    close_service(connection);
    fprintf(stderr, "HuntMob: effaceable %s query status=%x count=%u formatted=%llu\n",
            phase, result, count, (unsigned long long)formatted);
    if (result || count != 1 || formatted > 1) {
        fprintf(stderr, "HuntMob: effaceable state query rejected\n"); return 1;
    }
    *is_formatted = (int)formatted;
    return 0;
}

static int run(char *const args[]) {
    pid_t pid = fork();
    if (pid < 0) return 1;
    if (pid == 0) { alarm(60); execv(args[0], args); _exit(127); }
    int status = 0;
    while (waitpid(pid, &status, 0) < 0) { if (errno != EINTR) return 1; }
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}

static int directory(const char *path, mode_t mode) {
    struct stat info;
    if (lstat(path, &info) == 0) return !S_ISDIR(info.st_mode);
    if (errno != ENOENT) return 1;
    if (mkdir(path, mode) != 0 && errno != EEXIST) {
        perror("HuntMob: preparation directory"); return 1;
    }
    return lstat(path, &info) != 0 || !S_ISDIR(info.st_mode);
}

static int mounted_data_identity(void) {
#if HUNTMOB_RESUME_CREATED_DATA
    struct attrlist attributes = {0};
    unsigned char value[20] = {0};
    uuid_t expected;
    attributes.bitmapcount = ATTR_BIT_MAP_COUNT;
    attributes.volattr = ATTR_VOL_INFO | ATTR_VOL_UUID;
    if (uuid_parse(HUNTMOB_EXPECTED_DATA_UUID, expected) || uuid_is_null(expected) ||
        getattrlist("/mnt2", &attributes, value, sizeof(value), 0)) {
        fprintf(stderr,"HuntMob: created Data volume identity query failed\n"); return 1;
    }
    uint32_t length;
    memcpy(&length,value,sizeof(length));
    if (length != sizeof(value) || memcmp(value+sizeof(length), expected, sizeof(expected))) {
        fprintf(stderr,"HuntMob: created Data volume identity rejected\n"); return 1;
    }
    fprintf(stderr,"HuntMob: created Data volume identity matched\n");
#endif
    return 0;
}


int main(void) {
    alarm(90);
    if (virtual_v1_scope()) { fprintf(stderr,"HuntMob virtual v1: scope rejected\n"); return 1; }
    struct stat info;
    int data_present = lstat("/dev/disk0s1s2", &info) == 0;
    if (HUNTMOB_RESUME_CREATED_DATA ? (!data_present || !S_ISBLK(info.st_mode))
                                    : (data_present || errno != ENOENT)) {
        fprintf(stderr,"HuntMob virtual v1: Data slot does not match preparation phase\n"); return 1;
    }
    int formatted = 0;
    if (query_effaceable("before-ClassD", &formatted)) return 1;
    if (HUNTMOB_EFFACEABLE_OBSERVE_ONLY) {
        fprintf(stderr,"HuntMob: provisioning checkpoint ready; effaceable observation only; formatted=%d\n",formatted);
        for (;;) pause();
    }
    if (!formatted) {
        fprintf(stderr,"HuntMob: effaceable storage requires trusted restore initialization; no format attempted\n");
        return 1;
    }
    void *library = dlopen("/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag",RTLD_NOW|RTLD_LOCAL);
    int (*initialize_class_d)(void) = library ? dlsym(library,"MKBDeviceObliterateClassDKey") : NULL;
    int (*create_system)(void *,const char *) = library ? dlsym(library,"MKBKeyBagCreateSystem") : NULL;
    if (!initialize_class_d || !create_system) return 1;
    if (!HUNTMOB_RESUME_CREATED_DATA) {
        int class_d_status = initialize_class_d();
        fprintf(stderr,"HuntMob: ClassD initialization status=%d\n",class_d_status);
        if (class_d_status || query_effaceable("after-ClassD", &formatted) || !formatted) return 1;
        char *format[] = {"/System/Library/Filesystems/apfs.fs/newfs_apfs","-A","-E","-P",
                          "-o","role=d","-v","Data","/dev/disk0s1",NULL};
        if (run(format)) return 1;
    }
    if (directory("/mnt2",0755)) return 1;
    char *mount[] = {"/System/Library/Filesystems/apfs.fs/mount_apfs","/dev/disk0s1s2","/mnt2",NULL};
    if (run(mount)) return 1;
    int result = 1;
    struct statfs fs;
    if (statfs("/mnt2",&fs) || strcmp(fs.f_fstypename,"apfs") || strcmp(fs.f_mntonname,"/mnt2") ||
        strcmp(fs.f_mntfromname,"/dev/disk0s1s2") || !(fs.f_flags & MNT_CPROTECT) || mounted_data_identity() ||
        directory("/mnt2/keybags",0700)) goto unmount;
    if (HUNTMOB_RESUME_CREATED_DATA &&
        (lstat("/mnt2/keybags/systembag.kb", &info) == 0 || errno != ENOENT)) {
        fprintf(stderr,"HuntMob: unexpected existing systembag; refusing initialization\n"); goto unmount;
    }
    int status = create_system(NULL,"/mnt2");
    /* -4 is a failure here, including a bag from any earlier identity. */
    if (status != 0) {
        fprintf(stderr,"HuntMob virtual v1: fresh MKBCreateSystem rejected (%d)\n",status); goto unmount;
    }
    fprintf(stderr,"HuntMob virtual v1: fresh MKBCreateSystem returned zero\n");
    if (directory("/mnt2/root",0700) || directory("/mnt2/mobile",0755) ||
        directory("/mnt2/mobile/Library",0755) || chown("/mnt2/mobile",501,501) ||
        chown("/mnt2/mobile/Library",501,501)) goto unmount;
    int (*protected_open)(const char *,int,int,int,...) = dlsym(RTLD_DEFAULT,"open_dprotected_np");
    if (!protected_open) goto unmount;
    int fd = protected_open("/mnt2/.huntmob-protection-probe",O_CREAT|O_EXCL|O_RDWR|O_NOFOLLOW,3,0,0600);
    if (fd < 0) goto unmount;
    unsigned char random[32]; char canary[65],readback[64];
    if (fcntl(fd,F_GETPROTECTIONCLASS) != 3) { close(fd); goto unmount; }
    arc4random_buf(random,sizeof(random));
    for (size_t i=0;i<sizeof(random);i++) snprintf(canary+i*2,3,"%02x",random[i]);
    if (write(fd,canary,64) != 64 || fsync(fd) || pread(fd,readback,64,0) != 64 || memcmp(canary,readback,64)) {
        close(fd); goto unmount;
    }
    close(fd);
    /* Public synthetic test marker; never key material or user data. */
    fprintf(stderr,"HuntMob virtual v1: Class C roundtrip; synthetic canary=%s\n",canary);
    result = 0;
unmount:
    sync();
    char *unmount[] = {"/sbin/umount","/mnt2",NULL};
    if (run(unmount)) return 1;
    if (result) return result;
    fprintf(stderr,"HuntMob: provisioning checkpoint ready; virtual v1 fresh protected Data prepared\n");
    for (;;) pause();
}
