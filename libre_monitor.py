#!/usr/bin/env python3
"""
SystemMonitor — интерфейс к LibreHardwareMonitorLib.dll через PythonNet.
DLL-режим: не запускает отдельный процесс, работает напрямую с библиотекой.
"""

import logging
import os
import sys
import threading
from typing import Any, Optional

# ⭐ ДОБАВЛЕНО: модули резервных источников и определения системы
from fallback import apply_fallbacks
from system_detect import log_system_warnings, is_admin, is_memory_integrity_enabled
from validator import validate_reading, validate_sensor_value, validate_sensor_reading, suspicious_jump
from gpu_catalog import GPU_HARDWARE_TYPES, build_gpu_devices
from update_visitor import create_visitor

try:
    import clr
    from System import AppDomain
except ImportError:  # pythonnet is optional for diagnostics/fallback mode
    clr = None
    AppDomain = None

logger = logging.getLogger(__name__)

# ============================================================
# РАЗБЛОКИРОВКА DLL ОТ ЗАГРУЗКИ ИЗ ИНТЕРНЕТА
# ============================================================

def _unblock_dll(dll_path: str):
    """
    Удаляет Alternate Data Stream Zone.Identifier, который Windows
    добавляет к файлам, скачанным из интернета.
    Без этого .NET блокирует загрузку с ошибкой 0x80131515.
    """
    zone_id_path = dll_path + ":Zone.Identifier"
    try:
        if os.path.exists(zone_id_path):
            os.remove(zone_id_path)
            logger.info(f"Разблокирован файл: {dll_path}")
    except PermissionError:
        logger.warning(f"Не удалось разблокировать {dll_path} (файл занят)")
    except Exception as e:
        logger.warning(f"Ошибка разблокировки {dll_path}: {e}")


def _load_libre_assembly():
    """Загружает LibreHardwareMonitorLib.dll с обходом блокировок Windows."""
    dll_dir = os.path.dirname(os.path.abspath(__file__))
    dll_path = os.path.join(dll_dir, "LibreHardwareMonitorLib.dll")
    
    if not os.path.exists(dll_path):
        raise ImportError(f"Файл LibreHardwareMonitorLib.dll не найден в {dll_dir}")
    
    # 1. Разблокируем DLL (убираем Zone.Identifier)
    _unblock_dll(dll_path)
    
    # 2. Разрешаем загрузку из удалённых источников
    try:
        AppDomain.CurrentDomain.SetData("LOAD_FROM_REMOTE_SOURCES", True)
    except Exception:
        pass
    
    # 3. Добавляем папку в sys.path
    if dll_dir not in sys.path:
        sys.path.insert(0, dll_dir)
    
    # 4. Пробуем разные способы загрузки
    try:
        # Способ 1: по имени сборки (самый надёжный)
        clr.AddReference("LibreHardwareMonitorLib")
        logger.info("LibreHardwareMonitorLib загружена по имени")
    except Exception as e1:
        try:
            # Способ 2: по полному пути
            clr.AddReference(dll_path)
            logger.info("LibreHardwareMonitorLib загружена по пути")
        except Exception as e2:
            try:
                # Способ 3: через Assembly.LoadFrom
                from System.Reflection import Assembly
                assembly = Assembly.LoadFrom(dll_path)
                clr.AddReference(assembly)
                logger.info("LibreHardwareMonitorLib загружена через Assembly.LoadFrom")
            except Exception as e3:
                raise ImportError(
                    f"Не удалось загрузить LibreHardwareMonitorLib.dll ни одним способом:\n"
                    f"  Способ 1 (по имени): {e1}\n"
                    f"  Способ 2 (по пути): {e2}\n"
                    f"  Способ 3 (Assembly): {e3}\n\n"
                    f"Возможные причины:\n"
                    f"  1. Файл заблокирован Windows (правый клик → Свойства → Разблокировать)\n"
                    f"  2. Разрядность Python не совпадает с DLL (нужен 64-bit Python)\n"
                    f"  3. DLL повреждена или неполная"
                )


