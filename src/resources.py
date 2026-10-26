"""Словари, которые строятся по разметке train и справочнику подразделений."""
import csv
import json
import re
from collections import Counter, defaultdict

from .pipeline import TEXT_FIELDS, norm

ABBR_RE = re.compile(r"^[А-Я-]{1,5}\.?$")


def build(label_docs, subdivisions_path):
    vocab = {f: Counter() for f in TEXT_FIELDS}
    dot = defaultdict(lambda: [0, 0, 0])  # [с точкой, без точки в середине, без точки в конце]
    for d in label_docs:
        for f in TEXT_FIELDS:
            toks = norm(d["fields"][f]).split()
            for i, t in enumerate(toks):
                vocab[f][t] += 1
                if ABBR_RE.match(t):
                    base = t.rstrip(".")
                    if t.endswith("."):
                        dot[base][0] += 1
                    else:
                        dot[base][1 if i < len(toks) - 1 else 2] += 1
    ref_tokens = Counter()
    for r in csv.DictReader(open(subdivisions_path, encoding="utf-8")):
        toks = norm(r["name"]).split()
        ref_tokens.update(toks)
    return {
        "vocab": {f: dict(c) for f, c in vocab.items()},
        "ref_tokens": dict(ref_tokens),
        "dot": {k: v for k, v in dot.items()},
    }


def save(res, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def deletes(w):
    return {w[:i] + w[i + 1:] for i in range(len(w))}


def edit1(a, b):
    """Расстояние Левенштейна ровно 1."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if b[:i] + b[i + 1:] == a:
            return True
    return False


# пороги уверенности символа по источнику снимка; у mobile_v2 уверенность завышена,
# поэтому пороги для него строже
KNOWN_THR = {"web": 0.9, "mobile": 0.9, "mobile_v2": 0.999}
UNKNOWN_THR = {"web": 0.99, "mobile": 0.99, "mobile_v2": 0.9999}
DOT_THR = {"web": 0.99, "mobile": 0.99, "mobile_v2": 0.9995}
DOT_THR_STRICT = {"web": 0.999, "mobile": 0.999, "mobile_v2": 0.9995}


def prepare(raw, known_thr=None, unknown_thr=None, dot_thr=None, neighbor_min=3, corr_min=20):
    """Готовит словари к работе: функции проверок поверх сырых счетчиков."""
    vocab = raw["vocab"]
    ref = raw["ref_tokens"]
    all_vocab = Counter()
    for c in vocab.values():
        all_vocab.update(c)
    all_vocab.update(ref)
    frequent = {t for t, n in all_vocab.items() if n >= neighbor_min and len(t) >= 3}
    del_index = defaultdict(set)
    for t in frequent:
        del_index[t].add(t)
        for d in deletes(t):
            del_index[d].add(t)

    def known(field, tok):
        return vocab[field].get(tok, 0) > 0 or tok in ref

    def neighbors(tok):
        """Незнакомое слово на расстоянии одной правки от частого слова, скорее всего ошибка OCR."""
        if len(tok) < 3:
            return True
        keys = {tok} | deletes(tok)
        if any(k in del_index for k in keys):
            return True
        return False

    dot = raw["dot"]

    def dot_rule(tok, is_last):
        if tok.endswith(".") or tok not in dot:
            return "ok"
        with_dot, mid, last = dot[tok]
        without = last if is_last else mid
        total = with_dot + without
        if with_dot == 0:
            return "ok"
        share = without / total
        if share == 0 and with_dot >= 20:
            return "add"
        if share < 0.02:
            return "reject"
        if share < 0.9:
            return "ambiguous"
        return "ok"

    # кандидаты ищем среди всех известных слов, а исправляем только на частое слово
    corr_words = {t: n for t, n in all_vocab.items() if len(t) >= 2}
    corr_index = defaultdict(set)
    for t in corr_words:
        corr_index[t].add(t)
        for d in deletes(t):
            corr_index[d].add(t)

    def correct(tok, field):
        """Исправление незнакомого слова на единственное частое слово на расстоянии одной правки."""
        keys = {tok} | deletes(tok)
        cands = set()
        for k in keys:
            cands |= corr_index.get(k, set())
        cands = [c for c in cands if c != tok and edit1(tok, c)]
        # исправляем только длинные слова и только при единственном кандидате
        if len(tok) < 4 or len(cands) != 1 or corr_words[cands[0]] < corr_min:
            return None
        return cands[0]

    return {
        "correct": correct,
        "known": known,
        "neighbors": neighbors,
        "dot_rule": dot_rule,
        "known_thr": known_thr or KNOWN_THR,
        "unknown_thr": unknown_thr or UNKNOWN_THR,
        "dot_thr": dot_thr or DOT_THR,
    }
