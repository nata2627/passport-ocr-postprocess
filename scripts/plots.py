"""Рисует графики для отчета в figures/: python scripts/plots.py

Только стандартная библиотека, SVG пишется вручную."""
import contextlib
import difflib
import io
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import cv  # noqa: E402
from src.pipeline import FIELDS, NAME_FIELDS, viz_text  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = {"web": "#2a78d6", "mobile": "#eb6834", "mobile_v2": "#1baf7a"}
FONT = "font-family='-apple-system,Segoe UI,Helvetica,Arial,sans-serif'"
BUCKETS = [(0, 0.5, "&lt; 0.5"), (0.5, 0.9, "0.5-0.9"), (0.9, 0.99, "0.9-0.99"),
           (0.99, 0.999, "0.99-0.999"), (0.999, 1.01, "≥ 0.999")]


def text(x, y, s, size=12, color=INK2, anchor="start", weight="normal"):
    return (f"<text x='{x:.1f}' y='{y:.1f}' {FONT} font-size='{size}' fill='{color}' "
            f"text-anchor='{anchor}' font-weight='{weight}'>{s}</text>")


def bar(x, y0, y1, w, color):
    """Столбик со скругленным верхом, низ прижат к оси."""
    h = y0 - y1
    r = min(4, h / 2, w / 2)
    return (f"<path d='M{x:.1f},{y0:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 + r:.1f} V{y0:.1f} Z' "
            f"fill='{color}'/>")


def calibration():
    """Доля неверно прочитанных символов по корзинам уверенности и источникам."""
    preds = cv.load(ROOT / "data/train_predictions.jsonl")
    labels = {d["doc_id"]: d["fields"] for d in cv.load(ROOT / "data/train_labels.jsonl")}
    st = defaultdict(lambda: [0, 0])
    for p in preds:
        g = labels[p["doc_id"]]
        for f in FIELDS:
            t, conf = viz_text(p["viz"].get(f))
            if not t or not g[f]:
                continue
            wrong = set()
            sm = difflib.SequenceMatcher(None, t, g[f].upper(), autojunk=False)
            for op, i1, i2, _, _ in sm.get_opcodes():
                if op in ("replace", "delete"):
                    wrong.update(range(i1, i2))
            for i, c in enumerate(conf):
                if t[i] == " ":
                    continue
                b = next(k for k, (lo, hi, _) in enumerate(BUCKETS) if lo <= c < hi)
                st[(p["source"], b)][0] += 1
                st[(p["source"], b)][1] += i in wrong
    return st


def plot_calibration(st, path):
    W, H = 720, 360
    left, right, top, bottom = 70, 20, 64, 300
    lo, hi = -2.5, 2  # логарифм доли ошибок в процентах: от 0.003% до 100%
    y = lambda pct: bottom - (math.log10(max(pct, 10 ** lo)) - lo) / (hi - lo) * (bottom - top)
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' viewBox='0 0 {W} {H}'>",
           f"<rect width='{W}' height='{H}' fill='{SURFACE}'/>",
           text(left - 60, 24, "Доля ошибочных символов по уверенности модели", 15, INK, weight="600"),
           text(left - 60, 44, "train, все поля визуальной зоны; шкала логарифмическая", 12)]
    for pct, lab in [(0.01, "0,01%"), (0.1, "0,1%"), (1, "1%"), (10, "10%"), (100, "100%")]:
        yy = y(pct)
        out.append(f"<line x1='{left}' x2='{W - right}' y1='{yy:.1f}' y2='{yy:.1f}' stroke='{GRID}'/>")
        out.append(text(left - 8, yy + 4, lab, 11, INK2, "end"))
    gw = (W - left - right) / len(BUCKETS)
    bw = 22
    for b, (_, _, lab) in enumerate(BUCKETS):
        x0 = left + b * gw + (gw - 3 * bw - 4) / 2
        for k, src in enumerate(SERIES):
            n, e = st[(src, b)]
            if n < 30:
                continue
            pct = 100 * e / n
            bx = x0 + k * (bw + 2)
            out.append(bar(bx, bottom, y(pct), bw, SERIES[src]))
            if src == "mobile_v2" and b == 2:
                out.append(text(bx + bw / 2, y(pct) - 8, f"{pct:.0f}%", 12, INK, "middle", "600"))
            if src == "web" and b == 2:
                out.append(text(bx + bw / 2, y(pct) - 8, f"{pct:.1f}%".replace(".", ","), 11, INK2, "middle"))
        out.append(text(left + b * gw + gw / 2, bottom + 20, lab, 12, INK2, "middle"))
    out.append(f"<line x1='{left}' x2='{W - right}' y1='{bottom}' y2='{bottom}' stroke='{INK2}'/>")
    out.append(text(left + (W - left - right) / 2, bottom + 42, "уверенность символа", 12, INK2, "middle"))
    lx = W - right - 270
    for k, src in enumerate(SERIES):
        out.append(f"<rect x='{lx + k * 90}' y='16' width='12' height='12' rx='2' fill='{SERIES[src]}'/>")
        out.append(text(lx + k * 90 + 18, 27, src, 12, INK))
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def tradeoff():
    res = {}
    for name, strict in [("обычный", False), ("--strict", True)]:
        with contextlib.redirect_stdout(io.StringIO()):
            acc, good, bad = cv.run(seed=0, strict=strict)
        noise = sum(1 for e in cv.run.errors if set(e[2]) <= set(NAME_FIELDS) and e[4])
        res[name] = (acc, bad - noise, noise)
    return res


