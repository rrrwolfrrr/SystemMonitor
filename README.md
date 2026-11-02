# SystemMonitor

[English](#english) | [Русский](#русский)

## English

SystemMonitor is a Windows desktop application for monitoring PC hardware and
viewing sensor data in desktop and mobile dashboards. It also provides optional
per-process FPS monitoring through PresentMon and Windows ETW.

<p align="center">
  <a href="https://www.donationalerts.com/r/monsterhairy" target="_blank" rel="noopener noreferrer">
    <img src="assets/coffee-donation.gif" width="140" alt="Animated steaming coffee cup - support SystemMonitor">
  </a>
  <br>
  <a href="https://www.donationalerts.com/r/monsterhairy"><strong>Buy the author a coffee</strong></a>
  <br>
  Support the continued development of SystemMonitor.
</p>

### Requirements

- Windows 10/11, 64-bit
- Python and the project dependencies listed in `requirements.txt` to run from
  source
- The pinned runtime DLL dependencies and PresentMon executable used for the
  packaged app. The PawnIO driver is needed for some CPU/MSR/EC sensor
  readings. The official PawnIO 2.1.0 setup executable is included with the
  author's permission for this private repository. Driver source and license
  notices are under `third_party/PawnIO/2.1.0`.
  See [BUILD.md](BUILD.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

See [BUILD.md](BUILD.md) for setup, tests, and packaging instructions.

### Project status

SystemMonitor's original code is licensed under the MIT License; see
[LICENSE](LICENSE). Third-party components retain their own licenses and are
not relicensed by this license. Review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing the
application or its bundled dependencies.

## Русский

SystemMonitor — настольное приложение для Windows, предназначенное для
мониторинга оборудования компьютера и просмотра данных датчиков на настольной
и мобильной панелях. Также приложение может отслеживать FPS отдельных процессов
с помощью PresentMon и Windows ETW.

<p align="center">
  <a href="https://www.donationalerts.com/r/monsterhairy" target="_blank" rel="noopener noreferrer">
    <img src="assets/coffee-donation.gif" width="140" alt="Анимированная чашка кофе с паром — поддержать SystemMonitor">
  </a>
  <br>
  <a href="https://www.donationalerts.com/r/monsterhairy"><strong>Угостить автора кофе</strong></a>
  <br>
  На развитие программы ❤️
</p>

### Требования

- Windows 10/11, 64-разрядная версия
- Python и зависимости проекта, перечисленные в `requirements.txt`, для запуска
  из исходного кода
- Закреплённые версии DLL-библиотек и исполняемый файл PresentMon, необходимые
  для готовой сборки. Драйвер PawnIO нужен для получения некоторых показаний
  датчиков CPU/MSR/EC. Официальный установщик PawnIO 2.1.0 включён с
  разрешения автора для этого приватного репозитория. Исходный код драйвера и
  сведения о лицензиях находятся в `third_party/PawnIO/2.1.0`. См.
  [BUILD.md](BUILD.md) и
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Инструкции по настройке, тестированию и сборке приведены в [BUILD.md](BUILD.md).

### Статус проекта

Оригинальный код SystemMonitor распространяется по лицензии MIT; см.
[LICENSE](LICENSE). Эта лицензия не заменяет лицензии сторонних компонентов.
Перед распространением приложения и включённых зависимостей ознакомьтесь с
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
