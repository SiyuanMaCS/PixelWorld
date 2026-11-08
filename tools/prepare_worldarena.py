#!/usr/bin/env python3
"""Pinned WorldArena Track 1 text I2V inputs. Never extract reference futures.

latest2026-03-06 is a release label, not an HF branch. The immutable pin below
is the last commit on that release date, after the test archive upload.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

from PIL import Image

SOURCE_COMMIT = "2da2ae253b8637ba9de3afc7bea4e087f778ee4d"
DATASET_REPO = "WorldArena/WorldArena_Robotwin2.0"
DATASET_RELEASE = "latest2026-03-06"
DATASET_REVISION = "38ba38353df9a339dd533dcfafed71edbe985b7a"
ARCHIVE_SHA256 = "edba2131a11a94682a774094e02e28d6a3efb311c5cc42710cab5b43e095fc5d"
ARCHIVE_SIZE = 56632689
SPEC = {"task_type": "i2v", "width": 640, "height": 480,
        "frames": 121, "fps": 24, "audio": None, "benchmark": "worldarena-track1-text"}
OFFICIAL_PREFIX = ("In a fixed robotic workspace, generate a rigid, physically consistent embodied robotic arm. "
                   "The arm maintains high stability with no deformation and enters the frame to ")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def archive_index(tar: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    """Strip the publisher's archive root; never trust/extract archive paths."""
    result = {}
    for m in tar.getmembers():
        p = PurePosixPath(m.name)
        if p.is_absolute() or ".." in p.parts or m.issym() or m.islnk():
            raise ValueError("Unsafe archive member")
        if not m.isfile():
            continue
        if p.parts.count("test_dataset") != 1:
            raise ValueError("Unexpected dataset root")
        key = "/".join(p.parts[p.parts.index("test_dataset") + 1:])
        if key in result:
            raise ValueError("Duplicate archive member")
        result[key] = m
    return result


def episode_inventory(index: dict) -> list[str]:
    roles = ("instructions", "instructions_1", "instructions_2", "first_frame", "data")
    sets = {}
    for role in roles:
        selected = {Path(k).stem for k in index if k.startswith(role + "/fixed_scene_task/")}
        if any(not re.fullmatch(r"episode[1-9][0-9]*", x) for x in selected):
            raise ValueError("Invalid episode identity")
        sets[role] = selected
    expected = {f"episode{i}" for i in range(1, 1001)}
    if any(s != expected for s in sets.values()) or len(index) != 5000:
        raise ValueError("March 6 archive must contain exactly 1000 aligned episodes / 5000 files")
    return sorted(expected, key=lambda s: int(s[7:]))


def prepare(archive: Path, output: Path, episode: str = "episode1") -> dict:
    if archive.stat().st_size != ARCHIVE_SIZE or sha256(archive) != ARCHIVE_SHA256:
        raise ValueError("Dataset archive does not match the March 6 pin")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Legal input directory must be empty (no stale/reference files)")
    with tarfile.open(archive, "r:gz") as tar:
        index = archive_index(tar)
        ids = episode_inventory(index)
        if episode not in ids:
            raise ValueError("Episode is not in official TEST inventory")
        image_key = f"first_frame/fixed_scene_task/{episode}.png"
        prompt_key = f"instructions/fixed_scene_task/{episode}.json"
        image_bytes = tar.extractfile(index[image_key]).read()
        prompt_bytes = tar.extractfile(index[prompt_key]).read()
    instruction = json.loads(prompt_bytes)
    if set(instruction) != {"instruction"} or not isinstance(instruction["instruction"], str):
        raise ValueError("Unexpected official instruction schema")
    prompt = instruction["instruction"]
    if not prompt.startswith(OFFICIAL_PREFIX) or prompt.count(OFFICIAL_PREFIX) != 1:
        raise ValueError("Official source prefix missing or duplicated")
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if image.size != (320, 240):
        raise ValueError("Unexpected source initial image dimensions")
    output.mkdir(parents=True, exist_ok=True)
    # Deterministic non-learned upsampling of initial image only; no future data.
    image.resize((640, 480), Image.Resampling.LANCZOS).save(output / "first_frame.png")
    (output / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(output / "task_spec.json", SPEC)
    provenance = {
        "protocol": "worldarena-track1-text-i2v-pinned-v1", "scope": "one-episode-input-smoke",
        "source_commit": SOURCE_COMMIT, "dataset_repo": DATASET_REPO,
        "dataset_release": DATASET_RELEASE, "dataset_revision": DATASET_REVISION,
        "archive_sha256": ARCHIVE_SHA256, "official_test_count": len(ids),
        "episode": episode, "task": "fixed_scene_task", "split": "TEST",
        "submission_filename": f"fixed_scene_task_episode_{episode[7:]}.mp4",
        "instruction_member": prompt_key, "first_frame_member": image_key,
        "source_image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "source_instruction_json_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "prompt_sha256": sha256(output / "prompt.txt"),
        "first_frame_sha256": sha256(output / "first_frame.png"),
        "task_spec_sha256": sha256(output / "task_spec.json"),
        "prefix_policy": "verbatim-original-instruction-including-official-prefix; no added prefix",
        "resize": "320x240 to 640x480 Pillow LANCZOS RGB", "reference_future_accessed": False,
        "legal_files": ["first_frame.png", "prompt.txt", "task_spec.json"],
    }
    # Provenance/inventory live outside the generation-visible legal directory.
    write_json(output.parent / "input_provenance.json", provenance)
    write_json(output.parent / "test_inventory.json", {
        "dataset_revision": DATASET_REVISION, "archive_sha256": ARCHIVE_SHA256,
        "count": len(ids), "episodes": ids, "task": "fixed_scene_task"})
    return provenance


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--episode", default="episode1")
    args = p.parse_args()
    prepare(args.archive, args.output, args.episode)
    print(f"LEGAL_INPUT_READY {args.output.resolve()}")


if __name__ == "__main__":
    main()
