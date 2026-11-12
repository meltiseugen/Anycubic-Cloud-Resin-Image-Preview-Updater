# Verify the distributable itself, rather than relying on the Python environment.
[CmdletBinding()]
param(
    [string]$DistDirectory,
    [string]$ReportDirectory
)

$ErrorActionPreference = 'Stop'
if (-not $DistDirectory) { $DistDirectory = Join-Path $PSScriptRoot '..\dist' }
if (-not $ReportDirectory) { $ReportDirectory = Join-Path $PSScriptRoot '..\build\packaged-smoke' }
$distPath = (Resolve-Path -LiteralPath $DistDirectory).Path
$reportPath = [System.IO.Path]::GetFullPath($ReportDirectory)
$artifacts = @('PM7CloudPreviewFixer.exe', 'PM7CloudPreviewFixer-Setup.exe')
foreach ($artifact in $artifacts) {
    $artifactPath = Join-Path $distPath $artifact
    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "Expected build output is missing: $artifactPath"
    }
}

New-Item -ItemType Directory -Force -Path $reportPath | Out-Null
# A unique report avoids accepting results left by an earlier run.
$reportFile = Join-Path $reportPath ('smoke-' + [guid]::NewGuid().ToString('N') + '.json')
$oldPath = $env:PATH
$oldQtPlatform = $env:QT_QPA_PLATFORM
$appProcess = $null
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $appProcess = Start-Process -FilePath (Join-Path $distPath $artifacts[0]) `
        -ArgumentList @('--smoke-test', ('"' + $reportFile + '"')) `
        -WorkingDirectory $reportPath -WindowStyle Hidden -PassThru
    if (-not $appProcess.WaitForExit(120000)) {
        # Stop only the diagnostic process launched by this script and its children.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $appProcess.Id /T /F | Out-Null
        throw 'The packaged app did not exit within 120 seconds.'
    }
    $appProcess.Refresh()
    if ($appProcess.ExitCode -ne 0) {
        throw "The packaged app exited with code $($appProcess.ExitCode)."
    }
} finally {
    $env:PATH = $oldPath
    $env:QT_QPA_PLATFORM = $oldQtPlatform
    if ($null -ne $appProcess) { $appProcess.Dispose() }
}

$report = Get-Content -LiteralPath $reportFile -Raw | ConvertFrom-Json
foreach ($check in @('repair', 'non_preview_sha256', 'zip_integrity')) {
    if ($report.$check -ne 'passed') { throw "Packaged app check failed: $check" }
}
foreach ($extension in @('.pm7', '.pwsz', '.pm7m', '.pm4u', '.pp1', '.pp1m')) {
    if ($report.formats.$extension -ne 'passed') {
        throw "Packaged format check failed: $extension"
    }
}
if ($report.update_button -ne 'Update Preview') { throw 'Packaged UI check failed.' }

$checksumLines = foreach ($artifact in $artifacts) {
    $hash = Get-FileHash -LiteralPath (Join-Path $distPath $artifact) -Algorithm SHA256
    '{0}  {1}' -f $hash.Hash.ToLowerInvariant(), $artifact
}
[System.IO.File]::WriteAllLines(
    (Join-Path $distPath 'SHA256SUMS.txt'),
    [string[]]$checksumLines,
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output 'Packaged repair, SHA-256 integrity, ZIP, six file formats, UI and clean exit passed.'
Write-Output "Checksums: $(Join-Path $distPath 'SHA256SUMS.txt')"
