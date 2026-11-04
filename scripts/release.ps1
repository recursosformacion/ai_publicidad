# Release ai_publicidad to production.
#
# Default is a non-destructive dry run. Use -Apply to change production.
# Requires: git, ssh/scp/tar, access to the RemoteIA host and sudo on it.
#
# Typical:
#   pwsh -File scripts/release.ps1 -DryRun
#   pwsh -File scripts/release.ps1 -Apply
#
# The script runs the local test suite, creates a release tarball, backs up the
# remote code and OSAP_PUBLICIDAD database, installs dependencies, runs Alembic,
# restarts ai-publicidad and checks /health. On failure it restores both backups.

[CmdletBinding()]
param(
    [string]$HostAlias = "RemoteIA",
    [string]$RemoteDir = "/home/ocw/openmusicrepository.com/ai_publicidad",
    [string]$BackupRoot = "/home/ocw/backups",
    [string]$MaintenanceScript = "",
    [switch]$Apply,
    [switch]$DryRun,
    [switch]$SkipTests,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pyproject = Join-Path $Root "pyproject.toml"
$Main = Join-Path $Root "api\main.py"

function Fail([string]$Message) {
    throw $Message
}

function Invoke-Remote([string]$Command) {
    & ssh -o BatchMode=yes $HostAlias $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed: $Command"
    }
}

if (-not (Test-Path -LiteralPath $Python)) { Fail "No existe $Python" }
if (-not (Test-Path -LiteralPath $Pyproject)) { Fail "No existe $Pyproject" }
if (-not (Test-Path -LiteralPath $Main)) { Fail "No existe $Main" }

$pyprojectText = Get-Content -LiteralPath $Pyproject -Raw
if ($pyprojectText -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    Fail "No se pudo leer version de pyproject.toml"
}
$Version = $Matches[1]
$mainText = Get-Content -LiteralPath $Main -Raw
if ($mainText -notmatch 'version="([^"]+)"') {
    Fail "No se pudo leer version de api/main.py"
}
if ($Matches[1] -ne $Version) {
    Fail "La version de api/main.py ($($Matches[1])) no coincide con pyproject.toml ($Version)"
}

$dirty = @(git -C $Root status --porcelain)
if ($dirty.Count -gt 0 -and -not $AllowDirty) {
    Fail "El repositorio tiene cambios sin commitear. Usa -AllowDirty solo para una prueba local."
}

if (-not $SkipTests) {
    Write-Host "== Tests ==" -ForegroundColor Cyan
    Push-Location $Root
    try {
        & $Python -m pytest -q
        if ($LASTEXITCODE -ne 0) { Fail "pytest fallo" }
    } finally {
        Pop-Location
    }
}

