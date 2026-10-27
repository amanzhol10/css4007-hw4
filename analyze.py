import json
from pathlib import Path

C1_QUESTIONS = ["Q-01", "Q-05", "Q-09", "Q-11", "Q-20"]


def load(folder, qid):
    p = Path(folder) / f"{qid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def stats(d):
    log = d.get("tool_log", [])
    return {
        "calls": len(log),
        "lookup": sum(c["tool"] == "lookup" for c in log),
        "calculate": sum(c["tool"] == "calculate" for c in log),
        "errors": sum("error" in c["result"] for c in log),
        "rounds": d.get("rounds"),
        "in": d["in_tokens"],
        "out": d["out_tokens"],
        "ok": d["correct"],
    }


print("=== C1: your description (run1, run2) vs vague (runc1) ===")
print("Q      | run1 calls/rounds | run2 calls/rounds | vague calls/rounds | vague errors | vague ok")
for q in C1_QUESTIONS:
    r1 = stats(load("outputs/run1/S3", q))
    r2 = stats(load("outputs/run2/S3", q))
    v = stats(load("outputs/runc1/S3", q))
    print(f"{q} | {r1['calls']} / {r1['rounds']}".ljust(26),
          f"| {r2['calls']} / {r2['rounds']}".ljust(20),
          f"| {v['calls']} / {v['rounds']}".ljust(21),
          f"| {v['errors']}".ljust(14), f"| {v['ok']}")

print("\n=== Q-09, vague run: every call ===")
d = load("outputs/runc1/S3", "Q-09")
for c in d["tool_log"]:
    print(c["round"], c["tool"], c["arguments"], "->", json.dumps(c["result"], ensure_ascii=False)[:150])
print(d["final_text"])

print("\n=== S3: calls and rounds per question (run1 | run2) ===")
best = []
for i in range(1, 21):
    q = f"Q-{i:02d}"
    a, b = stats(load("outputs/run1/S3", q)), stats(load("outputs/run2/S3", q))
    print(q, f"run1 calls={a['calls']} rounds={a['rounds']} | run2 calls={b['calls']} rounds={b['rounds']}")
    best.append((a["calls"], q, 1))
    best.append((b["calls"], q, 2))
print("\nmost tool calls:", sorted(best, reverse=True)[:4])