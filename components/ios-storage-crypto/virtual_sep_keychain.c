/* HuntMob virtual SEP v1: host-owned experimental identity, not an Apple UID.
 * Root bytes are created inside this process and stored only through SecItem.
 * Delivery is exactly 32 binary bytes through an explicitly inherited pipe.
 * No root bytes, root digests or passwords are printed or accepted as argv.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <errno.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <uuid/uuid.h>

#define ROOT_BYTES 32
#define SERVICE "HuntMob.VirtualSEP.v1"

typedef struct Result {
    const char *status;
    OSStatus os_status;
    bool created;
    bool delivered;
} Result;

static SecKeychainRef keychain;

static void wipe(void *buffer, size_t length)
{
    volatile unsigned char *bytes = buffer;
    while (length--) {
        *bytes++ = 0;
    }
}

static bool valid_uuid(const char *value)
{
    if (!value || strlen(value) != 36) {
        return false;
    }
    for (size_t i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (value[i] != '-') {
                return false;
            }
        } else if (!((value[i] >= '0' && value[i] <= '9') ||
                     (value[i] >= 'a' && value[i] <= 'f'))) {
            return false;
        }
    }
    return true;
}

static bool valid_output_fd(int descriptor)
{
    struct stat info;
    if (descriptor < 3 || isatty(descriptor) || fstat(descriptor, &info) ||
        !S_ISFIFO(info.st_mode)) {
        return false;
    }
    for (int standard = 0; standard <= 2; standard++) {
        struct stat other;
        if (!fstat(standard, &other) && S_ISFIFO(other.st_mode) &&
            info.st_dev == other.st_dev && info.st_ino == other.st_ino) {
            return false;
        }
    }
    int flags = fcntl(descriptor, F_GETFL);
    return flags >= 0 && (flags & O_ACCMODE) != O_RDONLY;
}

static const char *status_name(OSStatus status)
{
    switch (status) {
    case errSecSuccess:
        return "ok";
    case errSecItemNotFound:
        return "missing_root";
    case errSecDuplicateItem:
        return "duplicate_root";
    case errSecInteractionNotAllowed:
        return "interaction_not_allowed";
    default:
        return "keychain_error";
    }
}

static CFMutableDictionaryRef query(const char *vm_uuid, bool adding)
{
    CFStringRef account = CFStringCreateWithCString(NULL, vm_uuid, kCFStringEncodingASCII);
    CFMutableDictionaryRef result = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    if (!account || !result) {
        if (account) CFRelease(account);
        if (result) CFRelease(result);
        return NULL;
    }
    CFDictionarySetValue(result, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(result, kSecAttrService, CFSTR(SERVICE));
    CFDictionarySetValue(result, kSecAttrAccount, account);
    CFDictionarySetValue(result, kSecUseAuthenticationUI, kSecUseAuthenticationUIFail);
    /* File-based macOS keychain: CLI tools have no provisioned access group.
     * Bind both add and query to the same default keychain, not the search list.
     * No iCloud synchronization or plaintext key file is configured. */
    CFDictionarySetValue(result, kSecUseDataProtectionKeychain, kCFBooleanFalse);
    if (adding) {
        CFDictionarySetValue(result, kSecUseKeychain, keychain);
        CFDictionarySetValue(result, kSecAttrLabel, CFSTR("HuntMob virtual SEP v1"));
    } else {
        const void *values[] = {keychain};
        CFArrayRef search = CFArrayCreate(NULL, values, 1, &kCFTypeArrayCallBacks);
        if (!search) {
            CFRelease(account);
            CFRelease(result);
            return NULL;
        }
        CFDictionarySetValue(result, kSecMatchSearchList, search);
        CFRelease(search);
    }
    CFRelease(account);
    return result;
}

