import json
from pathlib import Path

from PIL import Image

from pixelworld.config import load_config
from pixelworld.interaction import run_sequence
from pixelworld.runner import run_path


def test_each_turn_is_fresh_and_receives_only_generated_last_frame(tmp_path, monkeypatch):
    source = tmp_path / "inputs" / "episode"
    source.mkdir(parents=True)
    Image.new("RGB", (32, 24), "black").save(source / "first_frame.png")
    (source / "task_spec.json").write_text(json.dumps({"width":32,"height":24,"frames":2,"fps":1}))
    plan = [{"action":"W", "prompt":"Move forward."},
            {"action":"right", "prompt":"Rotate right."}]
    (source / "interactions.json").write_text(json.dumps(plan))
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"inputs_root":"inputs","runs_root":"runs", "models":[
        {"key":"model", "model":"example", "tracks":["vision-agent"]}]}))
    config = load_config(path)
    observed = []
    def fake(cfg, model, track, case):
        folder = cfg.inputs_root / case
        observed.append((set(p.name for p in folder.iterdir()),
                         (folder / "prompt.txt").read_text(),
                         Image.open(folder / "first_frame.png").getpixel((0,0))))
        run = run_path(cfg, cfg.model(model), track, case, 1)
        frames = run / "workspace" / "frames"
        frames.mkdir(parents=True)
        Image.new("RGB", (32,24), "red").save(frames / "01.png")
        (run / "workspace" / "generate.py").write_text("# prior code must stay private\n")
        return {"status":"complete"}
    monkeypatch.setattr("pixelworld.interaction.run_case", fake)
    result = run_sequence(config, "model", "vision-agent", "episode")
    assert result["status"] == "complete"
    assert observed == [({"first_frame.png","prompt.txt","task_spec.json"},"Move forward.",(0,0,0)),
                        ({"first_frame.png","prompt.txt","task_spec.json"},"Rotate right.",(255,0,0))]
    assert result["turns"][1]["input_sha256"] == result["turns"][0]["last_frame_sha256"]
