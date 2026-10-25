[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$statePath = Join-Path $projectRoot ".run\demo-processes.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host "No owned DEMO process state found. Nothing was stopped."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ([System.IO.Path]::GetFullPath([string]$state.workspace).TrimEnd('\') -ne $projectRoot) {
    throw "Ownership file belongs to another workspace. No process was stopped."
}

function ConvertTo-RoundTripUtcString($Value) {
    if ($Value -is [datetime]) {
        return $Value.ToUniversalTime().ToString("o")
    }
    return [string]$Value
}

function Get-DescendantIds([int]$ParentId) {
    $result = @()
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId")
    foreach ($child in $children) {
        $result += Get-DescendantIds ([int]$child.ProcessId)
        $result += [int]$child.ProcessId
    }
    return $result
}

function Stop-OwnedProcess(
    [int]$ProcessId,
    [string]$ExpectedExecutable,
    [string]$ExpectedToken,
    [string]$ExpectedCreatedAt,
    [string]$Label
) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Write-Host "$Label already stopped (PID $ProcessId)."
        return
    }
    $commandLine = [string]$process.CommandLine
    $actualExecutable = [System.IO.Path]::GetFullPath([string]$process.ExecutablePath)
    $actualCreatedAt = $process.CreationDate.ToUniversalTime().ToString("o")
    $sameExecutable = [string]::Equals($actualExecutable, [System.IO.Path]::GetFullPath($ExpectedExecutable), [System.StringComparison]::OrdinalIgnoreCase)
    $hasCommandToken = $commandLine.IndexOf($ExpectedToken, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    $sameCreation = [string]::Equals($actualCreatedAt, $ExpectedCreatedAt, [System.StringComparison]::Ordinal)
    if (-not $sameExecutable -or -not $hasCommandToken -or -not $sameCreation) {
        throw "$Label PID $ProcessId identity mismatch (executable, full workspace command token, or creation time). No such process was stopped."
    }
    $descendants = @(Get-DescendantIds $ProcessId)
    foreach ($childId in $descendants) {
        Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $Label (PID $ProcessId)."
}

Stop-OwnedProcess ([int]$state.frontendPid) ([string]$state.frontendExecutable) ([string]$state.frontendCommandToken) (ConvertTo-RoundTripUtcString $state.frontendCreatedAt) "frontend"
Stop-OwnedProcess ([int]$state.backendRootPid) ([string]$state.backendExecutable) ([string]$state.backendCommandToken) (ConvertTo-RoundTripUtcString $state.backendCreatedAt) "backend"
Remove-Item -LiteralPath $statePath -Force
Write-Host "Owned DEMO processes stopped. Foreign services, including port 8000, were not touched."