static Result operate(bool create, const char *vm_uuid, int output_fd)
{
    Result result = {"invalid_output_fd", errSecParam, false, false};
    unsigned char root[ROOT_BYTES] = {0};
    /* Validate before querying/creating any item, including on create. */
    if (!valid_output_fd(output_fd)) {
        return result;
    }
    CFMutableDictionaryRef attributes = query(vm_uuid, create);
    if (!attributes) {
        result.status = "allocation_failed";
        return result;
    }
    if (create) {
        result.os_status = SecRandomCopyBytes(kSecRandomDefault, sizeof(root), root);
        if (result.os_status != errSecSuccess) {
            result.status = "random_failed";
            goto cleanup;
        }
        CFMutableDataRef value = CFDataCreateMutable(NULL, sizeof(root));
        if (!value) {
            result.status = "allocation_failed";
            result.os_status = errSecAllocate;
            goto cleanup;
        }
        CFDataAppendBytes(value, root, sizeof(root));
        CFDictionarySetValue(attributes, kSecValueData, value);
        result.os_status = SecItemAdd(attributes, NULL);
        wipe(CFDataGetMutableBytePtr(value), (size_t)CFDataGetLength(value));
        CFRelease(value);
        result.created = result.os_status == errSecSuccess;
    } else {
        CFDictionarySetValue(attributes, kSecReturnData, kCFBooleanTrue);
        CFDictionarySetValue(attributes, kSecMatchLimit, kSecMatchLimitOne);
        CFTypeRef value = NULL;
        result.os_status = SecItemCopyMatching(attributes, &value);
        if (result.os_status == errSecSuccess) {
            if (!value || CFGetTypeID(value) != CFDataGetTypeID() ||
                CFDataGetLength((CFDataRef)value) != sizeof(root)) {
                if (value) CFRelease(value);
                result.status = "invalid_stored_root_length";
                result.os_status = errSecDecode;
                goto cleanup;
            }
            memcpy(root, CFDataGetBytePtr((CFDataRef)value), sizeof(root));
        }
        if (value) CFRelease(value);
    }
    result.status = status_name(result.os_status);
    if (result.os_status == errSecSuccess) {
        /* Writes <= PIPE_BUF are atomic. A broken pipe is a delivery failure;
         * a successfully created Keychain item is retained, never overwritten. */
        ssize_t count;
        do {
            count = write(output_fd, root, sizeof(root));
        } while (count < 0 && errno == EINTR);
        result.delivered = count == sizeof(root);
        if (!result.delivered) {
            result.status = "output_write_failed";
        }
    }
cleanup:
    wipe(root, sizeof(root));
    CFRelease(attributes);
    return result;
}

static bool read_root(int descriptor, unsigned char root[ROOT_BYTES])
{
    size_t received = 0;
    while (received < ROOT_BYTES) {
        struct pollfd item = {descriptor, POLLIN, 0};
        if (poll(&item, 1, 5000) <= 0) return false;
        ssize_t count = read(descriptor, root + received, ROOT_BYTES - received);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return false;
        received += (size_t)count;
    }
    struct pollfd item = {descriptor, POLLIN, 0};
    if (poll(&item, 1, 5000) <= 0) return false;
    unsigned char extra;
    return read(descriptor, &extra, 1) == 0;
}

static Result test_operation(bool create, const char *vm_uuid,
                             unsigned char root[ROOT_BYTES])
{
    int descriptors[2];
    Result failure = {"pipe_failed", errSecIO, false, false};
    if (pipe(descriptors)) return failure;
    Result result = operate(create, vm_uuid, descriptors[1]);
    close(descriptors[1]);
    if (result.delivered && !read_root(descriptors[0], root)) {
        result.delivered = false;
        result.status = "pipe_read_failed";
    }
    close(descriptors[0]);
    return result;
}

static bool equal_root(const unsigned char left[ROOT_BYTES],
                       const unsigned char right[ROOT_BYTES])
{
    unsigned char difference = 0;
    for (size_t i = 0; i < ROOT_BYTES; i++) difference |= left[i] ^ right[i];
    return difference == 0;
}

static void fresh_uuid(char output[37])
{
    uuid_t value;
    uuid_generate_random(value);
    uuid_unparse_lower(value, output);
}

