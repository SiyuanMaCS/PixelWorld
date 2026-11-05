import json
from pathlib import Path

from pixelworld.constants import (PHYSICS_IQ_COMMIT, PHYSICS_IQ_DATASET_REVISION,
                                  PHYSICS_IQ_INPUTS, REPO_ROOT)


def test_pinned_physics_iq_manifest():
    value = json.loads((REPO_ROOT / "data" / "physics_iq_verified_i2v.json").read_text())
    assert value["count"] == PHYSICS_IQ_INPUTS == 198
    assert value["dataset_revision"] == PHYSICS_IQ_DATASET_REVISION
    assert [case["id"] for case in value["cases"]] == [f"{index:04d}" for index in range(1, 199)]
    assert len({case["source_file"] for case in value["cases"]}) == 198
    assert all(len(case["resized_rgb_sha256"]) == 64 for case in value["cases"])
    assert len(PHYSICS_IQ_COMMIT) == 40
