#!/usr/bin/env python3
"""
SystemMonitor — ядро сервера.
Flask-приложение, WebSocket-сервер, фоновый поток обновления данных.
Использует DLL-режим LibreHardwareMonitor (не EXE).
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time

import websockets
from flask import Flask
from flask_cors import CORS

from cache import Cache
from config import Config
from fps_monitor import FPSMonitor
from libre_monitor import LibreMonitor
from routes import register_routes
from utils import get_psutil_data, parse_libre_data
from logging_setup import configure_logging
from network_utils import get_local_ip


def resource_path(relative_path):
    """Получить абсолютный путь к ресурсу (работает и в dev, и в exe)"""
    if hasattr(sys, '_MEIPASS'):
        # Запуск из собранного .exe
        return os.path.join(sys._MEIPASS, relative_path)
    # Обычный запуск из исходников
    return os.path.join(os.path.abspath("."), relative_path)

# --- Логирование ---

configure_logging(Config.LOG_FILE, Config.DEBUG)
logger = logging.getLogger(__name__)

logger.info("Запуск SystemMonitor (серверная часть)")

# --- Flask-приложение ---

app = Flask(
    __name__,
    template_folder=resource_path('templates'),
    static_folder=resource_path('static') if os.path.exists(resource_path('static')) else None
)
app.config['SECRET_KEY'] = 'dev-secret-key'
CORS(app, origins=['http://localhost:5000', 'http://127.0.0.1:5000'])

# --- Инициализация LibreHardwareMonitor (DLL-режим) ---

libre_dll_path = os.path.abspath(resource_path(Config.LIBRE_DLL))
logger.info(f"Путь к LibreHardwareMonitorLib.dll: {libre_dll_path}")

libre = LibreMonitor(dll_path=libre_dll_path)
fps_monitor = FPSMonitor()

# --- Инициализация кеша ---

cache = Cache(
    update_interval=Config.UPDATE_INTERVAL,
    history_size=Config.HISTORY_SIZE,
    db_file=Config.DB_FILE,
    max_entries=Config.MAX_HISTORY_ENTRIES,
    db_write_interval=getattr(Config, "DB_WRITE_INTERVAL", 5),
    db_batch_size=getattr(Config, "DB_BATCH_SIZE", 10)
)

# --- WebSocket клиенты ---

connected_clients = set()
client_queues = {}
connected_clients_lock = threading.Lock()

# Глобальный флаг: должен ли SystemMonitor перезапускать Libre
libre_should_run = True

# Событие для остановки сервера
shutdown_event = threading.Event()


# --- Рассылка данных ---

def broadcast_data(data):
    """Рассылает данные всем подключённым WebSocket клиентам."""
    if not connected_clients:
        logger.debug("broadcast_data: нет подключенных клиентов")
        return
    try:
        message = json.dumps(data, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сериализации данных: {e}")
        return

    with connected_clients_lock:
        clients = list(connected_clients)
        queues = {ws: client_queues[ws] for ws in clients if ws in client_queues}

    for queue in queues.values():
        try:
            def enqueue(q=queue, msg=message):
                try:
                    if q.full():
                        q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass
            loop.call_soon_threadsafe(enqueue)
        except Exception as e:
            logger.debug(f"Ошибка постановки WebSocket-сообщения: {e}")


# --- WebSocket обработчик ---

async def ws_handler(websocket, path=None):
    """Обработчик WebSocket подключений."""
    with connected_clients_lock:
        connected_clients.add(websocket)
        client_queues[websocket] = asyncio.Queue(maxsize=100)
    logger.info(f"WebSocket клиент подключился. Всего клиентов: {len(connected_clients)}")
    try:
        queue = client_queues[websocket]
        while True:
            message = await queue.get()
            await websocket.send(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"Ошибка WebSocket: {e}")
    finally:
        with connected_clients_lock:
            connected_clients.discard(websocket)
            client_queues.pop(websocket, None)
        logger.info(f"WebSocket клиент отключился. Всего клиентов: {len(connected_clients)}")


# --- WebSocket сервер ---

loop = None

async def start_websocket_server():
    """Запуск WebSocket сервера."""
    ws_port = 8765
    try:
        async with websockets.serve(ws_handler, "0.0.0.0", ws_port):
            logger.info(f"WebSocket-сервер успешно запущен на порту {ws_port}")
            await asyncio.Future()  # бесконечное ожидание
    except Exception as e:
        logger.error(f"Не удалось запустить WebSocket-сервер: {e}")


def run_websocket_server():
    """Запускает WebSocket сервер в отдельном потоке."""
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_websocket_server())


# Запуск WebSocket сервера в отдельном потоке
ws_thread = None


# --- Фоновый поток обновления данных ---

def background_updater():
    """Фоновый поток для периодического сбора данных."""
    global libre_should_run
    pythoncom = None
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        pass
    try:
        while not shutdown_event.is_set():
            try:
                if libre_should_run and not libre.is_running():
                    logger.info("LibreHardwareMonitor не инициализирован, пробуем запустить...")
                    libre.start()
                elif libre.is_running():
                    # Сбор данных из LibreHardwareMonitor
                    try:
                        libre_data = libre.fetch_data()
                        parsed = parse_libre_data(libre_data) if libre_data else {}
                    except Exception as e:
                        logger.error(f"Ошибка сбора данных Libre: {e}")
                        parsed = {}

                    # Сбор данных из psutil
                    try:
                        ps_data = get_psutil_data()
                    except Exception as e:
                        logger.error(f"Ошибка сбора данных psutil: {e}")
                        ps_data = {}

                    # Обновление кеша
                    cache.refresh(parsed, ps_data)
                    merged_data = cache.get()
                    merged_data["fps"] = fps_monitor.get_status()
                    broadcast_data(merged_data)
                    logger.debug("Кеш обновлён")
                else:
                    logger.debug("LibreHardwareMonitor не запущен и не должен быть запущен.")
            except Exception as e:
                logger.error(f"Ошибка в фоновом обновлении: {e}")

            shutdown_event.wait(Config.UPDATE_INTERVAL)
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


# Запуск фонового потока
updater_thread = None


def start_lifecycle():
    """Start background services explicitly (never as an import side effect)."""
    global ws_thread, updater_thread
    if ws_thread and ws_thread.is_alive():
        return
    shutdown_event.clear()
    fps_monitor.start()
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True,
                                 name="systemmonitor-websocket")
    ws_thread.start()
    updater_thread = threading.Thread(target=background_updater, daemon=True,
                                      name="systemmonitor-updater")
    updater_thread.start()


def stop_lifecycle():
    """Stop background services and release the optional LHM handle."""
    shutdown_event.set()
    fps_monitor.stop()
    if cache:
        cache.close()
    if libre:
        libre.close()

# --- Регистрация маршрутов ---

register_routes(app, cache, libre, None, fps_monitor)


# --- Запуск сервера ---

if __name__ == '__main__':
    start_lifecycle()
    local_ip = get_local_ip()

    logger.info(f"Сервер запускается на http://{local_ip}:{Config.SERVER_PORT}")
    logger.info(f"Эндпоинт: http://{local_ip}:{Config.SERVER_PORT}/stats")
    logger.info(f"Веб-интерфейс (ПК): http://{local_ip}:{Config.SERVER_PORT}/dashboard")
    logger.info(f"Мобильная версия: http://{local_ip}:{Config.SERVER_PORT}/mobile")
    logger.info(f"Страница истории: http://{local_ip}:{Config.SERVER_PORT}/history-page")
    logger.info(f"Логи: http://{local_ip}:{Config.SERVER_PORT}/logs")

    try:
        app.run(host='0.0.0.0', port=Config.SERVER_PORT, debug=Config.DEBUG)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    finally:
        stop_lifecycle()
        logger.info("Остановка сервера...")
        logger.info("Сервер остановлен.")