# HW4 — submission

**AI assistance:** I used Claude (Anthropic) to help draft the plan in Part A, to write the code (`tools.py`, `strategies.py`, `run.py`, `evaluate.py`, `summarize.py`, tests) and to structure this file. I read and checked the code and the corpus myself. All numbers in Parts B and C come from my own runs (`outputs/`), not from the AI.

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

<!-- what changed in your plan, and why. "None" is an answer too. -->

### B2 — Tests

```text
<!-- pytest output -->
```

### B3 — The loop

- Round limit, and why:
- Where the logs are:
- Real Q-09 conversation compared with my A3 version, what is different:

### B4 — Three strategies

**What I kept the same:**

<!-- model, temperature, k, prompts, answer format, anything else -->

**My rule for a correct answer** (written before the first full run):The name must match exactly (case-insensitive); the number must be within 1 unit of the last expected decimal of value (|number − value| ≤ 10^−decimals).

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | | | | | | | |
| 1 | S2 think and vote (k = ) | | | | | | | |
| 1 | S3 tools | | | | | | | |
| 2 | S1 direct | | | | | | | |
| 2 | S2 think and vote (k = ) | | | | | | | |
| 2 | S3 tools | | | | | | | |

**Per question (run 1):**

| Question | S1 | S2 | S3 |
|---|:---:|:---:|:---:|
| Q-01 | | | |
| Q-02 | | | |
| Q-03 | | | |
| Q-04 | | | |
| Q-05 | | | |
| Q-06 | | | |
| Q-07 | | | |
| Q-08 | | | |
| Q-09 | | | |
| Q-10 | | | |
| Q-11 | | | |
| Q-12 | | | |
| Q-13 | | | |
| Q-14 | | | |
| Q-15 | | | |
| Q-16 | | | |
| Q-17 | | | |
| Q-18 | | | |
| Q-19 | | | |
| Q-20 | | | |

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| | | | | |

### C2 — Three mistakes explained

### C3 — Which strategy I would use, and what would change it

### C4 — How sure I can be

### Final questions

1.
2.
3.
4.
5.
6.
7.
8.
