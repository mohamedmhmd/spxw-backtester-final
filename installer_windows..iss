; Inno Setup script for SPX 0DTE Backtester
; 1) Install Inno Setup (https://jrsoftware.org/isinfo.php)
; 2) Open this .iss and press Build.
#define MyAppName "SPX 0DTE Backtester"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Your Company"
#define MyAppExeName "SPX-0DTE-Backtester.exe"
#define MyAppDir "dist\SPX-0DTE-Backtester"

[Setup]
AppId={{D5A1E7D5-1B2A-4E70-AF7B-6B1F8B7A7D5A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={pf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=no
OutputDir=.
OutputBaseFilename=SPX-0DTE-Backtester-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
