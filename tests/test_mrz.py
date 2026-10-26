import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import mrz as M  # noqa: E402
from src.pipeline import passport_valid  # noqa: E402

LINE1 = "PNRUSZAINTINOV<<ZAKERIQ<NAZIFULOVI3<<<<<<<<<"
LINE2 = "6122839687RUS1006102M<<<<<<<4250911620004<28"


def test_parse_line2():
    m = M.parse({"lines": [{"text": LINE1}, {"text": LINE2}]})
    assert m["num_ok"] and m["birth_ok"] and m["opt_ok"] and m["final_ok"]
    assert m["series_number"] == "61 24 283968"
    assert m["birth_date"] == "10.06.2010"
    assert m["issue_date"] == "11.09.2025"
    assert m["code"] == "620-004"
    assert m["sex"] == "МУЖ."


def test_translit_roundtrip():
    assert M.to_lat("НАЗИФУЛОВИЧ") == "NAZIFULOVI3"
    assert M.to_cyr("NAZIFULOVI3") == "НАЗИФУЛОВИЧ"
    assert M.to_lat("АЙ-НЮР") == "AQ<N7R"


def test_repair_substitution():
    broken = LINE2[:3] + "3" + LINE2[4:]  # одна цифра номера прочитана неверно
    fixed, n = M.repair_line2(broken, lambda s: s[:9] == "612283968")
    assert fixed == LINE2 and n == 1


def test_repair_ambiguous_without_viz():
    broken = LINE2[:22] + LINE2[23:]  # потерян заполнитель, но подходящих вставок несколько
    fixed, n = M.repair_line2(broken)
    assert fixed is None and n > 1


def test_repair_uses_viz_to_choose():
    broken = LINE2[:15] + LINE2[16:]  # потеряна цифра в дате рождения, вариантов несколько
    fixed, _ = M.repair_line2(broken, lambda s: s[13:19] == "100610")
    assert fixed == LINE2


def test_repair_needs_unique_candidate():
    fixed, n = M.repair_line2("1" * 44)
    assert fixed is None


def test_passport_valid():
    birth = date(2008, 1, 1)
    assert passport_valid(birth, date(2022, 2, 1))       # 20 лет еще нет
    assert not passport_valid(birth, date(2026, 12, 1))  # выдан позже 01.10.2026
    assert not passport_valid(date(2006, 9, 1), date(2020, 9, 15))  # 20 лет, паспорт не заменен
    assert passport_valid(date(2006, 9, 1), date(2026, 9, 10))
