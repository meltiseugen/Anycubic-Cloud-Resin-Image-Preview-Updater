; Build with Inno Setup 6.4+ or 7. No admin rights or network required to install.
[Setup]
AppId={{F45EBFF8-579C-4851-817E-DDF63DF9EF8B}
AppName=Anycubic File Updater
AppVersion=1.1.0
AppPublisher=Anycubic File Updater
; The unchanged AppId and UsePreviousAppDir preserve existing install locations on upgrade.
DefaultDirName={localappdata}\Programs\Anycubic File Updater
UsePreviousAppDir=yes
DefaultGroupName=Anycubic File Updater
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=AnycubicFileUpdater-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AnycubicFileUpdater.exe
CloseApplications=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\AnycubicFileUpdater.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Anycubic File Updater"; Filename: "{app}\AnycubicFileUpdater.exe"
Name: "{autodesktop}\Anycubic File Updater"; Filename: "{app}\AnycubicFileUpdater.exe"; Tasks: desktopicon

[InstallDelete]
Type: files; Name: "{app}\PM7CloudPreviewFixer.exe"
Type: files; Name: "{userprograms}\PM7 Cloud Preview Fixer\PM7 Cloud Preview Fixer.lnk"
Type: dirifempty; Name: "{userprograms}\PM7 Cloud Preview Fixer"
Type: files; Name: "{userdesktop}\PM7 Cloud Preview Fixer.lnk"

[Run]
Filename: "{app}\AnycubicFileUpdater.exe"; Description: "Launch Anycubic File Updater"; Flags: nowait postinstall skipifsilent
