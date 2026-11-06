from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess

from .config import load_config
from .constants import REPO_ROOT
from .physics_iq import evaluate, setup_evaluator, setup_inputs
from .runner import run_case
from .supervisor import run as run_matrix
from .supervisor import snapshot as matrix_snapshot
from .supervisor import stop as stop_matrix
from .web import build as build_web
from .interaction import run_sequence


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def doctor(config_path: str | None = None) -> dict:
    tools = {}
    for name in ("codex", "git", "ffmpeg", "uv"):
        path = os.environ.get("PIXELWORLD_CODEX") if name == "codex" else shutil.which(name)
        if name == "codex" and not path:
            path = shutil.which(name)
        tools[name] = {"path": path, "ok": bool(path)}
    if tools["codex"]["ok"]:
        tools["codex"]["version"] = subprocess.check_output([tools["codex"]["path"], "--version"], text=True).strip()
        features = subprocess.check_output([tools["codex"]["path"], "features", "list"], text=True)
        tools["codex"]["view_image_feature"] = any(
            line.split()[:1] == ["view_image"] for line in features.splitlines())
    config = None
    if config_path:
        value = load_config(config_path)
        config = {"protocol": value.protocol, "models": len(value.models),
                  "configurations": sum(len(model.tracks) for model in value.models),
                  "inputs_root": value.inputs_root, "runs_root": value.runs_root}
    ok = all(tools[name]["ok"] for name in ("codex", "git", "ffmpeg"))
    return {"ok": ok, "tools": tools, "config": config}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixelworld")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor")
    check.add_argument("--config")

    case = commands.add_parser("run-case")
    case.add_argument("--config", required=True)
    case.add_argument("--model", required=True)
    case.add_argument("--track", required=True, choices=("text", "vision-input", "vision-agent"))
    case.add_argument("--case", required=True)
    case.add_argument("--attempt", type=int, default=1)
    case.add_argument("--codex")
    case.add_argument("--dry-run", action="store_true")
    case.add_argument('--task-file',type=Path,help='Explicit experimental task override, preserved in run metadata')
    case.add_argument('--rules-file',type=Path,help='Explicit experimental rules override')
    case.add_argument('--extra-input',action='append',default=[],help='Named additional input within the prepared case folder')

    sequence = commands.add_parser("run-sequence")
    sequence.add_argument("--config", required=True)
    sequence.add_argument("--model", required=True)
    sequence.add_argument("--track", required=True, choices=("text", "vision-agent"))
    sequence.add_argument("--episode", required=True)

    matrix = commands.add_parser("matrix")
    matrix_commands = matrix.add_subparsers(dest="matrix_command", required=True)
    for name in ("run", "status", "stop"):
        item = matrix_commands.add_parser(name)
        item.add_argument("--config", required=True)
        if name == "run":
            item.add_argument("--interval", type=float, default=5)

    physics = commands.add_parser("physics-iq")
    physics_commands = physics.add_subparsers(dest="physics_command", required=True)
    inputs = physics_commands.add_parser("setup-inputs")
    inputs.add_argument("--inputs-root", type=Path, default=REPO_ROOT / "data/physics_iq/inputs")
    inputs.add_argument("--upstream", type=Path, default=REPO_ROOT / "vendor/physics-IQ-benchmark")
    inputs.add_argument("--cache-root", type=Path)
    inputs.add_argument("--source-dir", type=Path,
                        help="Reuse an existing physics-IQ-benchmark-verified directory")
    evaluator = physics_commands.add_parser("setup-evaluator")
    evaluator.add_argument("--upstream", type=Path, default=REPO_ROOT / "vendor/physics-IQ-benchmark")
    evaluator.add_argument("--benchmark-parent", type=Path,
                           default=REPO_ROOT / "vendor/physics-iq-data")
    evaluator.add_argument("--no-install", action="store_true")
    evaluator.add_argument("--no-download", action="store_true")
    run_eval = physics_commands.add_parser("eval")
    run_eval.add_argument("--config", required=True)
    run_eval.add_argument("--model", required=True)
    run_eval.add_argument("--track", required=True, choices=("text", "vision-input", "vision-agent"))
    run_eval.add_argument("--upstream", type=Path, default=REPO_ROOT / "vendor/physics-IQ-benchmark")
    run_eval.add_argument("--benchmark-parent", type=Path,
                          default=REPO_ROOT / "vendor/physics-iq-data")
    run_eval.add_argument("--output", type=Path, default=REPO_ROOT / "evaluation_outputs")
    run_eval.add_argument("--n-process", type=int, default=8)
    web = commands.add_parser("web")
    web_commands = web.add_subparsers(dest="web_command", required=True)
    web_build = web_commands.add_parser("build")
    web_build.add_argument("--config", required=True)
    web_build.add_argument("--output", type=Path, default=REPO_ROOT / "site")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "doctor":
        value = doctor(args.config)
        _print(value)
        raise SystemExit(0 if value["ok"] else 1)
    if args.command == "run-case":
        value = run_case(load_config(args.config), args.model, args.track, args.case,
                         args.attempt, args.codex, args.dry_run,args.task_file,args.rules_file,tuple(args.extra_input))
        _print(value)
        raise SystemExit(0 if value["status"] in ("complete", "dry-run") else 1)
    if args.command == "run-sequence":
        value = run_sequence(load_config(args.config), args.model, args.track, args.episode)
        _print(value)
        raise SystemExit(0 if value["status"] == "complete" else 1)
    if args.command == "matrix":
        config = load_config(args.config)
        if args.matrix_command == "run":
            run_matrix(config, args.interval)
            _print(matrix_snapshot(config)[0])
        elif args.matrix_command == "status":
            _print(matrix_snapshot(config)[0])
        else:
            stop_matrix(config)
            _print({"stop_requested": True, "path": config.runs_root / "STOP"})
        return
    if args.command == "web":
        _print(build_web(load_config(args.config), args.output))
        return
    if args.physics_command == "setup-inputs":
        value = setup_inputs(args.inputs_root, args.upstream, args.cache_root, args.source_dir)
        _print({key: item for key, item in value.items() if key != "cases"} | {
            "manifest": str(args.inputs_root.resolve().parent / "manifest.json")})
    elif args.physics_command == "setup-evaluator":
        _print(setup_evaluator(args.upstream, args.benchmark_parent,
                               not args.no_install, not args.no_download))
    else:
        config = load_config(args.config)
        _print(evaluate(config, args.model, args.track, args.upstream,
                        args.benchmark_parent, args.output, args.n_process))


if __name__ == "__main__":
    main()
