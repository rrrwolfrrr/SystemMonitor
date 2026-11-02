# SystemMonitor

[English](#english) | [Русский](#русский)

## English

SystemMonitor is a Windows application for monitoring a PC's hardware and
viewing sensor data in desktop and mobile dashboards. It can also track the
frame rate of an individual running process.

The program collects data on the Windows PC where it is installed. You can
view that data locally or open the dashboards in a browser on another computer,
phone, or tablet.

<p align="center">
  <a href="https://www.donationalerts.com/r/monsterhairy" target="_blank" rel="noopener noreferrer">
    <img src="assets/coffee-donation.gif" width="140" alt="Animated steaming coffee cup - support SystemMonitor">
  </a>
  <br>
  <a href="https://www.donationalerts.com/r/monsterhairy"><strong>Buy the author a coffee</strong></a>
  <br>
  Support the continued development of SystemMonitor ❤️
</p>

### What SystemMonitor can do

- Read available hardware sensors, including temperatures, loads, clocks,
  voltages, fan speeds, and other values exposed by the PC's hardware and
  drivers. The exact sensors vary by computer.
- Show data in desktop and mobile dashboards, with configurable cards,
  layouts, themes, and sensor selections.
- Show available sensors in a separate card for each detected GPU; custom
  cards can combine sensors from different adapters.
- Display temperature history and configure CPU/GPU warning thresholds.
- Show battery information on supported laptops and GPU memory information
  when Windows and the graphics driver provide it.
- Track one process at a time with PresentMon and Windows ETW. It can show
  current and recent average FPS, 1% low, and frame time. It does not inject
  code into games or create an in-game overlay.
- Connect dashboards to other SystemMonitor PCs on a trusted local network
  and show data from multiple sources.

Sensor availability and accuracy depend on the hardware, Windows, and
installed drivers. Some CPU/MSR/EC readings require the PawnIO driver.

### Where it runs and where you can view the data

SystemMonitor itself runs on **64-bit Windows 10 or Windows 11**. This is the
computer that collects the sensor readings, so it must be powered on with
SystemMonitor running.

The dashboard can be viewed using a modern web browser on another Windows,
macOS, or Linux computer, or on an Android or iOS/iPadOS phone or tablet. You
do not need to install SystemMonitor on the viewing device. For the usual
setup, the viewing device and monitored PC must be able to reach each other
over the same trusted Wi-Fi or LAN.

The built-in server does not provide authentication and is intended for a
trusted local network. Access from outside that network requires separate,
secure remote-access configuration. Do not expose the application ports
directly to the public Internet.

### Desktop Dashboard

Screenshots below show the desktop Dashboard: its overview, temperature
threshold settings, and custom sensor cards.

<p align="center">
  <a href="assets/screenshots/desktop-dashboard-overview.png"><img src="assets/screenshots/desktop-dashboard-overview.png" width="32%" alt="SystemMonitor desktop Dashboard overview"></a>
  <a href="assets/screenshots/desktop-dashboard-temperature-alerts.png"><img src="assets/screenshots/desktop-dashboard-temperature-alerts.png" width="32%" alt="Desktop Dashboard temperature threshold settings"></a>
  <a href="assets/screenshots/desktop-dashboard-custom-card.png"><img src="assets/screenshots/desktop-dashboard-custom-card.png" width="32%" alt="Desktop Dashboard custom card sensor selection"></a>
</p>
<p align="center">
  <sub>Overview · Temperature thresholds · Custom sensor card</sub>
</p>

### Mobile Dashboard

The mobile Dashboard adapts to phone and tablet screens. Its browser-based
interface can show sensor cards, temperature history, and configurable
profiles without installing a separate mobile app.

<p align="center">
  <a href="assets/screenshots/mobile-dashboard-blue-theme.png"><img src="assets/screenshots/mobile-dashboard-blue-theme.png" width="32%" alt="SystemMonitor mobile Dashboard in blue theme"></a>
  <a href="assets/screenshots/mobile-dashboard-dark-theme.png"><img src="assets/screenshots/mobile-dashboard-dark-theme.png" width="32%" alt="SystemMonitor mobile Dashboard in dark theme"></a>
  <a href="assets/screenshots/mobile-dashboard-settings.png"><img src="assets/screenshots/mobile-dashboard-settings.png" width="32%" alt="SystemMonitor mobile Dashboard settings"></a>
</p>
<p align="center">
  <sub>Blue theme · Dark theme · Settings</sub>
</p>

### Why choose SystemMonitor?

- **A PC dashboard you can also open on a phone.** View the monitored
  computer's data in a browser without installing a client app on every
  device.
- **Hardware monitoring and per-process FPS in one project.** Sensor data
  and frame-rate monitoring are available from the same application.
- **Flexible dashboards.** Choose sensors, arrange cards, use different
  themes, and connect to other SystemMonitor PCs on a trusted network.
- **Free and open source.** The original SystemMonitor code is licensed under
  MIT. Third-party components retain their own licenses.

Hardware support and feature sets differ between monitoring applications;
SystemMonitor may not replace every specialized tool.

### Build SystemMonitor from source

#### Requirements

- A 64-bit Windows 10/11 PC.
- 64-bit Python 3.10 or later, Git, and an Internet connection for installing
  Python packages. You can also download the repository as a ZIP instead of
  using Git.
- The project includes its pinned LibreHardwareMonitor DLL dependencies and
  PresentMon executable. The official PawnIO.Setup v2.1.0 installer is not
  stored in the current Git tree. Download it from the
  [official release](https://github.com/namazso/PawnIO.Setup/releases/tag/2.1.0)
  and save it in the project root as `PawnIO_setup.exe` before building.
- `build.bat` also expects the .NET Framework C# compiler at
  `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` to create
  `LhmVisitorAdapter.dll`.
- WebView2 Runtime is used by the embedded dashboard window. If it is
  unavailable, use the browser dashboard instead.
- Inno Setup 6 or 7 is needed only if you want to create the Windows
  installer. The PyInstaller folder build does not require Inno Setup.

#### 1. Get the source

In PowerShell, clone the public repository and enter its folder:

```powershell
git clone https://github.com/rrrwolfrrr/SystemMonitor.git
Set-Location SystemMonitor
```

If you downloaded a ZIP, extract it and open PowerShell in the extracted
project folder instead.

#### 2. Install Python dependencies

Create a virtual environment and install the project requirements and
PyInstaller:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
```

If `py` is not available, use `python` to create the environment and make sure
it is 64-bit Python 3.10 or later.

#### 3. Run from source (optional)

```powershell
.\.venv\Scripts\python.exe main.py
```

The default web server port is `5000`. Open `http://127.0.0.1:5000` on the
same PC. Some hardware readings may require running with administrator
privileges and installing PawnIO.

#### 4. Run tests (optional)

Run the automated test suite:

```powershell
.\autotest.bat
```

To probe the sensors on the current PC as well:

```powershell
.\autotest.bat --live
```

Hardware-specific cases that the current PC does not support are skipped.
After building, verify the packaged folder with:

```powershell
.\autotest.bat --build dist\SystemMonitor
```

#### 5. Build the application folder

Download PawnIO.Setup v2.1.0 from the official release linked above, place it
in the repository root, and name it exactly `PawnIO_setup.exe`. Then run:

```powershell
.\build.bat
```

The script checks Python and PyInstaller, removes previous build output,
builds the C# visitor adapter, runs PyInstaller, and verifies the result. The
application is created at:

```text
dist\SystemMonitor\SystemMonitor.exe
```

This is a **one-folder build**. Keep the entire `dist\SystemMonitor` folder
together; the executable is not a standalone file. Building it does not
install or update an existing copy of SystemMonitor.

#### 6. Create the installer (optional)

Install Inno Setup 6 or 7, build the application folder first, then run from
the repository root:

```powershell
iscc installer.iss
```

The installer is written to `installer_output`. Its filename and version are
defined in `installer.iss`. Installation options can request UAC elevation
for PawnIO, firewall rules, and other administrative operations.

Before redistributing a build, review
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and follow the licenses and
notices for all included third-party components.

### License

The original SystemMonitor code is licensed under the MIT License; see
[`LICENSE`](LICENSE). Third-party components retain their own licenses. For
details, see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Русский

SystemMonitor — программа для Windows, которая помогает следить за
оборудованием компьютера и просматривать показания датчиков в настольной и
мобильной панелях. Также программа может отслеживать частоту кадров (FPS)
отдельного запущенного процесса.

Показатели собираются на компьютере с Windows, где установлена программа.
Их можно смотреть на этом же компьютере или открыть панели в браузере на
другом компьютере, телефоне либо планшете.

<p align="center">
  <a href="https://www.donationalerts.com/r/monsterhairy" target="_blank" rel="noopener noreferrer">
    <img src="assets/coffee-donation.gif" width="140" alt="Анимированная чашка кофе с паром — поддержать SystemMonitor">
  </a>
  <br>
  <a href="https://www.donationalerts.com/r/monsterhairy"><strong>Угостить автора кофе</strong></a>
  <br>
  На развитие программы ❤️
</p>

### Возможности SystemMonitor

- Показывает доступные датчики оборудования: например, температуры,
  загрузку, частоты, напряжения, скорость вентиляторов и другие параметры,
  предоставляемые оборудованием и драйверами. Набор датчиков зависит от
  конкретного компьютера.
- Отображает показатели в настольной и мобильной панелях. Можно настраивать
  карточки, их расположение, темы и список датчиков.
- Показывает доступные датчики каждой обнаруженной видеокарты в отдельной
  карточке; в пользовательской карточке можно объединять датчики разных
  адаптеров.
- Позволяет просматривать историю температур и задавать пороги
  предупреждений для CPU и GPU.
- Может показывать сведения о батарее на поддерживаемых ноутбуках и
  использовании видеопамяти, если эти данные доступны от Windows и драйвера.
- Отслеживает FPS одного процесса за раз с помощью PresentMon и Windows ETW.
  Показывает текущую и недавнюю среднюю частоту кадров, 1% low и время
  кадра. Программа не внедряет код в игры и не создаёт внутриигровой оверлей.
- Позволяет подключать панели к другим компьютерам с SystemMonitor в
  доверенной локальной сети и смотреть показатели из нескольких источников.

Набор и точность показаний зависят от оборудования, Windows и установленных
драйверов. Для некоторых датчиков CPU/MSR/EC требуется драйвер PawnIO.

### На каких компьютерах работает программа и где смотреть данные

Сам SystemMonitor запускается на **64-разрядной Windows 10 или Windows 11**.
Этот компьютер собирает показания, поэтому он должен быть включён, а
SystemMonitor — запущен.

Панель можно открыть в современном браузере на другом компьютере с Windows,
macOS или Linux, а также на смартфоне или планшете с Android либо
iOS/iPadOS. Устанавливать SystemMonitor на устройство для просмотра не нужно.
Обычно устройство-просмотрщик и компьютер с SystemMonitor должны иметь
сетевой доступ друг к другу через одну доверенную Wi-Fi или локальную сеть.

Встроенный сервер не использует аутентификацию и предназначен для доверенной
локальной сети. Для просмотра из другой сети нужно отдельно настроить
защищённый удалённый доступ. Не открывайте порты приложения напрямую в
публичный Интернет.

### Настольная панель Dashboard

На скриншотах показаны настольная панель, настройка температурных порогов и
пользовательская карточка датчиков.

<p align="center">
  <a href="assets/screenshots/desktop-dashboard-overview.png"><img src="assets/screenshots/desktop-dashboard-overview.png" width="32%" alt="Общий вид настольной панели SystemMonitor"></a>
  <a href="assets/screenshots/desktop-dashboard-temperature-alerts.png"><img src="assets/screenshots/desktop-dashboard-temperature-alerts.png" width="32%" alt="Настройка температурных порогов в настольной панели"></a>
  <a href="assets/screenshots/desktop-dashboard-custom-card.png"><img src="assets/screenshots/desktop-dashboard-custom-card.png" width="32%" alt="Выбор датчиков пользовательской карточки"></a>
</p>
<p align="center">
  <sub>Общий вид · Температурные пороги · Пользовательская карточка датчиков</sub>
</p>

### Мобильная панель Dashboard

Мобильная панель адаптируется к экрану смартфона или планшета. В браузере
можно просматривать карточки датчиков и историю температур, выбирать
оформление и настраивать профили — отдельное приложение на телефон
устанавливать не требуется.

<p align="center">
  <a href="assets/screenshots/mobile-dashboard-blue-theme.png"><img src="assets/screenshots/mobile-dashboard-blue-theme.png" width="32%" alt="Мобильная панель SystemMonitor в синей теме"></a>
  <a href="assets/screenshots/mobile-dashboard-dark-theme.png"><img src="assets/screenshots/mobile-dashboard-dark-theme.png" width="32%" alt="Мобильная панель SystemMonitor в тёмной теме"></a>
  <a href="assets/screenshots/mobile-dashboard-settings.png"><img src="assets/screenshots/mobile-dashboard-settings.png" width="32%" alt="Настройки мобильной панели SystemMonitor"></a>
</p>
<p align="center">
  <sub>Синяя тема · Тёмная тема · Настройки</sub>
</p>

### Чем может быть удобен SystemMonitor

- **Компьютер и браузер в одной связке.** Можно смотреть показатели ПК с
  телефона или другого компьютера, не устанавливая программу на эти
  устройства.
- **Мониторинг оборудования и FPS в одной программе.** Показания датчиков и
  отслеживание частоты кадров доступны в одном приложении.
- **Настраиваемые панели.** Можно выбирать датчики, менять расположение
  карточек и темы, подключать другие компьютеры с SystemMonitor в доверенной
  сети.
- **Бесплатный проект с открытым исходным кодом.** Оригинальный код
  SystemMonitor распространяется по лицензии MIT. Сторонние компоненты
  сохраняют собственные лицензии.

У разных программ мониторинга отличаются функции и поддерживаемое
оборудование; SystemMonitor может не заменить все специализированные
инструменты.

### Самостоятельная сборка SystemMonitor из репозитория

#### Что потребуется

- Компьютер с 64-разрядной Windows 10 или Windows 11.
- 64-разрядный Python версии 3.10 или новее, Git и подключение к Интернету
  для установки Python-пакетов. Вместо Git можно скачать ZIP-архив
  репозитория.
- В репозитории уже есть закреплённые DLL-зависимости
  LibreHardwareMonitor и исполняемый файл PresentMon. Официальный
  установщик PawnIO.Setup 2.1.0 не хранится в текущей версии Git. Скачайте
  его с [официальной страницы релиза](https://github.com/namazso/PawnIO.Setup/releases/tag/2.1.0)
  и сохраните в корне проекта под именем `PawnIO_setup.exe`.
- Для создания `LhmVisitorAdapter.dll` скрипт `build.bat` также проверяет
  наличие компилятора C# по пути
  `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`.
- Встроенное окно панели использует WebView2 Runtime. Если его нет, панель
  можно открыть в браузере.
- Inno Setup 6 или 7 нужен только для создания установщика. Для сборки EXE
  в папку он не требуется.

#### 1. Получите исходный код

Откройте PowerShell, клонируйте публичный репозиторий и перейдите в его
каталог:

```powershell
git clone https://github.com/rrrwolfrrr/SystemMonitor.git
Set-Location SystemMonitor
```

Если вы скачали ZIP-архив, распакуйте его и откройте PowerShell в папке
проекта.

#### 2. Установите зависимости Python

Создайте отдельное виртуальное окружение и установите зависимости проекта
вместе с PyInstaller:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
```

Если команда `py` недоступна, используйте `python` для создания окружения и
убедитесь, что это 64-разрядный Python версии 3.10 или новее.

#### 3. Запуск из исходного кода (необязательно)

```powershell
.\.venv\Scripts\python.exe main.py
```

Порт веб-сервера по умолчанию — `5000`. На этом же компьютере откройте
`http://127.0.0.1:5000`. Для некоторых показаний оборудования могут
потребоваться права администратора и установленный PawnIO.

#### 4. Запуск тестов (необязательно)

Запустите автоматические тесты:

```powershell
.\autotest.bat
```

Чтобы дополнительно проверить датчики текущего компьютера, выполните:

```powershell
.\autotest.bat --live
```

Проверки оборудования, которого нет на компьютере, будут пропущены.
Комплектность папки после сборки можно проверить командой:

```powershell
.\autotest.bat --build dist\SystemMonitor
```

#### 5. Соберите папку приложения

Скачайте PawnIO.Setup 2.1.0 по официальной ссылке выше, поместите файл в
корень репозитория и назовите его точно `PawnIO_setup.exe`. Затем запустите
из корня проекта:

```powershell
.\build.bat
```

Скрипт проверит Python и PyInstaller, удалит предыдущие результаты сборки,
соберёт C#-адаптер, запустит PyInstaller и проверит результат. Приложение
будет создано здесь:

```text
dist\SystemMonitor\SystemMonitor.exe
```

Это **сборка в папку**. Для запуска или передачи другим людям сохраняйте
всю папку `dist\SystemMonitor`, а не только EXE-файл. Сборка не устанавливает
и не обновляет уже установленную копию SystemMonitor.

#### 6. Создайте установщик (необязательно)

Установите Inno Setup 6 или 7 и сначала соберите папку приложения. Затем
выполните из корня проекта:

```powershell
iscc installer.iss
```

Установщик появится в `installer_output`. Имя файла и версия задаются в
`installer.iss`. Для установки PawnIO, настройки правил брандмауэра и других
административных действий установщик может запросить подтверждение UAC.

Перед распространением собранной программы ознакомьтесь с
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) и соблюдайте лицензии и
уведомления сторонних компонентов.

### Лицензия

Оригинальный код SystemMonitor распространяется по лицензии MIT; см.
[`LICENSE`](LICENSE). Сторонние компоненты сохраняют свои лицензии.
Подробности — в [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
