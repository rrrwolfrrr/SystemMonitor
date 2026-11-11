; ============================================================
; SystemMonitor — Инсталлятор с полной деинсталляцией
; Версия: 2.0.5
; Язык интерфейса: Русский
; Платформа: Windows 10/11 (64-bit)
; ============================================================

#define MyAppName "SystemMonitor"
#define MyAppVersion "2.0.5"
#define MyAppPublisher "SystemMonitor Team"
#define MyAppExeName "SystemMonitor.exe"
#define MyAppURL "http://localhost:5000"
#define MyAppAutostartTask "SystemMonitor-AutoStart"
#ifndef MyAppDistDir
  #define MyAppDistDir "dist\SystemMonitor"
#endif

[Setup]
AppId={{E5F3B7A2-9D1C-4A8F-B6E0-3C7D2F1A9B45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir=installer_output
OutputBaseFilename=SystemMonitor {#MyAppVersion}

Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern

; Установка и пользовательские настройки выполняются от имени текущего
; пользователя. Само приложение и PawnIO запрашивают повышение прав отдельно.
PrivilegesRequired=lowest

; Сборка содержит 64-битные Python/PyInstaller и .NET-компоненты.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Иконка в "Установка и удаление программ"
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"
Name: "autostart"; Description: "Автозапуск при старте Windows"; GroupDescription: "Дополнительно:"; Flags: unchecked
Name: "firewall"; Description: "Открыть порты в брандмауэре (5000, 8765)"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
; Копируем ВСЮ папку dist\SystemMonitor\ (результат сборки PyInstaller)
; Не переносим данные, созданные во время локального запуска сборки.
Source: "{#MyAppDistDir}\*"; DestDir: "{app}"; Excludes: "server.log;server.log.*;history.db;history.db-*;history.json"; Flags: ignoreversion recursesubdirs createallsubdirs

; Конфигурация и иконка также остаются доступными в корне каталога установки.
; Рабочая frozen-конфигурация берётся из _internal\env.env, включённого build.spec.
Source: "env.env"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Меню Пуск
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"

; Рабочий стол
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Дашборд открывается только по отдельному флажку на последнем шаге установки.
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: dword; ValueName: "AutoOpenDashboard"; ValueData: "0"

[Run]
; Открыть порты в брандмауэре при установке
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""{#MyAppName} HTTP"" dir=in action=allow program=""{app}\{#MyAppExeName}"" protocol=TCP localport=5000"; Verb: runas; Flags: runhidden shellexec; Tasks: firewall
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""{#MyAppName} WebSocket"" dir=in action=allow program=""{app}\{#MyAppExeName}"" protocol=TCP localport=8765"; Verb: runas; Flags: runhidden shellexec; Tasks: firewall
; PawnIO предоставляет низкоуровневый доступ к MSR/EC, необходимый части CPU-сенсоров.
; В PyInstaller-дистрибутиве файл находится в _internal.
; Эти пункты отображаются флажками на последнем шаге установки.
; SystemMonitor запускается только если пользователь выбрал этот пункт.
; SystemMonitor имеет requireAdministrator в собственном манифесте.
; Verb=runas гарантирует корректный UAC-запуск из финального окна.
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "Запустить SystemMonitor"; Verb: "runas"; Flags: postinstall nowait unchecked shellexec
; Открываем один дашборд после запуска сервера. Автооткрытие внутри приложения
; отключено выше, поэтому второй экземпляр страницы не появляется.
; Ждём запуска HTTP-сервера, затем открываем единственную страницу дашборда.
; ping используется только как тихая задержка и не требует PowerShell.
Filename: "{cmd}"; Parameters: "/C start http://localhost:5000/dashboard"; WorkingDir: "{app}"; Description: "Открыть Dashboard в браузере"; Flags: postinstall runhidden runasoriginaluser unchecked skipifsilent

; ============================================================
; ПОЛНАЯ ЗАЧИСТКА ПРИ УДАЛЕНИИ
; ============================================================

[UninstallRun]
; 1. Удаляем правила брандмауэра
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#MyAppName} HTTP"""; Verb: runas; Flags: runhidden shellexec; RunOnceId: "DelFW_HTTP"
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#MyAppName} WebSocket"""; Verb: runas; Flags: runhidden shellexec; RunOnceId: "DelFW_WS"

; 2. Удаляем задание автозапуска и старую запись Run от предыдущих версий.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""{#MyAppAutostartTask}"" /F"; Verb: runas; Flags: runhidden shellexec; RunOnceId: "DelAutostartTask"
Filename: "reg.exe"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""{#MyAppName}"" /f"; Flags: runhidden; RunOnceId: "DelReg_AutoStart"

; 3. Удаляем все настройки программы (весь ключ со вложенными)
Filename: "reg.exe"; Parameters: "delete ""HKCU\Software\{#MyAppName}"" /f"; Flags: runhidden; RunOnceId: "DelReg_Settings"

; 4. Страховка: удаляем возможные ключи от разных версий
Filename: "reg.exe"; Parameters: "delete ""HKCU\Software\SystemMonitor Team"" /f"; Flags: runhidden; RunOnceId: "DelReg_Publisher"

[UninstallDelete]
; Данные, созданные во время работы
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\templates"
Type: filesandordirs; Name: "{app}\static"
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\env.env"
Type: files; Name: "{app}\server.log"
Type: files; Name: "{app}\history.db"
Type: files; Name: "{app}\history.json"
Type: files; Name: "{app}\icon.ico"

[Code]
// ============================================================
// Проверка наличия .NET Framework 4.8+
// ============================================================
function IsDotNetInstalled(): Boolean;
var
  Release: Cardinal;
begin
  Result := RegQueryDWordValue(
    HKLM,
    'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
    'Release',
    Release
  ) and (Release >= 528040);
  if not Result then
  begin
    MsgBox('Для работы SystemMonitor требуется .NET Framework 4.8 или новее.' + #13#10 +
           'Установите или обновите .NET Framework и повторите установку.',
           mbError, MB_OK);
  end;
end;

// ============================================================
// Проверка, запущен ли SystemMonitor
// ============================================================
function IsSystemMonitorRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd.exe',
                 '/c tasklist /FI "IMAGENAME eq SystemMonitor.exe" | findstr /I "SystemMonitor.exe" >nul',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

// ============================================================
// Закрытие SystemMonitor с несколькими попытками
// ============================================================
procedure KillSystemMonitor();
var
  Started: Boolean;
  ResultCode: Integer;
  i: Integer;
begin
  if not IsSystemMonitorRunning() then Exit;

  Started := Exec(
    'taskkill',
    '/F /T /IM SystemMonitor.exe',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  if (not Started) or (ResultCode <> 0) then
  begin
    Started := ShellExec(
      'runas',
      'taskkill.exe',
      '/F /T /IM SystemMonitor.exe',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    );
    if (not Started) or (ResultCode <> 0) then Exit;
  end;

  for i := 1 to 5 do
  begin
    if not IsSystemMonitorRunning() then Exit;
    Sleep(1000);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if IsSystemMonitorRunning() then
  begin
    MsgBox('SystemMonitor запущен. Программа будет закрыта для продолжения установки.',
           mbInformation, MB_OK);
    KillSystemMonitor();
    if IsSystemMonitorRunning() then
      Result := 'Не удалось закрыть SystemMonitor. Закройте программу и повторите установку.';
  end;
end;

function PrepareToUninstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if IsSystemMonitorRunning() then
  begin
    MsgBox('SystemMonitor запущен. Программа будет закрыта для продолжения удаления.',
           mbInformation, MB_OK);
    KillSystemMonitor();
    if IsSystemMonitorRunning() then
      Result := 'Не удалось закрыть SystemMonitor. Закройте программу и повторите удаление.';
  end;
end;

// ============================================================
// Инициализация установки
// ============================================================
function InitializeSetup(): Boolean;
begin
  Result := IsDotNetInstalled();
end;

// ============================================================
// Перед установкой: закрыть запущенный процесс.
// ============================================================
procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
  Started: Boolean;
  ExePath: String;
  TaskParameters: String;
begin
  if CurStep = ssPostInstall then
  begin
      { Установщик уже запущен с правами администратора. Запускаем PawnIO
        напрямую, чтобы он унаследовал повышенный токен и не получил
        ошибку CreateProcess 740 из-за повторного runas. }
      if FileExists(ExpandConstant('{app}\_internal\PawnIO_setup.exe')) then
      begin
        Started := Exec(
          ExpandConstant('{app}\_internal\PawnIO_setup.exe'),
          '',
          ExpandConstant('{app}\_internal'),
          SW_SHOWNORMAL,
          ewWaitUntilTerminated,
          ErrorCode);
        if not Started then
        begin
          { На некоторых системах Inno Setup завершает установочную фазу
            уже с обычным токеном. В этом случае явно запрашиваем UAC. }
          Started := ShellExec(
            'runas',
            ExpandConstant('{app}\_internal\PawnIO_setup.exe'),
            '',
            ExpandConstant('{app}\_internal'),
            SW_SHOWNORMAL,
            ewWaitUntilTerminated,
            ErrorCode);
        end;
        if (not Started) or (ErrorCode <> 0) then
          MsgBox(
            'Не удалось запустить установку PawnIO. Код ошибки: ' +
            IntToStr(ErrorCode) + '. Запустите PawnIO_setup.exe вручную ' +
            'от имени администратора из папки _internal.',
            mbError,
            MB_OK);
      end
      else
        MsgBox(
          'Файл PawnIO_setup.exe не найден в установленной программе.',
          mbError,
          MB_OK);

      { Run-key startup cannot reliably launch this requireAdministrator app
        without an interactive UAC prompt. Register a highest-privilege logon
        task instead, scoped to the account that confirms the UAC request. }
      if WizardIsTaskSelected('autostart') then
      begin
        ExePath := ExpandConstant('{app}\{#MyAppExeName}');
        TaskParameters :=
          '/Create /SC ONLOGON /TN "' + '{#MyAppAutostartTask}' +
          '" /TR "\"' + ExePath + '\"" /RL HIGHEST /F /IT';
        Started := ShellExec(
          'runas',
          ExpandConstant('{sys}\schtasks.exe'),
          TaskParameters,
          '',
          SW_HIDE,
          ewWaitUntilTerminated,
          ErrorCode);
        if (not Started) or (ErrorCode <> 0) then
          MsgBox(
            'Не удалось включить автозапуск. Включите его позже через меню ' +
            'SystemMonitor в системном трее.',
            mbError,
            MB_OK);
      end;
  end;
end;

// ============================================================
// Деинсталляция: закрытие процесса + полная зачистка
// ============================================================
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  case CurUninstallStep of
    usPostUninstall:
      begin
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#MyAppName}');
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\{#MyAppName}');
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\SystemMonitor Team');
        DelTree(ExpandConstant('{app}'), True, True, True);
        DelTree(ExpandConstant('{userappdata}\{#MyAppName}'), True, True, True);
        DelTree(ExpandConstant('{localappdata}\{#MyAppName}'), True, True, True);
      end;
  end;
end;
