"""Build the B4 tables from outputs/run<N>/ . Usage: python summarize.py 1 2"""
import json
import statistics
import sys
from pathlib import Path

import config

ROOT = Path(__file__).parent / "outputs"
LABEL = {"S1": "S1 direct", "S2": f"S2 think and vote (k = {config.K_SAMPLES})", "S3": "S3 tools"}


def load(run, s):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / f"run{run}" / s).glob("Q-*.json"))}


def main(runs):
    print("| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median s / question | Total s | Cost ($) |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in runs:
        for s in ("S1", "S2", "S3"):
            d = load(r, s)
            if not d:
                continue
            v = list(d.values())
            ti, to = sum(x["in_tokens"] for x in v), sum(x["out_tokens"] for x in v)
            cost = ti / 1e6 * config.PRICE_INPUT_PER_M + to / 1e6 * config.PRICE_OUTPUT_PER_M
            secs = [x["seconds"] for x in v]
            print(f"| {r} | {LABEL[s]} | {sum(x['correct'] for x in v)} | {sum(x['unanswered'] for x in v)} | "
                  f"{ti} | {to} | {statistics.median(secs):.1f} | {sum(secs):.0f} | {cost:.3f} |")
    r = runs[0]
    print(f"\nPer question (run {r}):\n\n| Question | S1 | S2 | S3 | S3 rounds |\n|---|:---:|:---:|:---:|---:|")
    data = {s: load(r, s) for s in ("S1", "S2", "S3")}
    for qid in sorted({k for d in data.values() for k in d}):
        cell = lambda s: "" if qid not in data[s] else ("✓" if data[s][qid]["correct"] else "✗")
        rounds = data["S3"].get(qid, {}).get("rounds", "")
        print(f"| {qid} | {cell('S1')} | {cell('S2')} | {cell('S3')} | {rounds} |")


if __name__ == "__main__":
    main(sys.argv[1:] or ["1"])
