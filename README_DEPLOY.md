# Deploying SPX 0DTE Backtester

## Quick path (Windows)
1) Open **PowerShell** in the project root.
2) Run: `./build_win.ps1` (you may need `Set-ExecutionPolicy -Scope Process Bypass` once).
3) Test the portable build: `dist/SPX-0DTE-Backtester/SPX-0DTE-Backtester.exe`.
4) Build the installer with **Inno Setup** using `installer_windows.iss`.

## Quick path (macOS)
1) `chmod +x build_mac.sh && ./build_mac.sh`
2) Run the app: `dist/SPX-0DTE-Backtester/SPX-0DTE-Backtester.app`
3) Optionally sign and create a DMG before distributing.

## Notes
- Build **on the target OS** (Windows on Windows, macOS on macOS).
- If you bundle any config files, place them next to `main.py` or inside `engine/ data/ gui/` so they are collected.
- Remove any hard-coded API keys before building. Read them from an environment variable or a config file.
- Test the build on a clean VM to verify all DLLs/plugins are present.
