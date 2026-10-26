"""Решение accept/reject по одному документу и сборка значений полей."""
import difflib
import re
from datetime import date

from . import mrz as M

FIELDS = ["Last_name_ru", "First_name_ru", "Middle_name_ru", "Sex_ru", "Birth_date",
          "Birth_place_ru", "Issue_date", "Issue_organisation_code", "Licence_number",
          "Issue_organization_ru"]
NAME_FIELDS = ["Last_name_ru", "First_name_ru", "Middle_name_ru"]
TEXT_FIELDS = ["Birth_place_ru", "Issue_organization_ru"]
REF_DATE = date(2026, 10, 1)

DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def norm(s):
    return " ".join(str(s or "").split()).upper()


def parse_date(s):
    if not s or not DATE_RE.fullmatch(s):
        return None
    d, m, y = map(int, s.split("."))
    try:
        return date(y, m, d)
    except ValueError:
        return None


def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def passport_valid(birth, issue, ref=REF_DATE):
    """Паспорт действителен, если выдан не раньше последнего пройденного рубежа 14, 20 или 45 лет.
    Старый паспорт в первые 90 дней после 20 и 45 лет тоже считаем недействительным:
    случай спорный, а ошибочный accept дороже лишнего reject."""
    if birth is None or issue is None or issue > ref or issue < birth:
        return False
    passed = [m for m in (14, 20, 45) if add_years(birth, m) <= ref]
    if not passed:
        return False
    return issue >= add_years(birth, max(passed))


class Field:
    def __init__(self, value=None, ok=False, reason=""):
        self.value, self.ok, self.reason = value, ok, reason


def viz_text(v):
    if not v or not v.get("lines"):
        return None, []
    text = " ".join(ln["text"] for ln in v["lines"])
    conf = []
    for i, ln in enumerate(v["lines"]):
        conf += list(ln["char_conf"])
        if i < len(v["lines"]) - 1:
            conf.append(1.0)
    return text, conf


def geometry_ok(v):
    """Ищем пропущенную строку: большой пустой зазор в рамке поля сверху, снизу или между строк."""
    x, y, w, h = v["box"]
    boxes = sorted((ln["box"][1], ln["box"][1] + ln["box"][3]) for ln in v["lines"])
    lh = max(ln["box"][3] for ln in v["lines"])
    gaps = [boxes[0][0] - y, y + h - boxes[-1][1]]
    gaps += [boxes[i + 1][0] - boxes[i][1] for i in range(len(boxes) - 1)]
    return max(gaps) / lh < 0.5


