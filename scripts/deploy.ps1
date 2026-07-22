<#
.SYNOPSIS
    Build and deploy CRA Tax Helper to Aether Atlas.

.DESCRIPTION
    Builds the Docker image (aether-taxhelper:latest) from the CRATaxHelper repo
    and registers / updates it with Atlas.

.PARAMETER AtlasUrl
    Base URL for the Atlas API.  Defaults to http://localhost:8600.
    When running inside the Aether stack use http://atlas:8600.

.EXAMPLE
    .\scripts\deploy.ps1
    .\scripts\deploy.ps1 -AtlasUrl http://atlas:8600
#>

param(
    [string]$AtlasUrl              = ($env:ATLAS_URL ?? "http://localhost:8600"),
    [string]$PlatformInternalSecret = ($env:AETHER_SESSION_SECRET ?? ""),
    [string]$AuthPreviousKeyId      = ($env:CRA_TAXHELPER_AUTH_PREVIOUS_KEY_ID ?? ""),
    [string]$AuthPreviousSecretHex  = ($env:CRA_TAXHELPER_AUTH_PREVIOUS_SECRET_HEX ?? ""),
    [string]$AuthKeyId              = ($env:CRA_TAXHELPER_AUTH_KEY_ID ?? ""),
    [string]$AuthSecretHex          = ($env:CRA_TAXHELPER_AUTH_SECRET_HEX ?? ""),
    [string]$AuthNextKeyId          = ($env:CRA_TAXHELPER_AUTH_NEXT_KEY_ID ?? ""),
    [string]$AuthNextSecretHex      = ($env:CRA_TAXHELPER_AUTH_NEXT_SECRET_HEX ?? ""),
    [string]$ArchiveInternalSecret  = ($env:ARCHIVE_INTERNAL_SECRET ?? ""),
    [string]$EncryptionKey          = ($env:FIELD_ENCRYPTION_KEY ?? "")
)

# Helper: read a key from a .env file
function Read-EnvValue([string]$FilePath, [string]$Key) {
    if (-not (Test-Path $FilePath)) { return "" }
    $line = Get-Content $FilePath | Where-Object { $_ -match "^${Key}=" } | Select-Object -First 1
    if ($line) { return ($line -split "=", 2)[1].Trim() }
    return ""
}

$aetherEnv = Join-Path $PSScriptRoot "..\..\Aether\.env"
$localEnv = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
if (-not $PlatformInternalSecret) {
    $PlatformInternalSecret = Read-EnvValue $aetherEnv "SESSION_SECRET"
}
$authSources = @{
    AuthPreviousKeyId     = "CRA_TAXHELPER_AUTH_PREVIOUS_KEY_ID"
    AuthPreviousSecretHex = "CRA_TAXHELPER_AUTH_PREVIOUS_SECRET_HEX"
    AuthKeyId             = "CRA_TAXHELPER_AUTH_KEY_ID"
    AuthSecretHex         = "CRA_TAXHELPER_AUTH_SECRET_HEX"
    AuthNextKeyId         = "CRA_TAXHELPER_AUTH_NEXT_KEY_ID"
    AuthNextSecretHex     = "CRA_TAXHELPER_AUTH_NEXT_SECRET_HEX"
}
foreach ($entry in $authSources.GetEnumerator()) {
    $variable = Get-Variable -Name $entry.Key
    if (-not $variable.Value) {
        Set-Variable -Name $entry.Key -Value (Read-EnvValue $aetherEnv $entry.Value)
    }
    $variable = Get-Variable -Name $entry.Key
    if (-not $variable.Value) {
        $runtimeName = $entry.Value -replace "^CRA_TAXHELPER_", "AETHER_"
        Set-Variable -Name $entry.Key -Value (Read-EnvValue $localEnv $runtimeName)
    }
}
if (-not $ArchiveInternalSecret) {
    $ArchiveInternalSecret = Read-EnvValue $aetherEnv "ARCHIVE_INTERNAL_SECRET"
}

# Try reading FIELD_ENCRYPTION_KEY from local .env if not supplied
if (-not $EncryptionKey) {
    $EncryptionKey = Read-EnvValue $localEnv "FIELD_ENCRYPTION_KEY"
}

