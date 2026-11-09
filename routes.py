#!/usr/bin/env python3
"""
SystemMonitor — HTTP маршруты Flask.
Регистрирует все маршруты: данные, история, экспорт, логи, темы, пресеты, профили, веб-страницы.
"""

import csv
import http.client
import ipaddress
import io
import json
import os
import time
import traceback
from datetime import datetime, timezone

import qrcode
from qrcode.image.svg import SvgPathImage
from flask import (
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    url_for,
)
from werkzeug.exceptions import HTTPException

from config import Config
from logging_setup import get_log_path
from network_utils import get_local_ip
from storage import (
    get_presets,
    get_profile,
    get_themes,
    save_presets,
    save_profile,
    save_themes,
)
from system_detect import get_all_diagnostics
from diagnostic_snapshot import collect_snapshot, _dll_inventory
from providers import get_provider_registry, get_smart_status

app = None
cache = None
libre = None


def register_routes(
    app_instance,
    cache_instance,
    libre_instance,
    socketio_instance=None,
    fps_monitor_instance=None,
):
    """Регистрирует все маршруты Flask."""
    global app, cache, libre
    app = app_instance
    cache = cache_instance
    libre = libre_instance

    @app.before_request
    def log_request_start():
        g.request_started = time.perf_counter()
        app.logger.debug(
            "HTTP request started: method=%s path=%s remote=%s query=%s",
            request.method,
            request.path,
            request.remote_addr,
            request.query_string.decode("utf-8", errors="replace"),
        )

    @app.after_request
    def log_request_end(response):
        started = getattr(g, "request_started", None)
        duration_ms = (time.perf_counter() - started) * 1000 if started else None
        app.logger.debug(
            "HTTP request finished: method=%s path=%s status=%s duration_ms=%.2f",
            request.method,
            request.path,
            response.status_code,
            duration_ms or 0.0,
        )
        return response

    @app.errorhandler(Exception)
    def log_unhandled_exception(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception(
            "Unhandled HTTP exception: method=%s path=%s",
            request.method,
            request.path,
        )
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

    # --- Данные ---

    @app.route('/stats')
    def stats():
        """Возвращает текущие данные датчиков."""
        try:
            data = cache.get()
            if not data:
                return jsonify({"error": "Данные ещё не собраны"}), 503
            if fps_monitor_instance is not None:
                data["fps"] = fps_monitor_instance.get_status()
            data["smart"] = get_smart_status()
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/fps')
    def fps_stats():
        """Return separate FPS capture data for the selected local process."""
        if fps_monitor_instance is None:
            return jsonify({
                "mode": "auto",
                "target": None,
                "status": "unavailable",
                "error": "Мониторинг FPS не запущен",
                "fps": None,
                "average_fps": None,
                "one_percent_low_fps": None,
                "frame_time_ms": None,
                "sample_count": 0,
            }), 503
        return jsonify(fps_monitor_instance.get_status())

    @app.route('/api/fps/processes')
    def fps_processes():
        """List running processes available for manual FPS tracking."""
        if fps_monitor_instance is None:
            return jsonify({"error": "Мониторинг FPS не запущен"}), 503
        return jsonify({
            "processes": fps_monitor_instance.list_processes(),
            "target": fps_monitor_instance.get_status()["target"],
        })

    @app.route('/api/fps/target', methods=['POST'])
    def fps_set_target():
        """Select foreground tracking or one explicitly chosen process."""
        if fps_monitor_instance is None:
            return jsonify({"error": "Мониторинг FPS не запущен"}), 503
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Ожидался JSON с режимом отслеживания"}), 400
        mode = payload.get("mode")
        try:
            if mode == "auto":
                status = fps_monitor_instance.set_target("auto")
            elif mode == "manual":
                pid = payload.get("pid")
                if isinstance(pid, str) and pid.isdecimal():
                    pid = int(pid)
                if isinstance(pid, bool) or not isinstance(pid, int):
                    return jsonify({"error": "Укажите корректный PID процесса"}), 400
                status = fps_monitor_instance.set_target("manual", pid)
            else:
                return jsonify({"error": "Режим должен быть auto или manual"}), 400
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(status)

    @app.route('/api/remote-stats', methods=['POST'])
    def remote_stats():
        """Fetch sensor data from a configured private IPv4 SystemMonitor host."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Ожидался JSON с адресом и портом"}), 400
        address_text = payload.get("address")
        port = payload.get("port", 5000)
        if not isinstance(address_text, str):
            return jsonify({"error": "Укажите IPv4-адрес удалённого компьютера"}), 400
        try:
            address = ipaddress.ip_address(address_text.strip())
        except ValueError:
            return jsonify({"error": "Разрешены только IPv4-адреса"}), 400
        lan_ranges = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
        if address.version != 4 or not any(address in network for network in lan_ranges):
            return jsonify({"error": "Удалённый адрес должен быть частным IPv4-адресом локальной сети"}), 400
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return jsonify({"error": "Порт должен быть числом от 1 до 65535"}), 400

        connection = http.client.HTTPConnection(str(address), port, timeout=3)
        try:
            connection.request("GET", "/stats")
            response = connection.getresponse()
            if response.status != 200:
                app.logger.warning("Удалённый сервер %s вернул HTTP %s", address, response.status)
                return jsonify({"error": f"Удалённый сервер вернул HTTP {response.status}"}), 502
            raw_data = response.read(1_048_577)
            if len(raw_data) > 1_048_576:
                return jsonify({"error": "Ответ удалённого сервера превышает 1 МБ"}), 502
            data = json.loads(raw_data)
            if not isinstance(data, dict):
                return jsonify({"error": "Удалённый сервер вернул неверный формат данных"}), 502
            return jsonify(data)
        except (OSError, http.client.HTTPException, TimeoutError, json.JSONDecodeError) as exc:
            app.logger.warning("Не удалось получить данные с %s:%s: %s", address, port, exc)
            return jsonify({"error": "Не удалось получить данные с удалённого компьютера"}), 502
        finally:
            connection.close()

    @app.route('/api/mobile-dashboard-qr')
    def mobile_dashboard_qr():
        """Return a QR code and URL for opening the mobile Dashboard on this LAN."""
        try:
            address = ipaddress.ip_address(get_local_ip())
        except ValueError:
            return jsonify({"error": "Не удалось определить IPv4-адрес компьютера"}), 503
        if (
            address.version != 4
            or not address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
        ):
            return jsonify({
                "error": "Не найден частный IPv4-адрес для подключения из локальной сети"
            }), 503

        url = f"http://{address}:{Config.SERVER_PORT}/mobile"
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        output = io.BytesIO()
        image.save(output)
        return jsonify({"url": url, "svg": output.getvalue().decode("utf-8")})

    @app.route('/api/remote-history', methods=['POST'])
    def remote_history():
        """Fetch bounded sensor history from a configured private IPv4 host."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Ожидался JSON с адресом, портом и периодом"}), 400
        address_text = payload.get("address")
        port = payload.get("port", 5000)
        hours = payload.get("hours", 24)
        if not isinstance(address_text, str):
            return jsonify({"error": "Укажите IPv4-адрес удалённого компьютера"}), 400
        try:
            address = ipaddress.ip_address(address_text.strip())
        except ValueError:
            return jsonify({"error": "Разрешены только IPv4-адреса"}), 400
        lan_ranges = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
        if address.version != 4 or not any(address in network for network in lan_ranges):
            return jsonify({"error": "Удалённый адрес должен быть частным IPv4-адресом локальной сети"}), 400
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return jsonify({"error": "Порт должен быть числом от 1 до 65535"}), 400
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 720:
            return jsonify({"error": "Период истории должен быть от 1 до 720 часов"}), 400

        connection = http.client.HTTPConnection(str(address), port, timeout=5)
        try:
            connection.request("GET", "/history-data?hours=" + str(hours))
            response = connection.getresponse()
            if response.status != 200:
                app.logger.warning("История удалённого сервера %s вернула HTTP %s", address, response.status)
                return jsonify({"error": f"Удалённый сервер вернул HTTP {response.status}"}), 502
            raw_data = response.read(1_048_577)
            if len(raw_data) > 1_048_576:
                return jsonify({"error": "Ответ удалённого сервера превышает 1 МБ"}), 502
            data = json.loads(raw_data)
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                return jsonify({"error": "Удалённый сервер вернул неверный формат истории"}), 502
            return jsonify(data)
        except (OSError, http.client.HTTPException, TimeoutError, json.JSONDecodeError) as exc:
            app.logger.warning("Не удалось получить историю с %s:%s: %s", address, port, exc)
            return jsonify({"error": "Не удалось получить историю удалённого компьютера"}), 502
        finally:
            connection.close()

    @app.route('/history')
    def history():
        """Возвращает короткую историю (deque)."""
        try:
            return jsonify(cache.get_history())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/health')
    def health():
        """Проверка состояния сервера."""
        try:
            uptime = time.time() - cache.last_update if cache.last_update else 0
            return jsonify({
                "status": "ok",
                "last_update": cache.last_update,
                "uptime_seconds": round(uptime, 1),
                "libre_running": libre.is_running() if libre else False,
                "data_available": bool(cache.get()),
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route('/diagnostics')
    @app.route('/api/diagnostics')
    def diagnostics():
        """Безопасный отчёт о среде и доступности источников датчиков."""
        try:
            if not getattr(Config, "ENABLE_DIAGNOSTICS", True):
                return jsonify({"status": "disabled", "warnings": []})
            report = get_all_diagnostics()
            report["providers"] = get_provider_registry().availability()
            report["dlls"] = _dll_inventory()
            report["diagnostic_mode"] = bool(request.args.get("verbose")) or \
                os.environ.get("DIAGNOSTIC", "0") == "1"
            return jsonify(report)
        except Exception as e:
            # Диагностика не должна сделать сервер недоступным.
            app.logger.debug("Ошибка диагностики среды: %s", e)
            return jsonify({
                "status": "degraded",
                "warnings": ["Диагностика среды временно недоступна"],
                "error": str(e),
            }), 200

    @app.route('/api/diagnostics/snapshot')
    @app.route('/diagnostics/snapshot')
    def diagnostics_snapshot():
        """Расширенный локальный снимок CPU/GPU/платы/BIOS и драйверов."""
        try:
            if not getattr(Config, "ENABLE_DIAGNOSTICS", True):
                return jsonify({"status": "disabled"})
            return jsonify(collect_snapshot(get_provider_registry(), cache.get()))
        except Exception as e:
            app.logger.debug("Ошибка снимка диагностики: %s", e)
            return jsonify({
                "timestamp": time.time(),
                "status": "degraded",
                "error": type(e).__name__,
                "providers": get_provider_registry().availability(),
            }), 200

    @app.route('/api/sensors/self-test')
    @app.route('/sensors/self-test')
    def sensors_self_test():
        """Проверяет доступность зарегистрированных источников без изменения системы."""
        try:
            if not getattr(Config, "ENABLE_PROVIDER_SELF_TEST", True):
                return jsonify({"status": "disabled", "providers": {}})
            return jsonify({
                "timestamp": time.time(),
                "providers": get_provider_registry().self_test(),
            })
        except Exception as e:
            app.logger.debug("Ошибка self-test провайдеров: %s", e)
            return jsonify({"status": "degraded", "error": type(e).__name__}), 200

    @app.route('/api/sensors')
    def all_sensors_data():
        """Return the complete unfiltered LHM sensor schema."""
        data = cache.get() or {}
        return jsonify({
            "timestamp": data.get("timestamp", time.time()),
            "sensors": data.get("raw_sensors", []),
            "unknown": data.get("unknown_sensors", []),
        })

    # --- Экспорт ---

    @app.route('/export/csv')
    def export_csv():
        """Экспорт текущих данных в CSV."""
        try:
            data = cache.get()
            if not data:
                return "Нет данных", 404

            output = io.StringIO()
            writer = csv.writer(output)

            headers = [
                "Время", "CPU Температура (°C)", "CPU Загрузка (%)", "CPU Частота (МГц)", "CPU Напряжение (В)",
                "GPU Температура (°C)", "GPU Загрузка (%)", "GPU Частота (МГц)", "GPU Напряжение (В)",
                "GPU Память (МБ)", "RAM Использовано (МБ)", "RAM Всего (МБ)", "RAM Загрузка (%)",
                "Сеть Приём (КБ/с)", "Сеть Отдача (КБ/с)", "Время работы (сек)"
            ]
            writer.writerow(headers)

            row = [
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                data.get("cpu", {}).get("temperature", ""),
                data.get("cpu", {}).get("load") or data.get("cpu_percent", ""),
                data.get("cpu", {}).get("frequency") or data.get("cpu_freq_mhz", ""),
                data.get("cpu", {}).get("voltage", ""),
                data.get("gpu", {}).get("temperature", ""),
                data.get("gpu", {}).get("load", ""),
                data.get("gpu", {}).get("frequency", ""),
                data.get("gpu", {}).get("voltage", ""),
                data.get("gpu", {}).get("memory_used", ""),
                data.get("ram_used_mb", ""),
                data.get("ram_total_mb", ""),
                data.get("ram_percent", ""),
                data.get("net_recv_speed_kbps", ""),
                data.get("net_sent_speed_kbps", ""),
                data.get("uptime_seconds", ""),
            ]
            writer.writerow(row)

            disks = data.get("disks", [])
            if disks:
                writer.writerow([])
                writer.writerow(["Диск", "Всего (ГБ)", "Использовано (ГБ)", "Свободно (ГБ)", "Занято (%)"])
                for disk in disks:
                    if disk and isinstance(disk, dict):
                        writer.writerow([
                            disk.get("mount", ""),
                            disk.get("total_gb", ""),
                            disk.get("used_gb", ""),
                            disk.get("free_gb", ""),
                            disk.get("percent", ""),
                        ])

            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=system_stats.csv"}
            )
        except Exception as e:
            return f"Ошибка экспорта: {e}", 500

    @app.route('/sensors')
    def sensors():
        """Алиас для /stats (для совместимости)."""
        return stats()

    @app.route('/export/history-csv')
    def export_history_csv():
        """Экспорт истории за N часов в CSV."""
        try:
            hours = request.args.get('hours', 24, type=int)
            data = cache.get_recent_history(hours)
            if not data:
                return "Нет данных", 404

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Время", "CPU Темп. (°C)", "GPU Темп. (°C)", "CPU Загрузка (%)",
                "CPU Частота (МГц)", "CPU Напряжение (В)", "GPU Загрузка (%)",
                "GPU Частота (МГц)", "RAM Использовано (МБ)", "RAM Всего (МБ)",
                "RAM Загрузка (%)", "Сеть Приём (КБ/с)", "Сеть Отдача (КБ/с)"
            ])

            for entry in data:
                if entry and isinstance(entry, dict):
                    writer.writerow([
                        entry.get("timestamp"),
                        entry.get("cpu_temp"),
                        entry.get("gpu_temp"),
                        entry.get("cpu_load"),
                        entry.get("cpu_freq"),
                        entry.get("cpu_voltage"),
                        entry.get("gpu_load"),
                        entry.get("gpu_freq"),
                        entry.get("ram_used"),
                        entry.get("ram_total"),
                        entry.get("ram_percent"),
                        entry.get("net_recv_speed"),
                        entry.get("net_sent_speed"),
                    ])

            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=history_{hours}h.csv"}
            )
        except Exception as e:
            return f"Ошибка экспорта: {e}", 500

    # --- Логи ---

    @app.route('/api/logs')
    def get_logs():
        """Возвращает последние строки подробного лога с фильтрацией."""
        try:
            lines = request.args.get('lines', 100, type=int)
            lines = min(max(lines, 1), 5000)
            level = request.args.get('level', 'ALL').upper()
            search = request.args.get('search', '').strip().lower()
            log_file = get_log_path(Config.LOG_FILE)
            with open(log_file, 'r', encoding='utf-8', errors='replace') as log_handle:
                selected = []
                for line in log_handle:
                    if level != 'ALL' and f'| {level:<8} |' not in line:
                        continue
                    if search and search not in line.lower():
                        continue
                    selected.append(line)
            return jsonify({
                "logs": "".join(selected[-lines:]),
                "file": log_file,
                "level": level,
                "search": search,
                "available_levels": ["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            })
        except FileNotFoundError:
            return jsonify({"logs": "Лог-файл ещё не создан."}), 404
        except Exception as e:
            return jsonify({"logs": f"Ошибка чтения лога: {e}"}), 500

    @app.route('/api/logs/download')
    def download_logs():
        """Скачивает текущий подробный лог для диагностики."""
        log_file = get_log_path(Config.LOG_FILE)
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as log_handle:
                content = log_handle.read()
            return Response(
                content,
                mimetype='text/plain',
                headers={'Content-Disposition': 'attachment; filename=systemmonitor.log'},
            )
        except FileNotFoundError:
            return Response("Лог-файл ещё не создан.\n", status=404, mimetype='text/plain')

    @app.route('/logs')
    def logs_page():
        """Страница просмотра логов."""
        html = '''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Логи SystemMonitor</title>
<style>
body { font-family: "Segoe UI", sans-serif; background: #101418; color: #e8eef5; padding: 20px; }
h1 { color: #4da3ff; }
.controls { margin-bottom: 15px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
button, select { background: #2d2d2d; color: #e8eef5; border: 1px solid #555; padding: 8px 12px; cursor: pointer; border-radius: 4px; }
button:hover { background: #3d3d3d; }
a { color: #4da3ff; }
#logsContent { background: #1d232b; border: 1px solid #3a4654; border-radius: 8px; padding: 15px; font-family: Consolas, monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 70vh; overflow-y: auto; }
.filter-input { background: #2d2d2d; color: #e8eef5; border: 1px solid #555; padding: 8px 12px; border-radius: 4px; flex: 1; min-width: 200px; }
</style>
</head>
<body>
<h1>📋 Логи SystemMonitor</h1>
<div class="controls">
<button id="refreshBtn">🔄 Обновить</button>
<button id="downloadBtn">⬇ Скачать лог</button>
<select id="linesSelect">
<option value="100">100 строк</option>
<option value="200" selected>200 строк</option>
<option value="500">500 строк</option>
<option value="1000">1000 строк</option>
<option value="5000">5000 строк</option>
</select>
<select id="levelSelect">
<option value="ALL">Все уровни</option>
<option value="DEBUG">DEBUG</option>
<option value="INFO">INFO</option>
<option value="WARNING">WARNING</option>
<option value="ERROR">ERROR</option>
<option value="CRITICAL">CRITICAL</option>
</select>
<input type="text" id="filterInput" class="filter-input" placeholder="🔍 Фильтровать...">
<label><input type="checkbox" id="autoRefresh"> Автообновление (5 сек)</label>
<a href="/dashboard">← Вернуться на дашборд</a>
</div>
<div id="logsContent">Загрузка...</div>
<script>
let autoRefreshTimer = null;
let currentFilter = "";

async function loadLogs() {
    const lines = document.getElementById('linesSelect').value;
    try {
        const level = document.getElementById('levelSelect').value;
        const search = encodeURIComponent(currentFilter);
        const resp = await fetch('/api/logs?lines=' + lines + '&level=' + level + '&search=' + search);
        const data = await resp.json();
        let logs = data.logs || 'Лог пуст.';
        if (currentFilter) {
            logs = logs.split('\\n').filter(line => line.toLowerCase().includes(currentFilter.toLowerCase())).join('\\n');
        }
        document.getElementById('logsContent').textContent = logs;
        const el = document.getElementById('logsContent');
        el.scrollTop = el.scrollHeight;
    } catch (err) {
        document.getElementById('logsContent').textContent = 'Ошибка загрузки: ' + err.message;
    }
}

document.getElementById('refreshBtn').addEventListener('click', loadLogs);
document.getElementById('linesSelect').addEventListener('change', loadLogs);
document.getElementById('levelSelect').addEventListener('change', loadLogs);
document.getElementById('downloadBtn').addEventListener('click', function() {
    window.location.href = '/api/logs/download';
});
document.getElementById('filterInput').addEventListener('input', function() {
    currentFilter = this.value;
    loadLogs();
});
document.getElementById('autoRefresh').addEventListener('change', function() {
    if (this.checked) {
        autoRefreshTimer = setInterval(loadLogs, 5000);
    } else {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
});

loadLogs();
</script>
</body>
</html>'''
        return render_template_string(html)

    # --- Темы и пресеты (серверное хранение) ---

    @app.route('/api/themes', methods=['GET'])
    def api_get_themes():
        try:
            return jsonify({"themes": get_themes()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/themes', methods=['POST'])
    def api_save_themes():
        try:
            data = request.get_json()
            if data and 'themes' in data:
                save_themes(data['themes'])
                return jsonify({"status": "ok"})
            return jsonify({"error": "Неверный формат"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/themes/files', methods=['GET'])
    def api_list_theme_files():
        try:
            theme_directory = os.path.join(app.static_folder or "", "css", "themes")
            if not app.static_folder or not os.path.isdir(theme_directory):
                return jsonify({"error": "Каталог CSS-тем не найден"}), 404
            themes = []
            with os.scandir(theme_directory) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".css"):
                        themes.append({
                            "name": entry.name,
                            "url": url_for("static", filename="css/themes/" + entry.name),
                        })
            themes.sort(key=lambda theme: theme["name"].casefold())
            return jsonify({"themes": themes})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/presets', methods=['GET'])
    def api_get_presets():
        try:
            return jsonify({"presets": get_presets()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/presets', methods=['POST'])
    def api_save_presets():
        try:
            data = request.get_json()
            if data and 'presets' in data:
                save_presets(data['presets'])
                return jsonify({"status": "ok"})
            return jsonify({"error": "Неверный формат"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/profile', methods=['GET'])
    def api_get_profile():
        try:
            return jsonify(get_profile())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/profile', methods=['POST'])
    def api_save_profile():
        try:
            data = request.get_json()
            if data:
                save_profile(data)
                return jsonify({"status": "ok"})
            return jsonify({"error": "Неверный формат"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Веб-страницы ---

    @app.route('/')
    def index():
        return redirect('/dashboard')

    @app.route('/dashboard')
    def dashboard():
        try:
            return render_template('dashboard.html')
        except Exception as e:
            app.logger.error(f"Ошибка в маршруте /dashboard: {e}", exc_info=True)
            return f"Ошибка загрузки дашборда: {e}<br>{traceback.format_exc()}", 500

    @app.route('/all-sensors')
    @app.route('/dashboard/sensors')
    def all_sensors_page():
        try:
            return render_template('all_sensors.html')
        except Exception as e:
            app.logger.error("Ошибка страницы всех сенсоров: %s", e, exc_info=True)
            return f"Ошибка загрузки сенсоров: {e}", 500

    @app.route('/mobile')
    def mobile():
        try:
            return render_template('MobileDashboard.html')
        except Exception as e:
            app.logger.error(f"Ошибка в маршруте /mobile: {e}", exc_info=True)
            return f"Ошибка загрузки мобильной версии: {e}<br>{traceback.format_exc()}", 500

    @app.route('/history-page')
    def history_page():
        try:
            return render_template('history.html')
        except Exception as e:
            app.logger.error(f"Ошибка в маршруте /history-page: {e}", exc_info=True)
            return f"Ошибка загрузки истории: {e}<br>{traceback.format_exc()}", 500

    @app.route('/history-data')
    def history_data():
        try:
            hours = request.args.get('hours', 24, type=int)
            data = cache.get_recent_history(hours)
            return jsonify(data)
        except Exception as e:
            app.logger.error(f"Ошибка в маршруте /history-data: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500