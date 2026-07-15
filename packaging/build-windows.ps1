<#
Build the self-contained Windows application and its per-user installer.
Run from any directory: .\packaging\build-windows.ps1 [-SkipInstaller].
This script does not run repository test or formatting gates; release validation owns those gates.
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPath = Join-Path $RepoRoot '.build-venv'
$Python = Join-Path $VenvPath 'Scripts\python.exe'
$SpecPath = Join-Path $RepoRoot 'packaging\ebook-risk-analyzer.spec'
$DistPath = Join-Path $RepoRoot 'dist\EbookRiskAnalyzer'
$GuiExecutable = Join-Path $DistPath 'EbookRiskAnalyzer.exe'
$CliExecutable = Join-Path $DistPath 'EbookRiskAnalyzerCLI.exe'
$RequiredSourceAssets = @(
    (Join-Path $RepoRoot 'ebook_risk_analyzer\templates'),
    (Join-Path $RepoRoot 'ebook_risk_analyzer\static'),
    (Join-Path $RepoRoot 'config\default_rules.yaml')
)
$RequiredBundleAssets = @(
    (Join-Path $DistPath '_internal\ebook_risk_analyzer\templates\web_index.html'),
    (Join-Path $DistPath '_internal\ebook_risk_analyzer\static\web.css'),
    (Join-Path $DistPath '_internal\config\default_rules.yaml')
)

function Fail([string]$Message) {
    throw "Windows packaging failed: $Message"
}

function Require-Paths([string[]]$Paths, [string]$Description) {
    foreach ($Path in $Paths) {
        if (-not (Test-Path -LiteralPath $Path)) {
            Fail "$Description is missing: $Path"
        }
    }
}

function Invoke-HealthSmoke([string]$Executable, [string]$Label) {
    & $Executable '--help'
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label health smoke failed: $Executable --help exited with $LASTEXITCODE."
    }
}

Push-Location $RepoRoot
try {
    Require-Paths $RequiredSourceAssets 'Required source asset'

    # A clean environment prevents an installed local package or stale dependency from leaking in.
    if (Test-Path $VenvPath) {
        Remove-Item -Recurse -Force $VenvPath
    }
    & py -3.11 -m venv $VenvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Python)) {
        Fail 'Python 3.11 is required. Install it with the Windows Python launcher (py -3.11).'
    }

    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail 'Could not upgrade pip.' }
    & $Python -m pip install '.[dev]'
    if ($LASTEXITCODE -ne 0) { Fail 'Could not install project packaging dependencies.' }

    if (Test-Path $DistPath) {
        Remove-Item -Recurse -Force $DistPath
    }
    & $Python -m PyInstaller --noconfirm --clean $SpecPath
    if ($LASTEXITCODE -ne 0) { Fail 'PyInstaller failed.' }
    Require-Paths @($GuiExecutable, $CliExecutable) 'PyInstaller executable'
    Require-Paths $RequiredBundleAssets 'Packaged asset'
    Invoke-HealthSmoke $CliExecutable 'Portable CLI'

    if (-not $SkipInstaller) {
        $Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($null -eq $Iscc) {
            Fail 'Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup or rerun with -SkipInstaller.'
        }
        & $Iscc.Source (Join-Path $RepoRoot 'packaging\windows-installer.iss')
        if ($LASTEXITCODE -ne 0) { Fail 'Inno Setup failed to create the installer.' }
        $Installer = Join-Path $RepoRoot 'dist-installer\EbookRiskAnalyzer-Setup-x64.exe'
        Require-Paths @($Installer) 'Inno Setup output'

        $SmokeInstallPath = Join-Path ([System.IO.Path]::GetTempPath()) ("EbookRiskAnalyzer-smoke-" + [guid]::NewGuid())
        try {
            & $Installer '/VERYSILENT' '/SUPPRESSMSGBOXES' '/NORESTART' "/DIR=$SmokeInstallPath"
            if ($LASTEXITCODE -ne 0) { Fail 'Installer health smoke could not install the application.' }
            $InstalledCli = Join-Path $SmokeInstallPath 'EbookRiskAnalyzerCLI.exe'
            Invoke-HealthSmoke $InstalledCli 'Installed CLI'
        }
        finally {
            $Uninstaller = Join-Path $SmokeInstallPath 'unins000.exe'
            if (Test-Path -LiteralPath $Uninstaller) {
                & $Uninstaller '/VERYSILENT' '/SUPPRESSMSGBOXES' '/NORESTART'
            }
            if (Test-Path -LiteralPath $SmokeInstallPath) {
                Remove-Item -Recurse -Force $SmokeInstallPath
            }
        }
    }
}
finally {
    Pop-Location
}
