from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .constants import TRACKS, DEFAULT_TRACKS, DEFAULT_PROTOCOL, LEGACY_TRACK_PROTOCOLS


@dataclass(frozen=True)
class Provider:
    type: str = "builtin"
    id: str | None = None
    name: str | None = None
    base_url: str | None = None
    env_key: str | None = None
    model_catalog_json: str | None = None
    stream_idle_timeout_ms: int | None = None


@dataclass(frozen=True)
class Model:
    key: str
    model: str
    reasoning_effort: str
    provider: Provider
    tracks: tuple[str, ...]
    cli_backend: str = "codex"


@dataclass(frozen=True)
class Benchmark:
    source: Path
    protocol: str
    inputs_root: Path
    runs_root: Path
    max_concurrency: int
    max_per_config: int
    max_attempts: int
    max_total_attempts: int | None
    case_ids: tuple[str, ...] | None
    models: tuple[Model, ...]
    output_token_budget: int | None = None

    def model(self, key: str) -> Model:
        matches = [item for item in self.models if item.key == key]
        if len(matches) != 1:
            raise KeyError(f"Unknown or duplicate model key: {key}")
        return matches[0]


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: str | Path) -> Benchmark:
    source = Path(path).resolve()
    raw = json.loads(source.read_text())
    protocol = raw.get("protocol", DEFAULT_PROTOCOL)
    token_budget = raw.get('output_token_budget', None if protocol in LEGACY_TRACK_PROTOCOLS else 100000)
    if token_budget is not None and (not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 1):
        raise ValueError('output_token_budget must be a positive integer or null')
    default_tracks = TRACKS if protocol in LEGACY_TRACK_PROTOCOLS else DEFAULT_TRACKS
    base = source.parent.parent if source.parent.name == "configs" else source.parent
    models = []
    keys = set()
    for value in raw.get("models", []):
        key = value["key"]
        if key in keys:
            raise ValueError(f"Duplicate model key: {key}")
        keys.add(key)
        provider = Provider(**value.get("provider", {"type": "builtin"}))
        if provider.model_catalog_json:
            from dataclasses import replace
            provider = replace(provider, model_catalog_json=str(_resolve(base, provider.model_catalog_json)))
        if provider.stream_idle_timeout_ms is not None and (
                not isinstance(provider.stream_idle_timeout_ms, int) or isinstance(provider.stream_idle_timeout_ms, bool)
                or provider.stream_idle_timeout_ms <= 0):
            raise ValueError('stream_idle_timeout_ms must be a positive integer')
        if provider.type not in ("builtin", "responses", "oss"):
            raise ValueError(f"Unsupported provider type for {key}: {provider.type}")
        if provider.type == "responses" and not all(
                (provider.id, provider.name, provider.base_url, provider.env_key)):
            raise ValueError(f"Responses provider {key} needs id, name, base_url, and env_key")
        tracks = tuple(value.get("tracks", default_tracks))
        cli_backend = value.get("cli_backend", "codex")
        if cli_backend not in ("codex", "trae"):
            raise ValueError(f"Unknown CLI backend for {key}: {cli_backend}")
        if not tracks or any(track not in TRACKS for track in tracks):
            raise ValueError(f"Invalid tracks for {key}: {tracks}")
        models.append(Model(key=key, model=value["model"],
                            reasoning_effort=value.get("reasoning_effort", "high"),
                            provider=provider, tracks=tracks, cli_backend=cli_backend))
    if not models:
        raise ValueError("At least one model is required")
    result = Benchmark(
        source=source,
        protocol=protocol,
        inputs_root=_resolve(base, raw.get("inputs_root", "data/physics_iq/inputs")),
        runs_root=_resolve(base, raw.get("runs_root", "runs")),
        max_concurrency=int(raw.get("max_concurrency", 4)),
        max_per_config=int(raw.get("max_per_config", 2)),
        max_attempts=int(raw.get("max_attempts", 2)),
        max_total_attempts=(int(raw["max_total_attempts"])
                            if raw.get("max_total_attempts") is not None else None),
        case_ids=tuple(raw["case_ids"]) if raw.get("case_ids") else None,
        models=tuple(models),
        output_token_budget=token_budget,
    )
    if min(result.max_concurrency, result.max_per_config, result.max_attempts) < 1:
        raise ValueError("Concurrency and attempt limits must be positive")
    if result.max_total_attempts is not None and result.max_total_attempts < 1:
        raise ValueError("max_total_attempts must be positive when set")
    return result
