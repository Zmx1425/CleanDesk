#ifndef MyAppVersion
  #define MyAppVersion GetEnv("CLEANDESK_VERSION")
#endif

#if MyAppVersion == ""
  #error "CLEANDESK_VERSION is not set. Run build_installer.bat."
#endif

#define MyAppName "CleanDesk"
#define MyAppPublisher "Zmx"
#define MyAppExeName "CleanDesk.exe"

[Setup]
AppId={{009B8B20-63A3-4C03-BCE7-995B3E4381AE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir={#SourcePath}\..\releases\{#MyAppVersion}
OutputBaseFilename=CleanDesk_{#MyAppVersion}_Setup
SetupIconFile={#SourcePath}\..\assets\cleandesk.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
AllowNoIcons=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
DirExistsWarning=no
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "其他选项："; Flags: unchecked

[Files]
Source: "{#SourcePath}\..\dist\CleanDesk\*"; DestDir: "{app}"; Excludes: "config.json,logs\*,__pycache__\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
