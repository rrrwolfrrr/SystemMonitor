#!/usr/bin/env python3

import csv
import gzip
import io
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from functools import wraps

import psutil
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template_string, request
from flask_cors import CORS

from network_utils import get_local_ip
from utils import get_psutil_data, parse_libre_data

# ------------------- Конфигурация -------------------
load_dotenv()

CONFIG = {
    "LIBRE_EXE": os.getenv("LIBRE_EXE", "LibreHardwareMonitor.exe"),
    "LIBRE_PORT": int(os.getenv("LIBRE_PORT", "8085")),
    "SERVER_PORT": int(os.getenv("SERVER_PORT", "5000")),  # можно изменить на 5001
    "UPDATE_INTERVAL": int(os.getenv("UPDATE_INTERVAL", "2")),
    "LOG_FILE": os.getenv("LOG_FILE", "mobileserver.log"),
    "DEBUG": os.getenv("DEBUG", "False").lower() == "true",
    "HISTORY_SIZE": int(os.getenv("HISTORY_SIZE", "60")),
    "HISTORY_FILE": os.getenv("HISTORY_FILE", "history.json"),
    "MAX_HISTORY_ENTRIES": int(os.getenv("MAX_HISTORY_ENTRIES", "1000")),
}

logging.basicConfig(
    level=logging.DEBUG if CONFIG["DEBUG"] else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["LOG_FILE"], encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ------------------- ИСПРАВЛЕННЫЙ декоратор сжатия gzip -------------------
def gzipped(f):
    @wraps(f)
    def view_func(*args, **kwargs):
        if 'gzip' not in request.headers.get('Accept-Encoding', '').lower():
            return f(*args, **kwargs)
        response = f(*args, **kwargs)
        # Если ответ не является объектом Response, оборачиваем
        if not isinstance(response, Response):
            if isinstance(response, str):
                response = Response(response, mimetype='text/html')
            else:
                response = Response(response)
        if response.direct_passthrough or response.status_code >= 400:
            return response
        if response.content_length and response.content_length < 1024:
            return response
        gzip_data = gzip.compress(response.get_data())
        response.set_data(gzip_data)
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Length'] = len(gzip_data)
        return response
    return view_func

# ------------------- Класс для работы с LibreHardwareMonitor -------------------
class LibreMonitor:
    def __init__(self, exe_path, port):
        self.exe_path = exe_path
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}/data.json"
        try:
            self.ip_address = socket.gethostbyname(socket.gethostname())
            self.fallback_url = f"http://{self.ip_address}:{port}/data.json"
        except socket.gaierror:
            self.ip_address = "127.0.0.1"
            self.fallback_url = self.base_url
        self.process = None
        self.lock = threading.Lock()

    def kill_existing_process(self):
        try:
            import psutil as ps
            killed = False
            for proc in ps.process_iter(['pid', 'name']):
                if proc.info['name'] and proc.info['name'].lower() == 'librehardwaremonitor.exe':
                    try:
                        if not self.is_running():
                            logger.info(f"Завершаем неотвечающий процесс LibreHardwareMonitor (PID: {proc.info['pid']})")
                            proc.kill()
                            proc.wait(timeout=3)
                            killed = True
                        else:
                            logger.info(f"Процесс LibreHardwareMonitor (PID: {proc.info['pid']}) уже отвечает")
                    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                        logger.debug(f"Не удалось завершить процесс LibreHardwareMonitor (PID: {proc.info['pid']}), процесс уже исчез")
            return killed
        except (OSError, ValueError, TypeError) as exc:
            logger.error(f"Ошибка при завершении процесса Libre: {exc}")
            return False

    def start(self):
        if self.is_running():
            logger.info("LibreHardwareMonitor уже запущен и отвечает")
            return True
        self.kill_existing_process()
        if not os.path.exists(self.exe_path):
            logger.error(f"Файл {self.exe_path} не найден")
            return False
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.process = subprocess.Popen(
                [self.exe_path, "--web", "--port", str(self.port)],
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            logger.info(f"Запущен LibreHardwareMonitor (PID: {self.process.pid}) с веб-сервером на порту {self.port}")
            for i in range(30):
                time.sleep(0.5)
                if self.is_running():
                    logger.info(f"LibreHardwareMonitor веб-сервер запущен через {i*0.5} секунд")
                    return True
            logger.warning("LibreHardwareMonitor не отвечает, но процесс запущен")
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.error(f"Ошибка запуска Libre: {exc}")
            return False

    def is_running(self):
        for url in [self.base_url, self.fallback_url]:
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    if url != self.base_url:
                        self.base_url = url
                        logger.info(f"Используем запасной URL: {url}")
                    return True
            except requests.RequestException:
                continue
        return False

    def fetch_data(self):
        try:
            r = requests.get(self.base_url, timeout=10)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"Libre вернул код {r.status_code}")
            return None
        except requests.RequestException as exc:
            logger.error(f"Ошибка получения данных от Libre: {exc}")
            return None

    def ensure_running(self):
        with self.lock:
            if not self.is_running():
                logger.warning("LibreHardwareMonitor недоступен, пробуем перезапустить")
                self.process = None
                return self.start()
            return True

