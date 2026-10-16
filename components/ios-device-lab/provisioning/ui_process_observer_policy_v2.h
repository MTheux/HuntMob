/* AUTHORIZED TESTING ONLY — own transient DATA-v2 diagnostics. No UI claim. */
#ifndef HUNTMOB_UI_PROCESS_OBSERVER_POLICY_V2_H
#define HUNTMOB_UI_PROCESS_OBSERVER_POLICY_V2_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define HM_UI_MAX_BUFFER (1024u * 1024u)
#define HM_UI_MAX_SAMPLES 24u
#define HM_UI_INTERVAL_MS 5000u
#define HM_UI_MAX_DURATION_MS 120000u
#define HM_UI_MAX_ROWS 3u
#define HM_UI_MAX_PROCESS_LINES (HM_UI_MAX_SAMPLES * HM_UI_MAX_ROWS)
enum hm_ui_label { HM_UI_NONE = 0, HM_UI_SPRINGBOARD = 1, HM_UI_BACKBOARDD = 2, HM_UI_RUNNINGBOARDD = 3 };
struct hm_ui_row { enum hm_ui_label label; int pid; int status; };
struct hm_ui_operations {
    void *context;
    int (*snapshot)(void *, struct hm_ui_row *, size_t *);
    int (*clock_ms)(void *, uint64_t *);
    int (*wait_until_ms)(void *, uint64_t);
    int (*emit)(void *, unsigned, const struct hm_ui_row *);
};
/* Capacity is the fixed p_comm field size; unterminated/substring names fail. */
static inline enum hm_ui_label hm_ui_select(const char *name, size_t capacity) {
    static const char *const exact[] = {"SpringBoard", "backboardd", "runningboardd"};
    if (!name || !capacity || !memchr(name, 0, capacity)) return HM_UI_NONE;
    for (unsigned i = 0; i < HM_UI_MAX_ROWS; i++)
        if (!strcmp(name, exact[i])) return (enum hm_ui_label)(i + 1);
    return HM_UI_NONE;
}
static inline const char *hm_ui_static_label(enum hm_ui_label label) {
    switch (label) {
        case HM_UI_SPRINGBOARD: return "SpringBoard";
        case HM_UI_BACKBOARDD: return "backboardd";
        case HM_UI_RUNNINGBOARDD: return "runningboardd";
        default: return NULL;
    }
}
/* Callback errors and clock drift fail closed. No missing-process/exit inference. */
static inline int hm_ui_observe(const struct hm_ui_operations *ops) {
    uint64_t start, now, prior;
    unsigned emitted = 0;
    if (!ops || !ops->snapshot || !ops->clock_ms || !ops->wait_until_ms || !ops->emit ||
        ops->clock_ms(ops->context, &start) || start > UINT64_MAX - HM_UI_MAX_DURATION_MS) return 1;
    prior = start;
    for (unsigned sample = 0; sample < HM_UI_MAX_SAMPLES; sample++) {
        struct hm_ui_row rows[HM_UI_MAX_ROWS] = {{HM_UI_NONE, 0, 0}};
        size_t count = 0;
        uint64_t scheduled = start + (uint64_t)sample * HM_UI_INTERVAL_MS;
        if (sample && ops->wait_until_ms(ops->context, scheduled)) return 1;
        if (ops->clock_ms(ops->context, &now) || now < prior || now < scheduled ||
            now - start >= HM_UI_MAX_DURATION_MS) return 1;
        prior = now;
        if (ops->snapshot(ops->context, rows, &count) || count > HM_UI_MAX_ROWS) return 1;
        unsigned labels = 0;
        for (size_t i = 0; i < count; i++) {
            if (!hm_ui_static_label(rows[i].label) || rows[i].pid <= 0 || rows[i].status < 1 || rows[i].status > 7 ||
                (labels & (1u << rows[i].label))) return 1;
            labels |= 1u << rows[i].label;
        }
        if (ops->clock_ms(ops->context, &now) || now < prior || now - start >= HM_UI_MAX_DURATION_MS) return 1;
        prior = now;
        for (size_t i = 0; i < count; i++) {
            if (emitted >= HM_UI_MAX_PROCESS_LINES || ops->emit(ops->context, sample, &rows[i])) return 1;
            emitted++;
        }
        if (ops->clock_ms(ops->context, &now) || now < prior || now - start >= HM_UI_MAX_DURATION_MS) return 1;
        prior = now;
    }
    return 0; /* Successful bounded metadata collection, never UI readiness. */
}
#endif
