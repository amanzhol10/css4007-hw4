"""The two tools: lookup (facts from the corpus) and calculate (safe arithmetic).

Both functions NEVER raise: every problem comes back as {"error": "..."} so
that the model can read it and try again.
"""
import ast
import difflib
import json
import math
import operator
import re
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "corpus.jsonl"

DISTRICTS = [
    "Ossbridge", "Ossford", "Tarnvale", "Kelmarsh", "Brightwater", "Stonecairn",
    "Harrowfield", "Lindenmoor", "Redfen", "Ashgrove", "Millbrook", "Coldharbour",
]

# field -> (unit, [regexes with ONE capture group for the number])
# The profiles use two phrasings, so every field has one pattern per phrasing.
_NUM = r"([\d,]+(?:\.\d+)?)"
FIELDS = {
    "population_2025": ("residents", [
        r"census recorded " + _NUM + r" residents",
        r"in 2020 and " + _NUM + r" in 2025",
        r"counted " + _NUM + r" residents",
    ]),
    "population_2020": ("residents", [
        r"2020 census had recorded " + _NUM,
        r"Census population: " + _NUM + r" in 2020",
        r"up from " + _NUM + r" at the 2020 census",
    ]),
    "area_km2": ("square kilometres", [_NUM + r" square kilometres"]),
    "founded_year": ("year", [r"[Ff]ounded in (\d{4})"]),
    "budget_2025": ("million tenge", [_NUM + r" million tenge"]),
    "schools": ("schools", [_NUM + r" schools"]),
    "pupils_2025_26": ("pupils", [_NUM + r" pupils"]),
    "paved_road_km": ("km", [_NUM + r" km (?:long|of paved road)"]),
    # water is handled separately (two units in the corpus)
    "water_use_2025": ("megalitres", []),
}
TARIFF_FIELD = "water_tariff_2025"
ALL_FIELDS = list(FIELDS) + [TARIFF_FIELD]
_WATER = re.compile(_NUM + r" (megalitres|cubic metres)")


def _num(s):
    s = s.replace(",", "")
    return float(s) if "." in s else int(s)


def _load():
    docs = {}
    for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            docs[d["id"]] = d
    return docs


DOCS = _load()
# current profiles only: title ends with "district profile (2025)"; archived ones are skipped
PROFILES = {}
CORRECTIONS = {}   # (district, field) -> (value, notice id, wrong value text)
for _id, _d in DOCS.items():
    _t = _d["title"]
    if "ARCHIVED" in _t or _d["text"].startswith("ARCHIVED"):
        continue
    if _t.endswith("district profile (2025)"):
        PROFILES[_t.split()[0]] = _d
    elif _t.startswith("Correction notice"):
        _dist = _t.split("-")[-1].strip()
        _m = re.search(r"The correct area is " + _NUM + r" square kilometres", _d["text"])
        _w = re.search(r"gives the district's area as " + _NUM, _d["text"])
        if _m:
            CORRECTIONS[(_dist, "area_km2")] = (_num(_m.group(1)), _id, _w.group(1) if _w else "?")
TARIFF_DOC = DOCS["NR-15"]


def _err(msg):
    return {"error": msg}


def lookup(district, field):
    """Return one fact about one district (or the water tariff)."""
    try:
        if not isinstance(district, str) or not isinstance(field, str):
            return _err("district and field must both be strings")
        field = field.strip()
        if field not in ALL_FIELDS:
            close = difflib.get_close_matches(field, ALL_FIELDS, n=3, cutoff=0.5)
            hint = f"did you mean {', '.join(close)}? " if close else ""
            return _err(f"unknown field '{field[:40]}'; {hint}valid fields: {', '.join(ALL_FIELDS)}")

        if field == TARIFF_FIELD:
            m = re.search(r"tariff is ([\d.]+) tenge per cubic metre", TARIFF_DOC["text"])
            return {"field": field, "value": float(m.group(1)), "unit": "tenge per cubic metre",
                    "source": TARIFF_DOC["id"],
                    "note": "same in every district; 1 megalitre = 1000 cubic metres; household use only"}

        name = district.strip()
        match = [d for d in DISTRICTS if d.casefold() == name.casefold()]
        if not match:
            close = difflib.get_close_matches(name.title(), DISTRICTS, n=3, cutoff=0.6)
            if close:
                return _err(f"no district named '{name[:40]}'; did you mean {' or '.join(close)}?")
            return _err(f"no district named '{name[:40]}'; districts are: {', '.join(DISTRICTS)}")
        district = match[0]
        doc = PROFILES[district]
        text = doc["text"]
        out = {"district": district, "field": field}

        if field == "water_use_2025":
            m = _WATER.search(text)
            val, unit = _num(m.group(1)), m.group(2)
            if unit == "cubic metres":
                out.update(value=val / 1000, unit="megalitres", source=doc["id"],
                           note=f"profile states {m.group(1)} cubic metres; converted (1 ML = 1000 m3)")
            else:
                out.update(value=val, unit="megalitres", source=doc["id"])
            return out

        unit, patterns = FIELDS[field]
        for p in patterns:
            m = re.search(p, text)
            if m:
                out.update(value=_num(m.group(1)), unit=unit, source=doc["id"])
                break
        else:
            return _err(f"could not find {field} for {district} in {doc['id']}")

        corr = CORRECTIONS.get((district, field))
        if corr:
            out.update(value=corr[0], source=f"{doc['id']} corrected by {corr[1]}",
                       note=f"the profile printed {corr[2]}, a typo; the correction notice {corr[1]} takes precedence")
        return out
    except Exception as e:  # never crash
        return _err(f"lookup failed: {type(e).__name__}")


