"""Собирает словари по разметке train и справочнику: python scripts/build_resources.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import resources as R  # noqa: E402

labels = [json.loads(line) for line in open(ROOT / "data/train_labels.jsonl", encoding="utf-8")]
raw = R.build(labels, ROOT / "reference/subdivisions.csv")
R.save(raw, ROOT / "model/resources.json")
print("model/resources.json:", {k: len(v) for k, v in raw.items()})
