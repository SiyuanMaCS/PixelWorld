"""External retry authorizations; never exposed in agent workspaces."""
from __future__ import annotations

import fcntl
import json
from pathlib import Path
import re

from .config import Benchmark, Model
from .util import atomic_json, utc_now

_CACHE: dict[Path, tuple[tuple[int, int], dict]] = {}


def ledger_path(config: Benchmark) -> Path:
    return config.runs_root / "retry_authorizations.json"


def ledger(config: Benchmark) -> dict:
    path = ledger_path(config)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"schema_version": 1, "cases": {}}
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(path)
    if cached and cached[0] == signature:
        return cached[1]
    value = json.loads(path.read_text())
    if value.get("schema_version") != 1 or not isinstance(value.get("cases"), dict):
        raise ValueError("Invalid retry authorization ledger")
    _CACHE[path] = (signature, value)
    return value


def windows(config: Benchmark, model: Model, track: str, case: str) -> list[dict]:
    values = ledger(config)["cases"].get(f"{model.key}/{track}/{case}", [])
    for item in values:
        start, end = item.get("start_attempt"), item.get("end_attempt")
        if (not isinstance(start, int) or isinstance(start, bool) or start < 1
                or not isinstance(end, int) or isinstance(end, bool) or end < start):
            raise ValueError("Invalid retry attempt window")
    return values


def latest_window(config: Benchmark, model: Model, track: str, case: str) -> dict | None:
    values = windows(config, model, track, case)
    return values[-1] if values else None


def budget_window(config: Benchmark, model: Model, track: str, case: str, attempt: int) -> dict | None:
    for item in windows(config, model, track, case):
        if item["start_attempt"] <= attempt <= item["end_attempt"]:
            return item
    return None


def authorize_failed(config: Benchmark, extra_attempts: int = 2, max_rounds: int = 1,
                     apply: bool = False) -> dict:
    from .supervisor import case_ids, configurations, inspect
    if extra_attempts < 1 or max_rounds < 1:
        raise ValueError("Retry bounds must be positive")
    config.runs_root.mkdir(parents=True, exist_ok=True)
    path = ledger_path(config)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {"schema_version": 1, "cases": {}}
        _CACHE.pop(path, None)
        granted = []
        for model, track in configurations(config):
            parent = config.runs_root / model.key / track
            existing: dict[str, int] = {}
            if parent.is_dir():
                for child in parent.iterdir():
                    match = re.fullmatch(r"case_(.+)_attempt_(\d+)", child.name)
                    if match:
                        existing[match[1]] = max(existing.get(match[1], 0), int(match[2]))
            for case in case_ids(config):
                key = f"{model.key}/{track}/{case}"
                history = data["cases"].get(key, [])
                if len(history) >= max_rounds or inspect(config, model, track, case)["state"] != "exhausted":
                    continue
                start = max(config.max_attempts, existing.get(case, 0)) + 1
                item = {"round": len(history) + 1, "start_attempt": start,
                        "end_attempt": start + extra_attempts - 1,
                        "authorized_utc": utc_now(), "output_token_budget": config.output_token_budget,
                        "reason": "User authorized retry of failed samples; old artifacts and usage retained."}
                granted.append({"key": key, **item})
                if apply:
                    data["cases"].setdefault(key, []).append(item)
        if apply and granted:
            data["updated_utc"] = utc_now()
            atomic_json(path, data)
            _CACHE.pop(path, None)
        return {"apply": apply, "authorized_cases": len(granted), "items": granted,
                "extra_attempts": extra_attempts, "max_retry_rounds": max_rounds,
                "history_preserved": True}
