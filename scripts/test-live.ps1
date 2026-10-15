param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$Portal = ".\portals\github.json",
    [string]$Inputs = ".\examples\inputs.github.json",
    [string]$AlternateInputs = ".\examples\inputs.github.alternate.json",
    [switch]$Headed
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Python executable not found: $Python"
}
foreach ($path in @($Portal, $Inputs, $AlternateInputs)) {
    if (-not (Test-Path $path -PathType Leaf)) {
        throw "Required project file not found: $path"
    }
}

$configOutput = & $Python -m automation check-config --portal $Portal --inputs $Inputs 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Configuration check failed. Review the safe diagnostic above; do not paste secrets into chat."
}
$alternateConfigOutput = & $Python -m automation check-config --portal $Portal --inputs $AlternateInputs 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Alternate-input configuration check failed. Review the safe diagnostic above."
}

$stamp = "{0}-{1}" -f (Get-Date -Format "yyyyMMddTHHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 6))
$acceptanceRoot = Join-Path ".\runs" "live-acceptance-$stamp"
$statePath = Join-Path ".\.state\acceptance" "github.json"
$stateDirectory = Split-Path $statePath -Parent
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
Remove-Item $statePath -Force -ErrorAction SilentlyContinue

function Invoke-LiveAcceptanceRun([string]$Name, [string]$InputPath) {
    $outputPath = Join-Path $acceptanceRoot $Name
    $arguments = @(
        "-m", "automation", "run",
        "--portal", $Portal,
        "--inputs", $InputPath,
        "--output", $outputPath,
        "--state", $statePath
    )
    if ($Headed) {
        $arguments += "--headed"
    }

    $cliOutput = & $Python @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = $cliOutput -join [Environment]::NewLine
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode. CLI output: $outputText"
    }
    $jsonLine = ($outputText -split "`r?`n" | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1)
    if (-not $jsonLine) {
        throw "$Name did not return its JSON run summary. CLI output: $outputText"
    }
    $run = $jsonLine | ConvertFrom-Json
    if ($run.status -ne "success") {
        throw "$Name reported status '$($run.status)'. Manifest: $($run.manifest)"
    }
    $manifestPath = Join-Path (Get-Location) $run.manifest
    if (-not (Test-Path $manifestPath -PathType Leaf)) {
        throw "$Name manifest not found: $manifestPath"
    }
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if (-not $manifest.captured_files -or $manifest.captured_files.Count -lt 1) {
        throw "$Name completed without recording a captured document. Manifest: $manifestPath"
    }
    $capture = $manifest.captured_files[0]
    $documentPath = Join-Path (Split-Path $manifestPath -Parent) $capture.path
    if (-not (Test-Path $documentPath -PathType Leaf)) {
        throw "$Name recorded a document that is not on disk: $documentPath"
    }
    [PSCustomObject]@{
        name = $Name
        manifest = $run.manifest
        document = $documentPath
        sha256 = $capture.sha256
        inputs = $manifest.inputs
        duration_ms = $manifest.duration_ms
        session_reused = [bool]$run.session_reused
        full_login = [bool]$manifest.session.full_login
        session_state = $manifest.session.state
    }
}

$results = [System.Collections.Generic.List[object]]::new()
$fresh = Invoke-LiveAcceptanceRun "01-fresh-login" $Inputs
if ($fresh.session_reused -or -not $fresh.full_login) {
    throw "Fresh-login case did not perform a full login. Manifest: $($fresh.manifest)"
}
$results.Add($fresh)

$reused = Invoke-LiveAcceptanceRun "02-reused-session" $Inputs
if (-not $reused.session_reused) {
    throw "Second run did not reuse the saved session. Manifest: $($reused.manifest)"
}
$freshInputsJson = ConvertTo-Json -InputObject $fresh.inputs -Compress -Depth 20
$reusedInputsJson = ConvertTo-Json -InputObject $reused.inputs -Compress -Depth 20
if ($reusedInputsJson -ne $freshInputsJson) {
    throw "Reused-session run did not use the same inputs. Compare manifests: $($fresh.manifest), $($reused.manifest)"
}
$results.Add($reused)

$backupPath = "$statePath.backup"
Copy-Item $statePath $backupPath -Force
[System.IO.File]::WriteAllText($statePath, "{corrupt", [System.Text.UTF8Encoding]::new($false))
try {
    $recovered = Invoke-LiveAcceptanceRun "03-corrupt-state-recovery" $Inputs
    if ($recovered.session_reused -or -not $recovered.full_login -or $recovered.session_state -ne "corrupt") {
        throw "Corrupt-state case did not detect corruption and perform a full login. Manifest: $($recovered.manifest)"
    }
    $results.Add($recovered)
} catch {
    Copy-Item $backupPath $statePath -Force
    throw
} finally {
    Remove-Item $backupPath -Force -ErrorAction SilentlyContinue
}

$changed = Invoke-LiveAcceptanceRun "04-changed-input" $AlternateInputs
if (-not $changed.session_reused) {
    throw "Changed-input run did not reuse the saved session. Manifest: $($changed.manifest)"
}
$changedInputsJson = ConvertTo-Json -InputObject $changed.inputs -Compress -Depth 20
if ($changedInputsJson -eq $freshInputsJson) {
    throw "Alternate-input run did not use different inputs. Compare manifests: $($fresh.manifest), $($changed.manifest)"
}
$results.Add($changed)

$summaryPath = Join-Path $acceptanceRoot "acceptance-summary.json"
$summary = [PSCustomObject]@{
    status = "passed"
    real_portal = "GitHub"
    cases = $results
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding utf8
$summary | ConvertTo-Json -Depth 6
Write-Host "Acceptance artifacts are under $acceptanceRoot. Review them before copying any files into the submission."
Write-Host "PDF hashes are recorded for reference; Chromium PDF metadata can vary between runs even when the rendered page is unchanged. Compare the PDFs' visible content for the alternate-input case."
