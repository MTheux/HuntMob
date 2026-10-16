> Histórico: a integração MobSF descrita abaixo foi substituída pelo fluxo em native-dast-v1-2026-10-13.md. Não faz parte da interface/API ativa.

# HuntMob DAST and Frida — v1 — 2026-10-13

Native Android observation worker, local MobSF connector, and evidence session.

## Native workflow

Select the app bound to the lab. In Frida choose supported observers and spawn or attach. Preparing Frida downloads the official Android server matching the installed Python client and CPU architecture, records its digest, and listens on device loopback. Frida 17's Java bridge is loaded explicitly. Start/stop manage the session without killing the app when stopping.

DAST starts the same observation worker and attempts managed network capture. The console reports installed hooks, missing APIs, real calls and detach/error states. Screenshots use the existing private evidence store. JSON exports contain receipt, app SHA256, redacted events, traffic within the session interval, and screenshot references. The HTTP export includes a SHA256 header. Records are observations, not confirmed vulnerabilities.

Implemented observers: TLS initialization/trust methods, platform biometric calls, file checks associated with root indicators, WebView navigation host/scheme and bridges, crypto algorithm/call metadata, file I/O calls. Original arguments and return values are preserved. Keys, buffers, passwords, file contents and URL queries are not emitted by these observers. Classes missing from the app are reported as unavailable.

Without root, attach works with an app build already containing Frida Gadget on the fixed local transport. HuntMob does not automatically modify or re-sign an arbitrary APK. This path is implemented but has not been validated with a prepared Gadget app in this session. Active TLS overrides and biometric result fixtures remain disabled and are not claimed as implemented observers.

## MobSF workflow

Use **Preparar MobSF local**, or run `python3 scripts/prepare_mobsf.py`, with Docker available. It prepares only the pinned official image and a dedicated volume, with host ports bound to 127.0.0.1. Then use **Usar MobSF gerenciado**, or configure another explicitly chosen local instance with its API key (memory only).

Use **Criar lab API 30** to prepare/resume an independent AOSP Android 11 lab for the same verified APK. The worker prepares its image in the SDK if missing (without accepting licenses automatically): `system-images;android-30;default;arm64-v8a`. The original Android 15 lab is retained. APK splits are currently rejected. The Android 11 AVD uses `-writable-system`, as required by MobSF's preparation workflow.

Upload the exact installed APK, prepare the analysis, start/stop MobSF DAST, and import its report. Uploads check SHA256 locally and MD5 returned by MobSF. The connector allows only the required API routes; arbitrary ADB execution and arbitrary Frida source are not exposed. Redirects and external service URLs are rejected. Imported findings retain `imported_not_verified`; raw trace fields are omitted/redacted in the imported JSON.

MobSF remains a separately deployed upstream GPL-3.0 application. HuntMob uses its HTTP API and does not copy its implementation. Consult upstream distribution terms for a release that includes MobSF.

## Local validation

- Android 15/API35: Frida 17.23.3 loaded all six observers into InsecureBank; 36 events, 18 observed calls, one unavailable hook (OkHttp CertificatePinner absent).
- Actual emulator login generated a captured POST /login with HTTP200 from the original local AndroLab backend, with synthetic input. This is not proof of successful authentication.
- Screenshot captured from UI; native session stopped; export verified against SHA256, containing 36 events, one request, one screenshot reference.
- Android11/API30 lab: app installed/launched, real MobSF API probe/upload/scan/start/stop/report import completed. Imported report is not independently validated remediation or a confirmed finding.
- Windows/Linux runtime behavior and no-root Gadget attach are not validated here.

References: https://frida.re/docs/bridges/ and https://github.com/MobSF/Mobile-Security-Framework-MobSF
