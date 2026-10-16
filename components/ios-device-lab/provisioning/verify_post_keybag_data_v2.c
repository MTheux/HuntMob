/* Own DATA-v2 post-Boot/keybag experiment. NOT an independent keybag loader.
 * Staging must first prove the normal launchd Boot/keybag definition/order.
 * Program changes to this wrapper; original argv [keybagd,--init] stays exact.
 * The original /usr/libexec/keybagd remains untouched and executes once. */
#include "virtual_v1_scope.h"
#include "cold_read_policy_v2.h"
#include "post_keybag_sequence_v2.h"
#include <CommonCrypto/CommonDigest.h>
#include <dlfcn.h>
#include <stdint.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <uuid/uuid.h>
#ifndef HUNTMOB_EXPECTED_DATA_UUID
#error Exact previously created Data UUID is required.
#endif
#ifndef HUNTMOB_EXPECTED_CANARY_SHA256
#error SHA256 of the public probe is required, never its original bytes.
#endif
#ifdef HUNTMOB_POST_KEYBAG_PATH_SHIM_V2
#if HUNTMOB_POST_KEYBAG_PATH_SHIM_V2 != 1
#error Only the explicit owned v2 path-shim contract is supported.
#endif
#define STOCK_KEYBAGD "/usr/libexec/huntmob-original/keybagd"
#else
#define STOCK_KEYBAGD "/usr/libexec/keybagd"
#endif
#define STOCK_KEYBAGD_SHA256 "4cd2506d4f47a150da3748887127eca0420051d3095bf6dd1470f35805920cf6"
_Static_assert(sizeof(HUNTMOB_EXPECTED_CANARY_SHA256) == 65, "Exact probe SHA256 required");
struct verifier {
    struct stat keybag;
    bool identity_saved;
    unsigned char expected_digest[CC_SHA256_DIGEST_LENGTH];
    const char *result;
};
static int hex_digit(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}
static int parse_digest(const char *hex, unsigned char out[CC_SHA256_DIGEST_LENGTH]) {
    for (size_t i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
        int a = hex_digit(hex[i * 2]), b = hex_digit(hex[i * 2 + 1]);
        if (a < 0 || b < 0) return 1;
        out[i] = (unsigned char)((a << 4) | b);
    }
    return 0;
}
static int fixed_digest_equal(const unsigned char *a, const unsigned char *b) {
    unsigned difference = 0;
    for (size_t i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) difference |= a[i] ^ b[i];
    return !difference;
}
static int verify_stock(void) {
    int fd = open(STOCK_KEYBAGD, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return 1;
    struct stat before, after, path;
    unsigned char expected[CC_SHA256_DIGEST_LENGTH], actual[CC_SHA256_DIGEST_LENGTH], buffer[8192];
    CC_SHA256_CTX hash;
    int result = 1;
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_nlink != 1 || before.st_uid != 0 ||
        (before.st_mode & 0022) || before.st_size <= 0 || before.st_size > 16 * 1024 * 1024 ||
        parse_digest(STOCK_KEYBAGD_SHA256, expected) || !CC_SHA256_Init(&hash)) goto done;
    off_t total = 0;
    for (;;) {
        ssize_t count = read(fd, buffer, sizeof(buffer));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) goto done;
        if (!count) break;
        total += count;
        if (total > before.st_size || !CC_SHA256_Update(&hash, buffer, (CC_LONG)count)) goto done;
    }
    if (total != before.st_size || !CC_SHA256_Final(actual, &hash) || !fixed_digest_equal(actual, expected) ||
        fstat(fd, &after) || lstat(STOCK_KEYBAGD, &path) || !S_ISREG(path.st_mode) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino || before.st_size != after.st_size ||
        before.st_mtime != after.st_mtime || before.st_ctime != after.st_ctime ||
        before.st_dev != path.st_dev || before.st_ino != path.st_ino || before.st_size != path.st_size) goto done;
    result = 0;
