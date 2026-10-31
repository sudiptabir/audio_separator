# Build script: PyInstaller bundle -> Inno Setup installer.
# Run from the project root in PowerShell:
#     .\build_installer.ps1
#
# Prereqs:
#   - All app dependencies installed in the active Python (torch, demucs, PySide6, etc.)
#   - pyinstaller installed:   python -m pip install pyinstaller
#   - Inno Setup 6 installed:  https://jrsoftware.org/isdl.php
#
# The script finds the Inno Setup compiler (ISCC.exe) automatically in the
# usual install locations; override with -Iscc "C:\path\to\ISCC.exe".

param(
    [string]$Iscc = ""
)

$ErrorActionPreference = "Stop"

Write-Host "==> Step 1/3: Cleaning previous build artifacts" -ForegroundColor Cyan
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }
if (Test-Path Output) { Remove-Item -Recurse -Force Output }

Write-Host "==> Step 2/3: Running PyInstaller (this takes several minutes)" -ForegroundColor Cyan
python -m PyInstaller AudioStemSeparator.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path "dist\AudioStemSeparator\AudioStemSeparator.exe")) {
    throw "Expected exe not found at dist\AudioStemSeparator\AudioStemSeparator.exe"
}
Write-Host "    PyInstaller bundle created: dist\AudioStemSeparator\" -ForegroundColor Green

Write-Host "==> Step 3/3: Building installer with Inno Setup" -ForegroundColor Cyan
if ($Iscc -eq "") {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $Iscc = $c; break }
    }
}

if ($Iscc -eq "" -or -not (Test-Path $Iscc)) {
    Write-Host "Inno Setup compiler (ISCC.exe) not found." -ForegroundColor Yellow
    Write-Host "The standalone app is ready at: dist\AudioStemSeparator\AudioStemSeparator.exe" -ForegroundColor Yellow
    Write-Host "Install Inno Setup 6 from https://jrsoftware.org/isdl.php then re-run," -ForegroundColor Yellow
    Write-Host "or pass the path:  .\build_installer.ps1 -Iscc 'C:\path\to\ISCC.exe'" -ForegroundColor Yellow
    exit 0
}

& $Iscc installer.iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "==> Done!" -ForegroundColor Green
Write-Host "Installer: Output\AudioStemSeparator-Setup.exe" -ForegroundColor Green
