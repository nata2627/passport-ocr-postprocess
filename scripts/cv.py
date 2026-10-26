"""Кросс-валидация на train: словари строятся по 4 фолдам, решение проверяется на пятом."""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import resources as R  # noqa: E402
from src.pipeline import FIELDS, GRACE_DAYS, Decider, norm, parse_date, passport_valid  # noqa: E402


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def run(k=5, seed=0, verbose=False, **kw):
    preds = load(ROOT / "data/train_predictions.jsonl")
    labels = {d["doc_id"]: d for d in load(ROOT / "data/train_labels.jsonl")}
    ids = [p["doc_id"] for p in preds]
    random.Random(seed).shuffle(ids)
    fold = {d: i % k for i, d in enumerate(ids)}
    acc = good = bad = 0
    by_src = Counter()
    reasons = Counter()
    errors = []
    for f in range(k):
        train_labels = [labels[d] for d in ids if fold[d] != f]
        raw = R.build(train_labels, ROOT / "reference/subdivisions.csv")
        dec = Decider(R.prepare(raw), grace_days=0 if kw.get("no_grace") else GRACE_DAYS)
        for p in preds:
            if fold[p["doc_id"]] != f:
                continue
            ok, fields, why = dec.decide(p)
            for r in why:
                reasons[r.split(":")[0] + ":" + r.split(":")[1] if ":" in r else r] += 1
            if not ok:
                continue
            acc += 1
            by_src[(p["source"], "acc")] += 1
            g = labels[p["doc_id"]]["fields"]
            wrong = [x for x in FIELDS if norm(fields[x]) != norm(g[x])]
            valid = passport_valid(parse_date(g["Birth_date"]), parse_date(g["Issue_date"]))
            if wrong or not valid:
                bad += 1
                by_src[(p["source"], "bad")] += 1
                errors.append((p["doc_id"], p["source"], wrong, [(fields[x], g[x]) for x in wrong], valid))
            else:
                good += 1
    print(f"принято {acc} из {len(preds)}, верно {good}, с ошибкой {bad}")
    total = Counter(p["source"] for p in preds)
    for src in sorted(total):
        print(f"  {src:10s} документов {total[src]:5d}, принято {by_src[(src, 'acc')]:5d}, "
              f"с ошибкой {by_src[(src, 'bad')]}")
    if verbose:
        for r, n in reasons.most_common(25):
            print(f"  {n:5d} {r}")
        for e in errors:
            print("  ERR", e)
    run.by_src, run.total, run.errors = by_src, total, errors
    return acc, good, bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", action="store_true", help="причины отказов и список ошибок")
    ap.add_argument("--no-grace", action="store_true", help="без 90-дневного окна, как в postprocess.py")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    run(seed=a.seed, verbose=a.v, no_grace=a.no_grace)
