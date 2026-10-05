import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_hash_probe():
    for rel in ("scripts/g1_swarm_controller.py","tests/test_g1_swarm_controller.py"):
        print("HASH_PROBE", rel, hashlib.sha256((ROOT/rel).read_bytes()).hexdigest())
    assert False, "temporary hash probe"
