; Inno Setup installer for the PyInstaller one-folder Windows build.
; Build with ISCC.exe packaging\windows-installer.iss from the repository root.
#define MyAppName "Ebook Risk Analyzer"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "ebook-risk-analyzer contributors"
#define MyAppExeName "EbookRiskAnalyzer.exe"

[Setup]
AppId={{AFD8BA36-34E2-4D7C-8EC3-85985A4A45AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\Ebook Risk Analyzer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=EbookRiskAnalyzer-Setup-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}

[Files]
; Include the complete one-folder bundle; do not fetch dependencies at application runtime.
Source: "..\dist\EbookRiskAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "web"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "web"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "web"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
