# Build the pinned Inferno inventory binary on an owned Windows/MSYS2 worker.
# This script never downloads Apple firmware and never boots a guest.
[CmdletBinding()]
param(
    [string]$Repository = "$env:LOCALAPPDATA\HuntMob\research\Inferno",
    [string]$Output = "$env:LOCALAPPDATA\HuntMob\research\ios-engine",
    [ValidateRange(1, 8)][int]$Jobs = 4
)

$ErrorActionPreference = 'Stop'
$Pin = 'cc4302a99167abec69b714cfd00c38caece7e7de'
$RequiredPackages = @(
    'mingw-w64-ucrt-x86_64-gcc',
    'mingw-w64-ucrt-x86_64-meson',
    'mingw-w64-ucrt-x86_64-ninja',
    'mingw-w64-ucrt-x86_64-pkgconf',
    'mingw-w64-ucrt-x86_64-glib2',
    'mingw-w64-ucrt-x86_64-pixman',
    'mingw-w64-ucrt-x86_64-libpng',
    'mingw-w64-ucrt-x86_64-gnutls',
    'mingw-w64-ucrt-x86_64-nettle',
    'mingw-w64-ucrt-x86_64-libslirp'
)

if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'Inferno requires a 64-bit Windows worker.'
}
if (-not $env:LOCALAPPDATA) {
    throw 'LOCALAPPDATA is required for the private HuntMob research workspace.'
}
$Git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $Git) { throw 'Git for Windows is required.' }

$MsysRoot = if ($env:MSYS2_ROOT) { $env:MSYS2_ROOT } else { 'C:\msys64' }
$Bash = Join-Path $MsysRoot 'usr\bin\bash.exe'
if (-not (Test-Path -LiteralPath $Bash -PathType Leaf)) {
    throw "MSYS2 UCRT64 bash was not found at $Bash."
}
if (Test-Path -LiteralPath $Output) {
    throw "Output already exists and will not be overwritten: $Output"
}
if (-not (Test-Path -LiteralPath $Repository -PathType Container)) {
    throw "Pinned Inferno repository is absent: $Repository"
}

$Found = (& $Git.Source -C $Repository rev-parse "$Pin^{commit}").Trim()
if ($LASTEXITCODE -ne 0 -or $Found -ne $Pin) {
    throw 'The pinned Inferno revision is unavailable in the local repository.'
}
$Status = & $Git.Source -C $Repository status --porcelain
if ($LASTEXITCODE -ne 0 -or $Status) {
    throw 'The Inferno source tree must be clean; existing research changes were preserved.'
}

$Missing = @()
foreach ($Package in $RequiredPackages) {
    & $Bash -lc "pacman -Q '$Package' >/dev/null 2>&1"
    if ($LASTEXITCODE -ne 0) { $Missing += $Package }
}
if ($Missing.Count) {
    throw ('Missing reviewed MSYS2 packages: ' + ($Missing -join ', '))
}
& $Bash -lc 'test -f /ucrt64/include/lzfse.h && test -f /ucrt64/lib/liblzfse.a'
if ($LASTEXITCODE -ne 0) {
    throw 'A UCRT64 LZFSE static library and header are required.'
}

New-Item -ItemType Directory -Path $Output | Out-Null
$OutputPath = (Resolve-Path -LiteralPath $Output).Path
$RepositoryPath = (Resolve-Path -LiteralPath $Repository).Path
$Worktree = Join-Path $OutputPath 'source'
$Build = Join-Path $OutputPath 'build'
$Log = Join-Path $OutputPath 'build.log'
$Receipt = Join-Path $OutputPath 'build-receipt.json'

$Initial = [ordered]@{
    schema = 1
    provider = 'inferno'
    purpose = 'windows-t8030-engine-inventory'
    host_system = 'Windows'
    host_architecture = $env:PROCESSOR_ARCHITECTURE
    revision = $Pin
    state = 'building'
    ready = $false
    firmware_included = $false
    dmg_lzfse_supported = $true
    firmware_boot_validated = $false
    springboard_validated = $false
    ipa_execution_validated = $false
    required_packages = $RequiredPackages
}
$Initial | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Receipt -Encoding UTF8

try {
    & $Git.Source -C $Repository worktree add --detach $Worktree $Pin *>> $Log
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the pinned build worktree.' }
    & $Git.Source -C $Worktree submodule update --init --depth 1 util/mlib *>> $Log
    if ($LASTEXITCODE -ne 0) { throw 'Unable to populate the pinned mlib submodule.' }

    if ($Worktree -match "['`r`n]" -or $Build -match "['`r`n]") {
        throw 'Research paths cannot contain apostrophes or newlines.'
    }
    $MsysWorktree = (& $Bash -lc 'cygpath -u "$1"' -- $Worktree).Trim()
    $MsysBuild = (& $Bash -lc 'cygpath -u "$1"' -- $Build).Trim()
    $Command = @"
set -euo pipefail
export MSYSTEM=UCRT64
export PATH=/ucrt64/bin:/usr/bin
mkdir -p '$MsysBuild'
cd '$MsysBuild'
'$MsysWorktree/configure' --target-list=aarch64-softmmu --disable-werror \
  --disable-guest-agent --disable-gtk --disable-sdl \
  --enable-lzfse --enable-png --enable-gnutls --enable-nettle --enable-slirp
ninja -j $Jobs qemu-system-aarch64.exe
"@
    & $Bash -lc $Command *>> $Log
    if ($LASTEXITCODE -ne 0) { throw 'Inferno Windows compilation failed.' }

    $Binary = Join-Path $Build 'qemu-system-aarch64.exe'
    if (-not (Test-Path -LiteralPath $Binary -PathType Leaf)) {
        throw 'The expected qemu-system-aarch64.exe was not produced.'
    }
    $MsysBinary = (& $Bash -lc 'cygpath -u "$1"' -- $Binary).Trim()
    $Version = (& $Bash -lc "export PATH=/ucrt64/bin:/usr/bin; '$MsysBinary' --version" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -notmatch 'ChefKiss|Inferno') {
        throw 'The candidate did not identify itself as Inferno.'
    }
    $Machines = (& $Bash -lc "export PATH=/ucrt64/bin:/usr/bin; '$MsysBinary' -machine help" | Out-String)
    if ($LASTEXITCODE -ne 0 -or $Machines -notmatch '(?m)^t8030\s') {
        throw 'The compiled candidate does not expose the t8030 machine.'
    }
    $Hash = (Get-FileHash -LiteralPath $Binary -Algorithm SHA256).Hash.ToLowerInvariant()
    $Final = [ordered]@{
        schema = 1
        provider = 'inferno'
        purpose = 'windows-t8030-engine-inventory'
        host_system = 'Windows'
        host_architecture = $env:PROCESSOR_ARCHITECTURE
        revision = $Pin
        state = 'compiled'
        ready = $false
        binary = $Binary
        binary_sha256 = $Hash
        version = ($Version -split "`r?`n")[0]
        machine_t8030 = $true
        firmware_included = $false
        dmg_lzfse_supported = $true
        firmware_boot_validated = $false
        springboard_validated = $false
        ipa_execution_validated = $false
        required_packages = $RequiredPackages
    }
    $Final | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Receipt -Encoding UTF8
    $Final | ConvertTo-Json -Depth 5
}
catch {
    $Initial.state = 'failed'
    $Initial.failure_type = $_.Exception.GetType().Name
    $Initial | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Receipt -Encoding UTF8
    throw
}
