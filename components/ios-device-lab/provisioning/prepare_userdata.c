/* AUTHORIZED OWNED VIRTUAL LAB ONLY. iPhoneOS provisioning, never a host tool.
 * Initialize the stock system keybag and require a working protection class.
 * No key export, credential access, network or ROM/security-check changes.
 */
#include <TargetConditionals.h>
#if !TARGET_OS_IPHONE || TARGET_OS_SIMULATOR
#error This helper is only for the owned iPhoneOS guest.
#endif
#include <dlfcn.h>
#include <CommonCrypto/CommonDigest.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <mach/mach.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/mount.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <unistd.h>

/* Keep only short textual words from stock diagnostics. Numeric values,
 * paths, long identifiers and binary/key material are never logged here. */
static void keybag_diagnostic(const char *message) {
    if (!message) return;
    const char *payload_error = strstr(message, "APFSVolumePayloadGet failed with ");
    if (payload_error) {
        char *end = NULL;
        long code = strtol(payload_error + strlen("APFSVolumePayloadGet failed with "), &end, 10);
        if (end && end != payload_error + strlen("APFSVolumePayloadGet failed with ") &&
            code >= INT32_MIN && code <= INT32_MAX)
            fprintf(stderr, "HuntMob: APFS payload error code %ld\n", code);
    }
    fprintf(stderr, "HuntMob: stock keybag diagnostic:");
    size_t position = 0;
    while (position < 512 && message[position]) {
        if (!isalpha((unsigned char)message[position])) { position++; continue; }
        size_t start = position;
        while (position < 512 && isalpha((unsigned char)message[position])) position++;
        size_t length = position - start;
        if (length < 32 && (start == 0 || !isalnum((unsigned char)message[start-1])) &&
            !isalnum((unsigned char)message[position]))
            fprintf(stderr, " %.*s", (int)length, message + start);
    }
    fputc('\n', stderr);
}

/* Stock restored_external selectors: 3 queries formatting, 4 initializes
 * an empty store. Never clear an already formatted store or read lockers. */
static int initialize_effaceable(void) {
    void *library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!library) return 1;
    void *(*matching)(const char *) = dlsym(library, "IOServiceMatching");
    unsigned (*find)(unsigned, void *) = dlsym(library, "IOServiceGetMatchingService");
    int (*open_service)(unsigned, unsigned, unsigned, unsigned *) = dlsym(library, "IOServiceOpen");
    int (*call)(unsigned, unsigned, const uint64_t *, unsigned, uint64_t *, unsigned *) = dlsym(library, "IOConnectCallScalarMethod");
    int (*close_service)(unsigned) = dlsym(library, "IOServiceClose");
    int (*release)(unsigned) = dlsym(library, "IOObjectRelease");
    if (!matching || !find || !open_service || !call || !close_service || !release) return 1;
    unsigned service = find(0, matching("AppleEffaceableStorage")), connection = 0;
    if (!service) { fprintf(stderr, "HuntMob: effaceable service missing\n"); return 1; }
    int result = open_service(service, mach_task_self(), 0, &connection);
    release(service);
    if (result) { fprintf(stderr, "HuntMob: effaceable open rejected (%x)\n", result); return 1; }
    uint64_t formatted = 0; unsigned count = 1;
    result = call(connection, 3, NULL, 0, &formatted, &count);
    if (!result && count == 1 && !formatted) result = call(connection, 4, NULL, 0, NULL, NULL);
    close_service(connection);
    if (result || count != 1) {
        fprintf(stderr, "HuntMob: effaceable initialization rejected (%x)\n", result); return 1;
    }
    fprintf(stderr, "HuntMob: stock effaceable storage initialized or already formatted\n");
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
    if (mkdir(path, mode) != 0 && errno != EEXIST) {
        perror("HuntMob: preparation directory"); return 1;
    }
    return lstat(path, &info) != 0 || !S_ISDIR(info.st_mode);
}

