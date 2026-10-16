/* Owned HuntMob virtual SEP v1 lab. Scope marker is not hardware attestation. */
#ifndef HUNTMOB_VM_UUID
#error A per-profile public VM UUID must be compiled into this helper.
#endif
#include <TargetConditionals.h>
#if !TARGET_OS_IPHONE || TARGET_OS_SIMULATOR
#error Only an owned iPhoneOS guest is supported.
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <unistd.h>
static int virtual_v1_scope(void) {
    const char expected[] = "HUNTMOB VIRTUAL SEP MODEL V1\n" HUNTMOB_VM_UUID "\n";
    char build[64] = {0}, model[64] = {0}, marker[sizeof(expected)] = {0};
    size_t size = sizeof(build);
    if (sysctlbyname("kern.osversion", build, &size, NULL, 0) || strcmp(build,"18A5351d")) return 1;
    size = sizeof(model);
    if (sysctlbyname("hw.machine", model, &size, NULL, 0) || strcmp(model,"iPhone12,1")) return 1;
    int fd = open("/usr/libexec/huntmob-virtual-sep-v1", O_RDONLY|O_NOFOLLOW);
    if (fd < 0) return 1;
    struct stat info;
    int bad = fstat(fd,&info) || !S_ISREG(info.st_mode) || info.st_nlink != 1 ||
              info.st_size != sizeof(expected)-1 ||
              read(fd,marker,sizeof(marker)) != sizeof(expected)-1 ||
              memcmp(marker,expected,sizeof(expected)-1);
    close(fd);
    return bad != 0;
}
