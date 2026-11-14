"""A durable, capacity-bounded local buffer for asynchronous BN archival."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid


class StorageBackpressure(RuntimeError):
    pass


class SpoolBudget:
    def __init__(self, root: Path, max_bytes: int, min_free_bytes: int = 0):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.reservations: dict[str, int] = {}
        self.lock = threading.RLock()

    def used_bytes(self):
        total = 0
        for p in self.root.iterdir():
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except FileNotFoundError:
                continue  # The verified archival worker can remove a closed file.
        return total

    def acquire(self, request: str, request_bytes: int, timeout: float = 60):
        # Cover both request encodings, response/events and atomic-write peaks.
        reserve = request_bytes * 4 + 64 * 1024**2
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                used = self.used_bytes()
                free = shutil.disk_usage(self.root).free
                if (used + sum(self.reservations.values()) + reserve
                        <= self.max_bytes - 1024**2
                        and free >= self.min_free_bytes + reserve):
                    self.reservations[request] = reserve
                    return
            if time.monotonic() >= deadline:
                raise StorageBackpressure('storage_backpressure: durable log buffer full; no upstream sampling started')
            time.sleep(min(1, max(0, deadline - time.monotonic())))

    def release(self, request: str):
        with self.lock:
            self.reservations.pop(request, None)

    def write(self, request: str, name: str, data: bytes):
        if Path(name).name != name:
            raise ValueError('Log record must be a basename')
        with self.lock:
            target = self.root / name
            previous = target.stat().st_size if target.exists() else 0
            remaining = self.reservations[request]
            other = sum(self.reservations.values()) - remaining
            if (len(data) > remaining or self.used_bytes() + len(data) + other
                    > self.max_bytes - 1024**2):
                raise StorageBackpressure('storage_backpressure: record exceeds durable log reservation')
            temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(0o600)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            self.reservations[request] -= max(0, len(data) - previous)

    def append_summary(self, request: str, record: dict):
        data = (json.dumps(record, ensure_ascii=False) + '\n').encode()
        with self.lock:
            target = self.root / 'requests.jsonl'
            if target.exists() and target.stat().st_size >= 8 * 1024**2:
                target.rename(self.root / ('requests_' + uuid.uuid4().hex + '.jsonl'))
            remaining = self.reservations[request]
            if len(data) > remaining or self.used_bytes() + len(data) > self.max_bytes:
                raise StorageBackpressure('storage_backpressure: summary exceeds log reservation')
            with target.open('ab') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.reservations[request] -= len(data)

