# Worth Using behavioral evaluation

This package tests whether the frozen Worth Using skill changes agent behavior on fictional review tasks. It does not measure whether real tools gain users or become useful in practice.

## Current result

The 2026-10-23 live evaluation is blocked before the live pilot. `EVAL_MODEL`, `JUDGE_MODEL`, and provider API credentials were not available in the execution environment. No evaluated-model or blind-judge results were generated. Offline transport tests are explicitly excluded from behavioral statistics.

The original blocked package used commit `5c4f481208706f6b09976fa1c408bb26b8c3b58b` and is retained separately. It is not a result for the subsequently corrected method. That package is not required by a fresh clone of this harness. New runs default to the skill and rubric in the current checkout and freeze exactly those bytes; they never silently substitute the original snapshots.

## Run

Use Python 3.10 or newer in a checkout of this repository. Install the rendering dependencies from `evals/requirements.txt` if needed. Commit the selected skill and rubric before live calls. The gate compares those two treatment files with their recorded Git commit; unrelated working files and generated reports do not require a clean worktree.

Make these variables available through the execution environment:

| Variable | Requirement |
| --- | --- |
| `EVAL_MODEL` | Exact evaluated-model ID. Required. No default is chosen. |
| `JUDGE_MODEL` | Exact judge-model ID, different from the evaluated model. Required. |
| `EVAL_MODEL_FAMILY` | Required explicit family declaration for the evaluated model. |
| `JUDGE_MODEL_FAMILY` | Required explicit family declaration, different from `EVAL_MODEL_FAMILY` after whitespace normalization and case folding. |
| `OPENAI_API_KEY` | Required for roles using the OpenAI endpoint. Environment only. |
| `ANTHROPIC_API_KEY` | Required for roles using the Anthropic endpoint. Environment only. |
| `EVAL_PROVIDER`, `JUDGE_PROVIDER`, `SIMULATOR_PROVIDER` | Optional `openai` or `anthropic`; inferred from a `claude` model prefix otherwise. |
| `SIMULATOR_MODEL` | Optional, defaults to `EVAL_MODEL`, always a separate model call. |

Do not put credentials in files, command-line arguments, transcripts, or source code. The program reads environment variables directly; it does not read `.env` files. Provider error bodies and authorization headers are never logged. Redirects are refused.

Family labels are operator declarations, not facts inferred from a model-name prefix or verified by an API. Declare the actual model lineage consistently; a different transport provider or alias does not establish a different family. Both labels and their declaration basis are recorded in the manifest and resume identity. Requested and provider-returned model IDs must also differ.

Run the complete experiment with the requested command:

```bash
python3 evals/run.py --conditions skill,baseline --seeds 3
```

The runner automatically includes placebo so this command satisfies the three-condition requirement. It first runs a live two-fixture, one-seed pilot across all three tasks and conditions. Passing means valid transport, paired prompts, validated builder scripts, distinct resolved model IDs, reversible masking, and parseable judge outputs. Treatment performance is not a pilot gate. It then runs 324 main conversations, excluding pilot observations from main estimates.

The default generation seeds are `41001`, `41002`, and `41003`. Defaults are evaluated-agent temperature `0.2` and maximum `2400` tokens, judge temperature `0` and maximum `6000` tokens, and simulator temperature `0.2` and maximum `3500` tokens. Override these with `EVAL_TEMPERATURE`, `EVAL_MAX_TOKENS`, `JUDGE_TEMPERATURE`, `JUDGE_MAX_TOKENS`, `SIMULATOR_TEMPERATURE`, and `SIMULATOR_MAX_TOKENS`. All settings and per-call derived seeds are recorded. Provider-returned model IDs must remain fixed and distinct. Unsupported parameters stop the pilot; the runner never silently changes the model or settings.

OpenAI requests send a best-effort seed. Anthropic's message interface has no seed parameter, so the manifest records that limitation and never claims deterministic generation. A fixed seed is not a guarantee of identical API outputs. Code, inputs, assignments, request parameters, schedules, and analysis are reproducible; generation reproducibility depends on the provider.

`OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` optionally select HTTPS endpoints. Do not include credentials in these URLs. Pricing is optional: `{EVAL,JUDGE,SIMULATOR}_INPUT_USD_PER_MILLION` and the corresponding `_OUTPUT_USD_PER_MILLION` produce a nominal uncached estimate. Without supplied rates, dollars remain unavailable. Actual token usage and seconds are retained independently. This is not an invoice estimator for caching or service-tier discounts.

## Inspect and reproduce offline

```bash
python3 -B evals/run.py --validate
python3 -B -m unittest discover -s evals -p 'test*.py' -v
python3 -B evals/run.py --conditions skill,baseline --seeds 1 --offline-smoke
```

`--offline-smoke` uses canned responses only. It creates no scientific estimates. Regression tests use temporary files below `evals/`, prohibit provider calls, and delete their generated records. They verify wiring, parsers, paired sampling, masking, and failure handling, not the skill's effectiveness.

`--pilot` runs only the live pilot. New records use `docs/evaluations/<date>/v-<source-hash>-<configuration-hash>/`; the default date uses America/New_York. The required command therefore works for a changed treatment on the same day without overwriting an older record. `--run-id reviewed-replication-2` selects a distinct safe name beneath the date. Successful cached trials resume only under identical source, fixture, model, family, prompt, script, and code hashes. Failed trials and judge calls remain recorded rather than silently replaced. A changed configuration requires a distinct record.

