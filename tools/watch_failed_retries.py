"""Authorize one bounded extra retry round for terminal failed cases."""
from pathlib import Path
import argparse
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pixelworld.config import load_config
from pixelworld.retries import authorize_failed
from pixelworld.util import atomic_json, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--extra-attempts", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--status", type=Path)
    args = parser.parse_args()
    if args.interval < 1:
        raise ValueError("Watch interval must be positive")
    while True:
        reports = []
        for path in args.config:
            config = load_config(path)
            if (config.runs_root / "STOP").exists():
                reports.append({"config": str(path), "phase": "explicitly_stopped"})
                continue
            result = authorize_failed(config, args.extra_attempts, args.max_rounds, args.apply)
            reports.append({"config": str(path), **result})
        result = {"updated_utc": utc_now(), "reports": reports}
        if args.status:
            atomic_json(args.status, result)
        print(json.dumps({"updated_utc": result["updated_utc"],
                          "configs": [{"config": r["config"], "authorized_cases": r.get("authorized_cases", 0),
                                       "phase": r.get("phase")} for r in reports]}), flush=True)
        if not args.watch:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
