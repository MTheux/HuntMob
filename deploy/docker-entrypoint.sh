#!/bin/sh
set -eu

SDK_ROOT=${ANDROID_SDK_ROOT:-/opt/android-sdk}
if [ ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
    mkdir -p "$SDK_ROOT/cmdline-tools/latest"
    cp -a /opt/android-tools/cmdline-tools/. "$SDK_ROOT/cmdline-tools/latest/"
fi

case "${1:-serve}" in
    licenses)
        exec "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" "--sdk_root=$SDK_ROOT" --licenses
        ;;
    install-sdk)
        exec "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" "--sdk_root=$SDK_ROOT" \
            emulator platform-tools 'build-tools;35.0.0' \
            'system-images;android-35;default;x86_64'
        ;;
    serve)
        if [ ! -x "$SDK_ROOT/emulator/emulator" ] || [ ! -x "$SDK_ROOT/platform-tools/adb" ]; then
            echo 'Android SDK incompleto. Execute ./scripts/run-docker.sh.' >&2
            exit 2
        fi
        exec python -m huntmob.cli ui --bind 0.0.0.0 --port 8090 --authorized-remote
        ;;
    *)
        exec "$@"
        ;;
esac
