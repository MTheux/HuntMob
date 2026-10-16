FROM python:3.12-slim-bookworm

ARG ANDROID_TOOLS_VERSION=15859902
ARG ANDROID_TOOLS_SHA256=4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583

ENV ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_AVD_HOME=/root/.android/avd \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PYTHONPATH=/app/src \
    PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/emulator:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip openjdk-17-jre-headless ffmpeg \
    libasound2 libdbus-1-3 libfontconfig1 libgl1 libnss3 libpulse0 \
    libx11-6 libxcb1 libxext6 libxrender1 zlib1g \
    && rm -rf /var/lib/apt/lists/*

# The archive and digest are published together on developer.android.com/studio.
# SDK licenses are presented interactively by scripts/run-docker.sh.
RUN curl --fail --location --retry 3 \
      "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_TOOLS_VERSION}_latest.zip" \
      --output /tmp/android-tools.zip \
    && echo "${ANDROID_TOOLS_SHA256}  /tmp/android-tools.zip" | sha256sum --check \
    && mkdir -p /opt/android-tools \
    && unzip -q /tmp/android-tools.zip -d /opt/android-tools \
    && rm /tmp/android-tools.zip

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY web ./web
COPY components/analysis-core/manifest.json ./components/analysis-core/manifest.json
COPY components/scrcpy/LICENSE components/scrcpy/scrcpy-server-v5.0.1.jar ./components/scrcpy/
COPY scripts/build_analysis_bundle.py ./scripts/build_analysis_bundle.py
COPY deploy/docker-entrypoint.sh /usr/local/bin/huntmob-entrypoint

RUN pip install --no-cache-dir . 'mitmproxy>=11,<13' \
    && python scripts/build_analysis_bundle.py --target linux-x64 \
    && chmod +x /usr/local/bin/huntmob-entrypoint

EXPOSE 8090
ENTRYPOINT ["huntmob-entrypoint"]
CMD ["serve"]
