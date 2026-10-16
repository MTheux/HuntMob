/* Pinned iOS14 newfs_apfs: role=p is Update(192); role=u is User(2). */
#ifndef HUNTMOB_APPEND_UPDATE_POLICY_V2_H
#define HUNTMOB_APPEND_UPDATE_POLICY_V2_H
#include <string.h>
#define HUNTMOB_UPDATE_NEWFS "/System/Library/Filesystems/apfs.fs/newfs_apfs"
static inline int huntmob_update_append_arguments(int argc, char *const argv[]) {
    static const char *const exact[] = {HUNTMOB_UPDATE_NEWFS, "-A", "-o", "role=p", "-v", "Update", "/dev/disk0s1"};
    if (argc != 7 || !argv) return 0;
    for (unsigned i = 0; i < sizeof(exact) / sizeof(exact[0]); i++)
        if (!argv[i] || strcmp(argv[i], exact[i])) return 0;
    return argv[7] == NULL;
}
#endif