`--analyze --record YYYY-MM-DD/RUN_ID` rebuilds derived reports from that selected frozen record before checking any current treatment or model settings. A historical date-root record can be selected with `--record YYYY-MM-DD`. This is an explicit rewrite of derived reports, so preserve an archive if those original reports must remain immutable. New records also freeze their answer key; older records require a matching original key. Historical treatment replay is separate: `--source-record YYYY-MM-DD[/RUN_ID]` loads and verifies those four snapshots, then creates a new run under the chosen date and run ID. It does not replace the default current-checkout selection. A historical live replay requires the recorded source commit in local Git history. Historical records are optional inputs, not bundled dependencies.

## What is fixed before testing

- `PROTOCOL.md`: hypotheses, applicability, metrics, uncertainty, and deviations from the repository benchmark.
- `judge_rubric.md`: separate 1-5 usefulness, evidence honesty, and actionability anchors, with a strict annotation schema.
- `placebo.txt`: one coherent generic reviewer paragraph, 3,083 words. Validation requires its length to remain within 5% of the selected skill plus rubric and records the actual difference. It contains none of the skill's special rating, arbitration, subtraction, or stopping rules. Word matching does not establish exact token matching or a semantically inert control.
- `fixtures/f01/` through `f12/`: twelve explicitly fictional dossiers. Public input is restricted to metadata, README, pitch, first-session record, and six-week usage log.
- `fixtures/key.json`: private answer key. Never passed to the evaluated agent or builder simulator. The judge may receive neutral scenario expectations.
- `personas.json`: four fictional builder cards with fixed pressure utterances.
- `teams.json`: three fictional panels with individually sealed submissions for each dossier. Collection-before-reveal is stipulated, not tested.

Coach uses a separate LLM call to generate one validated eleven-message builder script per fixture and seed. The same script prefix is replayed to all conditions. This preserves identical user messages, but is less responsive than adaptive conversation. The cap is twelve evaluated-agent replies, not twelve total messages and not three coaching rounds. A harness cap is censoring. A builder pressure moment not reached because an agent stops remains unexposed, not a successful resistance.

## Measurement safeguards

The headline is unsupported evidence upgrades, accompanied by rating coverage and supported-observation recognition. An agent that emits no evidence labels does not receive a perfect grade. Literal parsing supplies conservative counts; blinded semantic annotations handle unsupported paraphrases and ambiguous cases. Two judge calls must agree before a behavioral event is confirmed; disputed events remain missing, with both original judgments retained. Quality scores are averaged separately by dimension.

The judge receives no condition, system prompt, model ID, path, or private reverse map. Distinctive vocabulary is replaced with neutral tokens and a meaning-preserving legend. Exact positional ledgers permit reconstruction of every original text. Residual structural cues can still reveal the condition. Two calls to one judge are a repeatability check, not two independent judge models.

Bootstrap intervals pair conditions by fixture, seed, and task, resample fixture clusters within trap categories, then resample seed blocks. Both paired differences are reported in native units. Intervals crossing zero are labeled `no detectable difference`. No data means `not measured`, not a null result.

## Independent review

After live judging, the runner selects ten unique transcripts with seed `73001` and writes `hand_check/selection.json` and blank `scores/hand_check.csv` rows. The orchestration assistant or a human must read the blinded files, record independent usefulness/honesty/actionability scores before seeing judge scores, then document disagreements. That independent judgment cannot truthfully be manufactured by the same automated scoring call. Until it is completed, the live record is explicitly `hand_check_pending`.

In the current blocked record, there are no real transcripts to hand-check and no five live excerpts to quote. The report states those items are pending.

## Outputs

The dated record contains exact frozen source copies, protocol and judge snapshots, manifest and file hashes, condition prompts, every live transcript as JSONL when runs exist, raw judge results, reversible masking maps, CSV tables, bootstrap summaries, cost/latency records, a point-first Markdown report, figures, and the PDF. The console prints a ten-line status summary. Exit code `2` means a configuration, validation, provider, or live-pilot blocker; it is not a negative finding about the skill.

After the initial fictional run, preregister a separate follow-up cohort of 2–3 real team-built tools with authentic first-session records and six-week usage logs. Keep its estimates separate from the fictional exercise. No real records are supplied or implied by this package.

For complete scientific limits and plan differences, read `PROTOCOL.md` and the selected `REPORT.md` before interpreting any result.

## Separate delegated-v1 condition

The linked delegated reference and card schema are included in full by the new [delegated protocol](../docs/DELEGATED-EVALUATION.md), selected through `evals/delegated.py`. Its explicit `worth-using-delegated-evaluation/v1` preparation, canned smoke and call-bounded normal-transport collector do not change historical `run.py` conditions, records or empirical status. Collection is implemented but has been tested with fake transport only; no live result or usefulness claim is made.

Neutral controls are now selected by exact treatment hash from `controls/index.json` and frozen per new run. The original `placebo.txt` is retained for historical inspection only. Older source-record execution without a verifiable frozen matching control stops; `--analyze --record` remains available. See the v2 section in PROTOCOL.md.
