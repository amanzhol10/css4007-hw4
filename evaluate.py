"""How an answer is parsed and judged. The rule is fixed BEFORE the first full run.

Correct  <=>  name equals the expected name (case-insensitive, exact word)
              AND |number - value| <= 1 unit of the last expected decimal
              (10 ** -decimals).
"""
import re

ANSWER_RE = re.compile(r"ANSWER:\s*\**\s*([^|\n]+?)\s*\**\s*\|\s*([^\n]+)", re.IGNORECASE)
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def parse_answer(text):
    """Return (name, number) from the LAST 'ANSWER: x | y' line, or None."""
    if not text:
        return None
    found = ANSWER_RE.findall(text)
    if not found:
        return None
    name, num = found[-1]
    m = NUM_RE.search(num.replace(",", "").replace(" ", ""))
    if not m:
        return None
    return name.strip().strip("*").strip(), float(m.group())


def is_correct(parsed, q):
    if parsed is None:
        return False
    name, num = parsed
    if name.casefold() != q["answer"].casefold():
        return False
    return abs(num - q["value"]) <= 10 ** (-q["decimals"]) * (1 + 1e-9)


def vote_key(parsed):
    """Group similar answers in S2: same name, same number to 3 significant digits."""
    name, num = parsed
    return (name.casefold(), float(f"{num:.3g}"))