LHM_VISITOR_RUNNER = None
def _load_visitor_adapter():
    """Load the native .NET visitor bridge when it is bundled."""
    global LHM_VISITOR_RUNNER
    if clr is None:
        logger.warning("Нативный visitor-адаптер не загружен: pythonnet недоступен")
        return
    adapter_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "LhmVisitorAdapter.dll",
    )
    logger.info("Проверка нативного visitor-адаптера: %s", adapter_path)
    if not os.path.exists(adapter_path):
        logger.warning("Нативный visitor-адаптер не найден: %s", adapter_path)
        return
    try:
        clr.AddReference(adapter_path)
        from System.Reflection import Assembly
        assembly = Assembly.LoadFrom(adapter_path)
        runner_type = assembly.GetType("LhmVisitorRunner")
        LHM_VISITOR_RUNNER = runner_type.GetMethod("Update")
        logger.info("Нативный .NET visitor-адаптер загружен: %s", adapter_path)
    except Exception as exc:
        logger.warning("Не удалось загрузить visitor-адаптер: %s", exc)

# Загружаем сборку только когда pythonnet действительно установлен.  Это
# позволяет импортировать сервер и его fallback-провайдеры без SDK/компилятора.
LHM_AVAILABLE = False
if clr is not None:
    try:
        _load_libre_assembly()
        _load_visitor_adapter()
        try:
            from LibreHardwareMonitor.Hardware import Computer, HardwareType, SensorType, IVisitor
        except ImportError:
            from LibreHardwareMonitorLib import Computer, HardwareType, SensorType, IVisitor
        LHM_AVAILABLE = True
    except Exception as exc:
        logger.warning("LibreHardwareMonitor DLL недоступна: %s", exc)
        Computer = HardwareType = SensorType = None
        IVisitor = object
else:
    Computer = HardwareType = SensorType = None
    IVisitor = object

# Флаг диагностики — включает подробное логирование всех датчиков
# Включается через переменную окружения: set DIAGNOSTIC=1
DIAGNOSTIC_MODE = os.environ.get("DIAGNOSTIC", "0") == "1"


class _UpdateVisitor(IVisitor):
    """Официальный обход LibreHardwareMonitor через IVisitor/Accept."""

    def VisitComputer(self, computer):
        traverse = getattr(computer, "Traverse", None)
        if callable(traverse):
            traverse(self)
        else:
            for hardware in getattr(computer, "Hardware", ()) or ():
                self.VisitHardware(hardware)

    def VisitHardware(self, hardware):
        hardware.Update()
        for child in getattr(hardware, "SubHardware", ()) or ():
            self.VisitHardware(child)

    def VisitSensor(self, sensor):
        return None

    def VisitParameter(self, parameter):
        return None