def plot_tradeoff(res, path):
    W, H = 760, 250
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' viewBox='0 0 {W} {H}'>",
           f"<rect width='{W}' height='{H}' fill='{SURFACE}'/>",
           text(10, 24, "Принятые документы и ошибки среди них, кросс-валидация на train (3000)", 15, INK, weight="600")]
    # левая панель: принято
    px, pw, top = 100, 270, 70
    out.append(text(10, 56, "Принято документов", 12, INK, weight="600"))
    xmax = 1600
    for v in (0, 500, 1000, 1500):
        xx = px + v / xmax * pw
        out.append(f"<line x1='{xx:.1f}' x2='{xx:.1f}' y1='{top - 6}' y2='{top + 110}' stroke='{GRID}'/>")
        out.append(text(xx, top + 126, str(v), 11, INK2, "middle"))
    for i, (name, (acc, real, noise)) in enumerate(res.items()):
        yy = top + 12 + i * 52
        out.append(text(px - 10, yy + 18, name, 12, INK, "end"))
        w = acc / xmax * pw
        out.append(f"<rect x='{px}' y='{yy}' width='{w:.1f}' height='26' rx='4' fill='{SERIES['web']}'/>")
        out.append(text(px + w + 6, yy + 18, str(acc), 12, INK, weight="600"))
    # правая панель: ошибки, стопка из промахов и шума разметки
    qx, qw = 520, 190
    out.append(text(qx - 70, 56, "Ошибок среди принятых", 12, INK, weight="600"))
    emax = 15
    for v in (0, 5, 10, 15):
        xx = qx + v / emax * qw
        out.append(f"<line x1='{xx:.1f}' x2='{xx:.1f}' y1='{top - 6}' y2='{top + 110}' stroke='{GRID}'/>")
        out.append(text(xx, top + 126, str(v), 11, INK2, "middle"))
    for i, (name, (acc, real, noise)) in enumerate(res.items()):
        yy = top + 12 + i * 52
        out.append(text(qx - 10, yy + 18, name, 12, INK, "end"))
        w1 = real / emax * qw
        w2 = noise / emax * qw
        out.append(f"<rect x='{qx}' y='{yy}' width='{w1:.1f}' height='26' rx='3' fill='{SERIES['mobile']}'/>")
        out.append(f"<rect x='{qx + w1 + 2:.1f}' y='{yy}' width='{max(w2 - 2, 0):.1f}' height='26' rx='3' "
                   f"fill='{SERIES['mobile']}' fill-opacity='0.35'/>")
        out.append(text(qx + w1 + w2 + 6, yy + 18, f"{real} + {noise}", 12, INK, weight="600"))
    ly = H - 24
    out.append(f"<rect x='{qx - 70}' y='{ly - 10}' width='12' height='12' rx='2' fill='{SERIES['mobile']}'/>")
    out.append(text(qx - 52, ly, "промахи решения", 12, INK))
    out.append(f"<rect x='{qx + 70}' y='{ly - 10}' width='12' height='12' rx='2' fill='{SERIES['mobile']}' fill-opacity='0.35'/>")
    out.append(text(qx + 88, ly, "шум разметки в ФИО", 12, INK))
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")
    return res


if __name__ == "__main__":
    (ROOT / "figures").mkdir(exist_ok=True)
    plot_calibration(calibration(), ROOT / "figures/calibration.svg")
    print(plot_tradeoff(tradeoff(), ROOT / "figures/tradeoff.svg"))
