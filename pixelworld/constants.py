from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = Path(__file__).resolve().parent / "assets"

WIDTH = 256
HEIGHT = 144
FRAMES = 20
FPS = 4
DURATION_SECONDS = 5
TENSOR_SHAPE = (HEIGHT, WIDTH, FRAMES)

PHYSICS_IQ_REPO = "https://github.com/google-deepmind/physics-IQ-benchmark.git"
PHYSICS_IQ_COMMIT = "d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48"
PHYSICS_IQ_DATASET = "Anates-Labs-Research/Physics-IQ-Verified"
PHYSICS_IQ_DATASET_REVISION = "b65f567dd8446a4076c7f72446335b3c217a8464"
PHYSICS_IQ_DESCRIPTIONS_SHA256 = "20ffd208acc0b0f50d4638d1da69218168e78336e96118244a53d0ae046729c8"
PHYSICS_IQ_INPUTS = 198

TRACKS = ("text", "vision-input", "vision-agent")
DEFAULT_TRACKS = ("text", "vision-agent")
DEFAULT_PROTOCOL = "pixelworld-v2"
LEGACY_TRACK_PROTOCOLS = {"pixelworld-v1", "pixelworld-physics-iq-v1", "pixelworld-smoke-v1"}