class LibreMonitorDirect:
    """Прямой интерфейс к LibreHardwareMonitorLib.dll."""

    def __init__(self):
        self._computer = None
        self._initialized = False
        self._lock = threading.Lock()
        self._diagnostic_done = False
        self._visitor_failed = False
        self._update_mode_logged = False
        self._value_summary_logged = False

    def _ensure_initialized(self):
        """Инициализирует Computer и открывает доступ к датчикам."""
        with self._lock:
            if self._initialized:
                return
            
            # ⭐ ДОБАВЛЕНО: логируем системные предупреждения (один раз)
            if not hasattr(self, '_env_checked'):
                log_system_warnings()
                self._env_checked = True
            
            try:
                self._computer = Computer()
                
                # Включаем ВСЕ типы оборудования
                self._computer.IsCpuEnabled = True
                self._computer.IsGpuEnabled = True
                self._computer.IsMemoryEnabled = True
                self._computer.IsMotherboardEnabled = True
                self._computer.IsStorageEnabled = True
                self._computer.IsNetworkEnabled = True
                
                # Вентиляторы (контроллер) — пробуем оба варианта имени
                try:
                    self._computer.IsControllerEnabled = True
                except Exception:
                    pass
                try:
                    self._computer.IsFanControllerEnabled = True
                except Exception:
                    pass
                
                # Блок питания и батарея
                try:
                    self._computer.IsPsuEnabled = True
                except Exception:
                    pass
                try:
                    self._computer.IsPowerMonitorEnabled = True
                except Exception:
                    logger.debug("IsPowerMonitorEnabled отсутствует в текущей версии DLL")
                try:
                    self._computer.IsBatteryEnabled = True
                except Exception:
                    pass
                
                # Открываем доступ к датчикам
                self._computer.Open()
                
                # ⭐ ВАЖНО: ждём инициализацию драйвера и SuperIO-чипов
                # Это нужно, чтобы материнская плата и вентиляторы успели "проснуться"
                import time
                time.sleep(2)
                
                self._initialized = True
                logger.info("LibreHardwareMonitor инициализирован успешно.")
                
            except Exception as e:
                logger.error(f"Ошибка инициализации LibreHardwareMonitor: {e}")
                raise

    def _run_diagnostics(self):
        """
        ДИАГНОСТИКА: выводит в лог все найденные датчики.
        Выполняется один раз при первом запросе данных.
        """
        if self._diagnostic_done:
            return
        self._diagnostic_done = True
        
        logger.info("=" * 70)
        logger.info("ДИАГНОСТИКА ОБОРУДОВАНИЯ (однократно при старте)")
        logger.info("=" * 70)
        
        try:
            for hw in self._computer.Hardware:
                self._log_hardware(hw, indent=0)
        except Exception as e:
            logger.error(f"Ошибка диагностики: {e}")
        
        logger.info("=" * 70)
        logger.info("КОНЕЦ ДИАГНОСТИКИ")
        logger.info("=" * 70)
        
        if not DIAGNOSTIC_MODE:
            logger.info(
                "Для расширенной диагностики установите переменную окружения "
                "DIAGNOSTIC=1 и перезапустите сервер"
            )

    def _log_hardware(self, hw, indent: int = 0):
        """Рекурсивно логирует оборудование и его датчики."""
        prefix = "  " * indent
        try:
            hw_type = str(hw.HardwareType)
            hw_name = str(hw.Name)
            sensors = list(hw.Sensors)
            
            logger.info(f"{prefix}Оборудование: тип={hw_type}, имя={hw_name}, сенсоров={len(sensors)}")
            
            # В расширенном режиме выводим каждый датчик
            if DIAGNOSTIC_MODE:
                for s in sensors:
                    try:
                        stype = str(s.SensorType)
                        sname = str(s.Name)
                        sval = s.Value
                        logger.info(f"{prefix}  Датчик: тип={stype}, имя={sname}, значение={sval}")
                    except Exception:
                        pass
            
            # Рекурсивно обходим вложенные устройства
            for sub in hw.SubHardware:
                self._log_hardware(sub, indent + 1)
        except Exception:
            pass

    def _update_recursive(self, hardware):
        """Рекурсивно обновляет hardware и все его SubHardware."""
        try:
            hardware.Update()
        except Exception as e:
            logger.debug(f"Ошибка обновления {hardware.Name}: {e}")
        for child in hardware.SubHardware:
            self._update_recursive(child)

    def _update_all(self):
        """Обновляет всё дерево официальным visitor-механизмом."""
        if LHM_VISITOR_RUNNER is not None:
            try:
                LHM_VISITOR_RUNNER.Invoke(None, [self._computer])
                if not self._update_mode_logged:
                    logger.info("Обновление LHM: нативный .NET UpdateVisitor")
                    self._update_mode_logged = True
                return
            except Exception as exc:
                logger.warning(
                    "Нативный UpdateVisitor не сработал, используется fallback: %s",
                    exc,
                )
        if self._visitor_failed:
            for hardware in self._computer.Hardware:
                self._update_recursive(hardware)
            if not self._update_mode_logged:
                logger.info("Обновление LHM: Python recursive fallback")
                self._update_mode_logged = True
            return
        try:
            self._computer.Accept(create_visitor(IVisitor))
            return
        except Exception as exc:
            self._visitor_failed = True
            logger.warning(
                "UpdateVisitor недоступен в PythonNet, используется полный совместимый обход: %s",
                exc,
            )
        for hardware in self._computer.Hardware:
            self._update_recursive(hardware)

    @staticmethod
    def _identifier(sensor):
        try:
            return str(sensor.Identifier)
        except (AttributeError, TypeError):
            return None

    @staticmethod
    def _hardware_type(hw):
        try:
            return str(hw.HardwareType)
        except (AttributeError, TypeError):
            return "unknown"

    @staticmethod
    def _hardware_identifier(hw):
        try:
            identifier = str(hw.Identifier)
            return identifier or None
        except (AttributeError, TypeError):
            return None

    def _get_val(self, sensor) -> Optional[float]:
        """Безопасно получает значение сенсора как float."""
        try:
            return validate_sensor_value(sensor.Value)
        except (TypeError, AttributeError):
            return None

    @staticmethod
    def _validated(field: str, value):
        """Применяет общее правило к значению конкретного поля."""
        checked = validate_reading(field, value)
        return checked.value if checked.valid else None

    def _parse_cpu(self, hw, result):
        """Парсит датчики CPU по HardwareType."""
        try:
            hw_type = str(hw.HardwareType)
        except Exception:
            return

        if hw_type == "Cpu":
            core_clocks = []
            core_loads = []
            clocks = []

            for sensor in hw.Sensors:
                try:
                    stype = str(sensor.SensorType)
                    name = str(sensor.Name)
                    val = self._get_val(sensor)
                    if val is None:
                        continue

                    # Температура CPU — берём максимум или пакетную
                    if stype == "Temperature":
                        val = self._validated("cpu.temperature", val)
                        if val is None:
                            continue
                        # Температуры отдельных ядер
                        if "Core" in name and "Tctl" not in name and "Tdie" not in name and "Max" not in name:
                            result["cpu"]["core_temps"].append({
                                "name": name,
                                "value": round(val, 1),
                                "identifier": self._identifier(sensor),
                            })
                        
                        # Общая температура — ищем по разным вариантам
                        if any(x in name for x in ["Tctl", "Tdie", "Package", "Core Max", "Core Average", "CPU Package"]):
                            if result["cpu"]["temperature"] is None or val > result["cpu"]["temperature"]:
                                result["cpu"]["temperature"] = round(val, 1)

                    # Напряжение CPU
                    elif stype == "Voltage":
                        val = self._validated("cpu.voltage", val)
                        if val is None:
                            continue
                        if any(x in name for x in ["Core", "Vcore", "CPU"]):
                            if result["cpu"]["voltage"] is None or val > result["cpu"]["voltage"]:
                                result["cpu"]["voltage"] = round(val, 3)

                    # Мощность CPU
                    elif stype == "Power":
                        val = self._validated("cpu.power", val)
                        if val is None:
                            continue
                        if any(x in name for x in ["Package", "CPU", "Cores"]):
                            if result["cpu"]["power"] is None or val > result["cpu"]["power"]:
                                result["cpu"]["power"] = round(val, 1)

                    # Частота CPU
                    elif stype == "Clock":
                        val = self._validated("cpu.frequency", val)
                        if val is None:
                            continue
                        clocks.append((name, val))
                        if "Core" in name and "Bus" not in name:
                            core_clocks.append(val)

                    # Загрузка CPU
                    elif stype == "Load":
                        val = self._validated("cpu.load", val)
                        if val is None:
                            continue
                        if "Total" in name or "CPU Total" in name:
                            if result["cpu"]["load"] is None or val > result["cpu"]["load"]:
                                result["cpu"]["load"] = round(val, 1)
                        elif "Core" in name:
                            core_loads.append(val)

                except Exception as e:
                    logger.debug(f"Ошибка парсинга CPU сенсора: {e}")

            # Частота фактическая и эффективная
            if clocks:
                # Фактическая: ищем "Cores (Average)" без "Effective"
                for name, val in clocks:
                    if "Cores (Average)" in name and "Effective" not in name:
                        result["cpu"]["frequency"] = round(val, 1)
                        break
                
                # Эффективная: ищем "Effective"
                for name, val in clocks:
                    if "Effective" in name:
                        result["cpu"]["frequency_effective"] = round(val, 1)
                        break
                
                # Fallback: среднее по ядрам
                if result["cpu"]["frequency"] is None and core_clocks:
                    result["cpu"]["frequency"] = round(sum(core_clocks) / len(core_clocks), 1)
                elif result["cpu"]["frequency"] is None and clocks:
                    # Берём первое найденное значение частоты
                    result["cpu"]["frequency"] = round(clocks[0][1], 1)
                
                # ⭐ FALLBACK ДЛЯ СТАРЫХ ПРОЦЕССОРОВ (Intel Haswell и др.)
                # Если нет датчика "Effective" — используем фактическую частоту
                # На старых CPU они будут одинаковы (процессор не спит в C-states)
                if result["cpu"]["frequency_effective"] is None and result["cpu"]["frequency"] is not None:
                    result["cpu"]["frequency_effective"] = result["cpu"]["frequency"]

            # Средняя загрузка по ядрам, если нет Total
            if result["cpu"]["load"] is None and core_loads:
                result["cpu"]["load"] = round(sum(core_loads) / len(core_loads), 1)

        # Рекурсивно обходим SubHardware
        for child in hw.SubHardware:
            self._parse_cpu(child, result)

    def _parse_gpu(self, hw, result):
        """Парсит датчики GPU по HardwareType."""
        try:
            hw_type = str(hw.HardwareType)
        except Exception:
            return

        if hw_type in ("GpuNvidia", "GpuAmd", "GpuIntel"):
            for sensor in hw.Sensors:
                try:
                    stype = str(sensor.SensorType)
                    name = str(sensor.Name)
                    val = self._get_val(sensor)
                    if val is None:
                        continue

                    if stype == "Temperature":
                        is_hotspot = any(
                            marker in name.lower()
                            for marker in ("hotspot", "hot spot", "junction")
                        )
                        field = "gpu.hotspot_temperature" if is_hotspot else "gpu.temperature"
                        val = self._validated(field, val)
                        if val is None:
                            continue
                        target = "hotspot_temperature" if is_hotspot else "temperature"
                        if result["gpu"][target] is None or val > result["gpu"][target]:
                            result["gpu"][target] = round(val, 1)

                    elif stype == "Voltage":
                        val = self._validated("gpu.voltage", val)
                        if val is None:
                            continue
                        if result["gpu"]["voltage"] is None or val > result["gpu"]["voltage"]:
                            result["gpu"]["voltage"] = round(val, 3)

                    elif stype == "Power":
                        val = self._validated("gpu.power", val)
                        if val is None:
                            continue
                        if result["gpu"]["power"] is None or val > result["gpu"]["power"]:
                            result["gpu"]["power"] = round(val, 1)

                    elif stype == "Clock":
                        val = self._validated("gpu.frequency", val)
                        if val is None:
                            continue
                        if "Core" in name or "GPU" in name:
                            if result["gpu"]["frequency"] is None or val > result["gpu"]["frequency"]:
                                result["gpu"]["frequency"] = round(val, 1)

                    elif stype == "Load":
                        val = self._validated("gpu.load", val)
                        if val is None:
                            continue
                        if result["gpu"]["load"] is None or val > result["gpu"]["load"]:
                            result["gpu"]["load"] = round(val, 1)

                    elif stype in ("SmallData", "Data"):
                        name_lower = name.lower()
                        if "used" in name_lower:
                            val = self._validated("gpu.memory_used", val)
                            if val is None:
                                continue
                            result["gpu"]["memory_used"] = round(val, 1)
                        elif "total" in name_lower or "dedicated" in name_lower:
                            val = self._validated("gpu.memory_total", val)
                            if val is None:
                                continue
                            result["gpu"]["memory_total"] = round(val, 1)

                except Exception as e:
                    logger.debug(f"Ошибка парсинга GPU сенсора: {e}")

        for child in hw.SubHardware:
            self._parse_gpu(child, result)

    def _parse_ram(self, hw, result):
        """Парсит датчики оперативной памяти."""
        try:
            hw_type = str(hw.HardwareType)
        except Exception:
            return

        if hw_type == "Memory":
            for sensor in hw.Sensors:
                try:
                    stype = str(sensor.SensorType)
                    name = str(sensor.Name)
                    val = self._get_val(sensor)
                    if val is None:
                        continue

                    name_lower = name.lower()
                    
                    if stype == "Data":
                        if "used" in name_lower:
                            result["ram"]["used"] = round(val, 1)
                        elif "total" in name_lower or "available" in name_lower:
                            result["ram"]["total"] = round(val, 1)
                    
                    elif stype == "Clock":
                        if result["ram"]["speed"] is None:
                            result["ram"]["speed"] = round(val, 0)
                    
                    elif stype == "Voltage":
                        if result["ram"]["voltage"] is None:
                            result["ram"]["voltage"] = round(val, 3)

                except Exception as e:
                    logger.debug(f"Ошибка парсинга RAM сенсора: {e}")

        for child in hw.SubHardware:
            self._parse_ram(child, result)

    def _parse_motherboard(self, hw, result):
        """Парсит датчики материнской платы."""
        try:
            hw_type = str(hw.HardwareType)
        except Exception:
            return

        if hw_type in ("Motherboard", "SuperIO"):
            for sensor in hw.Sensors:
                try:
                    stype = str(sensor.SensorType)
                    name = str(sensor.Name)
                    val = self._get_val(sensor)
                    if val is None:
                        continue

                    if stype == "Temperature":
                        result["motherboard"]["temperature"].append({
                            "name": name,
                            "value": round(val, 1),
                            "hardware": str(hw.Name),
                            "identifier": self._identifier(sensor),
                        })
                    elif stype == "Voltage":
                        result["motherboard"]["voltage"].append({
                            "name": name,
                            "value": round(val, 3),
                            "hardware": str(hw.Name),
                            "identifier": self._identifier(sensor),
                        })
                except Exception as e:
                    logger.debug(f"Ошибка парсинга motherboard сенсора: {e}")

        for child in hw.SubHardware:
            self._parse_motherboard(child, result)

    def _parse_storage(self, hw, result):
        """Парсит датчики накопителей."""
        try:
            hw_type = str(hw.HardwareType)
        except Exception:
            return

        if hw_type == "Storage":
            hw_name = str(hw.Name)
            disk = {
                "name": hw_name,
                "temp": None,
                "temp_sensor": None,
                "hardware_type": hw_type,
                "device_id": self._hardware_identifier(hw),
                "identifier": None,
                "status": "temporary_unavailable",
            }
            temperature_sensors = []
            for sensor in hw.Sensors:
                try:
                    stype = str(sensor.SensorType)
                    if stype != "Temperature":
                        continue
                    sensor_name = str(sensor.Name)
                    val = self._get_val(sensor)
                    if val is None:
                        continue
                    val = self._validated("storage.temperature", val)
                    if val is None:
                        continue
                    normalized_name = sensor_name.casefold()
                    is_limit = any(
                        marker in normalized_name
                        for marker in ("warning", "critical", "threshold", "limit")
                    )
                    temperature_sensors.append((
                        "composite" in normalized_name and not is_limit,
                        not is_limit,
                        sensor_name,
                        val,
                        self._identifier(sensor),
                    ))
                except Exception as e:
                    logger.debug(f"Ошибка парсинга storage сенсора: {e}")
            current_sensors = [
                sensor for sensor in temperature_sensors if sensor[1]
            ]
            if current_sensors:
                selected = next(
                    (sensor for sensor in current_sensors if sensor[0]),
                    current_sensors[0],
                )
                disk.update({
                    "temp": round(selected[3], 1),
                    "temp_sensor": selected[2],
                    "identifier": selected[4],
                    "status": "valid",
                })
            # Keep the disk visible when its temperature sensor is absent.
            result["storage"].append(disk)

        for child in hw.SubHardware:
            self._parse_storage(child, result)

    def _collect_fans(self, hw, fans_list):
        """Собирает вентиляторы со всего оборудования."""
        for sensor in hw.Sensors:
            if sensor.Value is None:
                continue
            try:
                if str(sensor.SensorType) == "Fan":
                    fans_list.append({
                        "hardware": str(hw.Name),
                        "name": str(sensor.Name),
                        "identifier": self._identifier(sensor),
                        "rpm": round(float(sensor.Value))
                    })
            except Exception:
                pass
        for child in hw.SubHardware:
            self._collect_fans(child, fans_list)

    def _collect_other(
        self, hw, other_list, parent_name=None, gpu_identifier=None,
        gpu_name=None, gpu_hardware_type=None,
    ):
        """Собирает все остальные сенсоры для карточки Прочие."""
        hardware_name = str(hw.Name)
        hardware_type = self._hardware_type(hw)
        path = f"{parent_name} / {hardware_name}" if parent_name else hardware_name
        if hardware_type in GPU_HARDWARE_TYPES:
            gpu_identifier = (
                self._hardware_identifier(hw)
                or gpu_identifier
                or f"{hardware_type}:{path.replace(' / ', '/')}"
            )
            gpu_name = hardware_name
            gpu_hardware_type = hardware_type
        for sensor in hw.Sensors:
            try:
                stype = str(sensor.SensorType)
                if stype == "Fan":
                    continue
                raw_value = sensor.Value
                if raw_value is None:
                    logger.debug(
                        "Сенсор без значения: hardware=%s type=%s name=%s identifier=%s",
                        path, stype, sensor.Name, self._identifier(sensor),
                    )
                    continue
                other_list.append({
                    "hardware": hardware_name,
                    "hardware_path": path,
                    "hardware_type": hardware_type,
                    "name": str(sensor.Name),
                    "type": stype,
                    "value": round(float(raw_value), 2),
                    "unit": self._unit(stype),
                    "identifier": self._identifier(sensor),
                    "gpu_identifier": gpu_identifier,
                    "gpu_name": gpu_name,
                    "gpu_hardware_type": gpu_hardware_type,
                })
            except (TypeError, ValueError, AttributeError) as exc:
                logger.debug(
                    "Сенсор пропущен: hardware=%s name=%s reason=%s",
                    path, getattr(sensor, "Name", "unknown"), exc,
                )
        for child in hw.SubHardware:
            self._collect_other(
                child, other_list, path, gpu_identifier, gpu_name,
                gpu_hardware_type,
            )

    def _collect_raw(
        self, hw, raw_list, parent_name=None, gpu_identifier=None,
        gpu_name=None, gpu_hardware_type=None,
    ):
        """Collect every LHM sensor without filtering unknown types/values."""
        hardware = str(getattr(hw, "Name", "") or "unknown")
        hardware_type = str(getattr(hw, "HardwareType", "") or "unknown")
        path = f"{parent_name}/{hardware}" if parent_name else hardware
        if hardware_type in GPU_HARDWARE_TYPES:
            gpu_identifier = (
                self._hardware_identifier(hw)
                or gpu_identifier
                or f"{hardware_type}:{path}"
            )
            gpu_name = hardware
            gpu_hardware_type = hardware_type
        for sensor in getattr(hw, "Sensors", ()) or ():
            try:
                sensor_type = str(getattr(sensor, "SensorType", "") or "unknown")
                name = str(getattr(sensor, "Name", "") or "unknown")
                raw_value = getattr(sensor, "Value", None)
                try:
                    value = None if raw_value is None else float(raw_value)
                except (TypeError, ValueError):
                    value = None
                unit = self._unit(sensor_type) or "unknown"
                identifier = self._identifier(sensor)
                checked = validate_sensor_reading(
                    value, sensor_type, unit, hardware, name,
                    field=f"{hardware_type.lower()}.{sensor_type.lower()}",
                )
                previous = next(
                    (item["value"] for item in reversed(raw_list)
                     if item["identifier"] == identifier and identifier),
                    None,
                )
                jump = suspicious_jump(previous, value, sensor_type)
                raw_list.append({
                    "hardware": hardware,
                    "hardware_type": hardware_type,
                    "subhardware": path if parent_name else None,
                    "type": sensor_type,
                    "name": name,
                    "value": value,
                    "raw_value": None if raw_value is None else str(raw_value),
                    "unit": unit,
                    "identifier": identifier,
                    "gpu_identifier": gpu_identifier,
                    "gpu_name": gpu_name,
                    "gpu_hardware_type": gpu_hardware_type,
                    "valid": bool(checked.valid),
                    "reason": checked.reason,
                    "suspicious": bool(jump),
                    "suspicious_reason": jump,
                })
            except Exception as exc:
                # Preserve an opaque sensor rather than silently dropping it.
                raw_list.append({
                    "hardware": hardware,
                    "hardware_type": hardware_type,
                    "subhardware": path if parent_name else None,
                    "type": "unknown",
                    "name": "unknown",
                    "value": None,
                    "unit": "unknown",
                    "identifier": None,
                    "gpu_identifier": gpu_identifier,
                    "gpu_name": gpu_name,
                    "gpu_hardware_type": gpu_hardware_type,
                    "valid": False,
                    "reason": type(exc).__name__,
                    "suspicious": False,
                })
        for child in getattr(hw, "SubHardware", ()) or ():
            self._collect_raw(
                child, raw_list, path, gpu_identifier, gpu_name,
                gpu_hardware_type,
            )

    def _unit(self, stype: str) -> str:
        """Возвращает единицу измерения для типа сенсора."""
        units = {
            "Temperature": "°C",
            "Voltage": "V",
            "Power": "W",
            "Clock": "MHz",
            "Load": "%",
            "Fan": "RPM",
            "Data": "MB",
            "SmallData": "MB",
            "Throughput": "KB/s",
            "Level": "%",
            "Current": "A",
            "Frequency": "MHz",
            "Control": "%",
            "Energy": "mWh",
            "TimeSpan": "s",
        }
        return units.get(stype, "")

    def fetch_data(self) -> Optional[dict[str, Any]]:
        """Собирает данные со всех датчиков."""
        self._ensure_initialized()
        try:
            # Запускаем диагностику при первом запросе
            self._run_diagnostics()
            
            # Используем тот же обход, что и официальный пример LHM.
            self._update_all()
            if not self._value_summary_logged:
                all_sensors = []
                for hardware in self._computer.Hardware:
                    self._collect_sensor_objects(hardware, all_sensors)
                readable = sum(
                    1 for sensor in all_sensors
                    if getattr(sensor, "Value", None) is not None
                )
                logger.info(
                    "Результат обновления LHM: сенсоров=%d, со значением=%d, "
                    "без значения=%d",
                    len(all_sensors), readable, len(all_sensors) - readable,
                )
                self._value_summary_logged = True

            result = {
                "cpu": {"temperature": None, "voltage": None, "power": None,
                        "frequency": None, "frequency_effective": None, "load": None, "core_temps": []},
                "gpu": {"temperature": None, "voltage": None, "power": None,
                        "frequency": None, "load": None,
                        "memory_used": None, "memory_total": None,
                        "hotspot_temperature": None},
                "ram": {"used": None, "total": None, "speed": None, "voltage": None},
                "motherboard": {"temperature": [], "voltage": []},
                "storage": [],
                "fans": [],
                "other": [],
                "raw_sensors": [],
                "gpu_devices": [],
                "unknown_sensors": [],
            }

            for hardware_index, hw in enumerate(self._computer.Hardware):
                self._parse_cpu(hw, result)
                self._parse_gpu(hw, result)
                self._parse_ram(hw, result)
                self._parse_motherboard(hw, result)
                self._parse_storage(hw, result)
                self._collect_fans(hw, result["fans"])
                gpu_identifier = None
                gpu_hardware_type = self._hardware_type(hw)
                if gpu_hardware_type in GPU_HARDWARE_TYPES:
                    gpu_identifier = (
                        self._hardware_identifier(hw)
                        or f"{gpu_hardware_type}:{hardware_index}:{hw.Name}"
                    )
                self._collect_other(hw, result["other"], gpu_identifier=gpu_identifier)
                self._collect_raw(hw, result["raw_sensors"], gpu_identifier=gpu_identifier)

            result["gpu_devices"] = build_gpu_devices(result["raw_sensors"])
            result["unknown_sensors"] = [
                sensor for sensor in result["raw_sensors"]
                if sensor.get("type") == "unknown"
                or sensor.get("unit") == "unknown"
                or sensor.get("reason") in {"not_numeric", "missing"}
            ]

            # ⭐ ДОБАВЛЕНО: применяем резервные источники
            try:
                result = apply_fallbacks(result)
            except Exception as e:
                logger.debug(f"Ошибка применения резервных источников: {e}")

            return result
        except Exception as e:
            logger.error(f"Ошибка сбора данных: {e}")
            return None

    @staticmethod
    def _collect_sensor_objects(hw, result):
        """Collect managed sensor objects for one diagnostic count."""
        result.extend(list(getattr(hw, "Sensors", ()) or ()))
        for child in getattr(hw, "SubHardware", ()) or ():
            LibreMonitorDirect._collect_sensor_objects(child, result)

    def close(self):
        """Закрывает доступ к датчикам."""
        with self._lock:
            if self._computer:
                try:
                    self._computer.Close()
                except Exception:
                    pass
                self._computer = None
                self._initialized = False
                logger.info("LibreHardwareMonitor закрыт.")


