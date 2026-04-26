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
    [string]$AtlasUrl       = ($env:ATLAS_URL            ?? "http://localhost:8600"),
    [string]$InternalSecret = ($env:AETHER_SESSION_SECRET ?? "")
)

# Try reading from Aether .env if secret not supplied
if (-not $InternalSecret) {
    $aetherEnv = Join-Path $PSScriptRoot "..\..\Aether\.env"
    if (Test-Path $aetherEnv) {
        $line = Get-Content $aetherEnv | Where-Object { $_ -match "^SESSION_SECRET=" } | Select-Object -First 1
        if ($line) { $InternalSecret = ($line -split "=", 2)[1].Trim() }
    }
}

$headers = @{ "Content-Type" = "application/json" }
if ($InternalSecret) { $headers["X-Aether-Internal"] = $InternalSecret }

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
$ImageName = "aether-taxhelper:latest"
$Slug = "cra-taxhelper"

Write-Host "==> Building Docker image $ImageName" -ForegroundColor Cyan
docker build -t $ImageName $RepoRoot
if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed"; exit 1 }

$AppConfig = Get-Content "$RepoRoot\atlas-app.json" | ConvertFrom-Json

# Inject the SESSION_SECRET so the app can validate Aether session cookies
if ($InternalSecret) {
    $AppConfig.env | Add-Member -NotePropertyName "SESSION_SECRET" -NotePropertyValue $InternalSecret -Force
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
