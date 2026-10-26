"""Постобработка OCR паспорта РФ.

python postprocess.py data/test_predictions.jsonl answers.jsonl [--strict]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from src import resources as R  # noqa: E402
from src.pipeline import Decider  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("answers")
    ap.add_argument("--strict", action="store_true",
                    help="строже к сокращениям без точки: меньше принятых, меньше риск ошибки")
    ap.add_argument("--reasons", help="записать причины отказов в этот файл")
    args = ap.parse_args()

    raw = R.load(ROOT / "model/resources.json")
    dec = Decider(R.prepare(raw, dot_thr=R.DOT_THR_STRICT if args.strict else R.DOT_THR))

    stats = Counter()
    reasons_out = open(args.reasons, "w", encoding="utf-8") if args.reasons else None
    with open(args.predictions, encoding="utf-8") as src, \
            open(args.answers, "w", encoding="utf-8") as dst:
        for line in src:
            p = json.loads(line)
            ok, fields, why = dec.decide(p)
            ans = {"doc_id": p["doc_id"], "decision": "accept" if ok else "reject"}
            if ok:
                ans["fields"] = fields
            dst.write(json.dumps(ans, ensure_ascii=False) + "\n")
            stats[ans["decision"]] += 1
            if reasons_out and not ok:
                reasons_out.write(json.dumps({"doc_id": p["doc_id"], "reasons": why},
                                             ensure_ascii=False) + "\n")
    if reasons_out:
        reasons_out.close()
    print(f"accept {stats['accept']}, reject {stats['reject']}")


if __name__ == "__main__":
    main()
