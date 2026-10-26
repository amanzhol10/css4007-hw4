import json
import time

import pytest

from tools import calculate, execute_tool_call, get_tools, lookup


# ---------------------------------------------------------------- lookup
def test_lookup_correct_2025_number():
    r = lookup("Brightwater", "population_2025")
    assert r["value"] == 44675 and r["source"].startswith("NR-05")


def test_lookup_ignores_2019_archived_profile():
    r = lookup("Tarnvale", "population_2025")
    assert r["value"] == 71388 and r["source"] == "NR-03"      # not 65,030 from NR-13
    assert lookup("Kelmarsh", "schools")["value"] == 11        # not 10 from NR-14


def test_lookup_applies_correction_notice():
    r = lookup("Brightwater", "area_km2")
    assert r["value"] == 921.4 and "NR-16" in r["source"]


def test_lookup_misspelled_name_gives_hint():
    r = lookup("Ossbrige", "population_2025")
    assert "error" in r and "Ossbridge" in r["error"]


def test_lookup_similar_names_not_confused():
    a, b = lookup("Ossbridge", "population_2025"), lookup("ossford", "population_2025")
    assert a["value"] == 52904 and a["source"] == "NR-01"
    assert b["value"] == 30982 and b["source"] == "NR-02"


def test_lookup_converts_cubic_metres_to_megalitres():
    r = lookup("Lindenmoor", "water_use_2025")
    assert r["unit"] == "megalitres" and r["value"] == pytest.approx(2151.4)


def test_lookup_tariff_and_bad_input_never_crash():
    assert lookup("anything", "water_tariff_2025")["value"] == 142.35
    for bad in [(None, None), (5, "area_km2"), ("Redfen", "nonsense"), ("", "")]:
        assert "error" in lookup(*bad)


# ---------------------------------------------------------------- calculate
def test_calculate_multiplication():
    assert calculate("48317 * 1.0947")["result"] == pytest.approx(52892.6199)


def test_calculate_precedence_and_parentheses():
    assert calculate("2 + 3 * 4")["result"] == 14
    assert calculate("(2 + 3) * 4")["result"] == 20
    assert calculate("-3 ** 2")["result"] == -9


@pytest.mark.parametrize("bad", ["__import__('os').system('echo hi')", "(1).__class__",
                                 "open('x')", "[1,2]", "abs(-1)", "x + 1", "'a'*3", "1 if 1 else 2"])
def test_calculate_refuses_code(bad):
    assert "error" in calculate(bad)


def test_calculate_power_tower_is_refused_fast():
    t = time.time()
    assert "error" in calculate("9**9**9")
    assert time.time() - t < 1


def test_calculate_division_by_zero_and_huge_numbers():
    assert "division by zero" in calculate("1/0")["error"]
    assert "error" in calculate("10**100")
    assert "error" in calculate("1" * 300)
    assert "error" in calculate("1e308 * 10")
    assert "error" in calculate("")


def test_calculate_non_string_and_thousands_separator():
    assert "error" in calculate(123)
    assert "error" in calculate("44,675 / 2")


# ---------------------------------------------------------------- argument validation
def test_execute_tool_call_validates_arguments():
    assert "error" in execute_tool_call("lookup", "{not json")
    assert "error" in execute_tool_call("lookup", "[1]")
    assert "error" in execute_tool_call("lookup", json.dumps({"district": "Redfen"}))
    assert "error" in execute_tool_call("calculate", json.dumps({"expression": "1", "x": 2}))
    assert "error" in execute_tool_call("rm_rf", "{}")
    assert execute_tool_call("calculate", '{"expression": "6*7"}')["result"] == 42


def test_tool_definitions_are_well_formed():
    for t in get_tools():
        f = t["function"]
        assert f["name"] in ("lookup", "calculate") and f["description"]
        assert set(f["parameters"]["required"]) <= set(f["parameters"]["properties"])
    assert get_tools(vague=True)[0]["function"]["description"] == "Looks things up."
