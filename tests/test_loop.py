"""Loop mechanics with a fake client: no API key, no network."""
import json
from types import SimpleNamespace as NS

import config
import strategies as S
from evaluate import is_correct, parse_answer


def tc(i, name, args):
    return NS(id=f"call_{i}", type="function", function=NS(name=name, arguments=args))


def resp(content=None, calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls))],
              usage=NS(prompt_tokens=100, completion_tokens=10))


class Fake:
    def __init__(self, script):
        self.script, self.seen = list(script), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.seen.append(json.loads(json.dumps(kw["messages"], default=lambda o: "<msg>")))
        return self.script.pop(0)


Q = {"id": "Q-X", "question": "?", "answer": "Millbrook", "value": 0.6, "decimals": 1}


def test_loop_answers_every_tool_call_id():
    f = Fake([resp(calls=[tc(1, "lookup", '{"district":"Redfen","field":"schools"}'),
                          tc(2, "calculate", "{broken")]),
              resp("ANSWER: Millbrook | 0.56")])
    r = S.run_s3(f, Q)
    tool_msgs = [m for m in f.seen[1] if isinstance(m, dict) and m.get("role") == "tool"]
    assert {m["tool_call_id"] for m in tool_msgs} == {"call_1", "call_2"}
    assert r["rounds"] == 2 and r["correct" if "correct" in r else "parsed"]
    assert is_correct(r["parsed"], Q)
    assert "error" in r["tool_log"][1]["result"]          # broken JSON did not crash the loop


def test_loop_stops_at_round_limit():
    f = Fake([resp(calls=[tc(i, "calculate", '{"expression":"1+1"}')]) for i in range(config.MAX_ROUNDS + 2)])
    r = S.run_s3(f, Q)
    assert r["unanswered"] and r["rounds"] == config.MAX_ROUNDS


def test_parse_and_correctness_rule():
    assert parse_answer("blah\nANSWER: Millbrook | 0.56") == ("Millbrook", 0.56)
    assert parse_answer("ANSWER: **yes** | 14,069") == ("yes", 14069.0)
    assert parse_answer("no answer line") is None
    assert is_correct(("Millbrook", 0.7), Q) and not is_correct(("Millbrook", 0.8), Q)
    assert not is_correct(("Brightwater", 0.6), Q)
