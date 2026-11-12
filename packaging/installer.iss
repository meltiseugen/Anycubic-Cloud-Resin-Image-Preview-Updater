; Build with Inno Setup 6.4+ or 7. No admin rights or network required to install.
[Setup]
AppId={{F45EBFF8-579C-4851-817E-DDF63DF9EF8B}
AppName=PM7 Cloud Preview Fixer
AppVersion=1.1.0
AppPublisher=PM7 Preview Fixer
DefaultDirName={localappdata}\Programs\PM7 Cloud Preview Fixer
DefaultGroupName=PM7 Cloud Preview Fixer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PM7CloudPreviewFixer-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\PM7CloudPreviewFixer.exe
CloseApplications=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\PM7CloudPreviewFixer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\PM7 Cloud Preview Fixer"; Filename: "{app}\PM7CloudPreviewFixer.exe"
Name: "{autodesktop}\PM7 Cloud Preview Fixer"; Filename: "{app}\PM7CloudPreviewFixer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PM7CloudPreviewFixer.exe"; Description: "Launch PM7 Cloud Preview Fixer"; Flags: nowait postinstall skipifsilent
