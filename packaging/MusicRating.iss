[Setup]
AppId=MusicRating.FuryMask
AppName=Music Rating
AppVersion={#AppVersion}
AppPublisher=FuryMask
DefaultDirName={localappdata}\Programs\Music Rating
DefaultGroupName=Music Rating
UninstallDisplayIcon={app}\MusicRating.exe
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
CloseApplications=yes
CloseApplicationsFilter=MusicRating.exe
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename={#InstallerBase}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\MusicRating.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Music Rating"; Filename: "{app}\MusicRating.exe"

[Run]
Filename: "{app}\MusicRating.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,Music Rating}"; Flags: nowait postinstall skipifsilent runascurrentuser; BeforeInstall: ResetPythonEnvironment

[Code]
function SetEnvironmentVariable(lpName, lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure ResetPythonEnvironment;
begin
  { Update installers started by older builds can inherit an expired extraction directory. }
  SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1');
end;
