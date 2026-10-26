"""Разбор MRZ внутреннего паспорта РФ (две строки по 44 символа)."""
import re

# транслитерация, которую использует МВД в MRZ внутреннего паспорта
LAT2CYR = {
    "A": "А", "B": "Б", "V": "В", "G": "Г", "D": "Д", "E": "Е", "2": "Ё", "J": "Ж",
    "Z": "З", "I": "И", "Q": "Й", "K": "К", "L": "Л", "M": "М", "N": "Н", "O": "О",
    "P": "П", "R": "Р", "S": "С", "T": "Т", "U": "У", "F": "Ф", "H": "Х", "C": "Ц",
    "3": "Ч", "4": "Ш", "W": "Щ", "X": "Ъ", "Y": "Ы", "9": "Ь", "6": "Э", "7": "Ю",
    "8": "Я",
}
CYR2LAT = {v: k for k, v in LAT2CYR.items()}
WEIGHTS = (7, 3, 1)


def char_value(ch):
    if ch.isdigit():
        return int(ch)
    if "A" <= ch <= "Z":
        return ord(ch) - 55
    return 0  # '<'


def check_digit(s):
    return str(sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(s)) % 10)


def to_cyr(s):
    out = []
    for ch in s:
        if ch not in LAT2CYR:
            return None
        out.append(LAT2CYR[ch])
    return "".join(out)


def to_lat(s):
    """Кириллица -> MRZ-транслит; пробел и дефис в MRZ передаются как '<'."""
    out = []
    for ch in s.upper():
        if ch in CYR2LAT:
            out.append(CYR2LAT[ch])
        elif ch in " -":
            out.append("<")
        else:
            return None
    return "".join(out)


def yymmdd_to_date(s, ref_year=2026):
    if not re.fullmatch(r"\d{6}", s):
        return None
    yy, mm, dd = int(s[:2]), s[2:4], s[4:]
    year = 2000 + yy if 2000 + yy <= ref_year else 1900 + yy
    return f"{dd}.{mm}.{year}"


def parse(mrz):
    """Возвращает dict с разобранными значениями и флагами контрольных цифр, либо None."""
    if not mrz or len(mrz.get("lines") or []) != 2:
        return None
    l1, l2 = (ln["text"] for ln in mrz["lines"])
    res = {"line1": l1, "line2": l2, "len_ok": len(l1) == 44 and len(l2) == 44}
    # строка 1: PNRUS + ФАМИЛИЯ<<ИМЯ<ОТЧЕСТВО
    names = None
    if l1.startswith("PNRUS"):
        body = l1[5:].rstrip("<")
        if "<<" in body:
            last, rest = body.split("<<", 1)
            parts = rest.split("<", 1)
            names = (last, parts[0], parts[1] if len(parts) > 1 else "")
    res["names_lat"] = names
    if not res["len_ok"]:
        return res
    num, num_cd = l2[0:9], l2[9]
    birth, birth_cd = l2[13:19], l2[19]
    sex = l2[20]
    opt, opt_cd = l2[28:42], l2[42]
    final_cd = l2[43]
    res["num_ok"] = check_digit(num) == num_cd
    res["birth_ok"] = check_digit(birth) == birth_cd
    res["opt_ok"] = check_digit(opt) == opt_cd
    composite = l2[0:10] + l2[13:20] + l2[21:43]
    res["final_ok"] = check_digit(composite) == final_cd
    res["nat_ok"] = l2[10:13] == "RUS"
    res["series_number"] = None
    if re.fullmatch(r"\d{9}", num) and opt[0].isdigit():
        series = num[:3] + opt[0]
        res["series_number"] = f"{series[:2]} {series[2:]} {num[3:]}"
    res["birth_date"] = yymmdd_to_date(birth)
    res["sex"] = {"M": "МУЖ.", "F": "ЖЕН."}.get(sex)
    res["issue_date"] = yymmdd_to_date(opt[1:7])
    code = opt[7:13]
    res["code"] = f"{code[:3]}-{code[3:]}" if re.fullmatch(r"\d{6}", code) else None
    return res


ALPHABET2 = "0123456789<MF"


def line2_valid(l2):
    if len(l2) != 44 or l2[10:13] != "RUS" or l2[20] not in "MF":
        return False
    p = parse({"lines": [{"text": "PNRUS" + "<" * 39}, {"text": l2}]})
    return bool(p["num_ok"] and p["birth_ok"] and p["opt_ok"] and p["final_ok"]
                and p["series_number"] and p["birth_date"] and p["issue_date"] and p["code"])


def repair_line2(l2, accept=None):
    """Одна правка (вставка, удаление или замена символа), после которой сходятся все
    контрольные цифры. Возвращает исправленную строку, только если вариант единственный.
    accept(строка) отсеивает варианты, которые противоречат визуальной зоне."""
    if line2_valid(l2):
        return l2, 0
    cands = set()
    n = len(l2)
    if n == 43:
        for i in range(n + 1):
            for ch in ALPHABET2:
                s = l2[:i] + ch + l2[i:]
                if line2_valid(s):
                    cands.add(s)
    elif n == 45:
        for i in range(n):
            s = l2[:i] + l2[i + 1:]
            if line2_valid(s):
                cands.add(s)
    elif n == 44:
        for i in range(n):
            for ch in ALPHABET2:
                if ch != l2[i]:
                    s = l2[:i] + ch + l2[i + 1:]
                    if line2_valid(s):
                        cands.add(s)
    if accept is not None:
        cands = {c for c in cands if accept(c)}
    if len(cands) == 1:
        return cands.pop(), 1
    return None, len(cands)
