<#
    Build RAMMIT and package RAMMIT-<version>.zip.     Run:  powershell -ExecutionPolicy Bypass -File Build.ps1

    1. checks: pyflakes, backend unit tests, theme folders in sync
    2. PyInstaller -> RAMMIT.exe
    3. dist\RAMMIT\        the ready-to-run app (exe + Src themes + user guides, NO Config)
       dist\Source\        clean source tree for the next developer
    4. dist\RAMMIT-<version>.zip  containing RAMMIT\ and Source\, plus RAMMIT-<version>.zip.sha256

    -Channel Dev      marks a test build: the footer reads "v1.0.0 · Dev (a1b2c3d)" (commit when there is one).
                      The default, Stable, is this tree's line: "v1.0.0 · Stable".
    -SkipChecks       skips step 1 (not recommended).
#>
param([switch]$SkipChecks, [ValidateSet("Dev", "Stable")][string]$Channel = "Stable", [string]$ZipName = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Dist = Join-Path $PSScriptRoot "dist"

function Step($Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }

if (-not $SkipChecks) {
    Step "Checks"
    python -m pyflakes App Tests Tools RAMMIT.py; if ($LASTEXITCODE) { throw "pyflakes found problems" }
    python -m unittest discover -s Tests -p "Test*.py"; if ($LASTEXITCODE) { throw "unit tests failed" }
    python Tools\SyncThemes.py --check; if ($LASTEXITCODE) { throw "theme folders drifted - run python Tools\SyncThemes.py" }
}

$Version = (python -c "from App.Version import AppVersion; print(AppVersion)").Trim()
if (-not $ZipName) { $ZipName = "RAMMIT-$Version" }

Step "PyInstaller ($Channel build of $Version)"
# App/BuildInfo.py exists only while PyInstaller runs, so running from source uses Version.py's default (Stable).
$Commit = ""
if (Get-Command git -ErrorAction SilentlyContinue) {
    # Outside a git repo git writes to stderr, which "Stop" would turn into a fatal error in Windows PowerShell.
    $ErrorActionPreference = "Continue"
    $Commit = (git rev-parse --short HEAD 2>$null) -join ""
    if ($LASTEXITCODE) { $Commit = "" }
    $ErrorActionPreference = "Stop"
}
$BuildInfo = Join-Path $PSScriptRoot "App\BuildInfo.py"
Set-Content -Encoding utf8 $BuildInfo "# Written by Build.ps1 for one build, then deleted. Never commit.`nAppChannel = `"$Channel`"`nAppCommit = `"$Commit`""
$Work = Join-Path $env:TEMP "RammitBuild"
try {
    python -m PyInstaller RAMMIT.spec --noconfirm --clean --distpath "$Work\dist" --workpath "$Work\build"
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
} finally {
    Remove-Item $BuildInfo -ErrorAction SilentlyContinue
}

Step "Assemble"
if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
$App = New-Item -ItemType Directory (Join-Path $Dist "RAMMIT")
# Folder build (see RAMMIT.spec): RAMMIT.exe + Runtime\ - never the one-file exe, which Defender's ML flags.
Copy-Item "$Work\dist\RAMMIT\*" $App -Recurse
if (-not (Test-Path (Join-Path $App "Runtime"))) { throw "Runtime folder missing - is RAMMIT.spec still the folder build?" }
Copy-Item -Recurse Src (Join-Path $App "Src")
Copy-Item Docs\README.txt, Docs\HowToMakeATheme.txt $App
# Never ship a Config folder: it would hold someone's accounts and settings.
if (Test-Path (Join-Path $App "Config")) { throw "Config must not be in the release" }

$SourceOut = New-Item -ItemType Directory (Join-Path $Dist "Source")
foreach ($Item in "App", "Src", "Tests", "Tools", "Docs","RAMMIT.py", "RAMMIT.spec", "Build.ps1", "requirements.txt",
                  "README.md", "SECURITY.md", "CHANGELOG.md", "AGENTS.md", ".gitignore") {
    if (Test-Path $Item) { Copy-Item -Recurse $Item $SourceOut }
}
Get-ChildItem $SourceOut -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Step "Zip"
$Zip = Join-Path $Dist "$ZipName.zip"
python Tools\MakeZip.py $Zip (Join-Path $Dist "RAMMIT") $SourceOut.FullName
if ($LASTEXITCODE) { throw "zip failed" }
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash
# Same format as sha256sum: the installer checks the download against this before installing it.
# LF line ending (not Set-Content's CRLF), or `sha256sum -c` on Linux/macOS reads the file name with a stray \r.
[IO.File]::WriteAllText("$Zip.sha256", "$($Hash.ToLower())  $ZipName.zip`n", [Text.Encoding]::ASCII)
Write-Host "`nBuilt $Zip ($([math]::Round((Get-Item $Zip).Length / 1MB, 1)) MB)  SHA-256 $Hash" -ForegroundColor Green