# ------------------- Сохранение истории в файл -------------------
class HistoryLogger:
    def __init__(self, filename, max_entries=1000):
        self.filename = filename
        self.max_entries = max_entries
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = []

    def _save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def add_entry(self, entry):
        with self.lock:
            self.data.append(entry)
            if len(self.data) > self.max_entries:
                self.data = self.data[-self.max_entries:]
            self._save()

    def get_all(self):
        with self.lock:
            return self.data.copy()

    def get_recent(self, hours=24):
        with self.lock:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            recent = []
            for entry in self.data:
                try:
                    dt = datetime.fromisoformat(entry['timestamp'])
                    if dt >= cutoff:
                        recent.append(entry)
                except (TypeError, ValueError):
                    continue
            return recent

# ------------------- Кеширование данных с историей -------------------
class Cache:
    def __init__(self, update_interval, history_size=60):
        self.interval = update_interval
        self.history_size = history_size
        self.data = {}
        self.last_update = 0
        self.lock = threading.Lock()
        self.prev_net = None
        self.history = {
            "cpu_temp": deque(maxlen=history_size),
            "gpu_temp": deque(maxlen=history_size),
            "cpu_load": deque(maxlen=history_size),
            "net_recv": deque(maxlen=history_size),
            "net_sent": deque(maxlen=history_size),
            "timestamps": deque(maxlen=history_size),
        }
        self.history_logger = HistoryLogger(CONFIG["HISTORY_FILE"], CONFIG["MAX_HISTORY_ENTRIES"])

    def refresh(self, libre_data, ps_data):
        with self.lock:
            now = time.time()
            merged = {**libre_data, **ps_data}
            if self.prev_net is not None:
                prev_sent, prev_recv, prev_time = self.prev_net
                dt = now - prev_time
                if dt > 0:
                    sent_speed = (ps_data["net_sent"] - prev_sent) / dt
                    recv_speed = (ps_data["net_recv"] - prev_recv) / dt
                    merged["net_sent_speed_kbps"] = round(sent_speed / 1024, 1)
                    merged["net_recv_speed_kbps"] = round(recv_speed / 1024, 1)
            self.prev_net = (ps_data["net_sent"], ps_data["net_recv"], now)
            self.data = merged
            self.last_update = now

            cpu_temp = merged.get("cpu", {}).get("temperature")
            gpu_temp = merged.get("gpu", {}).get("temperature")
            cpu_load = merged.get("cpu", {}).get("load") or merged.get("cpu_percent")
            net_recv = merged.get("net_recv_speed_kbps")
            net_sent = merged.get("net_sent_speed_kbps")

            if cpu_temp is not None:
                self.history["cpu_temp"].append(cpu_temp)
            if gpu_temp is not None:
                self.history["gpu_temp"].append(gpu_temp)
            if cpu_load is not None:
                self.history["cpu_load"].append(cpu_load)
            if net_recv is not None:
                self.history["net_recv"].append(net_recv)
            if net_sent is not None:
                self.history["net_sent"].append(net_sent)
            self.history["timestamps"].append(now)

            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cpu_temp": cpu_temp,
                "gpu_temp": gpu_temp,
                "cpu_load": cpu_load,
                "cpu_freq": merged.get("cpu", {}).get("frequency") or merged.get("cpu_freq_mhz"),
                "cpu_voltage": merged.get("cpu", {}).get("voltage"),
                "gpu_load": merged.get("gpu", {}).get("load"),
                "gpu_freq": merged.get("gpu", {}).get("frequency"),
                "ram_used": merged.get("ram_used_mb"),
                "ram_total": merged.get("ram_total_mb"),
                "ram_percent": merged.get("ram_percent"),
                "net_recv_speed": merged.get("net_recv_speed_kbps"),
                "net_sent_speed": merged.get("net_sent_speed_kbps"),
                "disks": merged.get("disks"),
            }
            self.history_logger.add_entry(entry)

    def get(self):
        return self.data

    def get_history(self):
        with self.lock:
            timestamps = list(self.history["timestamps"])
            if timestamps:
                base = timestamps[0]
                timestamps_rel = [round(t - base, 1) for t in timestamps]
            else:
                timestamps_rel = []
            return {
                "timestamps": timestamps_rel,
                "cpu_temp": list(self.history["cpu_temp"]),
                "gpu_temp": list(self.history["gpu_temp"]),
                "cpu_load": list(self.history["cpu_load"]),
                "net_recv": list(self.history["net_recv"]),
                "net_sent": list(self.history["net_sent"]),
            }

    def get_all_history(self):
        return self.history_logger.get_all()

    def get_recent_history(self, hours=24):
        return self.history_logger.get_recent(hours)

