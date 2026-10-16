/* AUTHORIZED TESTING ONLY - isolated own DATA-v2 lab.
 * A bounded process-metadata child after the ORIGINAL stock init exits zero.
 * No patch to launchd, SEP/ANS, key derivation, APFS or stock program bytes.
 */
#include "virtual_v1_scope.h"
#include "post_keybag_sequence_v2.h"
#include <CommonCrypto/CommonDigest.h>
#include <signal.h>
#include <stdint.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <uuid/uuid.h>
#ifndef HUNTMOB_EXPECTED_DATA_UUID
#error Exact owned Data UUID required
#endif
#ifndef HUNTMOB_EXPECTED_OBSERVER_SHA256
#error Exact signed observer executable digest required
#endif
#define STOCK_KEYBAGD "/usr/libexec/huntmob-original/keybagd"
#define STOCK_KEYBAGD_SHA256 "4cd2506d4f47a150da3748887127eca0420051d3095bf6dd1470f35805920cf6"
#define OBSERVER "/usr/libexec/huntmob-ui-process-observer"
_Static_assert(sizeof(HUNTMOB_EXPECTED_OBSERVER_SHA256) == 65, "Exact digest required");
static int readonly_system_identity(void);
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
static int verify_program(const char *program, const char *sha256) {
    int fd = open(program, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return 1;
    struct stat before, after, path;
    unsigned char expected[CC_SHA256_DIGEST_LENGTH], actual[CC_SHA256_DIGEST_LENGTH], buffer[8192];
    CC_SHA256_CTX hash;
    int result = 1;
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_nlink != 1 ||
        (before.st_uid != 0 && (strcmp(program, OBSERVER) || readonly_system_identity())) ||
        (before.st_mode & 0022) || before.st_size <= 0 || before.st_size > 16 * 1024 * 1024 ||
        parse_digest(sha256, expected) || !CC_SHA256_Init(&hash)) goto done;
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
        fstat(fd, &after) || lstat(program, &path) || !S_ISREG(path.st_mode) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino || before.st_size != after.st_size ||
        before.st_mtime != after.st_mtime || before.st_ctime != after.st_ctime ||
        before.st_dev != path.st_dev || before.st_ino != path.st_ino || before.st_size != path.st_size) goto done;
    result = 0;
