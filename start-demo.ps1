[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$lockFile = Join-Path $projectRoot "requirements.lock"
$runDir = Join-Path $projectRoot ".run"
$statePath = Join-Path $runDir "demo-processes.json"
$dataDir = Join-Path $projectRoot "data"
$frontendRoot = Join-Path $projectRoot "frontend"
$backendPort = 8010
$frontendPort = 5173
$backend = $null
$frontend = $null

function Assert-PortFree([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $Port is already in use by PID $($listener.OwningProcess). No process was stopped. Run stop-demo.cmd only for a DEMO started by this workspace, or free the port yourself."
    }
}

function Stop-StartedTree([int]$ParentId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-StartedTree ([int]$child.ProcessId)
    }
    Stop-Process -Id $ParentId -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $statePath) {
    throw "A DEMO ownership file already exists: $statePath. Run stop-demo.cmd first."
}

Assert-PortFree $backendPort
Assert-PortFree $frontendPort

if (-not (Test-Path -LiteralPath $venvPython)) {
    & python -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Unable to create .venv" }
}

$dependencyMarker = Join-Path $projectRoot ".venv\kpd-lock.sha256"
$lockHash = (Get-FileHash -LiteralPath $lockFile -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $dependencyMarker) { (Get-Content -LiteralPath $dependencyMarker -Raw).Trim() } else { "" }
if ($installedHash -ne $lockHash) {
    & $venvPython -m pip install --disable-pip-version-check -r $lockFile
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed" }
    Set-Content -LiteralPath $dependencyMarker -Value $lockHash -Encoding ascii
}

Push-Location $projectRoot
try {
    $databasePath = Join-Path $dataDir "demo.db"
    if (-not (Test-Path -LiteralPath $databasePath)) {
        & $venvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed" }
    }
    else {
        $currentRevision = & $venvPython -m alembic current
        if ($LASTEXITCODE -ne 0) { throw "Cannot inspect DEMO database migration state" }
        if (($currentRevision | Out-String).Trim().Length -eq 0) {
            & $venvPython -m alembic stamp head
            if ($LASTEXITCODE -ne 0) { throw "Cannot stamp the existing DEMO schema" }
        }
        & $venvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed" }
    }
    & $venvPython -m app.seed
    if ($LASTEXITCODE -ne 0) { throw "Synthetic seed failed" }

    $packageLock = Join-Path $frontendRoot "package-lock.json"
    $nodeMarker = Join-Path $frontendRoot "node_modules\.kpd-lock.sha256"
    $packageHash = (Get-FileHash -LiteralPath $packageLock -Algorithm SHA256).Hash
    $nodeHash = if (Test-Path -LiteralPath $nodeMarker) { (Get-Content -LiteralPath $nodeMarker -Raw).Trim() } else { "" }
    if ($nodeHash -ne $packageHash) {
        Push-Location $frontendRoot
        try {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
        }
        finally {
            Pop-Location
        }
        Set-Content -LiteralPath $nodeMarker -Value $packageHash -Encoding ascii
    }

    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    $backendOut = Join-Path $dataDir "backend.out.log"
    $backendErr = Join-Path $dataDir "backend.err.log"
    $frontendOut = Join-Path $dataDir "frontend.out.log"
    $frontendErr = Join-Path $dataDir "frontend.err.log"

    $backend = Start-Process -FilePath $venvPython -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$backendPort" -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
    $viteEntry = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"
    $nodePath = (Get-Command node.exe -ErrorAction Stop).Source
    $frontend = Start-Process -FilePath $nodePath -ArgumentList "`"$viteEntry`"",'--host','127.0.0.1','--port',"$frontendPort",'--strictPort' -WorkingDirectory $frontendRoot -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru

    $backendIdentity = Get-CimInstance Win32_Process -Filter "ProcessId = $($backend.Id)"
    $frontendIdentity = Get-CimInstance Win32_Process -Filter "ProcessId = $($frontend.Id)"
    if ($null -eq $backendIdentity -or $null -eq $frontendIdentity) {
        throw "A DEMO process exited before its ownership identity could be recorded"
    }

    $state = [ordered]@{
        workspace = $projectRoot
        backendRootPid = $backend.Id
        frontendPid = $frontend.Id
        backendExecutable = [System.IO.Path]::GetFullPath([string]$backendIdentity.ExecutablePath)
        frontendExecutable = [System.IO.Path]::GetFullPath([string]$frontendIdentity.ExecutablePath)
        backendCommandToken = $venvPython
        frontendCommandToken = $viteEntry
        backendCreatedAt = $backendIdentity.CreationDate.ToUniversalTime().ToString("o")
        frontendCreatedAt = $frontendIdentity.CreationDate.ToUniversalTime().ToString("o")
        backendPort = $backendPort
        frontendPort = $frontendPort
        startedAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8

    $ready = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/v1/health/ready" -TimeoutSec 1
            $frontendResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$frontendPort" -UseBasicParsing -TimeoutSec 1
            if ($health.status -eq "ready" -and $frontendResponse.StatusCode -eq 200) { $ready = $true; break }
        }
        catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $ready) {
        throw "Backend/API and frontend did not both become ready. Inspect $backendErr and $frontendErr."
    }

    Write-Host "DEMO is ready: http://127.0.0.1:$frontendPort"
    Write-Host "API docs:      http://127.0.0.1:$backendPort/docs"
    Write-Host "Stop safely:   stop-demo.cmd"
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$frontendPort"
    }
}
catch {
    if ($null -ne $frontend) { Stop-StartedTree ([int]$frontend.Id) }
    if ($null -ne $backend) { Stop-StartedTree ([int]$backend.Id) }
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath -Force }
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
