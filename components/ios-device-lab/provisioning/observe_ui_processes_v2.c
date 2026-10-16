/* AUTHORIZED TESTING ONLY — own DATA-v2 transient metadata observer.
 * This executable never starts another process, installs a job, signals a PID,
 * opens process memory, or reads argv/environment/maps/crash files or keys.
 * Future parent must bound/reap this child and preserve STOCK keybag exit status.
 */
#include "virtual_v1_scope.h"
#include "ui_process_observer_policy_v2.h"
#include <time.h>
#define UI_OBSERVER_VM_UUID "9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"
struct native_ui_context { void *buffer; };
static int native_snapshot(void *opaque, struct hm_ui_row *rows, size_t *count) {
    struct native_ui_context *context = opaque;
    int mib[] = {CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0};
    size_t size = 0;
    *count = 0;
    if (sysctl(mib, 4, NULL, &size, NULL, 0)) return 1;
    if (!size || size > HM_UI_MAX_BUFFER) { errno = EOVERFLOW; return 1; }
    size = HM_UI_MAX_BUFFER;
    if (sysctl(mib, 4, context->buffer, &size, NULL, 0)) return 1;
    if (size > HM_UI_MAX_BUFFER || size % sizeof(struct kinfo_proc)) { errno = EOVERFLOW; return 1; }
    const struct kinfo_proc *processes = context->buffer;
    unsigned labels = 0;
    for (size_t i = 0; i < size / sizeof(*processes); i++) {
        const struct extern_proc *process = &processes[i].kp_proc;
        enum hm_ui_label label = hm_ui_select(process->p_comm, sizeof(process->p_comm));
        if (label == HM_UI_NONE) continue;
        if (*count >= HM_UI_MAX_ROWS || (labels & (1u << label))) { errno = EOVERFLOW; return 1; }
        labels |= 1u << label;
        rows[*count] = (struct hm_ui_row){label, process->p_pid, process->p_stat};
        (*count)++;
    }
    return 0;
}
static int native_clock(void *opaque, uint64_t *milliseconds) {
    (void)opaque;
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) || value.tv_sec < 0 || value.tv_nsec < 0 ||
        value.tv_nsec >= 1000000000L || (uint64_t)value.tv_sec > UINT64_MAX / 1000u - 1u) return 1;
    *milliseconds = (uint64_t)value.tv_sec * 1000u + (uint64_t)value.tv_nsec / 1000000u;
    return 0;
}
static int native_wait(void *opaque, uint64_t deadline) {
    uint64_t now;
    for (;;) {
        if (native_clock(opaque, &now)) return 1;
        if (now >= deadline) return 0;
        uint64_t remaining = deadline - now;
        struct timespec duration = {(time_t)(remaining / 1000u), (long)(remaining % 1000u) * 1000000L};
        if (nanosleep(&duration, NULL) && errno != EINTR) return 1;
    }
}
static int native_emit(void *opaque, unsigned sample, const struct hm_ui_row *row) {
    (void)opaque;
    const char *label = hm_ui_static_label(row->label);
    if (!label) return 1;
    return fprintf(stderr, "HuntMob:ui-proc sample=%u service=%s pid=%d state=%d\n",
                   sample, label, row->pid, row->status) < 0 || fflush(stderr);
}
int main(int argc, char *argv[]) {
    alarm(130); /* Also bounds blocking sysctl/output; parent must reap this child. */
    if (argc != 2 || !argv || !argv[0] || !argv[1] || argv[2] ||
        strcmp(argv[0], "huntmob-ui-process-observer") || strcmp(argv[1], "--metadata-only") ||
        getuid() != 0 || strcmp(HUNTMOB_VM_UUID, UI_OBSERVER_VM_UUID) || virtual_v1_scope()) return 1;
    struct native_ui_context context = {malloc(HM_UI_MAX_BUFFER)};
    if (!context.buffer) return 1;
    const struct hm_ui_operations operations = {&context, native_snapshot, native_clock, native_wait, native_emit};
    int result = fprintf(stderr, "HuntMob:ui-proc begin metadata_only=1 samples_max=24\n") < 0 || fflush(stderr);
    if (!result) result = hm_ui_observe(&operations);
    free(context.buffer);
    if (result) {
        fprintf(stderr, "HuntMob:ui-proc failed\n");
        return 1;
    }
    if (fprintf(stderr, "HuntMob:ui-proc end samples=24 metadata_only=1 readiness=0\n") < 0 || fflush(stderr)) return 1;
    alarm(0);
    return 0;
}