static bool fresh_process_lookup(const char *vm_uuid, unsigned char root[ROOT_BYTES])
{
    char executable[4096];
    uint32_t capacity = sizeof(executable);
    int descriptors[2];
    if (_NSGetExecutablePath(executable, &capacity) || pipe(descriptors)) return false;
    char descriptor[32];
    snprintf(descriptor, sizeof(descriptor), "%d", descriptors[1]);
    pid_t child = fork();
    if (child == 0) {
        close(descriptors[0]);
        int null_fd = open("/dev/null", O_WRONLY);
        if (null_fd < 0 || dup2(null_fd, STDOUT_FILENO) < 0 ||
            dup2(null_fd, STDERR_FILENO) < 0) _exit(121);
        if (null_fd > STDERR_FILENO) close(null_fd);
        char *const arguments[] = {executable, "--lookup", (char *)vm_uuid,
                                  "--output-fd", descriptor, NULL};
        execv(executable, arguments);
        _exit(122);
    }
    close(descriptors[1]);
    bool read_ok = child > 0 && read_root(descriptors[0], root);
    close(descriptors[0]);
    if (child <= 0) return false;
    int status = 0;
    pid_t waited = waitpid(child, &status, WNOHANG);
    for (unsigned i = 0; waited == 0 && i < 500; i++) {
        usleep(10000);
        waited = waitpid(child, &status, WNOHANG);
    }
    if (waited == 0) {
        kill(child, SIGKILL);
        (void)waitpid(child, &status, 0);
        return false;
    }
    return read_ok && waited == child && WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static bool remove_owned_test_item(const char *vm_uuid, bool created_this_run)
{
    /* No external delete operation exists. Only internally generated UUIDs
     * successfully created by this invocation can reach this function. */
    if (!created_this_run) return true;
    CFMutableDictionaryRef attributes = query(vm_uuid, false);
    if (!attributes) return false;
    OSStatus status = SecItemDelete(attributes);
    CFRelease(attributes);
    return status == errSecSuccess;
}

static int self_test(void)
{
    char first[37], second[37], missing[37], invalid[37];
    fresh_uuid(first); fresh_uuid(second); fresh_uuid(missing); fresh_uuid(invalid);
    unsigned char a[ROOT_BYTES] = {0}, b[ROOT_BYTES] = {0}, again[ROOT_BYTES] = {0};
    Result created_a = test_operation(true, first, a);
    Result created_b = {"not_run", errSecInternalError, false, false};
    bool persistence = false, different = false, no_overwrite = false;
    bool missing_refused = false, invalid_fd_refused = false, invalid_fd_no_item = false;
    if (created_a.delivered) {
        persistence = fresh_process_lookup(first, again) && equal_root(a, again);
        created_b = test_operation(true, second, b);
        different = created_b.delivered && !equal_root(a, b);
        Result duplicate = test_operation(true, first, again);
        no_overwrite = duplicate.os_status == errSecDuplicateItem && !duplicate.delivered &&
                       fresh_process_lookup(first, again) && equal_root(a, again);
        Result absent = test_operation(false, missing, again);
        missing_refused = absent.os_status == errSecItemNotFound && !absent.delivered;
        Result bad_fd = operate(true, invalid, -1);
        invalid_fd_refused = !bad_fd.created && !bad_fd.delivered &&
                             !strcmp(bad_fd.status, "invalid_output_fd");
        const int standard_fds[] = {0, 1, 2};
        for (size_t i = 0; i < sizeof(standard_fds) / sizeof(standard_fds[0]); i++) {
            bad_fd = operate(true, invalid, standard_fds[i]);
            invalid_fd_refused &= !bad_fd.created && !bad_fd.delivered &&
                                  !strcmp(bad_fd.status, "invalid_output_fd");
        }
        int nonpipe = open("/dev/null", O_WRONLY);
        if (nonpipe >= 0) {
            bad_fd = operate(true, invalid, nonpipe);
            invalid_fd_refused &= !bad_fd.created && !bad_fd.delivered &&
                                  !strcmp(bad_fd.status, "invalid_output_fd");
            close(nonpipe);
        } else {
            invalid_fd_refused = false;
        }
        absent = test_operation(false, invalid, again);
        invalid_fd_no_item = absent.os_status == errSecItemNotFound && !absent.delivered;
    }
    bool cleaned_a = remove_owned_test_item(first, created_a.created);
    bool cleaned_b = remove_owned_test_item(second, created_b.created);
    bool ok = created_a.delivered && created_b.delivered && persistence && different &&
              no_overwrite && missing_refused && invalid_fd_refused && invalid_fd_no_item &&
              cleaned_a && cleaned_b;
    wipe(a, sizeof(a)); wipe(b, sizeof(b)); wipe(again, sizeof(again));
    printf("{\"schema\":\"huntmob.virtual-sep-keychain-selftest.v1\",\"ok\":%s,"
           "\"create_status\":\"%s\",\"create_os_status\":%d,"
           "\"fresh_process_pipe_lookup_matches\":%s,\"different_vm_roots_differ\":%s,"
           "\"duplicate_create_preserves_root\":%s,\"missing_lookup_refused\":%s,"
           "\"invalid_fd_refused\":%s,\"invalid_fd_created_no_item\":%s,"
           "\"own_fixture_items_removed\":%s,\"ready\":false,\"apple_sep_equivalent\":false}\n",
           ok ? "true" : "false", created_a.status, (int)created_a.os_status,
           persistence ? "true" : "false", different ? "true" : "false",
           no_overwrite ? "true" : "false", missing_refused ? "true" : "false",
           invalid_fd_refused ? "true" : "false", invalid_fd_no_item ? "true" : "false",
           cleaned_a && cleaned_b ? "true" : "false");
    return ok ? 0 : 1;
}

int main(int argc, char **argv)
{
    (void)signal(SIGPIPE, SIG_IGN);
    struct rlimit no_core = {0, 0};
    if (setrlimit(RLIMIT_CORE, &no_core) ||
        SecKeychainSetUserInteractionAllowed(false) != errSecSuccess) {
        puts("{\"ok\":false,\"status\":\"interaction_policy_failed\"}");
        return 1;
    }
    bool testing = argc == 2 && !strcmp(argv[1], "--self-test");
    bool create = argc == 5 && !strcmp(argv[1], "--create");
    bool lookup = argc == 5 && !strcmp(argv[1], "--lookup");
    if (!testing && (!(create || lookup) || !valid_uuid(argv[2]) ||
                     strcmp(argv[3], "--output-fd"))) {
        puts("{\"ok\":false,\"status\":\"invalid_arguments\"}");
        return 2;
    }
    int descriptor = -1;
    if (!testing) {
        char *end = NULL;
        errno = 0;
        long parsed = strtol(argv[4], &end, 10);
        if (errno || !argv[4][0] || !end || *end || parsed < 3 || parsed > INT32_MAX ||
            !valid_output_fd((int)parsed)) {
            puts("{\"ok\":false,\"status\":\"invalid_output_fd\",\"created\":false}");
            return 2;
        }
        descriptor = (int)parsed;
    }
    OSStatus status = SecKeychainCopyDefault(&keychain);
    if (status != errSecSuccess || !keychain) {
        printf("{\"ok\":false,\"status\":\"keychain_unavailable\",\"os_status\":%d}\n", (int)status);
        return 1;
    }
    if (testing) {
        int result = self_test();
        CFRelease(keychain);
        return result;
    }
    Result result = operate(create, argv[2], descriptor);
    close(descriptor);
    CFRelease(keychain);
    printf("{\"schema\":\"huntmob.virtual-sep-keychain.v1\",\"ok\":%s,"
           "\"action\":\"%s\",\"vm_uuid\":\"%s\",\"service\":\"" SERVICE "\","
           "\"backend\":\"macos-file-keychain\",\"status\":\"%s\",\"os_status\":%d,"
           "\"created\":%s,\"delivered\":%s,\"root_bytes\":32,\"model_version\":1}\n",
           result.delivered ? "true" : "false", create ? "create" : "lookup", argv[2],
           result.status, (int)result.os_status, result.created ? "true" : "false",
           result.delivered ? "true" : "false");
    return result.delivered ? 0 : 1;
}
