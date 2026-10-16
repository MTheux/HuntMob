# JADX partial results — v1.0 — 2026-10-13

Confirmed on the installed InsecureBankv2 lab APK with JADX 1.5.5:
exit code 3, two reported decompilation errors, 3668 generated files.
The HuntMob worker previously discarded all output on any nonzero exit code.

The worker now accepts exit 3 with fresh generated files as a partial result.
Exit 1/2, empty output and timeout remain failures. Each run uses a distinct
output directory to avoid confusing earlier files with current results.
The UI shows partial status, error count, source APK hash and generated files;
both result and error states provide a retry action. Errors are rendered as text.

81 Python tests, JavaScript syntax and whitespace checks passed. Local runtime
reproduction confirms the partial result and generated-file count. No claim of
complete decompilation or a validated security finding is implied.

Reference: JADX 1.5.5 JadxCLI runSave returns 3 after saving decompilation output
when getErrorsCount is nonzero:
https://github.com/skylot/jadx/blob/v1.5.5/jadx-cli/src/main/java/jadx/cli/JadxCLI.java

Changes are local, uncommitted and not pushed.
