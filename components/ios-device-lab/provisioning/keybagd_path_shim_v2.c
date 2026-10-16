/* Own System only. The untouched signed stock binary lives at the fixed
 * original path; verify its hash before either init or daemon execution.
 * This source does not patch launchd or any trust/security policy. */
#define HUNTMOB_POST_KEYBAG_PATH_SHIM_V2 1
#include "verify_post_keybag_data_v2.c"
