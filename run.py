"""Run strategies on the questions and save every result to outputs/run<N>/.

Examples:
  python run.py --run 0 --questions Q-09 --strategies S3          # smoke test, 1 question
  python run.py --run 1                                           # all 20 x S1,S2,S3
  python run.py --run c1 --strategies S3 --vague --questions Q-01,Q-05,Q-09,Q-11,Q-20
  python run.py --measure-tools                                   # tokens added by the tool definitions
"""
import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

import config
import strategies as S
from evaluate import is_correct
from tools import get_tools

ROOT = Path(__file__).parent


def load_questions():
    return json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))


def measure_tools(client):
    """Prompt tokens with the tools minus without them, same messages (measured, not guessed)."""
    msgs = [{"role": "user", "content": "Say OK."}]
    a, _ = S.call_model(client, msgs, None)
    b, _ = S.call_model(client, msgs, None, tools=get_tools())
    d = b.usage.prompt_tokens - a.usage.prompt_tokens
    print(f"tool definitions add {d} input tokens per S3 request")
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "tool_definition_tokens.json").write_text(
        json.dumps({"tokens": d}), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1")
    ap.add_argument("--questions", default="")
    ap.add_argument("--strategies", default="S1,S2,S3")
    ap.add_argument("--vague", action="store_true", help="C1: one-line vague lookup description")
    ap.add_argument("--measure-tools", action="store_true")
    a = ap.parse_args()

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set (put it in .env)")
    client = OpenAI()
    if a.measure_tools:
        return measure_tools(client)

    qs = load_questions()
    if a.questions:
        want = set(a.questions.split(","))
        qs = [q for q in qs if q["id"] in want]
    out = ROOT / "outputs" / f"run{a.run}"
    for name in a.strategies.split(","):
        (out / name).mkdir(parents=True, exist_ok=True)
        for q in qs:
            t0 = time.perf_counter()
            kw = {"vague": True} if (a.vague and name == "S3") else {}
            try:
                rec = S.STRATEGIES[name](client, q, **kw)
            except Exception as e:   # an API failure must not kill the whole run
                rec = {"final_text": "", "parsed": None, "unanswered": True, "in_tokens": 0,
                       "out_tokens": 0, "model_calls": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
                print(f"  !! API error on {name} {q['id']}: {rec['error']}")
            rec.update(id=q["id"], strategy=name, seconds=round(time.perf_counter() - t0, 3),
                       correct=bool(is_correct(rec["parsed"], q)), expected=[q["answer"], q["value"]],
                       vague=bool(kw))
            (out / name / f"{q['id']}.json").write_text(
                json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"{name} {q['id']} {'OK ' if rec['correct'] else 'BAD'} parsed={rec['parsed']} "
                  f"in={rec['in_tokens']} out={rec['out_tokens']} {rec['seconds']}s")
    (out / "settings.json").write_text(json.dumps({
        "model": config.MODEL, "reasoning_effort": config.REASONING_EFFORT,
        "k": config.K_SAMPLES, "max_rounds": config.MAX_ROUNDS,
        "temp_single": config.TEMP_SINGLE, "temp_vote": config.TEMP_VOTE,
        "temperature_accepted_by_model": S.SETTINGS["temperature_ok"],
        "price_in_per_m": config.PRICE_INPUT_PER_M, "price_out_per_m": config.PRICE_OUTPUT_PER_M,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()