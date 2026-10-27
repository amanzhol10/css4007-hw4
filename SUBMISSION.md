# HW4 — submission

**AI assistance:** I used Claude (Anthropic) as a coding assistant. It drafted the Part A plan and the first version of the code (`tools.py`, `strategies.py`, `run.py`, `evaluate.py`, `summarize.py`, tests), helped me debug Windows and API problems, and drafted the text of Parts B and C from the output of my own runs. I ran every experiment myself, checked the numbers against `outputs/`, and checked the log quotes and explanations myself. All numbers come from my runs (`outputs/`), not from the AI.

---

## Part A — Plan on paper (Easy)

> Committed before any `.py` file exists.

### A1 — The steps

Example question: "Which district is denser, Brightwater or Millbrook, and by how much?"

| # | Step | What goes in (types) | What comes out (types) | When it goes wrong | Who does it |
|---|---|---|---|---|---|
| 1 | **Understand the question**: which districts, which quantity, which year, which comparison | `question: str` | plan: districts `list[str]`, facts needed `list[(district, field)]`, formula `str` | question is ambiguous (e.g. "denser" = people or roads?) → state the interpretation in the reasoning | model |
| 2 | **Find the district** (name → one current profile) | `district: str` | `district: str` (canonical name) | name misspelled → error + "did you mean …"; two similar names (Ossbridge / Ossford) → only an exact case-insensitive match is accepted, never a guess; unknown → error + list of the 12 districts | `lookup` (inside) |
| 3 | **Pick the right document** | canonical district | one current 2025 profile (`doc id: str`) | only an ARCHIVED profile exists / two profiles for one district → the archived one (NR-13, NR-14) is ignored | `lookup` (inside) |
| 4 | **Read one fact** | profile text, `field: str` | `value: float`, `unit: str`, `source: str` | field not in the list → error with the valid fields; number not found in text → error naming the document | `lookup` (inside) |
| 5 | **Apply corrections and unit fixes** | value, district, field | corrected `value`, `source` ("NR-05 corrected by NR-16"), `note: str` | Brightwater area 912.4 → 921.4 (NR-16 takes precedence). Lindenmoor water given in m³ → converted to megalitres (÷1000) and the note says so | `lookup` (inside) |
| 6 | **Collect the facts** (one tool call per fact) | plan from step 1 | list of `{value, unit, source}` | a call returns `{"error": …}` → model reads the message, fixes the input and retries; after the round limit the question is "unanswered" | loop (runs the calls) + model (decides which) |
| 7 | **Calculate** (density = people / km², difference, %, totals) | `expression: str` | `result: float` | division by zero, huge number, not-arithmetic text → `{"error": …}`, never run | `calculate` |
| 8 | **Choose the winner and round** | two results, question | `name: str`, `number: float` | tie / sign wrong → model must give a positive difference; round only the final number | model |
| 9 | **Format and check the answer** | final text | line `ANSWER: <name> | <number>`, parsed to `(str, float)` | no ANSWER line / number unreadable → counted as wrong (not as unanswered) | model writes; `evaluate.py` parses |

**How the steps connect:**

```
question ──► [1 plan, model]
                │  (district, field) × N
                ▼
        loop sends each request to ──► lookup:  [2 find district] → [3 pick document] → [4 read fact] → [5 correct/convert]
                │                                         │ {value, unit, source}
                ▼                                         ▼
        model keeps the values ◄───────────────── results go back with the same tool_call_id
                │  expression string
                ▼
        loop ──► calculate [7] ──► {result} ──► model [8 choose + round] ──► [9 ANSWER: name | number]
```

Steps 2–5 are one tool (`lookup`) and step 7 is the other (`calculate`); steps 1, 6, 8, 9 are the model, and the loop only carries messages and stops after the round limit.

**What I am assuming:**

- "2025" means the 2025 census, the 2025 fiscal-year budget, calendar-2025 water use and 2025/26 pupils (NR-00). "Growth" uses the 2020 and 2025 censuses.
- ARCHIVED 2019 profiles (NR-13 Tarnvale, NR-14 Kelmarsh) are never used, even if they would give a number.
- Correction notices (NR-16) win over the profile they correct.
- All water use is converted to **megalitres**; the tariff is per m³, so ML × 1000 × 142.35 gives tenge.
- Rounding happens **once, at the end**. Calculations keep full precision. The most sensitive assumption is the correction/unit handling: if `lookup` used 912.4 for Brightwater, Q-09 would change from 0.6 to 0.08, i.e. a wrong answer that still looks plausible.
- Tool results are small facts (not whole documents), so S3 prompts stay small.

