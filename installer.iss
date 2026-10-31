; Inno Setup script for Audio Stem Separator
; Build the PyInstaller output first (dist\AudioStemSeparator\), then compile
; this with Inno Setup to produce Output\AudioStemSeparator-Setup.exe.

#define MyAppName "Audio Stem Separator"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Audio Stem Separator"
#define MyAppExeName "AudioStemSeparator.exe"

[Setup]
AppId={{A1B2C3D4-5E6F-47A8-9B0C-AUDIOSEP0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AudioStemSeparator
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install avoids requiring admin; switch to "admin" for machine-wide.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=AudioStemSeparator-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller output folder.
Source: "dist\AudioStemSeparator\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