done:
    close(fd);
    memset(buffer, 0, sizeof(buffer));
    return result;
}
static int data_identity(void *opaque) {
    struct verifier *state = opaque;
    struct statfs fs;
    struct attrlist attr = {0};
    unsigned char value[20] = {0};
    uuid_t expected;
    uint32_t length = 0;
    struct stat bag, volume, directory;
    if (statfs("/private/var", &fs) || strcmp(fs.f_fstypename, "apfs") ||
        strcmp(fs.f_mntonname, "/private/var") || strcmp(fs.f_mntfromname, "/dev/disk0s1s2") ||
        !(fs.f_flags & MNT_CPROTECT)) goto failed;
    attr.bitmapcount = ATTR_BIT_MAP_COUNT;
    attr.volattr = ATTR_VOL_INFO | ATTR_VOL_UUID;
    if (uuid_parse(HUNTMOB_EXPECTED_DATA_UUID, expected) || uuid_is_null(expected) ||
        getattrlist("/private/var", &attr, value, sizeof(value), 0)) goto failed;
    memcpy(&length, value, sizeof(length));
    if (length != sizeof(value) || memcmp(value + sizeof(length), expected, sizeof(expected))) goto failed;
    /* Names/stat only. Never open/hash/export this private system bag. An
     * absent or replaced bag is a failure, never a request to create one. */
    if (stat("/private/var", &volume) || lstat("/private/var/keybags", &directory) ||
        !S_ISDIR(directory.st_mode) || directory.st_dev != volume.st_dev ||
        lstat("/private/var/keybags/systembag.kb", &bag) || !S_ISREG(bag.st_mode) ||
        bag.st_nlink != 1 || bag.st_size <= 0 || bag.st_dev != volume.st_dev) goto failed;
    if (state->identity_saved && (state->keybag.st_dev != bag.st_dev || state->keybag.st_ino != bag.st_ino ||
                                 state->keybag.st_size != bag.st_size)) goto failed;
    state->keybag = bag;
    state->identity_saved = true;
    fprintf(stderr, "HuntMob: post-keybag Data UUID CPROTECT and existing-bag identity matched\n");
    return 0;
failed:
    fprintf(stderr, "HuntMob: post-keybag data-identity-failed\n");
    return 1;
}
static int stock_init(void *opaque) {
    (void)opaque;
    if (verify_stock()) {
        fprintf(stderr, "HuntMob: post-keybag stock-binary-pin-failed\n");
        return 1;
    }
    fprintf(stderr, "HuntMob: post-keybag stock-init-start\n");
    pid_t child = fork();
    if (child < 0) return 1;
    if (!child) {
        alarm(90);
        char *args[] = {"keybagd", "--init", NULL};
        execv(STOCK_KEYBAGD, args);
        _exit(127);
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 1;
    fprintf(stderr, "HuntMob: post-keybag stock-init-exit=%d signal=%d\n",
            WIFEXITED(status) ? WEXITSTATUS(status) : -1, WIFSIGNALED(status) ? WTERMSIG(status) : 0);
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}
static int read_probe(void *opaque) {
    struct verifier *state = opaque;
    void *library = dlopen("/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag", RTLD_NOW | RTLD_LOCAL);
    int (*unlocked)(void) = library ? dlsym(library, "MKBDeviceUnlockedSinceBoot") : NULL;
    if (!unlocked) return 1;
    int before = unlocked();
    fprintf(stderr, "HuntMob: post-keybag Class C unlocked-since-boot before=%d\n", before);
    if (before != 0 && before != 1) return 1;
    int fd = open("/private/var/.huntmob-protection-probe", O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    int access_error = fd < 0 ? errno : 0;
    bool metadata = false, complete = false, matches = false;
    if (fd >= 0) {
        struct stat file;
        metadata = !fstat(fd, &file) && S_ISREG(file.st_mode) && file.st_nlink == 1 &&
                   file.st_size == 64 && file.st_dev == state->keybag.st_dev &&
                   fcntl(fd, F_GETPROTECTIONCLASS) == 3;
        if (metadata) {
            unsigned char actual[64] = {0}, digest[CC_SHA256_DIGEST_LENGTH] = {0}, tail_byte = 0;
            ssize_t count = pread(fd, actual, sizeof(actual), 0);
            access_error = count < 0 ? errno : 0;
            if (count == (ssize_t)sizeof(actual)) {
                ssize_t tail = pread(fd, &tail_byte, 1, sizeof(actual));
                complete = tail == 0;
                if (tail < 0) access_error = errno;
            }
            matches = complete && CC_SHA256(actual, sizeof(actual), digest) &&
                      fixed_digest_equal(digest, state->expected_digest);
            memset(actual, 0, sizeof(actual));
            memset(digest, 0, sizeof(digest));
        }
        close(fd);
    }
    int after = unlocked();
    fprintf(stderr, "HuntMob: post-keybag Class C unlocked-since-boot after=%d\n", after);
    fprintf(stderr, "HuntMob: post-keybag Class C access_errno=%d metadata_valid=%d read_complete=%d digest_match=%d\n",
            access_error, metadata, complete, matches);
    switch (huntmob_cold_classify(before, after, access_error, metadata, complete, matches)) {
        case HUNTMOB_COLD_AFU_MATCH: state->result = "afu-read-match"; break;
        case HUNTMOB_COLD_BFU_DENIED: state->result = "bfu-denied"; break;
        case HUNTMOB_COLD_STATE_CHANGED: state->result = "unlock-state-changed-unvalidated"; break;
        default:
            fprintf(stderr, "HuntMob: post-keybag Class C result=read-failed-unvalidated\n");
            return 1;
    }
    return 0;
}
int main(int argc, char **argv) {
    alarm(180);
#ifdef HUNTMOB_POST_KEYBAG_PATH_SHIM_V2
    enum huntmob_keybag_shim_route route = huntmob_keybag_shim_arguments(argc, argv);
    if (route == HUNTMOB_KEYBAG_SHIM_REJECT || virtual_v1_scope()) return 1;
    if (route == HUNTMOB_KEYBAG_SHIM_DAEMON) {
        if (verify_stock()) return 1;
        /* Replace this process: preserve stock argv, environment, PID and its
         * launchd bootstrap namespace. No fork/init/probe/checkpoint here.
         * Never let the short experiment deadline kill the normal daemon. */
        alarm(0);
        execv(STOCK_KEYBAGD, argv);
        return 1;
    }
#else
    if (!huntmob_post_keybag_arguments(argc, argv) || virtual_v1_scope()) return 1;
#endif
    struct verifier state = {0};
    if (parse_digest(HUNTMOB_EXPECTED_CANARY_SHA256, state.expected_digest) ||
        huntmob_post_keybag_sequence(&state, data_identity, stock_init, read_probe)) return 1;
    fprintf(stderr, "HuntMob: post-keybag Class C result=%s\n", state.result);
    fprintf(stderr, "HuntMob: provisioning checkpoint ready; own DATA-v2 post-keybag cold-read observation\n");
    for (;;) pause();
}
