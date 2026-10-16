/* Own DATA-v2 only: seed the stock FactoryData directory ancestry on Hardware.
 * No Data/keybag/locker contents, class override, crypto API or formatting.
 * Primary restore contract: restored_external 0x100015078..509c creates this
 * ancestry recursively, mode0755 uid0 gid0, without a protection-class override.
 */
#include "virtual_v1_scope.h"
#include <stdbool.h>
#include <dirent.h>
#include <stdint.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <uuid/uuid.h>
#define FACTORY_VM_UUID "9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"
#define FACTORY_HARDWARE_UUID "A264DAE3-874A-4B57-9FAD-50DDB8E77A47"
_Static_assert(sizeof(HUNTMOB_VM_UUID) == sizeof(FACTORY_VM_UUID), "Exact own VM UUID required");

static void error_metadata(const char *stage, unsigned index, int error) {
    fprintf(stderr, "HuntMob: FactoryData failure stage=%s index=%u errno=%d\n", stage, index, error);
}

/* BEGIN PUBLIC-TESTABLE DIRECTORY METADATA CORE */
static int directory_metadata(int fd, dev_t device) {
    struct stat info;
    if (fstat(fd, &info)) return 1;
    if (!S_ISDIR(info.st_mode) || info.st_dev != device ||
        (info.st_mode & 07777) != 0755 || info.st_uid != 0 || info.st_gid != 0) {
        errno = EINVAL;
        return 1;
    }
    return 0;
}
static int prepare_factory_ancestry(int hardware_fd, dev_t device) {
    static const char *const components[] = {"FactoryData", "System", "Library", "Caches", "com.apple.factorydata"};
    int parent = dup(hardware_fd);
    if (parent < 0) { error_metadata("dup-root", 0, errno); return 1; }
    for (unsigned index = 0; index < sizeof(components) / sizeof(components[0]); index++) {
        bool created = false;
        int child = -1, failure = 0;
        if (mkdirat(parent, components[index], 0755) == 0) created = true;
        else if (errno != EEXIST) { error_metadata("mkdir", index + 1, errno); close(parent); return 1; }
        child = openat(parent, components[index], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (child < 0) { error_metadata("open-directory", index + 1, errno); close(parent); return 1; }
        /* Never repair or change existing directories. New directories only
         * receive the stock ownership/mode; no protection-class fcntl is used. */
        if (created && (fchown(child, 0, 0) || fchmod(child, 0755))) failure = errno;
        if (!failure && directory_metadata(child, device)) failure = errno;
        if (!failure && (fsync(child) || fsync(parent))) failure = errno;
        if (failure) {
            error_metadata("metadata-or-sync", index + 1, failure);
            close(child); close(parent); return 1;
        }
        fprintf(stderr, "HuntMob: FactoryData directory index=%u created=%d metadata_valid=1\n", index + 1, created);
        close(parent);
        parent = child;
    }
    close(parent);
    return 0;
}
/* END PUBLIC-TESTABLE DIRECTORY METADATA CORE */

static int command(const char *stage, char *const argv[]) {
    pid_t child = fork();
    if (child < 0) { error_metadata(stage, 0, errno); return 1; }
    if (!child) { alarm(60); execv(argv[0], argv); _exit(127); }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) { error_metadata(stage, 0, errno); return 1; }
    fprintf(stderr, "HuntMob: FactoryData command stage=%s exit=%d signal=%d\n", stage,
            WIFEXITED(status) ? WEXITSTATUS(status) : -1, WIFSIGNALED(status) ? WTERMSIG(status) : 0);
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}
static int empty_system_mountpoint(void) {
    struct stat point, root;
    struct statfs fs;
    if (lstat("/mnt6", &point) || !S_ISDIR(point.st_mode) || stat("/", &root) || point.st_dev != root.st_dev ||
        statfs("/mnt6", &fs) || strcmp(fs.f_fstypename, "apfs") || strcmp(fs.f_mntonname, "/")) return 1;
    int fd = open("/mnt6", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return 1;
    DIR *directory = fdopendir(fd);
    if (!directory) { close(fd); return 1; }
    struct dirent *entry;
    int result = 0;
    errno = 0;
    while ((entry = readdir(directory))) {
        if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) { result = 1; break; }
    }
    if (!entry && errno) result = 1;
    closedir(directory);
    return result;
}
static int hardware_identity(dev_t *device) {
    struct stat node, point;
    struct statfs fs;
    struct attrlist attr = {0};
    unsigned char value[20] = {0};
    uuid_t expected;
    uint32_t length = 0;
    if (lstat("/dev/disk0s1s4", &node) || !S_ISBLK(node.st_mode) ||
        lstat("/mnt6", &point) || !S_ISDIR(point.st_mode) || point.st_dev != node.st_rdev ||
        statfs("/mnt6", &fs) || strcmp(fs.f_fstypename, "apfs") || strcmp(fs.f_mntonname, "/mnt6") ||
        strcmp(fs.f_mntfromname, "/dev/disk0s1s4") || (fs.f_flags & MNT_RDONLY)) return 1;
    attr.bitmapcount = ATTR_BIT_MAP_COUNT;
    attr.volattr = ATTR_VOL_INFO | ATTR_VOL_UUID;
    if (uuid_parse(FACTORY_HARDWARE_UUID, expected) ||
        getattrlist("/mnt6", &attr, value, sizeof(value), 0)) return 1;
    memcpy(&length, value, sizeof(length));
    if (length != sizeof(value) || memcmp(value + sizeof(length), expected, sizeof(expected))) return 1;
    *device = point.st_dev;
    return 0;
}
int main(void) {
    alarm(150);
    umask(0);
    if (strcmp(HUNTMOB_VM_UUID, FACTORY_VM_UUID) || virtual_v1_scope()) return 1;
    struct stat node;
    if (lstat("/dev/disk0s1s4", &node) || !S_ISBLK(node.st_mode) || empty_system_mountpoint()) {
        error_metadata("preflight", 0, errno); return 1;
    }
    char *mount[] = {"/System/Library/Filesystems/apfs.fs/mount_apfs", "/dev/disk0s1s4", "/mnt6", NULL};
    if (command("mount-hardware", mount)) return 1;
    int result = 1, fd = -1;
    dev_t device = 0;
    if (hardware_identity(&device)) { error_metadata("hardware-identity", 0, errno); goto unmount; }
    fprintf(stderr, "HuntMob: FactoryData Hardware UUID exact matched\n");
    fd = open("/mnt6", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) { error_metadata("open-hardware", 0, errno); goto unmount; }
    if (prepare_factory_ancestry(fd, device)) goto unmount;
    if (hardware_identity(&device) || fsync(fd)) { error_metadata("final-identity-or-sync", 0, errno); goto unmount; }
    fprintf(stderr, "HuntMob: FactoryData metadata verified directories=5 mode=0755 uid=0 gid=0\n");
    result = 0;
unmount:
    if (fd >= 0) close(fd);
    char *unmount[] = {"/sbin/umount", "/mnt6", NULL};
    if (command("unmount-hardware", unmount)) return 1;
    if (empty_system_mountpoint()) { error_metadata("unmount-readback", 0, errno); return 1; }
    fprintf(stderr, "HuntMob: FactoryData Hardware unmounted\n");
    if (result) return 1;
    fprintf(stderr, "HuntMob: provisioning checkpoint ready; own DATA-v2 FactoryData metadata prepared\n");
    for (;;) pause();
}