done:
    close(fd);
    memset(buffer, 0, sizeof(buffer));
    return result;
}
static int readonly_system_identity(void) {
    struct statfs fs;
    struct attrlist attr = {0};
    unsigned char value[20] = {0};
    uuid_t expected;
    uint32_t length = 0;
    if (statfs("/", &fs) || strcmp(fs.f_fstypename, "apfs") ||
        strcmp(fs.f_mntonname, "/") || strcmp(fs.f_mntfromname, "/dev/disk0s1s1") ||
        !(fs.f_flags & MNT_RDONLY)) return 1;
    attr.bitmapcount = ATTR_BIT_MAP_COUNT;
    attr.volattr = ATTR_VOL_INFO | ATTR_VOL_UUID;
    if (uuid_parse("5133F48D-5D9E-499B-A8BA-45E692E36FD9", expected) ||
        getattrlist("/", &attr, value, sizeof(value), 0)) return 1;
    memcpy(&length, value, sizeof(length));
    return length != sizeof(value) || memcmp(value + sizeof(length), expected, sizeof(expected));
}
static int enable_alarm(void) {
    struct sigaction action = {0};
    sigset_t unblocked;
    action.sa_handler = SIG_DFL;
    if (sigemptyset(&action.sa_mask) || sigaction(SIGALRM, &action, NULL) ||
        sigemptyset(&unblocked) || sigaddset(&unblocked, SIGALRM) ||
        sigprocmask(SIG_UNBLOCK, &unblocked, NULL)) return 1;
    return 0;
}
static int data_identity(void) {
    struct statfs fs;
    struct attrlist attr = {0};
    unsigned char value[20] = {0};
    uuid_t expected;
    uint32_t length = 0;
    if (statfs("/private/var", &fs) || strcmp(fs.f_fstypename, "apfs") ||
        strcmp(fs.f_mntonname, "/private/var") || strcmp(fs.f_mntfromname, "/dev/disk0s1s2") ||
        !(fs.f_flags & MNT_CPROTECT)) return 1;
    attr.bitmapcount = ATTR_BIT_MAP_COUNT;
    attr.volattr = ATTR_VOL_INFO | ATTR_VOL_UUID;
    if (uuid_parse(HUNTMOB_EXPECTED_DATA_UUID, expected) || uuid_is_null(expected) ||
        getattrlist("/private/var", &attr, value, sizeof(value), 0)) return 1;
    memcpy(&length, value, sizeof(length));
    return length != sizeof(value) || memcmp(value + sizeof(length), expected, sizeof(expected));
}
static int stock_status(int status) {
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        signal(sig, SIG_DFL);
        kill(getpid(), sig);
        return 128 + sig;
    }
    return 126;
}
int main(int argc, char **argv) {
    enum huntmob_keybag_shim_route route = huntmob_keybag_shim_arguments(argc, argv);
    if (route == HUNTMOB_KEYBAG_SHIM_REJECT || virtual_v1_scope() ||
        verify_program(STOCK_KEYBAGD, STOCK_KEYBAGD_SHA256)) {
        fprintf(stderr, "HuntMob:ui-proc wrapper-guard-failed\n");
        return 125;
    }
    if (route == HUNTMOB_KEYBAG_SHIM_DAEMON) {
        alarm(0);
        execv(STOCK_KEYBAGD, argv);
        return 127;
    }
    if (enable_alarm()) return 125;
    alarm(100);
    if (data_identity()) {
        fprintf(stderr, "HuntMob:ui-proc wrapper-data-guard-failed\n");
        return 125;
    }
    fprintf(stderr, "HuntMob:ui-proc stock-init-start\n");
    pid_t child = fork();
    if (child < 0) return 125;
    if (!child) {
        alarm(90);
        char *stock_args[] = {"keybagd", "--init", NULL};
        execv(STOCK_KEYBAGD, stock_args);
        _exit(127);
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 125;
    fprintf(stderr, "HuntMob:ui-proc stock-init-exit=%d signal=%d\n",
        WIFEXITED(status) ? WEXITSTATUS(status) : -1, WIFSIGNALED(status) ? WTERMSIG(status) : 0);
    if (!WIFEXITED(status) || WEXITSTATUS(status)) return stock_status(status);
    if (virtual_v1_scope() || data_identity() ||
        verify_program(OBSERVER, HUNTMOB_EXPECTED_OBSERVER_SHA256)) {
        fprintf(stderr, "HuntMob:ui-proc wrapper-post-init-guard-failed\n");
        return 0;
    }
    child = fork();
    if (child < 0) {
        /* Diagnostic failure is explicit; do not invent a stock init failure. */
        fprintf(stderr, "HuntMob:ui-proc observer-spawn-failed\n");
        return 0;
    }
    if (!child) {
        if (enable_alarm()) _exit(125);
        alarm(130);
        if (setpgid(0, 0)) _exit(125);
        char *observer_args[] = {"huntmob-ui-process-observer", "--metadata-only", NULL};
        execv(OBSERVER, observer_args);
        _exit(127);
    }
    /* Establish and verify the child's group BEFORE this boot-task process
     * can exit. EACCES after child exec is accepted only if the group matches. */
    if ((setpgid(child, child) && errno != EACCES) || getpgid(child) != child) {
        fprintf(stderr, "HuntMob:ui-proc observer-group-failed\n");
        kill(child, SIGKILL);
        while (waitpid(child, &status, 0) < 0) if (errno != EINTR) break;
        alarm(0);
        return 0;
    }
    fprintf(stderr, "HuntMob:ui-proc observer-spawned pid=%d\n", child);
    alarm(0);
    /* No wait/checkpoint: let the stock launchd sequence continue. The child
     * is bounded by its own alarm/deadline and never installs a service. */
    return 0;
}
