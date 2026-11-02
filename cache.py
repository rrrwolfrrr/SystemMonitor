#!/usr/bin/env python3
"""
SystemMonitor — кэш данных и история.
Класс Cache хранит текущие данные и короткую историю (deque).
Класс HistoryDB хранит долгосрочную историю в SQLite.
"""

import json
import logging
import sqlite3
import threading
import time
import copy
from collections import deque
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class HistoryDB:
    """Долгосрочная история в SQLite."""
    
    def __init__(self, db_file, max_entries=1000, write_interval=5.0, batch_size=10):
        self.db_file = db_file
        self.max_entries = max_entries
        self.lock = threading.Lock()
        self.write_interval = max(0.0, float(write_interval))
        self.batch_size = max(1, int(batch_size))
        self._pending = []
        self._last_flush = time.monotonic()
        self._init_db()
    
    def _init_db(self):
        """Инициализирует базу данных и создаёт таблицу."""
        try:
            with sqlite3.connect(self.db_file) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        cpu_temp REAL,
                        gpu_temp REAL,
                        cpu_load REAL,
                        cpu_freq REAL,
                        cpu_voltage REAL,
                        gpu_load REAL,
                        gpu_freq REAL,
                        ram_used REAL,
                        ram_total REAL,
                        ram_percent REAL,
                        net_recv_speed REAL,
                        net_sent_speed REAL,
                        disks TEXT
                    )
                ''')
                # Индекс для быстрого поиска по времени
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_history_timestamp 
                    ON history(timestamp)
                ''')
                conn.commit()
        except sqlite3.Error as exc:
            logger.error(f"Ошибка инициализации базы данных: {exc}")
    
    def add_entry(self, entry):
        """Добавляет запись в историю."""
        with self.lock:
            self._pending.append(dict(entry))
            if (len(self._pending) >= self.batch_size or
                    time.monotonic() - self._last_flush >= self.write_interval):
                self._flush_locked()

    def _flush_locked(self):
        pending = self._pending
        self._pending = []
        if not pending:
            return
        try:
            with sqlite3.connect(self.db_file) as conn:
                for entry in pending:
                    disks_json = None
                    if entry.get("disks"):
                        try:
                            disks_json = json.dumps(entry["disks"], ensure_ascii=False)
                        except (TypeError, ValueError) as exc:
                            logger.debug(f"Ошибка сериализации disks: {exc}")
                    conn.execute('''
                        INSERT INTO history (
                            timestamp, cpu_temp, gpu_temp, cpu_load, cpu_freq, cpu_voltage,
                            gpu_load, gpu_freq, ram_used, ram_total, ram_percent,
                            net_recv_speed, net_sent_speed, disks
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
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
                        disks_json
                    ))
                count = conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]
                if count > self.max_entries:
                    conn.execute('''
                        DELETE FROM history WHERE id IN (
                            SELECT id FROM history ORDER BY id ASC LIMIT ?
                        )
                    ''', (count - self.max_entries,))
                conn.commit()
            self._last_flush = time.monotonic()
        except (sqlite3.Error, TypeError, ValueError) as exc:
            logger.error(f"Ошибка записи в историю: {exc}")
            self._pending = pending + self._pending
    
    def get_recent(self, hours=24):
        """Возвращает записи за последние N часов."""
        with self.lock:
            try:
                self._flush_locked()
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
                with sqlite3.connect(self.db_file) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute('''
                        SELECT * FROM history WHERE timestamp >= ? ORDER BY timestamp ASC
                    ''', (cutoff,)).fetchall()
                    
                    result = []
                    for row in rows:
                        entry = dict(row)
                        # Десериализуем disks из JSON
                        if entry.get("disks"):
                            try:
                                entry["disks"] = json.loads(entry["disks"])
                            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                                logger.debug(f"Ошибка десериализации disks: {exc}")
                                entry["disks"] = []
                        result.append(entry)
                    return result
            except (sqlite3.Error, TypeError, ValueError) as exc:
                logger.error(f"Ошибка чтения истории: {exc}")
                return []
    
    def get_all(self):
        """Возвращает все записи."""
        with self.lock:
            try:
                self._flush_locked()
                with sqlite3.connect(self.db_file) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute('SELECT * FROM history ORDER BY timestamp ASC').fetchall()
                    
                    result = []
                    for row in rows:
                        entry = dict(row)
                        if entry.get("disks"):
                            try:
                                entry["disks"] = json.loads(entry["disks"])
                            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                                logger.debug(f"Ошибка десериализации disks: {exc}")
                                entry["disks"] = []
                        result.append(entry)
                    return result
            except (sqlite3.Error, TypeError, ValueError) as exc:
                logger.error(f"Ошибка чтения истории: {exc}")
                return []

    def close(self):
        with self.lock:
            self._flush_locked()


class Cache:
    """Кэш текущих данных и короткой истории."""
    
    def __init__(self, update_interval, history_size=60, db_file='history.db',
                 max_entries=1000, db_write_interval=5.0, db_batch_size=10):
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
        self.history_db = HistoryDB(db_file, max_entries, db_write_interval, db_batch_size)
    
    def refresh(self, libre_data, ps_data):
        """Обновляет кэш данными из Libre и psutil."""
        with self.lock:
            now = time.time()
            merged = {**(libre_data or {}), **(ps_data or {})}
            new_storage = (libre_data or {}).get("storage")
            old_storage = self.data.get("storage")
            if isinstance(new_storage, list) and isinstance(old_storage, list):
                old_by_id = {
                    item.get("identifier") or item.get("name"): item
                    for item in old_storage if isinstance(item, dict)
                }
                for item in new_storage:
                    if isinstance(item, dict) and item.get("temp") is None:
                        previous = old_by_id.get(item.get("identifier") or item.get("name"))
                        if previous:
                            item.update({k: v for k, v in previous.items() if k != "status"})
                            item["status"] = "temporary_unavailable"
            
            # Вычисляем скорость сети
            if self.prev_net is not None:
                prev_sent, prev_recv, prev_time = self.prev_net
                dt = now - prev_time
                if dt > 0:
                    sent_speed = (ps_data.get("net_sent", prev_sent) - prev_sent) / dt
                    recv_speed = (ps_data.get("net_recv", prev_recv) - prev_recv) / dt
                    merged["net_sent_speed_kbps"] = round(max(0, sent_speed) / 1024, 1)
                    merged["net_recv_speed_kbps"] = round(max(0, recv_speed) / 1024, 1)
            self.prev_net = (ps_data.get("net_sent", 0), ps_data.get("net_recv", 0), now)
            # Единая схема сети; старые net_* ключи выше остаются для клиентов.
            network = dict(merged.get("network") or {})
            network["sent_total_bytes"] = ps_data.get("net_sent", network.get("sent_total_bytes", 0))
            network["received_total_bytes"] = ps_data.get("net_recv", network.get("received_total_bytes", 0))
            network["upload_speed_kbps"] = merged.get("net_sent_speed_kbps", network.get("upload_speed_kbps", 0.0))
            network["download_speed_kbps"] = merged.get("net_recv_speed_kbps", network.get("download_speed_kbps", 0.0))
            merged["network"] = network
            
            self.data = merged
            self.last_update = now
            
            # Обновляем короткую историю
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
            
            # Логируем в долгосрочную историю (SQLite)
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
            self.history_db.add_entry(entry)
    
    def get(self):
        """Возвращает текущие данные."""
        with self.lock:
            return copy.deepcopy(self.data)
    
    def get_history(self):
        """Возвращает короткую историю."""
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
        """Возвращает всю долгосрочную историю."""
        return self.history_db.get_all()

    def close(self):
        """Flush queued SQLite writes during orderly shutdown."""
        self.history_db.close()
    
    def get_recent_history(self, hours=24):
        """Возвращает долгосрочную историю за последние N часов."""
        return self.history_db.get_recent(hours)