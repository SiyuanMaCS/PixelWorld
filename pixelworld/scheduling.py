"""Optional shared launch limit for concurrent benchmark supervisors."""
from contextlib import contextmanager
import fcntl
import json
import shlex
import subprocess


@contextmanager
def launch_guard(config):
    root = config.runs_root.parent.parent
    settings = root / "scheduling_limits.json"
    if not settings.is_file():
        yield None, {}
        return
    limit = json.loads(settings.read_text())["max_per_model"]
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("Shared model concurrency must be a positive integer")
    with settings.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        counts = {}
        for line in subprocess.check_output(["ps", "-eo", "args="], text=True).splitlines():
            try:
                tokens = shlex.split(line)
                if not any(tokens[i:i+3] == ["-m", "pixelworld.cli", "run-case"]
                           for i in range(len(tokens)-2)):
                    continue
                from pathlib import Path
                source = Path(tokens[tokens.index("--config") + 1]).resolve()
                if not source.is_relative_to(root.resolve()):
                    continue
                model = tokens[tokens.index("--model") + 1]
                counts[model] = counts.get(model, 0) + 1
            except (ValueError, IndexError):
                continue
        yield limit, counts