# ------------------------------------------------------------------ calculate
MAX_EXPR_LEN = 200
MAX_ABS = 1e18        # any number (input or intermediate) above this is refused
MAX_EXPONENT = 100

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class _Refused(Exception):
    pass


def _check(v):
    if isinstance(v, complex) or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _Refused("result is not a real number")
    if isinstance(v, float) and not math.isfinite(v):
        raise _Refused("result is not finite")
    if abs(v) > MAX_ABS:
        raise _Refused(f"number too large (limit {MAX_ABS:.0e})")
    return v


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if type(node.value) in (int, float):
            return _check(node.value)
        raise _Refused("only numbers are allowed")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _check(_UN[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Div) and b == 0:
            raise _Refused("division by zero")
        if isinstance(node.op, ast.Pow):
            if abs(b) > MAX_EXPONENT:
                raise _Refused(f"exponent too large (limit {MAX_EXPONENT})")
            if a == 0 and b < 0:
                raise _Refused("division by zero")
        return _check(_BIN[type(node.op)](a, b))
    raise _Refused("only numbers and + - * / ** ( ) are allowed")


def calculate(expression):
    """Evaluate a plain arithmetic expression safely (no eval/exec)."""
    try:
        if not isinstance(expression, str):
            return _err("expression must be a string")
        expr = expression.strip()
        if not expr:
            return _err("empty expression")
        if len(expr) > MAX_EXPR_LEN:
            return _err(f"expression too long (limit {MAX_EXPR_LEN} characters)")
        try:
            tree = ast.parse(expr, mode="eval")
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return _err("cannot read the expression; use digits (no thousands separators) and + - * / ** ( )")
        value = _eval(tree)
        if isinstance(value, float):
            value = round(value, 10)
        return {"expression": expr, "result": value}
    except _Refused as e:
        return _err(f"refused: {e}")
    except (ZeroDivisionError, OverflowError):
        return _err("refused: arithmetic error (division by zero or overflow)")
    except Exception as e:
        return _err(f"calculate failed: {type(e).__name__}")


# ------------------------------------------------------------------ definitions for the model
LOOKUP_DESC = (
    "Look up ONE fact about ONE district of the Nine Rivers Region, or the household water tariff. "
    "Returns the value, its unit and the source document id. It always returns current 2025 data: "
    "archived 2019 profiles are ignored and correction notices are already applied. "
    "Water use is always given in megalitres. Use one call per district per field. "
    "Do not do arithmetic with this tool; use calculate for that. "
    "For field='water_tariff_2025' the district is ignored (pass any district name)."
)
CALC_DESC = (
    "Evaluate an arithmetic expression exactly, for example '44675 / 921.4' or '(37203 - 34590) / 34590 * 100'. "
    "Allowed: numbers, + - * / **, and parentheses. No variables, no functions, no thousands separators. "
    "Use it for every calculation instead of computing in your head. Returns {'result': number} or {'error': text}."
)

LOOKUP_PARAMS = {
    "type": "object",
    "properties": {
        "district": {"type": "string", "description": "District name, e.g. 'Ossbridge'. One of the twelve districts."},
        "field": {"type": "string", "enum": ALL_FIELDS,
                  "description": "Which fact to return."},
    },
    "required": ["district", "field"],
    "additionalProperties": False,
}
CALC_PARAMS = {
    "type": "object",
    "properties": {"expression": {"type": "string", "description": "Arithmetic expression, e.g. '44675 / 921.4'."}},
    "required": ["expression"],
    "additionalProperties": False,
}


def get_tools(vague=False):
    """Tool definitions in Chat Completions format. vague=True is only for experiment C1."""
    return [
        {"type": "function", "function": {
            "name": "lookup", "description": "Looks things up." if vague else LOOKUP_DESC,
            "parameters": LOOKUP_PARAMS}},
        {"type": "function", "function": {
            "name": "calculate", "description": CALC_DESC, "parameters": CALC_PARAMS}},
    ]


REGISTRY = {"lookup": lookup, "calculate": calculate}
REQUIRED = {"lookup": {"district", "field"}, "calculate": {"expression"}}


def execute_tool_call(name, arguments):
    """Validate the raw JSON-string arguments and run the tool. Never raises."""
    if name not in REGISTRY:
        return _err(f"unknown tool '{str(name)[:30]}'; available: lookup, calculate")
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (json.JSONDecodeError, TypeError):
        return _err("arguments are not valid JSON")
    if not isinstance(args, dict):
        return _err("arguments must be a JSON object")
    missing = REQUIRED[name] - set(args)
    extra = set(args) - REQUIRED[name]
    if missing:
        return _err(f"missing argument(s): {', '.join(sorted(missing))}")
    if extra:
        return _err(f"unexpected argument(s): {', '.join(sorted(map(str, extra)))}")
    return REGISTRY[name](**args)
