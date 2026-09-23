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

; Куда устанавливать — в LOCALAPPDATA, без прав админа
DefaultDirName={localappdata}\Programs\ZapretManager
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Метаданные
OutputDir=..\dist
OutputBaseFilename=ZapretManager-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; ИЗМЕНЕНО: раскомментирована иконка установщика.
; Требует многоразмерный .ico (16/32/48/256), иначе Windows подставит дефолт.
SetupIconFile=..\app\assets\icon.ico

UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; Архитектура
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Минимальная версия Windows
MinVersion=10.0

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
; Всё содержимое dist\ZapretManager (exe + _internal) идёт в папку установки
Source: "..\dist\ZapretManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; ИЗМЕНЕНО: во всех ярлыках явно указан IconFilename и IconIndex.
; Без этого Inno иногда подставляет иконку из Filename нестабильно
; (особенно если приложение самоэлевируется через UAC и на ярлык
; накладывается щит — тогда Windows может рисовать вместо иконки
; только щит).
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: quicklaunchicon; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Перед удалением убеждаемся, что приложение закрыто
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM {#MyAppExeName} /T"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
; Удаляем только файлы приложения. Данные пользователя (config.json, logs, zapret, tgproxy)
; НЕ трогаем, чтобы при переустановке настройки и списки сохранились.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\logs"

[Code]
// При удалении спросим, удалять ли данные пользователя
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

// При установке сохраняем язык, если он был выбран ранее
function InitializeSetup(): Boolean;
begin
  Result := True;
end;