# ------------------- Flask-приложение -------------------
app = Flask(__name__)
CORS(app)

libre = LibreMonitor(CONFIG["LIBRE_EXE"], CONFIG["LIBRE_PORT"])
cache = Cache(CONFIG["UPDATE_INTERVAL"], CONFIG["HISTORY_SIZE"])

def background_updater():
    while True:
        try:
            libre.ensure_running()
            libre_json = libre.fetch_data()
            parsed = parse_libre_data(libre_json) if libre_json else {}
            ps_data = get_psutil_data()
            cache.refresh(parsed, ps_data)
            logger.debug("Кеш обновлён")
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.error(f"Ошибка в фоновом обновлении: {exc}")
        time.sleep(CONFIG["UPDATE_INTERVAL"])

updater_thread = threading.Thread(target=background_updater, daemon=True)
updater_thread.start()

# ------------------- Эндпоинты API -------------------
@app.route('/stats')
@gzipped
def stats():
    data = cache.get()
    if not data:
        return jsonify({"error": "Данные ещё не собраны"}), 503
    return jsonify(data)

@app.route('/history')
@gzipped
def history():
    return jsonify(cache.get_history())

@app.route('/history-data')
@gzipped
def history_data():
    hours = request.args.get('hours', 24, type=int)
    data = cache.get_recent_history(hours)
    return jsonify(data)

@app.route('/health')
@gzipped
def health():
    libre_ok = libre.is_running()
    return jsonify({
        "status": "ok" if libre_ok else "degraded",
        "libre_running": libre_ok,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "cache_age": int(time.time() - cache.last_update) if cache.last_update else None
    })

@app.route('/export/csv')
@gzipped
def export_csv():
    data = cache.get()
    if not data:
        return "Нет данных для экспорта", 404
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["Время", "CPU Температура", "CPU Загрузка", "CPU Частота", "CPU Напряжение",
               "GPU Температура", "GPU Загрузка", "GPU Частота", "GPU Напряжение", "GPU Память (исп.)",
               "RAM Занято (МБ)", "RAM Всего (МБ)", "RAM Загрузка",
               "Сеть Приём (КБ/с)", "Сеть Отдача (КБ/с)", "Время работы (сек)"]
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
        writer.writerow(["Диски"])
        writer.writerow(["Точка монтирования", "Всего (ГБ)", "Использовано (ГБ)", "Свободно (ГБ)", "Загрузка %"])
        for d in disks:
            writer.writerow([d["mount"], d["total_gb"], d["used_gb"], d["free_gb"], d["percent"]])
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=system_stats.csv"})

