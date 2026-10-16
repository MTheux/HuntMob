# HuntMob: authenticated access to an owned worker; no runtime installation.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*$')]
    [string]$Worker,
    [ValidateRange(1024,65535)][int]$LocalPort = 8090,
    [ValidateRange(1024,65535)][int]$WorkerPort = 8090
)
$ErrorActionPreference = 'Stop'
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $ssh) {
    throw 'Instale o recurso OpenSSH Client do Windows antes de conectar.'
}
Write-Host "HuntMob: acesso em http://127.0.0.1:$LocalPort"
Write-Host 'A UI precisa estar ligada no worker. Ctrl+C encerra o túnel.'
Write-Host 'A chave do worker precisa estar previamente verificada no known_hosts.'
# Argument array: no shell interpolation, remote command or public listener.
$sshArguments = @(
    '-N', '-T',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=15',
    '-o', 'ServerAliveCountMax=3',
    '-L', "127.0.0.1:${LocalPort}:127.0.0.1:${WorkerPort}",
    $Worker
)
& $ssh.Source @sshArguments
if ($LASTEXITCODE -ne 0) { throw "Túnel SSH encerrado com código $LASTEXITCODE." }
