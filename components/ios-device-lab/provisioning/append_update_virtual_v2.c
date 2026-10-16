/* Own DATA-v2 only: append one Update volume using unchanged stock newfs_apfs.
 * The pinned tool routes -A through its existing-container lookup and uses
 * role=p for Update192. No Data format/protection/keybag/locker API is used.
 */
#include "virtual_v1_scope.h"
#include "append_update_policy_v2.h"
#include <CommonCrypto/CommonDigest.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/wait.h>
#include <time.h>
#define UPDATE_VM_UUID "9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"
#define NEWFS_SHA256 "8dbd1aa6abbfbae8d0797e35b518441172f2a1e3b8bb6cb3f8f9186aa7dfe997"
static void failure(const char *stage, int error) {
    fprintf(stderr, "HuntMob: Update append failure stage=%s errno=%d\n", stage, error);
}
static int block_identity(const char *path, dev_t *device) {
    struct stat info;
    if (lstat(path, &info)) return errno == ENOENT ? 0 : -1;
    if (!S_ISBLK(info.st_mode) || !info.st_rdev) { errno = EINVAL; return -1; }
    if (device) *device = info.st_rdev;
    return 1;
}
static int require_absent(const char *path) {
    int present = block_identity(path, NULL);
    if (present == 0) return 0;
    if (present == 1) errno = EEXIST;
    return 1;
}
static int existing_slots(dev_t expected[5], bool save) {
    for (unsigned i = 0; i < 5; i++) {
        char path[32];
        dev_t observed = 0;
        int length = snprintf(path, sizeof(path), "/dev/disk0s1s%u", i + 1);
        if (length <= 0 || (size_t)length >= sizeof(path) || block_identity(path, &observed) != 1) return 1;
        if (!save && observed != expected[i]) { errno = EINVAL; return 1; }
        for (unsigned j = 0; j < i; j++) if (observed == expected[j]) { errno = EINVAL; return 1; }
        if (save) expected[i] = observed;
    }
    return 0;
}
static int verify_stock_newfs(void) {
    int fd = open(HUNTMOB_UPDATE_NEWFS, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return 1;
    struct stat first, after, path;
    unsigned char hash[CC_SHA256_DIGEST_LENGTH], bytes[8192];
    char hex[CC_SHA256_DIGEST_LENGTH * 2 + 1];
    static const char digits[] = "0123456789abcdef";
    CC_SHA256_CTX context;
    int result = 1;
    if (fstat(fd, &first) || !S_ISREG(first.st_mode) || first.st_nlink != 1 || first.st_uid != 0 ||
        (first.st_mode & 0022) || first.st_size <= 0 || first.st_size > 32 * 1024 * 1024 ||
        !CC_SHA256_Init(&context)) goto done;
    off_t total = 0;
    for (;;) {
        ssize_t count = read(fd, bytes, sizeof(bytes));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) goto done;
        if (!count) break;
        total += count;
        if (total > first.st_size || !CC_SHA256_Update(&context, bytes, (CC_LONG)count)) goto done;
    }
    if (total != first.st_size || !CC_SHA256_Final(hash, &context) || fstat(fd, &after) ||
        lstat(HUNTMOB_UPDATE_NEWFS, &path) || !S_ISREG(path.st_mode) ||
        first.st_dev != after.st_dev || first.st_ino != after.st_ino || first.st_size != after.st_size ||
        first.st_mtime != after.st_mtime || first.st_ctime != after.st_ctime ||
        first.st_dev != path.st_dev || first.st_ino != path.st_ino || first.st_size != path.st_size) goto done;
    for (size_t i = 0; i < sizeof(hash); i++) { hex[i * 2] = digits[hash[i] >> 4]; hex[i * 2 + 1] = digits[hash[i] & 15]; }
    hex[sizeof(hex) - 1] = 0;
    result = strcmp(hex, NEWFS_SHA256) != 0;
done:
    close(fd);
    return result;
}
static int append_stock_update(char *const argv[]) {
    if (!huntmob_update_append_arguments(7, argv) || verify_stock_newfs()) {
        failure("stock-command-pin", 0); return 1;
    }
    fprintf(stderr, "HuntMob: Update append stock-newfs-start role=192 append_only=1\n");
    pid_t child = fork();
    if (child < 0) { failure("fork", errno); return 1; }
    if (!child) { alarm(60); execv(HUNTMOB_UPDATE_NEWFS, argv); _exit(127); }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) { failure("wait-child", errno); return 1; }
    fprintf(stderr, "HuntMob: Update append stock-newfs-exit=%d signal=%d\n",
            WIFEXITED(status) ? WEXITSTATUS(status) : -1, WIFSIGNALED(status) ? WTERMSIG(status) : 0);
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}
static int wait_single_new_slot(dev_t old_slots[5]) {
    struct timespec begin, now;
    if (clock_gettime(CLOCK_MONOTONIC, &begin)) return 1;
    for (;;) {
        dev_t added = 0;
        int present = block_identity("/dev/disk0s1s6", &added);
        if (present < 0 || require_absent("/dev/disk0s1s7") || existing_slots(old_slots, false)) return 1;
        if (present == 1) {
            for (unsigned i = 0; i < 5; i++) if (added == old_slots[i]) { errno = EINVAL; return 1; }
            return 0;
        }
        if (clock_gettime(CLOCK_MONOTONIC, &now)) return 1;
        if (now.tv_sec - begin.tv_sec >= 60) { errno = ETIMEDOUT; return 1; }
        usleep(100000);
    }
}
int main(void) {
    alarm(150);
    if (strcmp(HUNTMOB_VM_UUID, UPDATE_VM_UUID) || virtual_v1_scope()) return 1;
    dev_t old_slots[5] = {0};
    if (block_identity("/dev/disk0s1", NULL) != 1 || existing_slots(old_slots, true) ||
        require_absent("/dev/disk0s1s6") || require_absent("/dev/disk0s1s7")) {
        failure("preflight", errno); return 1;
    }
    fprintf(stderr, "HuntMob: Update append preflight existing_slots=5 slot6_absent=1 slot7_absent=1\n");
    char *argv[] = {HUNTMOB_UPDATE_NEWFS, "-A", "-o", "role=p", "-v", "Update", "/dev/disk0s1", NULL};
    if (append_stock_update(argv)) return 1;
    if (wait_single_new_slot(old_slots)) { failure("single-new-slot", errno); return 1; }
    sync();
    fprintf(stderr, "HuntMob: Update append slot6 ready existing_slots_preserved=5 slot7_absent=1\n");
    fprintf(stderr, "HuntMob: provisioning checkpoint ready; own DATA-v2 Update volume appended\n");
    for (;;) pause();
}
