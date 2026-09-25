; Inno Setup script для Zapret Manager
; Компилируется командой: ISCC.exe setup.iss
; Результат: ZapretManager-Setup-<version>.exe

#define MyAppName "Zapret Manager"
#define MyAppVersion "0.1.3"
#define MyAppPublisher "sedachkaa"
#define MyAppURL "https://github.com/sedachkaa/zapret-manager"
#define MyAppExeName "ZapretManager.exe"

[Setup]
; Уникальный AppId — не менять при обновлениях, иначе Windows будет считать
; каждую версию отдельным приложением.
AppId={{9A7E6C5F-2B41-4F08-9C3D-3B2F1A7D4E15}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases

; Куда устанавливать — в LOCALAPPDATA, без прав админа.
DefaultDirName={localappdata}\Programs\ZapretManager
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Мьютекс — не запускать два инсталлятора одновременно.
SetupMutex=ZapretManagerSetupMutex

; При апгрейде из silent-режима Inno Setup через Restart Manager
; сам закроет работающий ZapretManager.exe.
CloseApplications=yes

; Метаданные
OutputDir=..\dist
OutputBaseFilename=ZapretManager-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

SetupIconFile=..\app\assets\icon.ico

UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
Source: "..\dist\ZapretManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: quicklaunchicon; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0

[Run]
; Обычная (визард) установка: показываем галочку "Запустить приложение" на финальном экране.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall; Check: not WizardSilent
; Silent-режим (обновление): запускаем приложение сразу после установки.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM {#MyAppExeName} /T"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\logs"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  Res: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\ZapretManager');
    if DirExists(DataDir) then
    begin
      Res := MsgBox('Удалить также пользовательские данные?' + #13#10 +
                    DataDir + #13#10 + #13#10 +
                    'Там хранятся: config.json, логи, списки доменов, скачанные zapret и tg-ws-proxy.',
                    mbConfirmation, MB_YESNO);
      if Res = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;