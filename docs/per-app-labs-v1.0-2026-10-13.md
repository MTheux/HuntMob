# Per-app labs — v1.0 — 2026-10-13

New APK labs receive independent AVD names and userdata; the Android SDK system
image is shared. The previous running AVD is stopped, not deleted. Local private
metadata identifies the selected target, source APK hash and creation time.
Saved labs can be resumed through the sidebar. Creation copies the validated
GPU settings from the baseline AVD. Discarded labs are excluded from resume.

Workspaces and traffic snapshots are partitioned by AVD. New screenshot records
carry a lab ID and the UI filters their inventory for the active lab. Legacy
artifacts are retained. Target selection is automatic after installed-app inventory
confirms the recorded package. Additional installed packages appear under Advanced.

## Verification

Created a clean AVD from the already installed InsecureBankv2 lab APK, confirmed
only `com.android.insecurebankv2` in third-party package inventory, and confirmed
Apple M4 Max graphics in startup logs. Resumed the original AVD and then the new
one successfully; both remain saved. Browser confirmed the target heading,
Advanced count of zero, Labs saved and empty traffic for the new lab.

75 Python tests plus JavaScript syntax and diff checks passed. No commit or push.

## Bounds

System apps are not removed. This controls workspace isolation, not network
segmentation or Android sandbox security. The current system does not independently
validate an engagement registry; the UI no longer labels a hardcoded engagement
as authorized. Simultaneous per-device workers and auxiliary-app installation
management remain future work.