if (-not $PlatformInternalSecret) {
    Write-Error "SESSION_SECRET not found. Set AETHER_SESSION_SECRET env var or add SESSION_SECRET to Aether/.env"
    exit 1
}
$missingAuthValues = $authSources.Keys | Where-Object {
    -not (Get-Variable -Name $_).Value
}
if ($missingAuthValues) {
    Write-Error "Incomplete CRA Tax Helper auth keyring ($($missingAuthValues -join ', ')). Run Aether scripts/sync-auth-scope-secrets.ps1."
    exit 1
}
if (-not $ArchiveInternalSecret) {
    Write-Error "ARCHIVE_INTERNAL_SECRET not found. Run Aether scripts/sync-auth-scope-secrets.ps1."
    exit 1
}

if (-not $EncryptionKey) {
    Write-Warning "FIELD_ENCRYPTION_KEY not set — form data will be stored as plaintext."
    Write-Warning "Set FIELD_ENCRYPTION_KEY in the repo root .env file to enable encryption."
}

$headers = @{ "Content-Type" = "application/json" }
if ($PlatformInternalSecret) {
    $headers["X-Aether-Internal"] = $PlatformInternalSecret
}

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
$ImageName = "aether-taxhelper:latest"
$Slug = "cra-taxhelper"

Write-Host "==> Building Docker image $ImageName" -ForegroundColor Cyan
docker build -t $ImageName $RepoRoot
if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed"; exit 1 }

$AppConfig = Get-Content "$RepoRoot\atlas-app.json" | ConvertFrom-Json

# Inject the complete rotating scoped keyring; never store the platform master in the app.
$AppConfig.env | Add-Member -NotePropertyName "AETHER_AUTH_PREVIOUS_KEY_ID" -NotePropertyValue $AuthPreviousKeyId -Force
$AppConfig.env | Add-Member -NotePropertyName "AETHER_AUTH_PREVIOUS_SECRET_HEX" -NotePropertyValue $AuthPreviousSecretHex -Force
$AppConfig.env | Add-Member -NotePropertyName "AETHER_AUTH_KEY_ID" -NotePropertyValue $AuthKeyId -Force
$AppConfig.env | Add-Member -NotePropertyName "AETHER_AUTH_SECRET_HEX" -NotePropertyValue $AuthSecretHex -Force
$AppConfig.env | Add-Member -NotePropertyName "AETHER_AUTH_NEXT_KEY_ID" -NotePropertyValue $AuthNextKeyId -Force
$AppConfig.env | Add-Member -NotePropertyName "AETHER_AUTH_NEXT_SECRET_HEX" -NotePropertyValue $AuthNextSecretHex -Force
$AppConfig.env | Add-Member -NotePropertyName "ARCHIVE_INTERNAL_SECRET" -NotePropertyValue $ArchiveInternalSecret -Force
if ($EncryptionKey) {
    $AppConfig.env | Add-Member -NotePropertyName "FIELD_ENCRYPTION_KEY" -NotePropertyValue $EncryptionKey -Force
}

$Body = $AppConfig | ConvertTo-Json -Depth 5

Write-Host "==> Checking if '$Slug' is already registered with Atlas..." -ForegroundColor Cyan
try {
    $existing = Invoke-RestMethod -Uri "$AtlasUrl/api/v1/apps/$Slug" -Method GET -Headers $headers -ErrorAction Stop
    Write-Host "    App exists (status: $($existing.status)) — updating config and redeploying..." -ForegroundColor Yellow
    Invoke-RestMethod -Uri "$AtlasUrl/api/v1/apps/$Slug" -Method PUT `
        -Body $Body -Headers $headers | Out-Null
    Invoke-RestMethod -Uri "$AtlasUrl/api/v1/apps/$Slug/restart" -Method POST -Headers $headers | Out-Null
    Write-Host "==> Redeployed." -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 404) {
        Write-Host "    Not found — registering new app..." -ForegroundColor Yellow
        Invoke-RestMethod -Uri "$AtlasUrl/api/v1/apps" -Method POST `
            -Body $Body -Headers $headers | Out-Null
        Write-Host "==> Registered and deployed." -ForegroundColor Green
    } else {
        Write-Error "Atlas API error: $_"
    }
}

Write-Host ""
Write-Host "CRA Tax Helper is available at: $AtlasUrl/app/$Slug/" -ForegroundColor Cyan
