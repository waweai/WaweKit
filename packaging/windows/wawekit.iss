; Inno Setup script for the Wawekit Windows installer.
;
; Turns the PyInstaller folder build into a normal Windows application: an
; installer with a Start Menu group, an optional desktop icon, and a proper
; Add/Remove Programs entry that uninstalls cleanly.
;
;   1. pyinstaller wawekit.spec                 -> dist\Wawekit\
;   2. iscc packaging\windows\wawekit.iss       -> dist\installer\WawekitSetup-x.y.z.exe
;
; Inno Setup (free, https://jrsoftware.org/isinfo.php) provides `iscc`.
;
; Why per-user by default
; -----------------------
; PrivilegesRequired=lowest installs into %LOCALAPPDATA% with no UAC prompt,
; which is what most researchers on managed lab machines can actually do.
; Passing /ALLUSERS on the command line still gives a machine-wide install for
; anyone with admin rights, so nothing is lost by defaulting to the option that
; always works.

#define AppName        "Wawekit"
#define AppVersion     "0.1.0"
#define AppPublisher   "TheWaweAI"
#define AppURL         "https://github.com/waweai/WaweKit"
#define AppExeName     "Wawekit.exe"
; Both paths are relative to this .iss file (packaging\windows\).
#define BuildDir       "..\..\dist\Wawekit"
#define IconFile       "..\..\src\wawekit\resources\icons\wawekit.ico"

[Setup]
; A stable GUID identifies the app across versions — an upgrade replaces the
; previous install instead of stacking up a second copy. Never reuse it for a
; different application.
AppId={{7C2F1B8E-4A6D-4C1F-9E3B-0D5A8F1C2E47}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist\installer
OutputBaseFilename=WawekitSetup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user by default; `WawekitSetup.exe /ALLUSERS` installs machine-wide.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
; RDKit/Qt/scikit-learn are all 64-bit wheels, so the frozen bundle is x64-only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Checked by default: an installed desktop application is expected to leave an
; icon behind, and the user can still clear the box.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
; The whole PyInstaller folder: the executable plus Qt, RDKit, matplotlib and
; every bundled data file. `recursesubdirs` matters — QtWebEngine's resources
; and RDKit's data tables live several levels down.
Source: "{#BuildDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "Desktop workbench for cheminformatics research"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
; Desktop — the icon this installer exists to place.
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "Desktop workbench for cheminformatics research"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: quicklaunchicon

[Registry]
; Register the chemistry file types Wawekit opens, so .sdf/.smi files show its
; icon and offer it under "Open with". Written to the same hive the install
; used (HKCU for per-user, HKLM for /ALLUSERS) via the `root: HKA` shorthand.
Root: HKA; Subkey: "Software\Classes\.sdf\OpenWithProgids"; ValueType: string; ValueName: "Wawekit.Molecules"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.smi\OpenWithProgids"; ValueType: string; ValueName: "Wawekit.Molecules"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mol\OpenWithProgids"; ValueType: string; ValueName: "Wawekit.Molecules"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Wawekit.Molecules"; ValueType: string; ValueName: ""; ValueData: "Molecule file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Wawekit.Molecules\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"
Root: HKA; Subkey: "Software\Classes\Wawekit.Molecules\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
// The application itself creates a desktop icon on first launch (for people
// who installed with pip, where no installer runs). Dropping the same marker
// file the app uses tells it the shortcut question is already settled here —
// otherwise a user who *unchecked* the desktop-icon task would get one anyway
// the first time they started Wawekit.
procedure MarkShortcutHandled();
var
  Dir: string;
begin
  Dir := ExpandConstant('{userappdata}\{#AppPublisher}\{#AppName}');
  if ForceDirectories(Dir) then
    SaveStringToFile(Dir + '\.desktop-shortcut',
      'Shortcut setup performed by the {#AppName} installer.' + #13#10, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    MarkShortcutHandled();
end;

[UninstallDelete]
; PyInstaller's bundle plus anything Qt wrote beside it; the user's settings and
; logs in %APPDATA%\TheWaweAI\Wawekit are deliberately left alone.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"
