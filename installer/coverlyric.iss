; coverlyric-setup.exe: a per-user install (no admin rights). Built by .github/workflows/installer.yml:
;   iscc /DVersion=0.2.0 installer\coverlyric.iss
; with uv.exe placed in installer\uv\ first. The user's data folder is chosen on its own page and kept
; in %LOCALAPPDATA%\coverlyric\data-folder.txt, which tools/start.ps1 and the page read.

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
; The same AppId on every version, so a new version installs over the old one.
AppId={{4297D240-C551-4ACA-A335-915B65192ED2}
AppName=coverlyric
AppVersion={#Version}
AppVerName=coverlyric {#Version}
AppPublisher=NaNIsaac
AppPublisherURL=https://github.com/NaNIsaac/coverlyric
AppSupportURL=https://github.com/NaNIsaac/coverlyric/issues
SourceDir=..
OutputDir=installer\Output
OutputBaseFilename=coverlyric-setup
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\coverlyric
DisableProgramGroupPage=yes
SetupIconFile=installer\icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName=coverlyric
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=LICENSE

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.DataTitle=데이터 폴더
korean.DataHeading=만든 영상과 작업 중인 노래, 설정을 둘 폴더
korean.DataNote=프로그램을 다시 설치하거나 지워도 이 폴더는 그대로 남습니다. 나중에 프로그램의 설정에서 바꿀 수 있습니다.
korean.StartNow=coverlyric 시작
english.DataTitle=Data folder
english.DataHeading=Where your videos, the song in progress and the settings are kept
english.DataNote=Reinstalling or uninstalling the program leaves this folder as it is. You can change it later in the program's settings.
english.StartNow=Start coverlyric

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; A module removed in a new version must not stay behind from the old one.
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\tools"

[Files]
Source: "src\*"; DestDir: "{app}\src"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs createallsubdirs
Source: "tools\start.ps1"; DestDir: "{app}\tools"
Source: "pyproject.toml"; DestDir: "{app}"
Source: "uv.lock"; DestDir: "{app}"
Source: "LICENSE"; DestDir: "{app}"
Source: "README.md"; DestDir: "{app}"
Source: "README.en.md"; DestDir: "{app}"
Source: "가사영상 만들기.bat"; DestDir: "{app}"
Source: "installer\icon.ico"; DestDir: "{app}"
Source: "installer\uv\uv.exe"; DestDir: "{app}\uv"

[Icons]
Name: "{userprograms}\coverlyric"; Filename: "{app}\가사영상 만들기.bat"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{userdesktop}\coverlyric"; Filename: "{app}\가사영상 만들기.bat"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\가사영상 만들기.bat"; WorkingDir: "{app}"; Description: "{cm:StartNow}"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
; Made by the first start, not by the installer. The data folder is elsewhere and is never removed.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\src"

[Code]
var
  DataPage: TInputDirWizardPage;

function SavedFile(): String;
begin
  Result := ExpandConstant('{localappdata}\coverlyric\data-folder.txt');
end;

{ The folder chosen before (in an earlier install or in the program), else Documents\coverlyric.
  userdocs is the shell's Documents, which follows a OneDrive move. }
function DefaultDataFolder(): String;
var
  Lines: TArrayOfString;
begin
  Result := ExpandConstant('{userdocs}\coverlyric');
  if LoadStringsFromUTF8File(SavedFile(), Lines) and (GetArrayLength(Lines) > 0) and (Trim(Lines[0]) <> '') then
    Result := Trim(Lines[0]);
end;

procedure InitializeWizard();
begin
  DataPage := CreateInputDirPage(wpSelectDir, CustomMessage('DataTitle'), CustomMessage('DataHeading'),
    CustomMessage('DataNote'), False, '');
  DataPage.Add('');
  DataPage.Values[0] := DefaultDataFolder();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(DataPage.Values[0]);
    ForceDirectories(ExtractFileDir(SavedFile()));
    SetArrayLength(Lines, 1);
    Lines[0] := DataPage.Values[0];
    SaveStringsToUTF8File(SavedFile(), Lines, False);
  end;
end;
