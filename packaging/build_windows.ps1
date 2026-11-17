# Build the Windows release folder on Windows: dist\windows\MXL Capybara Editor V2\
# Needs Python 3.10 (py -3.10). -BaseDir: folder holding the base exe and _internal\ (the original
# MXL Item Collector folder, or an unzipped MXL Capybara Editor release). Without it, release v1.2 is downloaded.
param([string]$BaseDir = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Title = "MXL Capybara Editor V2"
if (-not $BaseDir) {
    $Cache = Join-Path $Root ".cache\base"
    if (-not (Get-ChildItem -Path $Cache -Filter *.exe -Recurse -ErrorAction SilentlyContinue)) {
        New-Item -ItemType Directory -Force $Cache | Out-Null
        $Zip = Join-Path $Cache "base.zip"
        Invoke-WebRequest "https://github.com/Nugwa628/capybara-heroeditor/releases/download/v1.2/MXL-Capybara-Editor-v1.2.zip" -OutFile $Zip
        Expand-Archive $Zip -DestinationPath $Cache -Force
        Remove-Item $Zip
    }
    $BaseDir = (Get-ChildItem -Path $Cache -Directory | Select-Object -First 1).FullName
}
$BaseExe = (Get-ChildItem -Path $BaseDir -Filter *.exe | Select-Object -First 1).FullName
$Out = Join-Path $Root "dist\windows\$Title"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force (Join-Path $Out "lang") | Out-Null
Copy-Item -Recurse (Join-Path $BaseDir "_internal") (Join-Path $Out "_internal")
Copy-Item (Join-Path $Root "lang\*.json") (Join-Path $Out "lang")
& py -3.10 (Join-Path $Root "src\repack.py") $BaseExe (Join-Path $Out "$Title.exe") "--icon=$(Join-Path $Root 'src\capybara.ico')"
if ($LASTEXITCODE -ne 0) { throw "repack.py failed" }
Compress-Archive -Path $Out -DestinationPath (Join-Path $Root "dist\windows\MXL-Capybara-Editor-V2-windows.zip") -Force
Write-Host "built: $Out"
