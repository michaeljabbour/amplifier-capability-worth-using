# Delegated evaluation condition v1

This is a new condition, `delegated-v1`, under protocol identifier `worth-using-delegated-evaluation/v1`. It does not replace the historical `skill`, `baseline` or `placebo` conditions in `run.py`. Their prompt bytes, frozen snapshots and historical records remain unchanged.

The complete treatment is the current committed SKILL, rubric, delegated-runs reference and usefulness-card schema. The two linked files are inserted in full rather than assumed available to a model with no filesystem. Every byte, source path, Git blob, selected commit and exact prompt is frozen in a fresh record. A change to either new reference changes the condition version. Missing or dirty treatment files fail before a record is prepared. Existing records are never rewritten.

Prepare without a provider call:

```sh
python3 evals/delegated.py --prepare --record 2026-11-01/delegated-v1-preparation
```

This command creates a **preparation record only**. It does not run an evaluated agent or judge, and it does not modify `docs/BENCHMARK.md`. The manifest records zero empirical trials and zero API calls. The historical runner intentionally rejects this new condition rather than accidentally analyzing it as its old `skill` arm.

The optional offline transport check consumes those exact frozen prompts and tasks with the existing canned client:

```sh
python3 evals/delegated.py --offline-smoke --record 2026-11-01/delegated-v1-preparation
```

It writes a new `offline-smoke/RESULT.json`, refuses changed input hashes or task membership, and records zero empirical trials. It never replaces the preparation or an earlier smoke result.

## Paired fictional tasks

Both the new treatment and its plain baseline use the same task file. The public requests are constructed only from `request` and `context`; `expected_checks` are not included in model requests. The fixture set covers a builder/agent walkthrough, a supplied record of specific outside use, and a later independent Score card. Every person and event is fictional. Scoring within a fictional record does not establish actual outside-user usefulness.

Required checks are separate: six criteria and their evidence grades; no upgrade of a team walkthrough; supported outside observations only; no invented unprompted return; unknown costs and unanswered questions preserved; no fabricated builder choice/growth; null Score budget; explicit positive Coach budget and index within it; later cards do not rewrite earlier ones. Native boundary tests use fixed candidate cards and supplied record metadata. They test the checker, not model behavior.

`card_contract.semantic_errors` checks cross-field relationships and the presence of matching dated outside-use metadata. Such metadata must be supplied by the operator. It makes no network requests, does not open evidence paths and cannot establish that records are authentic or sufficient in the real world. Read the records yourself. JSON Schema covers structure; the semantic checker covers relations such as index versus budget.

## Empirical collection remains unrun

No new provider budget is authorized. This preparation has no length-matched placebo, different-family blind judge, calibrated metric or measured treatment effect. It is not Right Shape L1 and cannot inherit historical results. Before a live collection, preregister a fixed task set, shared transport, budget and stop rule, a length-matched placebo, paired randomization, independent-family judgment and evidence-grounded error denominators. A collector must use the frozen prompt/task bytes and identify this new condition explicitly; no live collection is implemented by this entry point.

Run the standard-library semantic and treatment tests with `python3 -m unittest discover -s evals -p 'test_*.py'`. JSON Schema tests also run when the existing `jsonschema` test tool is available; otherwise those cases explicitly skip. No dependency is downloaded by tests or preparation. These are software/conformance results, not observations of a human using a tool.