### A2 — The two tools

#### `lookup`

```json
{
  "type": "function",
  "function": {
    "name": "lookup",
    "description": "Look up ONE fact about ONE district of the Nine Rivers Region, or the household water tariff. Returns the value, its unit and the source document id. It always returns current 2025 data: archived 2019 profiles are ignored and correction notices are already applied. Water use is always given in megalitres. Use one call per district per field. Do not do arithmetic with this tool; use calculate for that. For field='water_tariff_2025' the district is ignored (pass any district name).",
    "parameters": {
      "type": "object",
      "properties": {
        "district": {"type": "string", "description": "District name, e.g. 'Ossbridge'. One of the twelve districts."},
        "field": {"type": "string",
                  "enum": ["population_2025", "population_2020", "area_km2", "founded_year", "budget_2025",
                           "schools", "pupils_2025_26", "paved_road_km", "water_use_2025", "water_tariff_2025"],
                  "description": "Which fact to return."}
      },
      "required": ["district", "field"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"district": "Brightwater", "field": "area_km2", "value": 921.4, "unit": "square kilometres", "source": "NR-05 corrected by NR-16", "note": "…"}` |
| misspelled / unknown district | `{"error": "no district named 'Ossbrige'; did you mean Ossbridge?"}` or the list of the 12 districts |
| unknown field | `{"error": "unknown field 'x'; did you mean …? valid fields: …"}` |
| wrong types (not strings) | `{"error": "district and field must both be strings"}` |
| number not found in profile | `{"error": "could not find <field> for <district> in <doc id>"}` |
| archived data | never returned (archived profiles are not indexed) |

**Worst thing it could do with strange or dangerous input:** nothing harmful: it only reads one local file at start-up and matches the input against a fixed list; input is never used as a file path, a regex or code. The worst case is a wrong or "error" answer, or a long error string (error texts cut the user input to 40 characters).

#### `calculate`

```json
{
  "type": "function",
  "function": {
    "name": "calculate",
    "description": "Evaluate an arithmetic expression exactly, for example '44675 / 921.4' or '(37203 - 34590) / 34590 * 100'. Allowed: numbers, + - * / **, and parentheses. No variables, no functions, no thousands separators. Use it for every calculation instead of computing in your head. Returns {'result': number} or {'error': text}.",
    "parameters": {
      "type": "object",
      "properties": {"expression": {"type": "string", "description": "Arithmetic expression, e.g. '44675 / 921.4'."}},
      "required": ["expression"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"expression": "44675 / 921.4", "result": 48.4859995659}` (rounded to 10 decimals to hide float noise) |
| division by zero | `{"error": "refused: division by zero"}` |
| number or exponent too large (> 1e18, exponent > 100), e.g. `9**9**9` | `{"error": "refused: exponent too large (limit 100)"}` |
| not arithmetic (names, calls, attributes, strings, lists) | `{"error": "refused: only numbers and + - * / ** ( ) are allowed"}` |
| syntax error / `44,675` / empty / > 200 chars | `{"error": "cannot read the expression; …"}` |

**Worst thing it could do with strange or dangerous input:** the expression is parsed with `ast.parse(mode="eval")` and only `Constant(int/float)`, `+ - * / **` and unary ± nodes are walked, so no code runs. The remaining risks are CPU/memory (blocked by the length limit, exponent limit and the 1e18 cap on every intermediate value) and a **wrong but valid** expression written by the model (e.g. wrong numbers) that the tool cannot detect.

### A3 — Q-09 by hand

Question Q-09: "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?" NR-05 says Brightwater: 44,675 residents, area printed as 912.4 km². NR-16 says the area is a typo and the correct area is **921.4** km². NR-11: Millbrook 37,203 residents, 758.6 km².

