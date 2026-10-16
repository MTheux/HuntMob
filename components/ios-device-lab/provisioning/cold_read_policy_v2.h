/* Own DATA-v2 cold-read classification. No unlock or keybag operation. */
#ifndef HUNTMOB_COLD_READ_POLICY_V2_H
#define HUNTMOB_COLD_READ_POLICY_V2_H
#include <errno.h>
#include <stdbool.h>
enum huntmob_cold_result {
    HUNTMOB_COLD_FAILURE, HUNTMOB_COLD_AFU_MATCH,
    HUNTMOB_COLD_BFU_DENIED, HUNTMOB_COLD_STATE_CHANGED,
    HUNTMOB_COLD_UNEXPECTED_BFU_ACCESS
};
static inline enum huntmob_cold_result huntmob_cold_classify(
    int before, int after, int access_error, bool metadata_valid,
    bool read_complete, bool matches)
{
    if ((before != 0 && before != 1) || (after != 0 && after != 1))
        return HUNTMOB_COLD_FAILURE;
    if (before != after) return HUNTMOB_COLD_STATE_CHANGED;
    if (!before) {
        if (access_error == EACCES || access_error == EPERM)
            return HUNTMOB_COLD_BFU_DENIED;
        if (!access_error) return HUNTMOB_COLD_UNEXPECTED_BFU_ACCESS;
        return HUNTMOB_COLD_FAILURE;
    }
    return !access_error && metadata_valid && read_complete && matches
        ? HUNTMOB_COLD_AFU_MATCH : HUNTMOB_COLD_FAILURE;
}
#endif