class LibreMonitor:
    """Обёртка над LibreMonitorDirect для использования в server_core.py."""

    def __init__(self, dll_path=None):
        self._direct = None
        self._initialized = False
        self._lock = threading.Lock()

    def start(self) -> bool:
        """Инициализирует и запускает LibreHardwareMonitor."""
        with self._lock:
            if self._initialized:
                return True
            try:
                self._direct = LibreMonitorDirect()
                self._direct._ensure_initialized()
                self._initialized = True
                logger.info("LibreHardwareMonitor (dll) запущен.")
                return True
            except Exception as e:
                logger.error(f"Ошибка запуска Libre (DLL): {e}")
                return False

    def is_running(self) -> bool:
        """Возвращает True, если LibreHardwareMonitor инициализирован."""
        return self._initialized

    def fetch_data(self):
        """Собирает данные со всех датчиков."""
        if not self._initialized and not self.start():
            return None
        try:
            return self._direct.fetch_data()
        except Exception as e:
            logger.error(f"Ошибка получения данных через .dll: {e}")
            return None

    def restart(self) -> bool:
        """Перезапускает LibreHardwareMonitor."""
        self.close()
        return self.start()

    def close(self):
        """Закрывает LibreHardwareMonitor."""
        with self._lock:
            if self._direct:
                self._direct.close()
                self._direct = None
                self._initialized = False
                logger.info("Libre (DLL) закрыт.")

    def kill_existing_process(self):
        """В DLL-режиме нет отдельного процесса."""

    def ensure_running(self) -> bool:
        """Убеждается, что LibreHardwareMonitor запущен."""
        return self.start() if not self.is_running() else True

    def cleanup(self):
        """Очищает ресурсы."""
        self.close()
