#!/bin/sh
set -eu

if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
    echo 'HuntMob Docker com emulador requer Linux x86_64 com KVM. Em macOS/Windows, use o worker nativo.' >&2
    exit 2
fi
if [ ! -c /dev/kvm ] || [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
    echo 'KVM indisponível para este usuário. Habilite virtualização e acesso a /dev/kvm antes de iniciar.' >&2
    exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
    echo 'Docker Compose v2 não encontrado.' >&2
    exit 2
fi

cd "$(dirname "$0")/.."
echo 'O SDK Android requer aceite dos termos em https://developer.android.com/studio#terms'
printf 'Deseja baixar as ferramentas oficiais e revisar as licenças? [s/N] '
IFS= read -r answer
case "$answer" in
    s|S|sim|SIM) ;;
    *) echo 'Preparação cancelada.'; exit 2 ;;
esac

docker compose build huntmob
docker compose run --rm --no-deps huntmob licenses
docker compose run --rm --no-deps huntmob install-sdk
docker compose up -d --no-build huntmob
echo 'HuntMob: http://127.0.0.1:8090'