```json
[
  {"role": "user", "content": "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"},
  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"population_2025\"}"}},
    {"id": "call_2", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"area_km2\"}"}},
    {"id": "call_3", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"population_2025\"}"}},
    {"id": "call_4", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"area_km2\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_1", "content": "{\"district\": \"Brightwater\", \"field\": \"population_2025\", \"value\": 44675, \"unit\": \"residents\", \"source\": \"NR-05\"}"},
  {"role": "tool", "tool_call_id": "call_2", "content": "{\"district\": \"Brightwater\", \"field\": \"area_km2\", \"value\": 921.4, \"unit\": \"square kilometres\", \"source\": \"NR-05 corrected by NR-16\", \"note\": \"the profile printed 912.4, a typo; the correction notice NR-16 takes precedence\"}"},
  {"role": "tool", "tool_call_id": "call_3", "content": "{\"district\": \"Millbrook\", \"field\": \"population_2025\", \"value\": 37203, \"unit\": \"residents\", \"source\": \"NR-11\"}"},
  {"role": "tool", "tool_call_id": "call_4", "content": "{\"district\": \"Millbrook\", \"field\": \"area_km2\", \"value\": 758.6, \"unit\": \"square kilometres\", \"source\": \"NR-11\"}"},
  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_5", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"44675 / 921.4\"}"}},
    {"id": "call_6", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203 / 758.6\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_5", "content": "{\"expression\": \"44675 / 921.4\", \"result\": 48.4859995659}"},
  {"role": "tool", "tool_call_id": "call_6", "content": "{\"expression\": \"37203 / 758.6\", \"result\": 49.0416556815}"},
  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_7", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"49.0416556815 - 48.4859995659\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_7", "content": "{\"expression\": \"49.0416556815 - 48.4859995659\", \"result\": 0.5556561156}"},
  {"role": "assistant", "content": "Millbrook is denser: 49.04 vs 48.49 residents per km² (Brightwater's area is 921.4 km² after correction NR-16).\nANSWER: Millbrook | 0.556"}
]
```

**My arithmetic:**

- Brightwater: 44,675 / 921.4 = 48.4860 residents/km².
- Millbrook: 37,203 / 758.6 = 49.0417 residents/km².
- Difference: 49.0417 − 48.4860 = **0.5557 ≈ 0.6** → Millbrook is denser.
- Trap check: with the uncorrected area 912.4, Brightwater would be 48.964 and the gap only 0.077 — so the correction notice matters.

### A4 — Why I split it this way

Another way: **no `lookup` tool at all, only `calculate`** (the documents stay in the prompt, as in S1/S2, and the model only offloads arithmetic). I did not choose it for the tools strategy because then S3 would be S2 plus a calculator: the prompt still carries all ~2,300 tokens of documents on every round, and the model still has to find the right profile among archived and corrected ones, so the traps (similar names, archived profiles, typo, unit) stay with the model. Moving them into `lookup` makes them deterministic code that I can unit-test. A second alternative, **one "answer the question" tool**, would just hide the same problem inside a black box that I cannot test, and a separate tool per calculation (density, growth, …) would multiply tool definitions that cost tokens on every request while `calculate` already covers all of them.

---

## Part B — Build it and run it (Medium)

### What I changed from Part A while coding

- `gpt-5.6-luna` refuses function tools in Chat Completions unless `reasoning_effort="none"`. I set it for **all three strategies** (same conditions) and reran everything.
- Logs are saved as UTF-8 (cp1251 crashed on `÷` in a model answer). Otherwise the plan, tools and fields are as in Part A.

### B2 — Tests

```text
============================= test session starts =============================
platform win32 -- Python 3.13.15, pytest-9.1.1, pluggy-1.7.0 -- C:\Users\77051\Desktop\css4007-hw4\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\77051\Desktop\css4007-hw4
plugins: anyio-4.15.1
collecting ... collected 25 items

tests/test_loop.py::test_loop_answers_every_tool_call_id PASSED          [  4%]
tests/test_loop.py::test_loop_stops_at_round_limit PASSED                [  8%]
tests/test_loop.py::test_parse_and_correctness_rule PASSED               [ 12%]
tests/test_tools.py::test_lookup_correct_2025_number PASSED              [ 16%]
tests/test_tools.py::test_lookup_ignores_2019_archived_profile PASSED    [ 20%]
tests/test_tools.py::test_lookup_applies_correction_notice PASSED        [ 24%]
tests/test_tools.py::test_lookup_misspelled_name_gives_hint PASSED       [ 28%]
tests/test_tools.py::test_lookup_similar_names_not_confused PASSED       [ 32%]
tests/test_tools.py::test_lookup_converts_cubic_metres_to_megalitres PASSED [ 36%]
tests/test_tools.py::test_lookup_tariff_and_bad_input_never_crash PASSED [ 40%]
tests/test_tools.py::test_calculate_multiplication PASSED                [ 44%]
tests/test_tools.py::test_calculate_precedence_and_parentheses PASSED    [ 48%]
tests/test_tools.py::test_calculate_refuses_code[__import__('os').system('echo hi')] PASSED [ 52%]
tests/test_tools.py::test_calculate_refuses_code[(1).__class__] PASSED   [ 56%]
tests/test_tools.py::test_calculate_refuses_code[open('x')] PASSED       [ 60%]
tests/test_tools.py::test_calculate_refuses_code[[1,2]] PASSED           [ 64%]
tests/test_tools.py::test_calculate_refuses_code[abs(-1)] PASSED         [ 68%]
tests/test_tools.py::test_calculate_refuses_code[x + 1] PASSED           [ 72%]
tests/test_tools.py::test_calculate_refuses_code['a'*3] PASSED           [ 76%]
tests/test_tools.py::test_calculate_refuses_code[1 if 1 else 2] PASSED   [ 80%]
tests/test_tools.py::test_calculate_power_tower_is_refused_fast PASSED   [ 84%]
tests/test_tools.py::test_calculate_division_by_zero_and_huge_numbers PASSED [ 88%]
tests/test_tools.py::test_calculate_non_string_and_thousands_separator PASSED [ 92%]
tests/test_tools.py::test_execute_tool_call_validates_arguments PASSED   [ 96%]
tests/test_tools.py::test_tool_definitions_are_well_formed PASSED        [100%]

============================= 25 passed in 6.92s ==============================
```

