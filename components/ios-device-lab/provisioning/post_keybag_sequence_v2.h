/* Own DATA-v2: ordering only; never implements or invokes a keybag loader. */
#ifndef HUNTMOB_POST_KEYBAG_SEQUENCE_V2_H
#define HUNTMOB_POST_KEYBAG_SEQUENCE_V2_H
#include <string.h>
static inline int huntmob_post_keybag_arguments(int argc, char *const argv[]) {
    return argc == 2 && argv && argv[0] && argv[1] &&
           !strcmp(argv[0], "keybagd") && !strcmp(argv[1], "--init");
}
enum huntmob_keybag_shim_route {
    HUNTMOB_KEYBAG_SHIM_REJECT, HUNTMOB_KEYBAG_SHIM_INIT, HUNTMOB_KEYBAG_SHIM_DAEMON
};
static inline enum huntmob_keybag_shim_route huntmob_keybag_shim_arguments(int argc, char *const argv[]) {
    if (huntmob_post_keybag_arguments(argc, argv)) return HUNTMOB_KEYBAG_SHIM_INIT;
    /* Exact normal System cache, not a generic daemon/CLI passthrough. */
    if (argc == 3 && argv && argv[0] && argv[1] && argv[2] &&
        !strcmp(argv[0], "/usr/libexec/keybagd") && !strcmp(argv[1], "-t") && !strcmp(argv[2], "15"))
        return HUNTMOB_KEYBAG_SHIM_DAEMON;
    return HUNTMOB_KEYBAG_SHIM_REJECT;
}
/* Callbacks are fixed local functions. Recheck identity after the stock child;
 * never run the probe after a failed/signal-terminated child or changed mount. */
static inline int huntmob_post_keybag_sequence(void *context,
    int (*identity)(void *), int (*stock_init)(void *), int (*probe)(void *)) {
    if (identity(context)) return 1;
    if (stock_init(context)) return 1;
    if (identity(context)) return 1;
    return probe(context);
}
#endif