static int code_matches(const void *code, size_t size, const unsigned char expected[32]) {
    unsigned char observed[32];
    CC_SHA256(code, (CC_LONG)size, observed);
    return memcmp(observed, expected, sizeof(observed)) == 0;
}

/* Exact private ABI observed in the original 18A5351d keybagd/cache.
 * This isolated mapper-only test loads no keybag and unlocks nothing. It
 * calls the original permission-checked code with the stock zero options.
 * Any different guest/build/module/body refuses before making the call. */
static int map_existing_systembag(void *create_system) {
    char build[64] = {0}; size_t count = sizeof(build);
    struct statfs filesystem;
    if (sysctlbyname("kern.osversion", build, &count, NULL, 0) != 0 ||
        strcmp(build, "18A5351d") != 0 || statfs("/mnt2", &filesystem) != 0 ||
        !(filesystem.f_flags & MNT_CPROTECT)) {
        fprintf(stderr, "HuntMob: existing system bag map preconditions rejected\n"); return 1;
    }
    uintptr_t anchor = (uintptr_t)create_system;
    const void *get_code = (const void *)(anchor + 0x191e0);
    const void *map_code = (const void *)(anchor - 0x3418);
    Dl_info origin, get_origin, map_origin;
    if (!dladdr(create_system, &origin) || !dladdr(get_code, &get_origin) ||
        !dladdr(map_code, &map_origin) || !origin.dli_fname ||
        strcmp(origin.dli_fname, "/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag") != 0 ||
        get_origin.dli_fbase != origin.dli_fbase || map_origin.dli_fbase != origin.dli_fbase) {
        fprintf(stderr, "HuntMob: original keybag module binding rejected\n"); return 1;
    }
    const unsigned char get_sha[32] = {
        0x2f,0x26,0x66,0xda,0x2b,0x4c,0xe4,0x31,0x9c,0x02,0x13,0x82,0xad,0x10,0x66,0x54,
        0xd3,0x2b,0x02,0xac,0x60,0x08,0x3d,0x85,0x26,0xb0,0x6f,0xcf,0x08,0x00,0x90,0x25};
    const unsigned char map_sha[32] = {
        0x7f,0xe4,0x16,0xe7,0x2e,0x78,0x50,0x56,0xc3,0x9d,0xf7,0xc1,0xbb,0x21,0x4e,0x4f,
        0x71,0xe6,0x8a,0x70,0xd1,0x48,0x50,0xd6,0x82,0xfe,0x67,0x57,0x8e,0xd7,0xcd,0xfb};
    if (!code_matches(get_code, 0xc8, get_sha) || !code_matches(map_code, 0x1c4, map_sha)) {
        fprintf(stderr, "HuntMob: original keybag routine fingerprint rejected\n"); return 1;
    }
    int32_t (*get_system)(int32_t, int32_t *) = (void *)get_code;
    int32_t (*map_device)(const char *, uintptr_t, void *) = (void *)map_code;
    int32_t handle = 0;
    int32_t status = get_system(0, &handle);
    if (status != 0) {
        fprintf(stderr, "HuntMob: existing system bag unavailable for map (%x)\n", (unsigned)status);
        return 1;
    }
    status = map_device("/mnt2", 0, NULL);
    if (status != 0) {
        fprintf(stderr, "HuntMob: original system bag association rejected (%d)\n", status);
        return 1;
    }
    fprintf(stderr, "HuntMob: original system bag association call completed; readback required\n");
    return 0;
}

/* ABI declared by Apple WebKit MobileKeyBagSPI: int(void), -1/0/1.
 * This is a read-only state query, never an unlock or key export. */
static void first_unlock_diagnostic(void *library) {
    int (*unlocked_since_boot)(void) = dlsym(library, "MKBDeviceUnlockedSinceBoot");
    if (!unlocked_since_boot) {
        fprintf(stderr, "HuntMob: first-unlock state unavailable\n"); return;
    }
    int state = unlocked_since_boot();
    if (state == 0 || state == 1 || state == -1)
        fprintf(stderr, "HuntMob: first-unlock state %d\n", state);
    else fprintf(stderr, "HuntMob: first-unlock state unknown\n");
}

