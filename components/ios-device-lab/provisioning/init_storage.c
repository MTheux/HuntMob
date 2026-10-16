/* Owned virtual lab provisioning. Keep the stock Data Protection verifier.
 * No network, no credential reads, no secret logging. iPhoneOS binary only.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
static int stock_utility(const char *option, const char *input) {
    pid_t child = fork();
    if (child < 0) { perror("HuntMob: utility fork"); return 1; }
    if (child == 0) {
        char *args[] = {"/usr/libexec/seputil", (char *)option, (char *)input, NULL};
        execv(args[0], args);
        perror("HuntMob: stock utility"); _exit(127);
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) { perror("HuntMob: utility wait"); return 1; }
    }
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}
static int stock_restore_sep(void) {
    const char *firmware = "/usr/libexec/huntmob-restore-sep.img4";
    struct stat info;
    if (lstat(firmware, &info) != 0) {
        if (errno == ENOENT) return 0;
        perror("HuntMob: restore firmware preflight"); return 1;
    }
    if (!S_ISREG(info.st_mode)) {
        fprintf(stderr, "HuntMob: invalid owned restore firmware\n"); return 1;
    }
    fprintf(stderr, "HuntMob: stock SEP restore with ART initialization\n");
    if (stock_utility("--restore+art", firmware) != 0) {
        fprintf(stderr, "HuntMob: stock SEP restore failed; protection remains required\n");
        return 1;
    }
    fprintf(stderr, "HuntMob: stock fresh-restore SEP erase notification\n");
    if (stock_utility("--erase", NULL) != 0) {
        fprintf(stderr, "HuntMob: stock SEP erase notification failed\n"); return 1;
    }
    /* The owned clone has no installed client app or Data volume. This is the
     * stock fresh-restore commit, never an operation on the host's SEP. */
    fprintf(stderr, "HuntMob: stock fresh-restore SEP hash commit\n");
    if (stock_utility("--commit-hash", "--erase") != 0) {
        fprintf(stderr, "HuntMob: stock SEP hash commit failed\n"); return 1;
    }
    fprintf(stderr, "HuntMob: stock normal SEP nonce initialization\n");
    if (stock_utility("--new-nonce", NULL) != 0) {
        fprintf(stderr, "HuntMob: stock SEP nonce initialization failed\n"); return 1;
    }
    fprintf(stderr, "HuntMob: releasing restore Gigalocker before stock boot initialization\n");
    if (stock_utility("--gigalocker-shutdown", NULL) != 0) {
        fprintf(stderr, "HuntMob: stock Gigalocker shutdown failed\n"); return 1;
    }
    if (access("/usr/libexec/huntmob-provision-checkpoint", F_OK) == 0) {
        sync();
        fprintf(stderr, "HuntMob: provisioning checkpoint ready; waiting for owned VM shutdown\n");
        /* Preparation only: never report the Data Protection boot task as
         * successful in place of its original verifier. The host stops this
         * exclusive VM through QMP and cold-boots the complete saved cohort. */
        for (;;) pause();
    }
    return 0;
}
int main(int argc, char **argv) {
    struct stat info;
    const char *locker = "/private/xarts/81879F33-B0F2-573A-AE12-6B517C322E33.gl";
    int locker_status = stat(locker, &info);
    if (locker_status != 0 && errno != ENOENT) {
        perror("HuntMob: xART preflight"); return 1;
    }
    if (locker_status != 0 || access("/usr/libexec/huntmob-restore-sep.img4", F_OK) == 0) {
        fprintf(stderr, "HuntMob: stock virtual xART initialization\n");
        if (stock_utility("--gigalocker-init", NULL) != 0) {
            fprintf(stderr, "HuntMob: stock provisioning failed; protection remains required\n");
            return 1;
        }
    }
    if (stock_restore_sep() != 0) return 1;
    size_t count = argc > 0 ? (size_t)argc : 1;
    char **args = calloc(count + 1, sizeof(char *));
    if (!args) { perror("HuntMob: verifier arguments"); return 1; }
    args[0] = "/usr/libexec/init_data_protection";
    for (int index = 1; index < argc; index++) args[index] = argv[index];
    fprintf(stderr, "HuntMob: invoking stock Data Protection verifier\n");
    const char *data_marker = "/usr/libexec/huntmob-prepare-data";
    if (lstat(data_marker, &info) == 0) {
        if (!S_ISREG(info.st_mode)) {
            fprintf(stderr, "HuntMob: invalid owned Data preparation marker\n"); free(args); return 1;
        }
        pid_t child = fork();
        if (child < 0) { perror("HuntMob: verifier fork"); free(args); return 1; }
        if (child == 0) {
            execv("/usr/libexec/huntmob-original/init_data_protection", args);
            perror("HuntMob: stock verifier"); _exit(127);
        }
        int status = 0;
        while (waitpid(child, &status, 0) < 0) {
            if (errno != EINTR) { perror("HuntMob: verifier wait"); free(args); return 1; }
        }
        free(args);
        if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
            fprintf(stderr, "HuntMob: Data volume creation blocked by stock protection verifier\n");
            return WIFEXITED(status) && WEXITSTATUS(status) != 0 ? WEXITSTATUS(status) : 1;
        }
        fprintf(stderr, "HuntMob: stock protection verifier completed; initializing iOS protected Data\n");
        char *format[] = {"/usr/libexec/huntmob-prepare-userdata", NULL};
        execv(format[0], format);
        perror("HuntMob: stock Data volume formatter"); return 1;
    }
    if (errno != ENOENT) { perror("HuntMob: Data preparation preflight"); free(args); return 1; }
    execv("/usr/libexec/huntmob-original/init_data_protection", args);
    perror("HuntMob: stock verifier"); free(args); return 1;
}
