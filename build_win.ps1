param(
    [string]$Python = "py",
    [string]$Name = "SPX-0DTE-Backtester"
)

# Create & use a clean venv
$env:PYTHONUTF8="1"
& $Python -m venv .venv
. .\.venv\Scripts\Activate.ps1

# Install your deps (edit if you have a requirements.txt)
python -m pip install --upgrade pip wheel
# If you have requirements.txt, prefer: pip install -r requirements.txt
pip install pyinstaller PyQt6 pandas numpy

# Build with the .spec (recommended for PyQt6)
pyinstaller --noconfirm --clean spx_backtester.spec

Write-Host "Build complete. Output folder: dist\$Name"

# OPTIONAL: Create a portable zip for testing
if (Test-Path "dist\$Name") {
    Compress-Archive -Path "dist\$Name\*" -DestinationPath "$Name-portable.zip" -Force
    Write-Host "Portable zip created: $PWD\$Name-portable.zip"
}