/* Opt-in diagnostic of the existing synthetic probe. Never truncates it,
 * assigns another class, unlocks the device or reads other app files. */
static int persisted_probe_diagnostic(void) {
    int metadata = open("/mnt2/.huntmob-protection-probe", O_EVTONLY | O_NOFOLLOW);
    if (metadata < 0) perror("HuntMob: Class C metadata open rejected");
    else {
        struct stat info;
        if (fstat(metadata, &info) != 0 || !S_ISREG(info.st_mode)) {
            fprintf(stderr, "HuntMob: existing synthetic probe is not regular\n");
            close(metadata); return 1;
        }
        int protection_class = fcntl(metadata, F_GETPROTECTIONCLASS);
        if (protection_class < 0) perror("HuntMob: Class C metadata query rejected");
        else fprintf(stderr, "HuntMob: persisted probe protection class %d\n", protection_class);
        close(metadata);
    }
    int fd = open("/mnt2/.huntmob-protection-probe", O_RDONLY | O_NOFOLLOW);
    if (fd < 0) { perror("HuntMob: Class C read-only open rejected"); return 1; }
    struct stat info;
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size != 64 ||
        fcntl(fd, F_GETPROTECTIONCLASS) != 3) {
        fprintf(stderr, "HuntMob: persisted class C probe metadata rejected\n"); close(fd); return 1;
    }
    char synthetic[64];
    ssize_t received = pread(fd, synthetic, sizeof(synthetic), 0);
    if (received != 64) {
        if (received < 0) perror("HuntMob: Class C read-only read rejected");
        else fprintf(stderr, "HuntMob: Class C read-only short read\n");
        close(fd); return 1;
    }
    close(fd);
    fprintf(stderr, "HuntMob: persisted class C read-only read completed; crypto not validated\n");
    return 0;
}

/* A separate, never-before-existing synthetic file, only when explicitly
 * requested in the owned ephemeral comparison clone. Keep the old file. */
static int fresh_class_c_diagnostic(void) {
    int (*protected_open)(const char *, int, int, int, ...) =
        dlsym(RTLD_DEFAULT, "open_dprotected_np");
    if (!protected_open) {
        fprintf(stderr, "HuntMob: fresh class C atomic API unavailable\n"); return 1;
    }
    int fd = protected_open("/mnt2/.huntmob-fresh-protection-probe",
                            O_CREAT | O_EXCL | O_RDWR | O_NOFOLLOW, 3, 0, 0600);
    if (fd < 0) { perror("HuntMob: fresh class C create rejected"); return 1; }
    if (fcntl(fd, F_GETPROTECTIONCLASS) != 3) {
        fprintf(stderr, "HuntMob: fresh class C assignment rejected\n"); close(fd); return 1;
    }
    fprintf(stderr, "HuntMob: fresh probe protection class 3\n");
    const char payload[] = "HUNTMOB SYNTHETIC FRESH CLASS C COMPARISON V1\n";
    ssize_t size = (ssize_t)(sizeof(payload) - 1);
    if (write(fd, payload, (size_t)size) != size) {
        perror("HuntMob: fresh class C write rejected"); close(fd); return 1;
    }
    if (fsync(fd) != 0) {
        perror("HuntMob: fresh class C fsync rejected"); close(fd); return 1;
    }
    char readback[sizeof(payload) - 1];
    if (pread(fd, readback, sizeof(readback), 0) != size) {
        perror("HuntMob: fresh class C read rejected"); close(fd); return 1;
    }
    close(fd);
    if (memcmp(payload, readback, sizeof(readback)) != 0) {
        fprintf(stderr, "HuntMob: fresh class C readback mismatch\n"); return 1;
    }
    fprintf(stderr, "HuntMob: fresh class C roundtrip completed; crypto not validated\n");
    return 0;
}

