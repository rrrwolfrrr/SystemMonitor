# SystemMonitor

[English](#english) | [Русский](#русский)

## English

SystemMonitor is a Windows desktop application for monitoring PC hardware and
viewing sensor data in desktop and mobile dashboards. It also provides optional
per-process FPS monitoring through PresentMon and Windows ETW.

### Requirements

- Windows 10/11, 64-bit
- Python and the project dependencies listed in `requirements.txt` to run from
  source
- The pinned runtime DLL dependencies and PresentMon executable used for the
  packaged app. The separate PawnIO setup executable is not included; its
  driver source and license notices are under `third_party/PawnIO/2.1.0`.
  See [BUILD.md](BUILD.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

See [BUILD.md](BUILD.md) for setup, tests, and packaging instructions.

### Project status

This project is hosted in a private GitHub repository. The project license has
not been selected yet. No license to use, modify, or redistribute the
SystemMonitor project is granted until one is added. Third-party components
retain their own licenses; review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistribution.

## Русский

SystemMonitor — настольное приложение для Windows, предназначенное для
мониторинга оборудования компьютера и просмотра данных датчиков на настольной
и мобильной панелях. Также приложение может отслеживать FPS отдельных процессов
с помощью PresentMon и Windows ETW.

### Требования

- Windows 10/11, 64-разрядная версия
- Python и зависимости проекта, перечисленные в `requirements.txt`, для запуска
  из исходного кода
- Закреплённые версии DLL-библиотек и исполняемый файл PresentMon, необходимые
  для готовой сборки. Отдельный установщик PawnIO в репозиторий не включён;
  исходный код драйвера и сведения о лицензиях находятся в
  `third_party/PawnIO/2.1.0`. См. [BUILD.md](BUILD.md) и
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Инструкции по настройке, тестированию и сборке приведены в [BUILD.md](BUILD.md).

### Статус проекта

Проект размещён в приватном репозитории GitHub. Лицензия самого проекта пока не
выбрана. До её добавления права на использование, изменение и распространение
SystemMonitor не предоставляются. Сторонние компоненты сохраняют собственные
лицензии; перед распространением ознакомьтесь с файлом
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
