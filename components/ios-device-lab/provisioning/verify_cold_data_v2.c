/* Own DATA-v2: read the existing public Class C probe; never provision/unlock. */
#include "virtual_v1_scope.h"
#include "cold_read_policy_v2.h"
#include <dlfcn.h>
#include <CommonCrypto/CommonDigest.h>
#include <stdint.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <uuid/uuid.h>
#ifndef HUNTMOB_EXPECTED_DATA_UUID
#error Exact previously created Data UUID is required.
#endif
#ifndef HUNTMOB_EXPECTED_CANARY_SHA256
#error SHA256 of the exact public 64-byte probe is required.
#endif
_Static_assert(sizeof(HUNTMOB_EXPECTED_CANARY_SHA256) == 65, "SHA256 must contain exactly 64 hex characters");

static int hex_digit(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}

static int command(char *const args[]) {
    pid_t child = fork();
    if (child < 0) return 1;
    if (!child) { alarm(60); execv(args[0], args); _exit(127); }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 1;
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}

static int mounted_identity(void) {
    struct statfs fs;
    struct attrlist attributes = {0};
    unsigned char value[20] = {0};
    uuid_t expected;
    uint32_t length = 0;
    if (statfs("/mnt2", &fs) || strcmp(fs.f_fstypename, "apfs") ||
        strcmp(fs.f_mntonname, "/mnt2") || strcmp(fs.f_mntfromname, "/dev/disk0s1s2") ||
        !(fs.f_flags & MNT_CPROTECT) || !(fs.f_flags & MNT_RDONLY)) return 1;
    attributes.bitmapcount = ATTR_BIT_MAP_COUNT;
    attributes.volattr = ATTR_VOL_INFO | ATTR_VOL_UUID;
    if (uuid_parse(HUNTMOB_EXPECTED_DATA_UUID, expected) || uuid_is_null(expected) ||
        getattrlist("/mnt2", &attributes, value, sizeof(value), 0)) return 1;
    memcpy(&length, value, sizeof(length));
    return length != sizeof(value) || memcmp(value + sizeof(length), expected, sizeof(expected));
}

static void checkpoint(const char *result) {
    /* This checkpoint is an observation, never an assertion of full readiness. */
    fprintf(stderr, "HuntMob: cold Class C result=%s\n", result);
    fprintf(stderr, "HuntMob: provisioning checkpoint ready; own DATA-v2 cold-read observation\n");
    for (;;) pause();
}

int main(void) {
    alarm(90);
    if (virtual_v1_scope()) return 1;
    unsigned char expected_digest[CC_SHA256_DIGEST_LENGTH] = {0};
    for (size_t i = 0; i < sizeof(expected_digest); i++) {
        int high = hex_digit(HUNTMOB_EXPECTED_CANARY_SHA256[i * 2]);
        int low = hex_digit(HUNTMOB_EXPECTED_CANARY_SHA256[i * 2 + 1]);
        if (high < 0 || low < 0) return 1;
        expected_digest[i] = (unsigned char)((high << 4) | low);
    }
    struct stat device, point;
    struct statfs prior;
    if (lstat("/dev/disk0s1s2", &device) || !S_ISBLK(device.st_mode) ||
        lstat("/mnt2", &point) || !S_ISDIR(point.st_mode) ||
        statfs("/mnt2", &prior) || !strcmp(prior.f_mntonname, "/mnt2")) return 1;
    void *library = dlopen("/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag", RTLD_NOW | RTLD_LOCAL);
    int (*unlocked_since_boot)(void) = library ? dlsym(library, "MKBDeviceUnlockedSinceBoot") : NULL;
    if (!unlocked_since_boot) return 1;
    int before = unlocked_since_boot();
    fprintf(stderr, "HuntMob: cold Class C unlocked-since-boot before=%d\n", before);
    if (before != 0 && before != 1) return 1;
    char *mount[] = {"/System/Library/Filesystems/apfs.fs/mount_apfs", "-o", "rdonly",
                     "/dev/disk0s1s2", "/mnt2", NULL};
    if (command(mount)) {
        fprintf(stderr, "HuntMob: cold Class C mount-unavailable\n");
        int after = unlocked_since_boot();
        fprintf(stderr, "HuntMob: cold Class C unlocked-since-boot after=%d\n", after);
        if (!before && !after) checkpoint("bfu-mount-unvalidated");
        return 1;
    }
    enum huntmob_cold_result outcome = HUNTMOB_COLD_FAILURE;
    if (mounted_identity()) {
        fprintf(stderr, "HuntMob: cold Class C mount-identity-failed\n");
        goto unmount;
    }
    fprintf(stderr, "HuntMob: cold Class C exact Data UUID and readonly CPROTECT matched\n");
    int fd = open("/mnt2/.huntmob-protection-probe", O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    int access_error = fd < 0 ? errno : 0;
    bool metadata = false, complete = false, matches = false;
    if (fd >= 0) {
        struct stat file;
        metadata = !fstat(fd, &file) && S_ISREG(file.st_mode) && file.st_nlink == 1 &&
                   file.st_size == 64 && fcntl(fd, F_GETPROTECTIONCLASS) == 3;
        if (metadata) {
            unsigned char actual[64] = {0}, actual_digest[CC_SHA256_DIGEST_LENGTH] = {0}, extra = 0;
            ssize_t count = pread(fd, actual, sizeof(actual), 0);
            access_error = count < 0 ? errno : 0;
            if (count == (ssize_t)sizeof(actual)) {
                ssize_t tail = pread(fd, &extra, 1, sizeof(actual));
                complete = tail == 0;
                if (tail < 0) access_error = errno;
            }
            unsigned difference = 0;
            bool hashed = complete && CC_SHA256(actual, sizeof(actual), actual_digest) != NULL;
            for (size_t i = 0; i < sizeof(actual_digest); i++) difference |= actual_digest[i] ^ expected_digest[i];
            matches = hashed && !difference;
            memset(actual, 0, sizeof(actual));
        }
        close(fd);
    }
    int after = unlocked_since_boot();
    fprintf(stderr, "HuntMob: cold Class C unlocked-since-boot after=%d\n", after);
    outcome = huntmob_cold_classify(before, after, access_error, metadata, complete, matches);
    fprintf(stderr, "HuntMob: cold Class C access_errno=%d metadata_valid=%d read_complete=%d digest_match=%d\n",
            access_error, metadata, complete, matches);
unmount:;
    char *unmount_args[] = {"/sbin/umount", "/mnt2", NULL};
    if (command(unmount_args)) return 1;
    if (outcome == HUNTMOB_COLD_AFU_MATCH) checkpoint("afu-read-match");
    if (outcome == HUNTMOB_COLD_BFU_DENIED) checkpoint("bfu-denied");
    if (outcome == HUNTMOB_COLD_STATE_CHANGED) checkpoint("unlock-state-changed-unvalidated");
    if (outcome == HUNTMOB_COLD_UNEXPECTED_BFU_ACCESS)
        fprintf(stderr, "HuntMob: cold Class C unexpected BFU access; read not validated\n");
    return 1;
}
