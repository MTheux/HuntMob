# Google search with managed capture — v1, 2026-10-15

Confirmed on the owned Android 15/API 35 AOSP root lab, WebView Shell
124.0.6367.219. Google homepage and the launcher QuickSearchBox search loaded
without a proxy. Routing the same lab through the managed listener reproduced
a blank page and Chromium `net_error -202` (untrusted certificate authority).

The passive capture addon now configures mitmproxy `ignore_hosts` for HTTPS
on google.com, google.com.br, gstatic.com and googleusercontent.com, including
subdomains. These connections tunnel with their original certificates; their
contents are not inspected. Existing operator exclusions are preserved. The
policy also loads when the running addon reloads. googleapis.com remains
capturable because it may serve an authorized app backend. Other HTTPS apps
still need the appropriate lab CA trust configuration.

Validated after the change:

- Google returned HTTP 200 through the managed proxy with ordinary host TLS
  verification, without supplying the lab CA.
- A search submitted through Android's launcher search component rendered
  results while `http_proxy` was `10.0.2.2:8080`.
- An isolated loopback HTTP fixture returned 204 through the proxy and appeared
  in the current lab capture with that status.
- Seven capture tests and six managed-proxy tests passed, including exclusion
  boundary checks and preservation of custom operator exclusions.
- The original device proxy setting was restored after the comparison.

Evidence: `~/.huntmob/run/google-proxy-comparison.png` (blank page before),
`~/.huntmob/run/google-fixed-proxy-search.png` (results with proxy after).
No Google account login or Play Store installation was tested. This is a local
change; no commit, push or remote deployment was performed.

References:

- https://docs.mitmproxy.org/stable/howto-ignoredomains/
- https://github.com/chromium/chromium/blob/main/net/base/net_error_list.h
