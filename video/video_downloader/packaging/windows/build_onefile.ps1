# Builds a single-file Windows executable (PyInstaller onefile) that bundles:
# - yt-dlp.exe
# - ffmpeg.exe + ffprobe.exe
# Result: dist\video_downloader.exe (no Python install needed on host).

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

$projectDir = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$scriptPath = Join-Path $projectDir 'video_downloader.py'

$buildRoot = Join-Path $projectDir 'packaging\windows\_build'
$null = New-Item -ItemType Directory -Force -Path $buildRoot

# --- Check Python launcher ---
Write-Step "Checking for Python (py.exe)"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' not found. Install Python 3 from https://www.python.org/downloads/windows/ (check 'Add to PATH')."
}

# --- Download yt-dlp.exe ---
Write-Step "Downloading yt-dlp.exe (if missing)"
$ytDlpUrl  = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
$ytDlpPath = Join-Path $buildRoot 'yt-dlp.exe'
if (-not (Test-Path $ytDlpPath)) {
    Invoke-WebRequest -Uri $ytDlpUrl -OutFile $ytDlpPath
}

# --- Download and extract ffmpeg ---
Write-Step "Downloading ffmpeg (if missing)"
$ffZipUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$ffZip    = Join-Path $buildRoot 'ffmpeg-release-essentials.zip'
$ffOut    = Join-Path $buildRoot 'ffmpeg'
if (-not (Test-Path $ffZip)) {
    Invoke-WebRequest -Uri $ffZipUrl -OutFile $ffZip
}

Write-Step "Extracting ffmpeg"
if (Test-Path $ffOut) {
    Remove-Item -Recurse -Force $ffOut
}
$null = New-Item -ItemType Directory -Force -Path $ffOut
Expand-Archive -Path $ffZip -DestinationPath $ffOut -Force

$ffTop = Get-ChildItem -Path $ffOut -Directory | Select-Object -First 1
if (-not $ffTop) {
    throw "ffmpeg zip extraction failed: no top-level directory found"
}

$ffmpegPath  = Join-Path $ffTop.FullName 'bin\ffmpeg.exe'
$ffprobePath = Join-Path $ffTop.FullName 'bin\ffprobe.exe'
if (-not (Test-Path $ffmpegPath)) { throw "ffmpeg.exe not found at expected path: $ffmpegPath" }
if (-not (Test-Path $ffprobePath)) { throw "ffprobe.exe not found at expected path: $ffprobePath" }

# --- Build venv for repeatable builds ---
Write-Step "Creating build venv"
$venvDir = Join-Path $buildRoot '.venv'
if (Test-Path $venvDir) {
    Remove-Item -Recurse -Force $venvDir
}
py -3 -m venv $venvDir
$python = Join-Path $venvDir 'Scripts\python.exe'

Write-Step "Installing PyInstaller"
& $python -m pip install -U pip pyinstaller

# --- Run PyInstaller ---
Write-Step "Building onefile EXE"
Push-Location $projectDir
try {
    $pyArgs = @(
        '-m','PyInstaller',
        '--noconfirm','--clean','--onefile',
        '--name','video_downloader',
        '--add-binary', "$ytDlpPath;bin",
        '--add-binary', "$ffmpegPath;bin",
        '--add-binary', "$ffprobePath;bin",
        $scriptPath
    )
    & $python @pyArgs
}
finally {
    Pop-Location
}

$exePath = Join-Path $projectDir 'dist\video_downloader.exe'
Write-Step "Done"
Write-Host "EXE: $exePath"
Write-Host "Tip: Put input.txt next to the EXE; output/ will be created next to it."