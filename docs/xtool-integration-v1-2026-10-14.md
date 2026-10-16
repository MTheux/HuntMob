# xtool integration v1 — 2026-10-14

Local worker: macOS arm64. Installed official Homebrew cask xtool-org/tap/xtool; xtool 1.22.2 confirmed. Homebrew's upstream cask declares no checksum. No Apple authentication or provisioning performed by the agent. No physical USB device found.

## Use

In HuntMob, choose iOS → Perfil → Instalar IPA no iPhone → Verificar xtool e dispositivos. Select a connected and paired USB iPhone, choose an authorized IPA, and approve signing/installation. xtool may change Bundle ID; opening is separate and requires the identifier actually installed. This panel does not change Simulator selection or emulate hardware.

Configure Apple authentication locally with `xtool setup`; HuntMob does not request or return credentials. Developer Mode, compatible signing/provisioning and device pairing remain prerequisites. Some entitlements require paid membership or specific Apple permissions.

Build trusted SwiftPM sources without signing/installing:

```sh
PYTHONPATH=src python3 scripts/build_ios_xtool.py /absolute/path/project --trusted-source --configuration debug
```

Project must contain Package.swift and xtool.yml. SwiftPM manifests/plugins execute code: only use trusted sources. The command produces an unsigned IPA via `xtool dev build --ipa`; actual Apple SDK/toolchain setup remains necessary. Build not validated on a fixture in this integration.

Windows uses WSL and USB forwarding per upstream documentation; native Windows execution is not claimed or tested. Adapter executes in the worker where xtool is installed.

## Validation and limits

- Actual `--version`, devices/install/launch/build `--help` inspected.
- Actual `devices --usb --no-wait` returned no devices.
- Tests cover invalid/simulator UDIDs, no adoption of disconnected devices, no guessed Bundle ID or automatic launch, no success receipt on install failure, and missing tool.
- USB installation, signing, launch and build remain NOT_TESTED end to end. There is no physical device or configured Apple account in this test.
- No jailbreak, Frida fix, camera/sensor support, ANS/NVMe implementation, physical video/input or universal IPA compatibility is supplied by xtool.
- Receipts saved privately in ~/.huntmob/ios/xtool, separately from Simulator metadata. CLI errors are summarized without exposing credential-bearing output.

Primary sources: https://github.com/xtool-org/xtool ; https://github.com/xtool-org/xtool/blob/main/Documentation/xtool.docc/Installation-Linux.md ; https://github.com/xtool-org/xtool/blob/main/Sources/XToolSupport/ConnectionOptions.swift .

Local changes only; no commit, push or deployment.