### B3 — The loop

- **Round limit: 10 model calls.** A question needs 3–4 rounds (facts, calculations, answer). The maximum I saw was 4 in run 1 and 5 in run 2 (Q-07), so 10 is twice the maximum: room for an error and a retry, but it still stops a looping model. No question hit the limit.
- **Logs:** `outputs/run1/`, `outputs/run2/`, `outputs/runc1/` (`<strategy>/Q-xx.json`: each tool call with id, arguments, result, seconds) and `settings.json` in each run.
- **Q-09, real vs A3:** the same. Round 1: the same 4 `lookup` calls; round 2: the same 2 divisions (48.4860 and 49.0417); round 3: one `calculate`; then the answer `Millbrook | 0.556` (7 calls, 4 rounds, no errors). `lookup` returned Brightwater's area as 921.4 (`NR-05 corrected by NR-16`), so the model never saw 912.4. Differences: in round 3 the model wrote `37203 / 758.6 - 44675 / 921.4` with the original numbers instead of subtracting the rounded results as I did (same result, 0.5556561156), and its final text is one sentence without the densities or NR-16.

### B4 — Three strategies

**Kept the same:** model `gpt-5.6-luna`, Chat Completions, `reasoning_effort="none"`; the same 20 questions in the same order; the same last line `ANSWER: <name or yes/no> | <number>` and one parser (`evaluate.py`). S1 and S2 get all 17 documents (about 2,200 tokens) in the system prompt; S3 gets none, only the two tools. Temperature 0.0 for S1 and S3, 1.0 for the S2 samples (accepted by the model); k = 5, most common answer wins (answers grouped by name and 3 significant digits, ties to the first). S3 round limit 10. Only the instruction differs ("only the ANSWER line" / "think step by step" / "use the tools"). Prices: $0.20 / $1.20 per 1M input / output tokens. Tokens are summed from `usage` over all calls.

**My rule for a correct answer** (written before the first full run): The name must match exactly (case-insensitive); the number must be within 1 unit of the last expected decimal of value (|number − value| ≤ 10^−decimals).

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | 4 | 0 | 44,280 | 246 | 1.3 | 31 | 0.009 |
| 1 | S2 think and vote (k = 5) | 15 | 0 | 223,100 | 20,151 | 15.7 | 310 | 0.069 |
| 1 | S3 tools | 20 | 0 | 58,898 | 4,349 | 7.9 | 169 | 0.017 |
| 2 | S1 direct | 3 | 0 | 44,280 | 243 | 1.3 | 49 | 0.009 |
| 2 | S2 think and vote (k = 5) | 16 | 0 | 223,100 | 19,967 | 17.4 | 362 | 0.069 |
| 2 | S3 tools | 20 | 0 | 58,772 | 4,408 | 8.1 | 172 | 0.017 |

Whole experiment (both runs, all strategies): about $0.19.

**Per question (run 1):**