class Decider:
    def __init__(self, resources):
        self.r = resources

    # ---------- поля, продублированные в MRZ ----------
    def mrz_fields(self, p, m, out):
        good2 = bool(m and m.get("len_ok") and m["nat_ok"] and m["final_ok"])
        trusted = {
            "Licence_number": m.get("series_number") if good2 and m["num_ok"] and m["opt_ok"] else None,
            "Birth_date": m.get("birth_date") if good2 and m["birth_ok"] else None,
            "Issue_date": m.get("issue_date") if good2 and m["opt_ok"] else None,
            "Issue_organisation_code": m.get("code") if good2 and m["opt_ok"] else None,
        }
        for f, mv in trusted.items():
            v = p["viz"].get(f)
            text, _ = viz_text(v)
            if mv is not None and m.get("repaired") and norm(text) != mv:
                out[f] = Field(text, False, "repaired_mrz_disagrees")
            elif mv is not None:
                # контрольные цифры MRZ сошлись: значение надежнее визуальной зоны
                out[f] = Field(mv, True, "mrz" if norm(text) == mv else "mrz_override")
            else:
                # без MRZ визуальная зона ошибается примерно в 0,5% полей даже при высокой
                # уверенности, для четырех полей сразу это слишком много
                out[f] = Field(text, False, "no_mrz_confirmation")
        for f in ("Birth_date", "Issue_date"):
            if out[f].ok and parse_date(out[f].value) is None:
                out[f].ok, out[f].reason = False, "bad_date"

    # ---------- ФИО и пол ----------
    def names(self, p, out):
        """ФИО сверяем со строкой 1 MRZ. Расхождение в одном месте разрешаем в пользу более
        уверенного чтения, если второе чтение явно неуверенное."""
        raw = (p.get("mrz") or {}).get("lines") or []
        vals, confs = {}, {}
        for f in NAME_FIELDS:
            vals[f], confs[f] = viz_text(p["viz"].get(f))
        if not raw or not raw[0]["text"].startswith("PNRUS"):
            for f in NAME_FIELDS:
                out[f] = Field(vals[f], False, "no_mrz_line1")
            return
        l1, c1 = raw[0]["text"], raw[0]["char_conf"]
        body = l1[5:].rstrip("<")
        bconf = c1[5:5 + len(body)]
        if vals["Last_name_ru"] is None or vals["First_name_ru"] is None:
            self.names_from_mrz(body, l1, vals, out)
            return
        lat = [M.to_lat(vals[f] or "") for f in NAME_FIELDS]
        if None in lat:
            for f in NAME_FIELDS:
                out[f] = Field(vals[f], False, "names_not_translit")
            return
        exp = lat[0] + "<<" + lat[1] + ("<" + lat[2] if lat[2] else "")
        econf = confs["Last_name_ru"] + [1.0, 1.0] + confs["First_name_ru"]
        if lat[2]:
            econf += [1.0] + confs["Middle_name_ru"]
        truncated = len(l1) >= 44 and 5 + len(exp) > 44 and exp.startswith(body)
        if body == exp or truncated:
            for f in NAME_FIELDS:
                out[f] = Field(vals[f] or "", True, "viz=mrz")
            return
        # у mobile_v2 уверенность не откалибрована, расхождение не разрешаем
        if p["source"] == "mobile_v2":
            for f in NAME_FIELDS:
                out[f] = Field(vals[f], False, "names_mismatch")
            return
        ops = [o for o in difflib.SequenceMatcher(None, exp, body, autojunk=False).get_opcodes()
               if o[0] != "equal"]
        merged = []
        prev = 0
        for op, i1, i2, j1, j2 in ops:
            merged.append(exp[prev:i1])
            vmin = min(econf[max(0, i1 - 1):i2 + 1] or [1.0])
            mmin = min(bconf[max(0, j1 - 1):j2 + 1] or [1.0])
            if vmin >= 0.99 and mmin < 0.9:
                merged.append(exp[i1:i2])
            elif mmin >= 0.99 and vmin < 0.9:
                merged.append(body[j1:j2])
            else:
                for f in NAME_FIELDS:
                    out[f] = Field(vals[f], False, "names_mismatch")
                return
            prev = i2
        merged.append(exp[prev:])
        merged = "".join(merged)
        if merged == exp:
            for f in NAME_FIELDS:
                out[f] = Field(vals[f] or "", True, "viz_over_mrz")
            return
        parsed = self.split_names(merged, vals)
        if parsed is None:
            for f in NAME_FIELDS:
                out[f] = Field(vals[f], False, "names_mismatch")
            return
        for f in NAME_FIELDS:
            out[f] = Field(parsed[f], True, "mrz_over_viz")

    @staticmethod
    def split_names(latin, vals):
        """Латиница MRZ -> три поля; только для имен без пробелов и дефисов."""
        if any(v and (" " in v or "-" in v) for v in vals.values()):
            return None
        if latin.count("<<") != 1:
            return None
        last, rest = latin.split("<<")
        parts = rest.split("<")
        if "<" in last or len(parts) > 2 or not all(parts):
            return None
        cyr = [M.to_cyr(x) for x in [last] + parts]
        if None in cyr:
            return None
        return {"Last_name_ru": cyr[0], "First_name_ru": cyr[1],
                "Middle_name_ru": cyr[2] if len(cyr) > 2 else ""}

    def names_from_mrz(self, body, l1, vals, out):
        """Фамилия или имя не найдены в визуальной зоне: берем ФИО из MRZ, если найденные поля
        с ней совпадают и строка не обрезана."""
        parsed = self.split_names(body, vals) if len(body) + 5 < 44 else None
        if parsed:
            if all(vals[f] is None or norm(vals[f]) == norm(parsed[f]) for f in NAME_FIELDS):
                for f in NAME_FIELDS:
                    out[f] = Field(parsed[f], True, "mrz_names")
                return
        for f in NAME_FIELDS:
            out[f] = Field(vals[f], False, "names_missing")

    def sex(self, p, m, out):
        text, conf = viz_text(p["viz"].get("Sex_ru"))
        msex = m.get("sex") if m and m.get("len_ok") else None
        if text in ("МУЖ.", "ЖЕН.") and text == msex:
            out["Sex_ru"] = Field(text, True, "viz=mrz")
            return
        mid = out["Middle_name_ru"].value if out["Middle_name_ru"].ok else None
        by_patr = None
        if mid:
            if mid.endswith(("ВИЧ", "ИЧ", "ОГЛЫ", "УЛЫ")):
                by_patr = "МУЖ."
            elif mid.endswith(("ВНА", "ЧНА", "ИНИЧНА", "КЫЗЫ", "ГЫЗЫ")):
                by_patr = "ЖЕН."
        for cand in (msex, text):
            if cand in ("МУЖ.", "ЖЕН.") and cand == by_patr:
                out["Sex_ru"] = Field(cand, True, "patronymic")
                return
        out["Sex_ru"] = Field(text, False, "sex_unconfirmed")

    # ---------- место рождения и орган выдачи ----------
    def text_field(self, p, f, out):
        v = p["viz"].get(f)
        text, conf = viz_text(v)
        if not text:
            out[f] = Field(None, False, "missing")
            return
        if not geometry_ok(v):
            out[f] = Field(text, False, "missing_line")
            return
        src = p["source"]
        known_thr = self.r["known_thr"].get(src, 0.9)
        unknown_thr = self.r["unknown_thr"].get(src, 0.999)
        known = self.r["known"]
        fixed = []
        toks = list(re.finditer(r"\S+", text))
        for i, m in enumerate(toks):
            tok, tc = m.group(), conf[m.start():m.end()]
            is_last = i == len(toks) - 1
            dot = self.r["dot_rule"](tok, is_last)
            if dot == "add":
                # модель потеряла точку после сокращения, в разметке оно всегда с точкой
                tok = tok + "."
            elif dot == "reject" or (dot == "ambiguous" and tc[-1] < self.r["dot_thr"].get(src, 0.99)):
                # потерянная точка роняет уверенность в предыдущей букве
                out[f] = Field(text, False, f"dot:{tok}")
                return
            if known(f, tok):
                if min(tc) < known_thr:
                    out[f] = Field(text, False, f"low_conf:{tok}")
                    return
            else:
                if min(tc) < unknown_thr:
                    fixed_tok = self.try_correct(tok, tc, f)
                    if fixed_tok is None:
                        out[f] = Field(text, False, f"unknown_low_conf:{tok}")
                        return
                    fixed.append(fixed_tok)
                    continue
                if self.r["neighbors"](tok):
                    out[f] = Field(text, False, f"near_known:{tok}")
                    return
            fixed.append(tok)
        out[f] = Field(" ".join(fixed), True, "vocab")

    def try_correct(self, tok, tc, f):
        """Исправляем слово, только если правка приходится на неуверенный символ,
        а остальные символы прочитаны уверенно."""
        cand = self.r["correct"](tok, f)
        if cand is None:
            return None
        if len(tok) == len(cand):
            pos = next(i for i, (a, b) in enumerate(zip(tok, cand)) if a != b)
        else:
            pos = 0
            while pos < min(len(tok), len(cand)) and tok[pos] == cand[pos]:
                pos += 1
        near = [i for i in range(len(tc)) if abs(i - pos) <= 1]
        far = [i for i in range(len(tc)) if abs(i - pos) > 1]
        if min(tc[i] for i in near) < 0.9 and all(tc[i] >= 0.9 for i in far):
            return cand
        return None

    def read_mrz(self, p):
        raw = p.get("mrz")
        m = M.parse(raw)
        if not m or "line2" not in m or M.line2_valid(m["line2"]):
            return m
        viz = {f: viz_text(p["viz"].get(f))[0] for f in
               ("Licence_number", "Birth_date", "Issue_date", "Issue_organisation_code")}
        keys = {"Licence_number": "series_number", "Birth_date": "birth_date",
                "Issue_date": "issue_date", "Issue_organisation_code": "code"}

        def consistent(l2):
            r = M.parse({"lines": [{"text": "PNRUS" + "<" * 39}, {"text": l2}]})
            # исправленная строка должна совпасть с визуальной зоной во всех найденных полях
            return all(viz[f] is None or norm(viz[f]) == r[k] for f, k in keys.items())

        fixed, _ = M.repair_line2(m["line2"], consistent)
        if not fixed:
            return m
        l1 = m["line1"]
        m2 = M.parse({"lines": [{"text": l1 if len(l1) == 44 else "PNRUS" + "<" * 39},
                                {"text": fixed}]})
        m2["line1"] = l1
        m2["names_lat"] = m.get("names_lat")
        m2["repaired"] = True
        return m2

    def decide(self, p):
        m = self.read_mrz(p)
        out = {}
        self.mrz_fields(p, m or {}, out)
        self.names(p, out)
        self.sex(p, m, out)
        for f in TEXT_FIELDS:
            self.text_field(p, f, out)
        birth = parse_date(out["Birth_date"].value) if out["Birth_date"].ok else None
        issue = parse_date(out["Issue_date"].value) if out["Issue_date"].ok else None
        reasons = [f"{f}:{out[f].reason}" for f in FIELDS if not out[f].ok]
        if not reasons and not passport_valid(birth, issue):
            reasons.append("invalid_passport")
        accept = not reasons
        return accept, {f: (out[f].value or "") for f in FIELDS}, reasons
