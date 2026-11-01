#!/usr/bin/env python3
"""Prepare or explicitly collect the separately versioned delegated-v1 condition.

The historical run.py conditions and records are deliberately unchanged. This
entry point freezes complete delegated treatment and paired fictional requests
for an explicitly call-bounded collection; preparation is not a live eval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import sys
import time

sys.dont_write_bytecode = True
from prompts import PREAMBLE, parse_envelope
from providers import APIClient, ConfigurationError, ProviderError, OfflineClient, Settings, settings_for
from source_selection import load_sources, record_path, safe_run_id, _git, git_blob

PROFILE = "worth-using-delegated-evaluation/v1"
CONDITION = "delegated-v1"
COLLECTOR_VERSION = "worth-using-delegated-collector/v1"
ROOT = Path(__file__).resolve().parents[1]
TREATMENT = (
    ("skills/worth-using/SKILL.md", "SKILL.snapshot.md"),
    ("skills/worth-using/references/rubric.md", "rubric.snapshot.md"),
    ("skills/worth-using/references/delegated-runs.md", "delegated-runs.snapshot.md"),
    ("skills/worth-using/references/usefulness-card.schema.json", "usefulness-card.schema.snapshot.json"),
)


def digest(value):
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def material(root):
    """Load every linked treatment file; missing extras never fall back to legacy."""
    result = {}
    for path, snapshot in TREATMENT:
        target = root / path
        if not target.is_file() or target.is_symlink():
            raise ConfigurationError("Delegated treatment requires a regular file: " + path)
        result[snapshot] = target.read_bytes()
    return result


def condition_prompt(files):
    parts = [PREAMBLE]
    for _, snapshot in TREATMENT:
        parts.append("<treatment_file name=" + json.dumps(snapshot) + ">\n" + files[snapshot].decode() + "\n</treatment_file>")
    return "\n\n".join(parts)


def prepare(root, record):
    """Create a fresh, immutable preparation record; reject historical collisions."""
    output = record_path(root, record)
    if output.exists():
        raise ConfigurationError("Delegated preparation needs a fresh record; existing records are never rewritten")
    files = material(root)
    provenance = load_sources(root).provenance
    commit = provenance.get("commit")
    if not commit:
        raise ConfigurationError("Commit the delegated treatment before freezing it")
    for source, snapshot in TREATMENT:
        if _git(root, "show", commit + ":" + source) != files[snapshot]:
            raise ConfigurationError("Delegated treatment differs from selected commit: " + source)
    full = condition_prompt(files)
    baseline = PREAMBLE
    tasks = json.loads((root / "evals/delegated-fixtures.json").read_text())
    protocol = (root / "docs/DELEGATED-EVALUATION.md").read_bytes()
    inputs = dict(files)
    inputs.update({"prompts/delegated-v1.txt": full.encode(), "prompts/baseline.txt": baseline.encode(),
                   "inputs/fixtures.json": json.dumps(tasks, indent=2).encode() + b"\n",
                   "PROTOCOL.frozen.md": protocol})
    for fixture in tasks["fixtures"]:
        safe_run_id(fixture["id"])
        request = fixture["request"] + "\n\n<fictional_context>\n" + json.dumps(fixture["context"], indent=2) + "\n</fictional_context>"
        inputs["tasks/" + fixture["id"] + ".txt"] = request.encode()
    source_hashes = {name: digest(data) for name, data in files.items()}
    identity = {"profile": PROFILE, "source_hashes": source_hashes,
                "inputs": {name: digest(data) for name, data in inputs.items()}}
    manifest = {"schema_version": PROFILE, "status": "prepared-not-executed", "is_empirical": False,
                "conditions": [CONDITION, "baseline"], "source_commit": commit,
                "condition_version": digest(json.dumps(identity, sort_keys=True)),
                "sources": [{"path": source, "snapshot": snapshot, "sha256": source_hashes[snapshot], "blob_sha": git_blob(files[snapshot])}
                            for source, snapshot in TREATMENT],
                "file_hashes": identity["inputs"], "completed_empirical_trials": 0,
                "api_calls": 0, "control_limit": "No length-matched placebo or blinded different-family run collected. Not Right Shape L1.",
                "historical_runner": "run.py skill/baseline/placebo conditions and historical records are unchanged.",
                "reproduction": "python3 evals/delegated.py --prepare --record " + record}
    output.mkdir(parents=True)
    for name, data in inputs.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def frozen_inputs(root, record):
    """Validate and capture one immutable in-memory request set before any call."""
    folder = record_path(root, record)
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("schema_version") != PROFILE:
        raise ConfigurationError("Select a delegated-v1 preparation, not a historical condition record")
    core = {snapshot for _, snapshot in TREATMENT} | {"prompts/delegated-v1.txt", "prompts/baseline.txt", "inputs/fixtures.json", "PROTOCOL.frozen.md"}
    hashes = manifest.get("file_hashes")
    if not isinstance(hashes, dict) or not core.issubset(hashes):
        raise ConfigurationError("Frozen delegated input membership is incomplete")
    captured = {}
    for name, expected in manifest["file_hashes"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ConfigurationError("Unsafe frozen input path")
        path = folder / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != folder.parent):
            raise ConfigurationError("Frozen inputs must not use symlinks")
        captured[name] = path.read_bytes()
        if digest(captured[name]) != expected:
            raise ConfigurationError("Frozen delegated input changed: " + name)
    task_names = sorted(name for name in manifest["file_hashes"] if name.startswith("tasks/") and name.endswith(".txt"))
    fixtures = json.loads(captured["inputs/fixtures.json"])
    expected_tasks = set()
    for fixture in fixtures["fixtures"]:
        safe_run_id(fixture["id"])
        expected_tasks.add("tasks/" + fixture["id"] + ".txt")
    if set(hashes) != core | expected_tasks:
        raise ConfigurationError("Frozen delegated input membership differs from its fixture set")
    files = {snapshot: captured[snapshot] for _, snapshot in TREATMENT}
    sources = manifest.get("sources", [])
    if not isinstance(sources, list) or len(sources) != len(TREATMENT):
        raise ConfigurationError("Delegated source membership changed")
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise ConfigurationError("Frozen delegated source requires an exact full Git commit hash")
    resolved = _git(root, "rev-parse", "--verify", commit + "^{commit}")
    if not resolved or resolved.decode().strip() != commit:
        raise ConfigurationError("Frozen delegated source commit is unavailable or not exact")
    for source, (expected_path, snapshot) in zip(sources, TREATMENT):
        if not isinstance(source, dict) or source.get("path") != expected_path or source.get("snapshot") != snapshot:
            raise ConfigurationError("Delegated source membership changed")
        if source.get("sha256") != digest(files[snapshot]) or source.get("blob_sha") != git_blob(files[snapshot]):
            raise ConfigurationError("Delegated source snapshot identity changed")
        if _git(root, "show", commit + ":" + expected_path) != files[snapshot]:
            raise ConfigurationError("Frozen delegated source differs from its selected commit")
    identity = {"profile": PROFILE, "source_hashes": {name: digest(data) for name, data in files.items()}, "inputs": hashes}
    if manifest.get("condition_version") != digest(json.dumps(identity, sort_keys=True)):
        raise ConfigurationError("Frozen delegated condition version changed")
    if captured["prompts/delegated-v1.txt"].decode() != condition_prompt(files) or captured["prompts/baseline.txt"].decode() != PREAMBLE:
        raise ConfigurationError("Frozen prompts differ from the declared condition composition")
    actual_tasks = sorted(str(path.relative_to(folder)) for path in (folder / "tasks").glob("*.txt"))
    if actual_tasks != task_names:
        raise ConfigurationError("Frozen delegated task membership changed")
    return folder, manifest, task_names, captured


def offline_smoke(root, record):
    """Exercise frozen requests with a canned transport; never a model result."""
    folder, manifest, task_names, captured = frozen_inputs(root, record)
    output = folder / "offline-smoke"
    if output.exists():
        raise ConfigurationError("Offline probe already exists; never overwrite its outcome")
    client = OfflineClient(Settings("eval", None, "offline", 0, 128, False))
    calls = []
    for name in task_names:
        task = folder / name
        request = captured[name].decode()
        for condition in (CONDITION, "baseline"):
            system = captured["prompts/" + condition + ".txt"].decode()
            response = client.complete([{"role": "system", "content": system}, {"role": "user", "content": request}], 41001)
            _, _, valid = parse_envelope(response["content"])
            calls.append({"task": task.stem, "condition": condition,
                          "system_prompt_sha256": digest(system), "user_prompt_sha256": digest(request),
                          "envelope_valid": valid, "response": response})
    result = {"schema_version": PROFILE, "status": "offline-transport-only", "is_empirical": False,
              "synthetic": True, "completed_empirical_trials": 0, "provider_api_calls": 0,
              "completed_transport_probes": len(calls), "calls": calls,
              "scope": "Canned responses verify frozen input plumbing only; no quality, usefulness or evidence-grade outcome is inferred."}
    output.mkdir()
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def collect(root, record, client, *, max_calls, collection_id="trial-1", seed=41001,
            configuration=None, synthetic=True):
    """Execute fixed single-turn requests through an explicitly supplied transport.

    Injection defaults to synthetic. Only the CLI's explicitly selected APIClient
    path sets synthetic=False. Errors stop the collection with no automatic retry.
    No advice is executed and no usefulness or comparative score is assigned here.
    """
    folder, manifest, task_names, captured = frozen_inputs(root, record)
    safe_run_id(collection_id)
    schedule = [(name, condition) for name in task_names for condition in (CONDITION, "baseline")]
    if type(max_calls) is not int or max_calls < 1 or len(schedule) > max_calls:
        raise ConfigurationError("The entire fixed collection must fit an explicit positive --max-calls budget")
    output = folder / "collections" / collection_id
    if (folder / "collections").is_symlink() or not output.resolve().is_relative_to(folder.resolve()):
        raise ConfigurationError("Collection destination escapes the selected record")
    if output.exists():
        raise ConfigurationError("Collection already exists; select a new ID instead of overwriting or retrying it")
    output.mkdir(parents=True)
    for name, data in captured.items():
        path = output / "captured-inputs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    calls = []
    result = {"schema_version": PROFILE, "status": "collection-running", "is_empirical": False,
              "collector_version": COLLECTOR_VERSION, "collector_sha256": digest(Path(__file__).read_bytes()),
              "synthetic": synthetic, "condition_version": manifest["condition_version"],
              "source_commit": manifest["source_commit"], "conditions": [CONDITION, "baseline"],
              "configuration": configuration or {}, "seed": seed, "max_calls": max_calls,
              "input_hashes": manifest["file_hashes"], "schedule_order": "sorted tasks; delegated-v1 then baseline; no randomization claim",
              "scheduled_trials": len(schedule), "attempted_calls": 0, "completed_transport_calls": 0,
              "completed_trials": 0, "completed_empirical_trials": 0, "calls": calls,
              "scope": "One response per paired fictional request. No follow-up or advice execution. Raw trials need separate grading; no effect, calibration or outside-user outcome is inferred."}

    def save():
        (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

    save()
    allowed_response = {"content", "model_requested", "model_returned", "provider", "system_fingerprint",
                        "temperature", "max_tokens", "seed_requested", "seed_sent", "latency_seconds",
                        "usage", "usage_missing", "estimated_uncached_cost_usd", "finish_reason", "is_empirical"}
    for name, condition in schedule:
        system = captured["prompts/" + condition + ".txt"].decode()
        request = captured[name].decode()
        call = {"task": Path(name).stem, "condition": condition,
                "system_prompt_sha256": digest(system), "user_prompt_sha256": digest(request),
                "status": "started", "is_empirical": False}
        calls.append(call)
        result["attempted_calls"] += 1
        save()
        started = time.monotonic()
        try:
            response = client.complete([{"role": "system", "content": system}, {"role": "user", "content": request}], seed)
            if not isinstance(response, dict) or not isinstance(response.get("content"), str):
                raise ProviderError("Transport response must provide text content")
            call["response"] = {key: value for key, value in response.items() if key in allowed_response}
            reply, done, valid = parse_envelope(response["content"])
            call.update(reply=reply, done=done, envelope_valid=valid,
                        status="completed" if valid and done else "incomplete-response",
                        is_empirical=not synthetic and response.get("is_empirical") is not False)
            result["completed_transport_calls"] += 1
            if call["status"] == "completed":
                result["completed_trials"] += 1
                result["completed_empirical_trials"] += int(call["is_empirical"])
        except Exception as error:
            call.update(status="transport-error", error_type=type(error).__name__,
                        error=str(error) if isinstance(error, (ProviderError, ConfigurationError)) else "Transport failed; details omitted",
                        billing_or_server_execution_unknown=not synthetic)
            result["status"] = "collection-stopped-on-error"
            call["seconds"] = time.monotonic() - started
            save()
            break
        call["seconds"] = time.monotonic() - started
        save()
    else:
        result["status"] = "collection-complete" if result["completed_trials"] == len(schedule) else "collection-has-incomplete-responses"
    result["is_empirical"] = any(call["is_empirical"] for call in calls)
    save()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--offline-smoke", action="store_true")
    mode.add_argument("--collect", action="store_true", help="Execute an approved normal-transport collection; incurs provider calls")
    parser.add_argument("--record", required=True, help="Fresh YYYY-MM-DD/RUN_ID beneath docs/evaluations")
    parser.add_argument("--max-calls", type=int, help="Required explicit call budget for --collect; no automatic retries")
    parser.add_argument("--collection-id", default="trial-1")
    parser.add_argument("--seed", type=int, default=41001)
    args = parser.parse_args(argv)
    try:
        root = ROOT
        if args.prepare:
            result = prepare(root, args.record)
        elif args.offline_smoke:
            result = offline_smoke(root, args.record)
        else:
            if args.max_calls is None:
                raise ConfigurationError("--collect requires an explicit --max-calls budget")
            cfg = settings_for("eval")
            if not cfg.model or cfg.max_tokens <= 0:
                raise ConfigurationError("Choose EVAL_MODEL and a positive EVAL_MAX_TOKENS before collection")
            if not 0 <= cfg.temperature <= (1 if cfg.provider == "anthropic" else 2):
                raise ConfigurationError("EVAL_TEMPERATURE is outside the configured provider range")
            key = "ANTHROPIC_API_KEY" if cfg.provider == "anthropic" else "OPENAI_API_KEY"
            if not os.environ.get(key):
                raise ConfigurationError(key + " is unset")
            result = collect(root, args.record, APIClient(cfg), max_calls=args.max_calls,
                             collection_id=args.collection_id, seed=args.seed,
                             configuration=cfg.public(), synthetic=False)
    except (ConfigurationError, ValueError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    if args.collect and result["status"] != "collection-complete":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
