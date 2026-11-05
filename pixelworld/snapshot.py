from __future__ import annotations

from pathlib import Path
import argparse
import json
import shutil
import time

from PIL import Image

from .util import atomic_json, sha256, utc_now


def candidate_key(workspace: Path):
    code = workspace / "generate.py"
    pixels = workspace / "pixels.npz"
    inspection = workspace / "inspection.png"
    frames = workspace / "frames"
    if not (code.is_file() and pixels.is_file() and inspection.is_file() and frames.is_dir()):
        return None
    if min(code.stat().st_size, pixels.stat().st_size, inspection.stat().st_size) == 0:
        return None
    if len(list(frames.glob("*.png"))) != 20 or pixels.stat().st_mtime_ns < code.stat().st_mtime_ns:
        return None
    try:
        with Image.open(inspection) as image:
            image.verify()
    except Exception:
        return None
    first = (sha256(code), sha256(pixels), sha256(inspection))
    time.sleep(0.35)
    second = (sha256(code), sha256(pixels), sha256(inspection))
    return first if first == second else None


def freeze(workspace: Path, trace: Path, index: int, key) -> dict:
    target = trace / f"round_{index:03d}"
    temporary = trace / f".round_{index:03d}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    copied = []
    for name in ("generate.py", "pixels.npz", "inspection.png", "transition_check.png",
                 "OBSERVATION.md", "METHOD.md", "index.html"):
        source = workspace / name
        if source.is_file():
            shutil.copy2(source, temporary / name)
            copied.append(name)
    shutil.copytree(workspace / "frames", temporary / "frames")
    copied.append("frames/")
    record = {
        "round": index,
        "utc": utc_now(),
        "generate_sha256": key[0],
        "pixels_sha256": key[1],
        "inspection_sha256": key[2],
        "files": copied,
    }
    atomic_json(temporary / "snapshot.json", record)
    temporary.replace(target)
    with (trace / "rounds.jsonl").open("a") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def watch(workspace: Path, trace: Path, stop_file: Path, interval: float = 0.5) -> None:
    trace.mkdir(parents=True, exist_ok=True)
    seen = set()
    index = 0
    while True:
        key = candidate_key(workspace)
        if key and key not in seen:
            print(json.dumps(freeze(workspace, trace, index, key)), flush=True)
            seen.add(key)
            index += 1
        if stop_file.exists():
            break
        time.sleep(interval)
    atomic_json(trace / "watcher_complete.json", {"completed_utc": utc_now(), "rounds": index})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    watch(args.workspace.resolve(), args.trace.resolve(), args.stop_file.resolve(), args.interval)


if __name__ == "__main__":
    main()