| Question | S1 | S2 | S3 | S3 rounds |
|---|:---:|:---:|:---:|---:|
| Q-01 | ✓ | ✓ | ✓ | 4 |
| Q-02 | ✗ | ✓ | ✓ | 3 |
| Q-03 | ✗ | ✓ | ✓ | 4 |
| Q-04 | ✗ | ✓ | ✓ | 3 |
| Q-05 | ✗ | ✗ | ✓ | 4 |
| Q-06 | ✗ | ✓ | ✓ | 3 |
| Q-07 | ✗ | ✓ | ✓ | 4 |
| Q-08 | ✗ | ✗ | ✓ | 3 |
| Q-09 | ✗ | ✓ | ✓ | 4 |
| Q-10 | ✓ | ✓ | ✓ | 3 |
| Q-11 | ✗ | ✓ | ✓ | 4 |
| Q-12 | ✗ | ✗ | ✓ | 4 |
| Q-13 | ✓ | ✓ | ✓ | 3 |
| Q-14 | ✗ | ✓ | ✓ | 4 |
| Q-15 | ✗ | ✓ | ✓ | 3 |
| Q-16 | ✓ | ✓ | ✓ | 3 |
| Q-17 | ✗ | ✗ | ✓ | 3 |
| Q-18 | ✗ | ✓ | ✓ | 3 |
| Q-19 | ✗ | ✓ | ✓ | 3 |
| Q-20 | ✗ | ✗ | ✓ | 4 |

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

I ran S3 on five questions with the `lookup` description replaced by `"Looks things up."` (schema and `calculate` unchanged). "Yours" is run 1.