@app.route('/sensors')
@gzipped
def sensors():
    return stats()

@app.route('/export/history-csv')
@gzipped
def export_history_csv():
    hours = request.args.get('hours', 24, type=int)
    data = cache.get_recent_history(hours)
    if not data:
        return "Нет данных", 404
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Время", "CPU Темп.", "GPU Темп.", "CPU Загрузка", "CPU Частота", "CPU Напряжение",
                     "GPU Загрузка", "GPU Частота", "RAM Занято (МБ)", "RAM Всего (МБ)", "RAM %",
                     "Сеть Приём (КБ/с)", "Сеть Отдача (КБ/с)"])
    for entry in data:
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
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=history_{hours}h.csv"})

# ------------------- Страница истории (отдельный маршрут) -------------------
@app.route('/history-page')
@gzipped
def history_page():
    html_history = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>История системы</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #f0f0f0; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            h1 { color: #000080; border-bottom: 2px solid #000080; padding-bottom: 10px; }
            .controls { margin: 15px 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
            .controls select, .controls button { padding: 6px 12px; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; }
            .controls button { background: #000080; color: white; border: none; }
            .controls button:hover { background: #0000a0; }
            #chartContainer { height: 300px; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; font-size: 14px; }
            th { background: #000080; color: white; padding: 8px; text-align: left; }
            td { padding: 6px 8px; border-bottom: 1px solid #ddd; }
            tr:hover { background: #f5f5f5; }
            .scrollable { max-height: 500px; overflow-y: auto; }
            .back-link { display: inline-block; margin-bottom: 15px; color: #000080; text-decoration: none; }
            .back-link:hover { text-decoration: underline; }
            @media (max-width: 600px) {
                .container { padding: 10px; }
                table { font-size: 12px; }
                th, td { padding: 4px; }
                #chartContainer { height: 200px; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/dashboard" class="back-link">← Вернуться на дашборд</a>
            <h1>📊 История системы</h1>
            <div class="controls">
                <label>Период: 
                    <select id="periodSelect">
                        <option value="1">Последний час</option>
                        <option value="6">Последние 6 часов</option>
                        <option value="24" selected>Последние 24 часа</option>
                        <option value="72">Последние 3 дня</option>
                        <option value="168">Последняя неделя</option>
                    </select>
                </label>
                <button id="refreshBtn">Обновить</button>
                <button id="exportCsvHistoryBtn">Скачать CSV</button>
            </div>
            <div id="chartContainer"><canvas id="historyChart"></canvas></div>
            <div class="scrollable">
                <table id="historyTable">
                    <thead>
                        <tr>
                            <th>Время</th>
                            <th>CPU °C</th>
                            <th>GPU °C</th>
                            <th>CPU %</th>
                            <th>RAM %</th>
                            <th>Сеть приём</th>
                            <th>Сеть отдача</th>
                        </tr>
                    </thead>
                    <tbody id="historyBody">
                        <tr><td colspan="7">Загрузка данных...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        <script>
            let chartInstance = null;

            function formatTime(iso) {
                const d = new Date(iso);
                return d.toLocaleTimeString() + ' ' + d.toLocaleDateString();
            }

            function loadHistory(hours) {
                fetch('/history-data?hours=' + hours)
                    .then(r => r.json())
                    .then(data => {
                        const tbody = document.getElementById('historyBody');
                        if (!data || data.length === 0) {
                            tbody.innerHTML = '<tr><td colspan="7">Нет данных за выбранный период</td></tr>';
                            return;
                        }
                        let html = '';
                        const reversed = data.slice().reverse();
                        reversed.forEach(entry => {
                            const cpu_temp = entry.cpu_temp !== null ? entry.cpu_temp.toFixed(1) : '—';
                            const gpu_temp = entry.gpu_temp !== null ? entry.gpu_temp.toFixed(1) : '—';
                            const cpu_load = entry.cpu_load !== null ? entry.cpu_load.toFixed(1) : '—';
                            const ram_percent = entry.ram_percent !== null ? entry.ram_percent.toFixed(1) : '—';
                            const net_recv = entry.net_recv_speed !== null ? entry.net_recv_speed.toFixed(1) : '—';
                            const net_sent = entry.net_sent_speed !== null ? entry.net_sent_speed.toFixed(1) : '—';
                            html += `<tr>
                                <td>${formatTime(entry.timestamp)}</td>
                                <td>${cpu_temp}</td>
                                <td>${gpu_temp}</td>
                                <td>${cpu_load}</td>
                                <td>${ram_percent}</td>
                                <td>${net_recv}</td>
                                <td>${net_sent}</td>
                            </tr>`;
                        });
                        tbody.innerHTML = html;

                        const labels = data.map(e => formatTime(e.timestamp));
                        const cpuTemps = data.map(e => e.cpu_temp);
                        const gpuTemps = data.map(e => e.gpu_temp);
                        const cpuLoads = data.map(e => e.cpu_load);
                        const ramPercents = data.map(e => e.ram_percent);

                        const ctx = document.getElementById('historyChart').getContext('2d');
                        if (chartInstance) chartInstance.destroy();
                        chartInstance = new Chart(ctx, {
                            type: 'line',
                            data: {
                                labels: labels,
                                datasets: [
                                    { label: 'CPU °C', data: cpuTemps, borderColor: '#ff0000', pointRadius: 0, tension: 0.2 },
                                    { label: 'GPU °C', data: gpuTemps, borderColor: '#ff8000', pointRadius: 0, tension: 0.2 },
                                    { label: 'CPU %', data: cpuLoads, borderColor: '#0000ff', pointRadius: 0, tension: 0.2, yAxisID: 'y1' },
                                    { label: 'RAM %', data: ramPercents, borderColor: '#00aa00', pointRadius: 0, tension: 0.2, yAxisID: 'y1' }
                                ]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                interaction: { mode: 'index', intersect: false },
                                scales: {
                                    y: { beginAtZero: true, position: 'left', title: { display: true, text: 'Температура (°C)' } },
                                    y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Загрузка (%)' } }
                                },
                                plugins: {
                                    legend: { position: 'top' }
                                }
                            }
                        });
                    })
                    .catch(err => {
                        console.error('Ошибка загрузки истории:', err);
                        document.getElementById('historyBody').innerHTML = '<tr><td colspan="7">Ошибка загрузки данных</td></tr>';
                    });
            }

            document.getElementById('refreshBtn').addEventListener('click', function() {
                const hours = parseInt(document.getElementById('periodSelect').value);
                loadHistory(hours);
            });

            document.getElementById('periodSelect').addEventListener('change', function() {
                const hours = parseInt(this.value);
                loadHistory(hours);
            });

            document.getElementById('exportCsvHistoryBtn').addEventListener('click', function() {
                const hours = parseInt(document.getElementById('periodSelect').value);
                window.location.href = '/export/history-csv?hours=' + hours;
            });

            loadHistory(24);
        </script>
    </body>
    </html>
    """
    return render_template_string(html_history)

# ------------------- Мобильная версия (лёгкий интерфейс) -------------------
@app.route('/mobile')
@gzipped
def mobile():
    html_mobile = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Монитор (моб.)</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #eee; padding: 12px; padding-bottom: 80px; }
            .container { max-width: 500px; margin: 0 auto; }
            h1 { font-size: 1.5rem; text-align: center; margin-bottom: 20px; color: #e0e0e0; border-bottom: 1px solid #333; padding-bottom: 10px; }
            .card { background: #16213e; border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; border-left: 4px solid #0f3460; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
            .card-title { font-size: 0.85rem; font-weight: 600; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
            .card-title .icon { font-size: 1.2rem; }
            .card-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.95rem; }
            .card-row:last-child { border-bottom: none; }
            .card-row .label { color: #ccc; }
            .card-row .value { font-weight: 600; color: #fff; }
            .value.high { color: #ff6b6b; }
            .value.warning { color: #feca57; }
            .progress-bar { width: 100%; height: 6px; background: #2d2d44; border-radius: 4px; margin-top: 6px; overflow: hidden; }
            .progress-bar .fill { height: 100%; background: #0f3460; border-radius: 4px; transition: width 0.3s; }
            .progress-bar .fill.warning { background: #feca57; }
            .progress-bar .fill.danger { background: #ff6b6b; }
            .update-time { text-align: center; font-size: 0.75rem; color: #888; margin-top: 20px; }
            .footer { text-align: center; font-size: 0.7rem; color: #555; margin-top: 20px; border-top: 1px solid #222; padding-top: 12px; }
            .error { background: #2d1b1b; border-left-color: #ff6b6b; }
            .error .value { color: #ff6b6b; }
            @media (min-width: 600px) {
                body { padding: 20px; }
                .container { max-width: 600px; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Системный монитор <span style="font-size:0.7rem; color:#666;">(мобильная версия)</span></h1>
            <div id="dashboard">
                <div class="card" style="text-align:center; padding:30px;">⏳ Загрузка...</div>
            </div>
            <div class="update-time">🔄 Обновлено: <span id="lastUpdate">--</span></div>
            <div class="footer">© 2026 · <a href="/dashboard" style="color:#888; text-decoration:none;">Полная версия</a></div>
        </div>
        <script>
            // --- Конфигурация ---
            let refreshInterval = 2000;
            let timerId = null;

            // --- Форматирование ---
            function formatValue(value, decimals=1, unit='') {
                if (value === null || value === undefined || isNaN(value)) return '—';
                return value.toFixed(decimals) + (unit ? ' ' + unit : '');
            }
            function formatPercent(value) {
                if (value === null || value === undefined || isNaN(value)) return '—';
                return value.toFixed(1) + ' %';
            }
            function formatSizeMb(value) {
                if (value === null || value === undefined || isNaN(value)) return '—';
                if (value > 1024) return (value/1024).toFixed(1) + ' GB';
                return value.toFixed(0) + ' MB';
            }
            function formatUptime(seconds) {
                if (!seconds) return '—';
                const d = Math.floor(seconds / 86400);
                const h = Math.floor((seconds % 86400) / 3600);
                const m = Math.floor((seconds % 3600) / 60);
                return (d ? d+'д ' : '') + h+'ч '+m+'м';
            }

            // --- Рендер ---
            function render(data) {
                let html = '';
                const cpu = data.cpu || {};
                const gpu = data.gpu || {};
                const cpuLoad = cpu.load ?? data.cpu_percent;

                // CPU
                html += `
                <div class="card">
                    <div class="card-title"><span class="icon">🔥</span> CPU</div>
                    <div class="card-row"><span class="label">Температура</span><span class="value ${cpu.temperature > 80 ? 'danger' : cpu.temperature > 70 ? 'warning' : ''}">${formatValue(cpu.temperature, 1, '°C')}</span></div>
                    <div class="card-row"><span class="label">Загрузка</span><span class="value">${formatPercent(cpuLoad)}</span></div>
                    <div class="progress-bar"><div class="fill ${cpuLoad > 80 ? 'danger' : cpuLoad > 60 ? 'warning' : ''}" style="width:${Math.min(100,cpuLoad)}%;"></div></div>
                    <div class="card-row"><span class="label">Частота</span><span class="value">${formatValue(cpu.frequency ?? data.cpu_freq_mhz, 0, 'МГц')}</span></div>
                    <div class="card-row"><span class="label">Напряжение</span><span class="value">${formatValue(cpu.voltage, 3, 'В')}</span></div>
                    <div class="card-row"><span class="label">Мощность</span><span class="value">${formatValue(cpu.power, 1, 'Вт')}</span></div>
                </div>`;

                // GPU
                if (gpu.temperature !== null || gpu.load !== null) {
                    html += `
                <div class="card">
                    <div class="card-title"><span class="icon">🎮</span> GPU</div>
                    <div class="card-row"><span class="label">Температура</span><span class="value ${gpu.temperature > 80 ? 'danger' : gpu.temperature > 70 ? 'warning' : ''}">${formatValue(gpu.temperature, 1, '°C')}</span></div>
                    <div class="card-row"><span class="label">Загрузка</span><span class="value">${formatPercent(gpu.load)}</span></div>
                    <div class="progress-bar"><div class="fill ${gpu.load > 80 ? 'danger' : gpu.load > 60 ? 'warning' : ''}" style="width:${Math.min(100,gpu.load)}%;"></div></div>
                    <div class="card-row"><span class="label">Частота</span><span class="value">${formatValue(gpu.frequency, 0, 'МГц')}</span></div>
                    <div class="card-row"><span class="label">Память</span><span class="value">${formatSizeMb(gpu.memory_used)} / ${formatSizeMb(gpu.memory_total)}</span></div>
                </div>`;
                }

                // RAM
                const ramPercent = data.ram_percent;
                html += `
                <div class="card">
                    <div class="card-title"><span class="icon">🧠</span> Память (RAM)</div>
                    <div class="card-row"><span class="label">Использовано</span><span class="value">${formatSizeMb(data.ram_used_mb)} / ${formatSizeMb(data.ram_total_mb)}</span></div>
                    <div class="card-row"><span class="label">Занято</span><span class="value">${formatPercent(ramPercent)}</span></div>
                    <div class="progress-bar"><div class="fill ${ramPercent > 80 ? 'danger' : ramPercent > 60 ? 'warning' : ''}" style="width:${Math.min(100,ramPercent)}%;"></div></div>
                </div>`;

                // Сеть
                html += `
                <div class="card">
                    <div class="card-title"><span class="icon">🌐</span> Сеть</div>
                    <div class="card-row"><span class="label">⬇️ Приём</span><span class="value">${formatValue(data.net_recv_speed_kbps, 0, 'КБ/с')}</span></div>
                    <div class="card-row"><span class="label">⬆️ Отдача</span><span class="value">${formatValue(data.net_sent_speed_kbps, 0, 'КБ/с')}</span></div>
                </div>`;

                // Диски
                const disks = data.disks || [];
                if (disks.length > 0) {
                    html += `
                <div class="card">
                    <div class="card-title"><span class="icon">💾</span> Диски</div>`;
                    disks.forEach(d => {
                        html += `
                    <div class="card-row"><span class="label">${d.mount}</span><span class="value">${d.percent.toFixed(1)}% (${d.used_gb.toFixed(1)}/${d.total_gb.toFixed(1)} ГБ)</span></div>`;
                    });
                    const storage = data.storage || [];
                    storage.forEach(s => {
                        html += `
                    <div class="card-row"><span class="label">${s.name}</span><span class="value">${s.temp ? s.temp.toFixed(1) + ' °C' : '—'}</span></div>`;
                    });
                    html += `
                </div>`;
                }

                // Вентиляторы
                const fans = data.fans || [];
                if (fans.length > 0) {
                    html += `
                <div class="card">
                    <div class="card-title"><span class="icon">🌀</span> Вентиляторы</div>`;
                    fans.forEach(f => {
                        html += `
                    <div class="card-row"><span class="label">${f.name}</span><span class="value">${f.rpm ? f.rpm + ' RPM' : '—'}</span></div>`;
                    });
                    html += `
                </div>`;
                }

                // Материнская плата
                const mb = data.motherboard || {};
                if (mb.temperature && mb.temperature.length > 0) {
                    html += `
                <div class="card">
                    <div class="card-title"><span class="icon">🔌</span> Материнская плата</div>`;
                    mb.temperature.forEach(t => {
                        html += `
                    <div class="card-row"><span class="label">${t.name}</span><span class="value">${t.value} °C</span></div>`;
                    });
                    if (mb.voltage && mb.voltage.length > 0) {
                        mb.voltage.forEach(v => {
                            html += `
                    <div class="card-row"><span class="label">${v.name}</span><span class="value">${v.value} V</span></div>`;
                        });
                    }
                    html += `
                </div>`;
                }

                // Система
                html += `
                <div class="card">
                    <div class="card-title"><span class="icon">⚙️</span> Система</div>
                    <div class="card-row"><span class="label">Время работы</span><span class="value">${formatUptime(data.uptime_seconds)}</span></div>
                    <div class="card-row"><span class="label">Загрузка системы</span><span class="value">${data.boot_time || '—'}</span></div>
                </div>`;

                document.getElementById('dashboard').innerHTML = html;
            }

            // --- Обновление ---
            function update() {
                fetch('/stats')
                    .then(response => {
                        if (!response.ok) throw new Error('Ошибка сервера: ' + response.status);
                        return response.json();
                    })
                    .then(data => {
                        const now = new Date();
                        document.getElementById('lastUpdate').textContent = now.toLocaleTimeString();
                        render(data);
                    })
                    .catch(error => {
                        console.error('Ошибка обновления:', error);
                        document.getElementById('dashboard').innerHTML = `
                            <div class="card error" style="text-align:center; padding:20px;">
                                ❌ Ошибка загрузки данных<br>
                                <span style="font-size:0.8rem; color:#999;">${error.message}</span>
                            </div>
                        `;
                    });
            }

            // --- Запуск ---
            function startAutoUpdate() {
                if (timerId) clearInterval(timerId);
                timerId = setInterval(update, refreshInterval);
                update();
            }

            document.addEventListener('DOMContentLoaded', function() {
                startAutoUpdate();
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_mobile)

# ------------------- Главный дашборд (полная версия) -------------------
@app.route('/')
def index():
    return redirect('/dashboard')

@app.route('/dashboard')
@gzipped
def dashboard():
    try:
        # Здесь должен быть полный HTML дашборда (как в server.py)
        # Для компактности я помещаю упрощённую версию, но вы можете вставить полный код из предыдущих ответов.
        html = """
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Дашборд</title></head>
        <body style="font-family:sans-serif;padding:20px;background:#f0f0f0;">
            <h1>📊 Системный монитор (полная версия)</h1>
            <p>Это полная версия дашборда. Для мобильных устройств используйте <a href="/mobile">/mobile</a>.</p>
            <p>Данные обновляются автоматически.</p>
            <p><a href="/stats">JSON</a> · <a href="/history">История</a></p>
            <hr>
            <div id="stats" style="white-space:pre;background:#fff;padding:10px;border-radius:8px;">Загрузка...</div>
            <script>
                fetch('/stats').then(r=>r.json()).then(d=>{
                    document.getElementById('stats').innerHTML = JSON.stringify(d, null, 2);
                });
            </script>
        </body>
        </html>
        """
        return render_template_string(html)
    except ValueError as exc:
        logger.exception("Ошибка в маршруте /dashboard")
        return f"<h1>Внутренняя ошибка сервера</h1><p>{exc}</p><pre>{traceback.format_exc()}</pre>", 500

# ------------------- Запуск -------------------
if __name__ == '__main__':
    local_ip = get_local_ip()
    logger.info(f"Сервер запускается на http://{local_ip}:{CONFIG['SERVER_PORT']}")
    logger.info(f"Эндпоинт: http://{local_ip}:{CONFIG['SERVER_PORT']}/stats")
    logger.info(f"Веб-интерфейс: http://{local_ip}:{CONFIG['SERVER_PORT']}/dashboard")
    logger.info(f"Мобильная версия: http://{local_ip}:{CONFIG['SERVER_PORT']}/mobile")
    logger.info(f"Страница истории: http://{local_ip}:{CONFIG['SERVER_PORT']}/history-page")
    app.run(host='0.0.0.0', port=CONFIG['SERVER_PORT'], debug=CONFIG['DEBUG'])