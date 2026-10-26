"""S1 direct, S2 think-and-vote, S3 tools. Everything except the strategy is shared."""
import json
import time
from collections import Counter

from openai import BadRequestError

import config
from evaluate import parse_answer, vote_key
from tools import DOCS, execute_tool_call, get_tools

FORMAT = (
    "End your reply with exactly one last line in this form:\n"
    "ANSWER: <name or yes/no> | <number>\n"
    "Write the district name exactly as in the documents, or yes/no for a yes/no question. "
    "The number is plain: no thousands separators, no unit, at most 3 decimal places. "
    "Round only the final number, never intermediate values."
)

DOCS_TEXT = "\n\n".join(f"[{d['id']}] {d['title']}\n{d['text']}" for d in DOCS.values())

SYS_DOCS = (
    "You answer questions about the Nine Rivers Region using ONLY the documents below.\n\n"
    f"{DOCS_TEXT}\n\n{FORMAT}"
)
SYS_TOOLS = (
    "You answer questions about the Nine Rivers Region, a made-up place. You have no documents. "
    "Get every fact with the lookup tool and do every calculation with the calculate tool. "
    "Never use facts from memory.\n\n" + FORMAT
)
S1_SUFFIX = "\n\nReply with only the ANSWER line."
S2_SUFFIX = ("\n\nThink step by step. Write every fact you use with its document id, then each "
             "calculation, then the ANSWER line.")

SETTINGS = {"temperature_ok": True}   # flips to False if the model rejects temperature


def call_model(client, messages, temperature, tools=None):
    """One API call. Returns (response, seconds). Drops temperature if the model refuses it."""
    kw = dict(model=config.MODEL, messages=messages, reasoning_effort=config.REASONING_EFFORT)
    if tools:
        kw["tools"] = tools
    if temperature is not None and SETTINGS["temperature_ok"]:
        kw["temperature"] = temperature
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(**kw)
    except BadRequestError as e:
        if "temperature" in str(e).lower() and "temperature" in kw:
            SETTINGS["temperature_ok"] = False
            kw.pop("temperature")
            resp = client.chat.completions.create(**kw)
        else:
            raise
    return resp, time.perf_counter() - t0


def _usage(resp):
    u = resp.usage
    return (u.prompt_tokens, u.completion_tokens) if u else (0, 0)


def run_s1(client, q):
    msgs = [{"role": "system", "content": SYS_DOCS}, {"role": "user", "content": q["question"] + S1_SUFFIX}]
    resp, sec = call_model(client, msgs, config.TEMP_SINGLE)
    text = resp.choices[0].message.content or ""
    i, o = _usage(resp)
    return {"final_text": text, "parsed": parse_answer(text), "unanswered": False,
            "in_tokens": i, "out_tokens": o, "model_calls": 1}


def run_s2(client, q):
    msgs = [{"role": "system", "content": SYS_DOCS}, {"role": "user", "content": q["question"] + S2_SUFFIX}]
    samples, tin, tout = [], 0, 0
    for _ in range(config.K_SAMPLES):
        resp, _ = call_model(client, msgs, config.TEMP_VOTE)
        text = resp.choices[0].message.content or ""
        i, o = _usage(resp)
        tin, tout = tin + i, tout + o
        samples.append({"text": text, "parsed": parse_answer(text)})
    votes = Counter(vote_key(s["parsed"]) for s in samples if s["parsed"])
    if votes:
        best = max(votes.values())   # ties: first sample that reaches the top count wins
        winner = next(s["parsed"] for s in samples if s["parsed"] and votes[vote_key(s["parsed"])] == best
                      and vote_key(s["parsed"]) in [k for k, v in votes.items() if v == best])
    else:
        winner = None
    return {"final_text": samples[-1]["text"], "parsed": winner, "unanswered": winner is None,
            "in_tokens": tin, "out_tokens": tout, "model_calls": config.K_SAMPLES,
            "votes": {f"{k[0]}|{k[1]}": v for k, v in votes.items()},
            "samples": [{"parsed": s["parsed"], "text": s["text"]} for s in samples]}


def run_s3(client, q, vague=False):
    tools = get_tools(vague=vague)
    msgs = [{"role": "system", "content": SYS_TOOLS}, {"role": "user", "content": q["question"]}]
    log, tin, tout, text = [], 0, 0, ""
    for rnd in range(1, config.MAX_ROUNDS + 1):
        resp, sec = call_model(client, msgs, config.TEMP_SINGLE, tools=tools)
        i, o = _usage(resp)
        tin, tout = tin + i, tout + o
        msg = resp.choices[0].message
        if not msg.tool_calls:
            text = msg.content or ""
            return {"final_text": text, "parsed": parse_answer(text), "unanswered": False,
                    "in_tokens": tin, "out_tokens": tout, "model_calls": rnd, "rounds": rnd,
                    "tool_log": log, "round_input_tokens": None}
        if rnd == config.MAX_ROUNDS:
            break   # round limit reached while the model still asks for tools
        msgs.append(msg)   # the assistant message with tool_calls, unchanged
        for tc in msg.tool_calls:   # EVERY tool_call_id gets an answer
            t0 = time.perf_counter()
            result = execute_tool_call(tc.function.name, tc.function.arguments)
            log.append({"round": rnd, "id": tc.id, "tool": tc.function.name,
                        "arguments": tc.function.arguments, "result": result,
                        "seconds": round(time.perf_counter() - t0, 6)})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    return {"final_text": text, "parsed": None, "unanswered": True,
            "in_tokens": tin, "out_tokens": tout, "model_calls": config.MAX_ROUNDS,
            "rounds": config.MAX_ROUNDS, "tool_log": log}


STRATEGIES = {"S1": run_s1, "S2": run_s2, "S3": run_s3}