| Question | Calls (yours) | Calls (vague) | Input tokens (yours → vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|---|
| Q-01 | 7 | 7 | 3,460 → 3,052 | Ossbridge 4.57 ✓ | Ossbridge 4.57 ✓ |
| Q-05 | 7 | 7 | 3,558 → 3,150 | Coldharbour 14235.314 ✓ | Coldharbour 14235.314 ✓ |
| Q-09 | 7 | 7 (5 rounds, not 4) | 3,514 → 3,922 | Millbrook 0.556 ✓ | Millbrook 0.556 ✓ |
| Q-11 | 10 | 10 | 3,885 → 3,477 | Redfen 56.1 ✓ | Redfen 56.1 ✓ |
| Q-20 | 10 | 10 | 4,027 → 3,619 | Ashgrove 2993.343 ✓ | Ashgrove 2993.343 ✓ |

Answers, calls and inputs did not change, and no call returned an error. The shorter description saves exactly 102 input tokens per request (408 on the four questions with 4 requests). In Q-09 the model sent the two divisions in separate rounds (5 rounds), which costs one more request; but with my full description Q-07 did the same in run 2 (5 rounds against 4), so I read it as chance, not as an effect of the description. The reason is that the schema already tells the model what to do: the `enum` lists the fields, the parameters are described, and errors contain a hint. The description would matter more for rules the schema cannot show (archived and corrected data, units). Five questions and one run is a weak test.

### C2 — Three mistakes explained

**S1, Q-09 (`Brightwater | 0.001`, correct `Millbrook | 0.6`).** The whole reply in `outputs/run1/S1/Q-09.json` is `ANSWER: Brightwater | 0.001` (12 output tokens): with no reasoning and "reply with only the ANSWER line" the model had to find four numbers, divide twice, subtract and name the winner in one pass. In run 2 it gave `Brightwater | 1.0`, a different wrong number, so it is guessing. A single call cannot check its work.

**S2, Q-05 (voted `14193.569` in run 1 and `14246.403` in run 2, correct `14235`).** Votes in run 1: `{'coldharbour|14300.0': 2, 'coldharbour|14200.0': 3}`. The facts in the samples are right (2,884.6 million tenge / 14,926 residents; 2,366.9 million / 11,407); only the long divisions are wrong. Sample 1 wrote `2,884.6 × 1,000,000 ÷ 14,926 = 193,164.278` (true: 193,260.083), sample 2 wrote `193,284.738` for the same division. The errors differ between samples but all are far outside my tolerance of 1 tenge. Voting fixes random slips when some samples are exactly right (Q-17 and Q-20 were wrong in run 1 and right in run 2), but when every sample makes a different error in a six-digit quotient no exact value repeats. My vote also groups answers to 3 significant digits and returns the first sample of the biggest group, which here was 42 away from the answer.

**S3, Q-20 (correct; the most input tokens in run 1: 4,027 in, 315 out; in run 2 only Q-07 was higher).** The `tool_log` shows round 1: six `lookup` calls (`budget_2025` and `population_2025` for Ossbridge, Ashgrove, Harrowfield); round 2: three `calculate` calls (`9284.5*1000000/52904`, …); round 3: `178490.4697072839-175497.1268713141`; round 4: the answer `Ashgrove | 2993.343`. The calculator gives exact quotients, so the hand-division errors of S2 cannot happen; the model only chooses the expressions. It needed 4 rounds because each step needs the previous one (facts → divisions → difference → answer). Each round costs more input because the API keeps no memory: every request resends the whole conversation (all earlier calls and results) plus the 426 tokens of tool definitions.

### C3 — Which strategy I would use, and what would change it

**S3.** It was correct 20/20 in both runs (S2 15 and 16, S1 4 and 3), cost about $0.017 per run against $0.069 for S2, and took a median of 7.9 s against 15.7 s. S1 is cheapest ($0.009) and fastest (1.3 s) but too inaccurate; S2 costs 4 times more than S3, is slower, and cannot make long divisions exact. S1 and S2 were measured with `reasoning_effort="none"` (needed by the tools), so a reasoning model might do better on them.

What would change my choice:
- **Tiny budget or strict time limit, and questions with little arithmetic:** S1 (it got Q-10, Q-13, Q-16 right in both runs in about 1 s).
- **1,000 times more documents:** S1 and S2 are impossible (about 2 million tokens per prompt); S3 stays, but `lookup` must become a real search (final question 6).
- **Free-text questions with no tool-friendly structure:** S2.

### C4 — How sure I can be

- **Two runs:** S1 4 vs 3, S2 15 vs 16, S3 20 vs 20: at most one question apart. S2 failed on different questions: Q-05, Q-08, Q-12 in both runs; Q-17, Q-20 only in run 1; Q-14 only in run 2.
- **Is the best gap bigger?** S3 vs S2 is 4–5 questions against 0–1 between runs, so yes. But two runs on the same questions say little about the real spread.
- **How many questions?** With 20 questions the standard error near 80% is about 0.09 (±2 questions), so a gap of 4–5 is only about two standard errors. I would want 60–100 questions of different types (these 20 use a few templates, so they are not independent). S3's 20/20 cannot be told from a strategy that is right 95% of the time.

### Final questions

1. **What has run when a `tool_calls` message arrives?** Nothing. The model only asks for a function and its arguments; my code (`execute_tool_call`) runs it and sends the result back with the same `tool_call_id`.
2. **Why is `arguments` a string?** The model generates text, so it is JSON text. Passed straight into `lookup`, it would be one `str` instead of `district` and `field` (a `TypeError`), and it can also be invalid JSON or have missing or extra keys; so I `json.loads` it in `try` and check keys and types first.
3. **Tokens added by the two definitions:** **426** per S3 request, measured with `python run.py --measure-tools` (difference in `prompt_tokens` with and without `tools`).
4. **S2 vs S1 cost:** about **7.5×** (run 1: $0.0688 vs $0.0092). Input is 5× (223,100 vs 44,280, because the documents are sent in 5 calls) and output about 80× (20,151 vs 246) because S2 writes out its reasoning; output tokens also cost 6× more each.
5. **Most rounds in S3:** by rounds, Q-07 in run 2 (5 rounds against 4 in run 1 with the same 7 calls: the model split its calculations). By tool calls, Q-11 and Q-20 (10 calls in 4 rounds in both runs): three districts mean 6 lookups, 3 divisions and 1 difference.
6. **100,000 documents:** a fixed list of districts and a regex per profile would not work. I would build an index once (a table of facts, or BM25/embeddings) and return only the top few snippets with document ids, with archived and corrected documents handled at index time and the result size capped.
7. **What stops `calculate` from running dangerous code?** It never calls `eval`: `ast.parse` plus a whitelist of numbers and `+ - * / **` refuses everything else (tested with `__import__('os').system('echo hi')`, `(1).__class__`, `9**9**9`), and limits on length, exponent and size stop heavy work. The model can still send a valid but wrong expression, or call the tool many times; only the round limit controls that.
8. **Where tools helped most / not at all:** most on multi-step arithmetic with traps: Q-05, Q-08 and Q-12 failed in S2 in both runs but were exact in S3, and `lookup` handled Brightwater's corrected area (Q-09) and Lindenmoor's cubic metres (Q-03). They helped least on simple questions that S1 already solved (Q-10, Q-13, Q-16), where S3 gave the same answer but took 3 rounds and about 5× longer (Q-10: 7.9 s against 1.5 s).