int main(void) {
    alarm(90);
    char machine[64] = {0}, bootargs[1024] = {0}, marker[64] = {0};
    size_t size = sizeof(machine);
    if (sysctlbyname("hw.machine", machine, &size, NULL, 0) != 0 || strcmp(machine, "iPhone12,1") != 0) {
        fprintf(stderr, "HuntMob: unsupported guest model; no provisioning performed\n"); return 1;
    }
    size = sizeof(bootargs);
    if (sysctlbyname("kern.bootargs", bootargs, &size, NULL, 0) != 0 || !strstr(bootargs, "agm-genuine=1")) {
        fprintf(stderr, "HuntMob: owned research boot configuration required\n"); return 1;
    }
    int authorization = open("/usr/libexec/huntmob-prepare-data", O_RDONLY | O_NOFOLLOW);
    if (authorization < 0) return 1;
    ssize_t count = read(authorization, marker, sizeof(marker)-1);close(authorization);
    if (count < 0 || strcmp(marker, "HUNTMOB OWNED EMPTY DATA PREPARATION V1\n") != 0) {
        fprintf(stderr, "HuntMob: explicit owned Data preparation marker required\n"); return 1;
    }
    struct stat info;
    /* This slot is the previously empty Data slot of the pinned virtual
     * n104ap layout. -A adds a volume; it never reformats the container. */
    if (stat("/dev/disk0s1s2", &info) != 0) {
        if (errno != ENOENT) return 1;
        if (initialize_effaceable()) return 1;
        /* Original erase-restorer creates the Class D key before Data. This
         * is allowed only while the owned guest's Data volume is absent. */
        void *keybag = dlopen("/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag", RTLD_NOW | RTLD_LOCAL);
        int (*initialize_class_d)(void) = keybag ? dlsym(keybag, "MKBDeviceObliterateClassDKey") : NULL;
        if (!initialize_class_d) return 1;
        int class_d_result = initialize_class_d();
        if (class_d_result) {
            fprintf(stderr, "HuntMob: empty-guest Class D initialization failed (%d)\n", class_d_result); return 1;
        }
        fprintf(stderr, "HuntMob: stock empty-guest Class D initialized\n");
        char *format[] = {"/System/Library/Filesystems/apfs.fs/newfs_apfs", "-A", "-E", "-P",
                          "-o", "role=d", "-v", "Data", "/dev/disk0s1", NULL};
        if (run(format)) { fprintf(stderr, "HuntMob: stock Data format failed\n"); return 1; }
    }
    if (directory("/mnt2", 0755)) return 1;
    char *mount[] = {"/System/Library/Filesystems/apfs.fs/mount_apfs", "/dev/disk0s1s2", "/mnt2", NULL};
    if (run(mount)) { fprintf(stderr, "HuntMob: owned Data mount failed\n"); return 1; }
    if (directory("/mnt2/keybags", 0700)) return 1;
    void *library = dlopen("/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag", RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "HuntMob: stock keybag framework unavailable\n"); return 1; }
    /* ABI verified in this build's restored_external: NULL, mount path. */
    int (*create_system)(void *, const char *) = dlsym(library, "MKBKeyBagCreateSystem");
    if (!create_system) { fprintf(stderr, "HuntMob: stock system keybag API unavailable\n"); return 1; }
    void (*set_log)(void (*)(const char *)) = dlsym(library, "MKBSetLogFunction");
    if (set_log) set_log(keybag_diagnostic);
    int result = create_system(NULL, "/mnt2");
    if (result != 0 && result != -4) {
        fprintf(stderr, "HuntMob: stock system keybag initialization failed (%d)\n", result); return 1;
    }
    if (result == -4)
        fprintf(stderr, "HuntMob: stock system keybag already exists; CreateSystem did not associate it\n");
    else fprintf(stderr, "HuntMob: stock system keybag initialized\n");
    if (lstat("/usr/libexec/huntmob-map-existing-systembag", &info) == 0) {
        if (!S_ISREG(info.st_mode) || result != -4 || map_existing_systembag((void *)create_system) != 0)
            return 1;
    } else if (errno != ENOENT) return 1;
    first_unlock_diagnostic(library);
    if (lstat("/usr/libexec/huntmob-probe-diagnostics-only", &info) == 0) {
        if (!S_ISREG(info.st_mode)) return 1;
        int diagnostic_result = persisted_probe_diagnostic();
        if (lstat("/usr/libexec/huntmob-probe-compare-fresh", &info) == 0) {
            if (!S_ISREG(info.st_mode)) return 1;
            /* A fresh success cannot turn a failed persisted read into success. */
            if (fresh_class_c_diagnostic() != 0) diagnostic_result = 1;
        } else if (errno != ENOENT) return 1;
        char *unmount[] = {"/sbin/umount", "/mnt2", NULL};
        if (run(unmount)) return 1;
        return diagnostic_result;
    }
    if (errno != ENOENT) { perror("HuntMob: diagnostic marker query"); return 1; }
    if (result == -4) {
        fprintf(stderr, "HuntMob: existing system keybag requires stock load/association before provisioning\n");
        return 1;
    }
    if (directory("/mnt2/root", 0700) || directory("/mnt2/mobile", 0755) ||
        directory("/mnt2/mobile/Library", 0755)) return 1;
    if (chown("/mnt2/mobile", 501, 501) || chown("/mnt2/mobile/Library", 501, 501)) return 1;
    int fd = open("/mnt2/.huntmob-protection-probe", O_CREAT | O_TRUNC | O_RDWR | O_NOFOLLOW, 0600);
    if (fd < 0) { perror("HuntMob: Class C probe open rejected"); return 1; }
    if (fcntl(fd, F_SETPROTECTIONCLASS, 3) != 0) {
        perror("HuntMob: Class C protection assignment rejected"); close(fd); return 1;
    }
    int protection_class = fcntl(fd, F_GETPROTECTIONCLASS);
    if (protection_class != 3) {
        if (protection_class < 0) perror("HuntMob: protection class query rejected");
        else fprintf(stderr, "HuntMob: unexpected protection class %d\n", protection_class);
        close(fd); return 1;
    }
    unsigned char random[32]; char canary[65];
    arc4random_buf(random, sizeof(random));
    for (size_t index = 0; index < sizeof(random); index++) snprintf(canary + index * 2, 3, "%02x", random[index]);
    ssize_t written = write(fd, canary, 64);
    if (written != 64) {
        if (written < 0) perror("HuntMob: Class C probe write rejected");
        else fprintf(stderr, "HuntMob: Class C probe short write (%zd bytes)\n", written);
        close(fd); return 1;
    }
    if (fsync(fd) != 0) { perror("HuntMob: Class C probe fsync rejected"); close(fd); return 1; }
    char readback[64];
    ssize_t received = pread(fd, readback, sizeof(readback), 0);
    if (received != 64) {
        if (received < 0) perror("HuntMob: Class C probe read rejected");
        else fprintf(stderr, "HuntMob: Class C probe short read (%zd bytes)\n", received);
        close(fd); return 1;
    }
    if (memcmp(canary, readback, 64) != 0) {
        fprintf(stderr, "HuntMob: Class C probe readback mismatch\n"); close(fd); return 1;
    }
    close(fd);
    /* Synthetic test data, not a key or authentication token. Kept in private
     * serial logs to compare with raw storage before claiming encryption. */
    fprintf(stderr, "HuntMob: Class C probe roundtrip completed; synthetic canary=%s\n", canary);
    sync();
    char *unmount[] = {"/sbin/umount", "/mnt2", NULL};
    if (run(unmount)) return 1;
    if (lstat("/usr/libexec/huntmob-data-checkpoint", &info) == 0) {
        if (!S_ISREG(info.st_mode)) return 1;
        sync();
        fprintf(stderr, "HuntMob: provisioning checkpoint ready; protected Data prepared; waiting for owned VM shutdown\n");
        for (;;) pause();
    }
    return 0;
}