$archive = Join-Path $env:TEMP "ai-publicidad-$Version.tar.gz"
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Push-Location $Root
try {
    & tar -czf $archive --exclude=__pycache__ --exclude=*.pyc --exclude=.venv --exclude=data `
        api application domain infrastructure scripts alembic.ini pyproject.toml
    if ($LASTEXITCODE -ne 0) { Fail "tar fallo" }
} finally {
    Pop-Location
}

Write-Host "== Preflight ==" -ForegroundColor Cyan
Invoke-Remote "test -d '$RemoteDir' && test -x '$RemoteDir/.venv/bin/python' && test -f '$RemoteDir/osap.toml'"

if (-not $Apply) {
    Write-Host "DRY RUN: $Version empaquetada en $archive" -ForegroundColor Yellow
    Write-Host "No se ha modificado producción. Repite con -Apply para liberar." -ForegroundColor Yellow
    return
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = "$BackupRoot/ai-publicidad-$Version-$timestamp"
$maintenanceWasOn = $false
$deployed = $false
$backupReady = $false

try {
    if ($MaintenanceScript) {
        if (-not (Test-Path -LiteralPath $MaintenanceScript)) {
            Fail "No existe MaintenanceScript: $MaintenanceScript"
        }
        Write-Host "== Mantenimiento ON ==" -ForegroundColor Cyan
        & $MaintenanceScript -RemoteOnly -On
        if ($LASTEXITCODE -ne 0) { Fail "No se pudo activar mantenimiento" }
        $maintenanceWasOn = $true
    }

    Write-Host "== Backup producción ==" -ForegroundColor Cyan
    Invoke-Remote "set -e; mkdir -p '$backupDir'; cd '$RemoteDir'; tar -czf '$backupDir/code.tgz' --exclude='__pycache__' --exclude='*.pyc' api application domain infrastructure scripts alembic.ini pyproject.toml; sudo -n mysqldump --single-transaction OSAP_PUBLICIDAD | gzip > '$backupDir/db.sql.gz'; echo '$backupDir'"
    $backupReady = $true

    Write-Host "== Subiendo release $Version ==" -ForegroundColor Cyan
    Invoke-Remote "rm -rf /tmp/ai-publicidad-release && mkdir -p /tmp/ai-publicidad-release"
    & scp -o BatchMode=yes $archive "$($HostAlias):/tmp/ai-publicidad-release.tar.gz"
    if ($LASTEXITCODE -ne 0) { Fail "scp fallo" }

    Write-Host "== Parando servicio ==" -ForegroundColor Cyan
    Invoke-Remote "sudo -n systemctl stop ai-publicidad"
    $deployed = $true

    Write-Host "== Instalando código ==" -ForegroundColor Cyan
    Invoke-Remote "set -e; rm -rf /tmp/ai-publicidad-release; mkdir -p /tmp/ai-publicidad-release; tar -xzf /tmp/ai-publicidad-release.tar.gz -C /tmp/ai-publicidad-release; cd '$RemoteDir'; cp -a /tmp/ai-publicidad-release/api /tmp/ai-publicidad-release/application /tmp/ai-publicidad-release/domain /tmp/ai-publicidad-release/infrastructure /tmp/ai-publicidad-release/scripts ./; cp -a /tmp/ai-publicidad-release/alembic.ini /tmp/ai-publicidad-release/pyproject.toml ./; .venv/bin/pip install --quiet -e ."

    Write-Host "== Migrando base de datos ==" -ForegroundColor Cyan
    Invoke-Remote "sudo -n bash -c 'set -a; . /etc/openmusicrepository/ai-publicidad.env; set +a; cd $RemoteDir && .venv/bin/alembic upgrade head'"

    Write-Host "== Arrancando servicio ==" -ForegroundColor Cyan
    Invoke-Remote "sudo -n systemctl start ai-publicidad"

    Write-Host "== Verificando salud ==" -ForegroundColor Cyan
    Invoke-Remote "for i in $(seq 1 30); do if curl -fsS http://127.0.0.1:8305/health >/tmp/ai-publicidad-health.json 2>/dev/null; then cat /tmp/ai-publicidad-health.json; exit 0; fi; sleep 1; done; echo health_failed; exit 1"

    Write-Host "== Versión instalada ==" -ForegroundColor Cyan
    Invoke-Remote "cd '$RemoteDir' && .venv/bin/pip show ai-publicidad | sed -n 's/^Version: //p'"
    Write-Host "Release $Version OK. Backup: $backupDir" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($deployed -and $backupReady) {
        Write-Host "== Rollback ==" -ForegroundColor Yellow
        try {
            Invoke-Remote "sudo -n systemctl stop ai-publicidad || true; cd '$RemoteDir'; (tar -xzf '$backupDir/code.tgz' --overwrite || true); (zcat '$backupDir/db.sql.gz' | sudo -n mysql OSAP_PUBLICIDAD || true); sudo -n systemctl start ai-publicidad"
            Write-Host "Rollback completado" -ForegroundColor Yellow
        } catch {
            Write-Host "El rollback también falló: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    throw
}
finally {
    if ($maintenanceWasOn) {
        Write-Host "== Mantenimiento OFF ==" -ForegroundColor Cyan
        try { & $MaintenanceScript -RemoteOnly -Off } catch { Write-Host "No se pudo desactivar mantenimiento: $($_.Exception.Message)" -ForegroundColor Red }
    }
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}
