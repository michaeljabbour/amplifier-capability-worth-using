#!/usr/bin/env python3
"""Prepare the separately versioned delegated-v1 condition. Never calls a model.

The historical run.py conditions and records are deliberately unchanged. This
entry point freezes complete delegated treatment and paired fictional requests
for a later explicitly budgeted collection; preparation is not a live eval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
from prompts import PREAMBLE, parse_envelope
from providers import ConfigurationError, OfflineClient, Settings
from source_selection import load_sources, record_path, safe_run_id, _git, git_blob

PROFILE = "worth-using-delegated-evaluation/v1"
CONDITION = "delegated-v1"
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


def offline_smoke(root, record):
    """Exercise frozen requests with a canned transport; never a model result."""
    folder = record_path(root, record)
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("schema_version") != PROFILE:
        raise ConfigurationError("Select a delegated-v1 preparation, not a historical condition record")
    core = {snapshot for _, snapshot in TREATMENT} | {"prompts/delegated-v1.txt", "prompts/baseline.txt", "inputs/fixtures.json", "PROTOCOL.frozen.md"}
    hashes = manifest.get("file_hashes")
    if not isinstance(hashes, dict) or not core.issubset(hashes):
        raise ConfigurationError("Frozen delegated input membership is incomplete")
    for name, expected in manifest["file_hashes"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ConfigurationError("Unsafe frozen input path")
        path = folder / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != folder.parent):
            raise ConfigurationError("Frozen inputs must not use symlinks")
        if digest(path.read_bytes()) != expected:
            raise ConfigurationError("Frozen delegated input changed: " + name)
    output = folder / "offline-smoke"
    if output.exists():
        raise ConfigurationError("Offline probe already exists; never overwrite its outcome")
    task_names = sorted(name for name in manifest["file_hashes"] if name.startswith("tasks/") and name.endswith(".txt"))
    fixtures = json.loads((folder / "inputs/fixtures.json").read_text())
    expected_tasks = set()
    for fixture in fixtures["fixtures"]:
        safe_run_id(fixture["id"])
        expected_tasks.add("tasks/" + fixture["id"] + ".txt")
    if set(hashes) != core | expected_tasks:
        raise ConfigurationError("Frozen delegated input membership differs from its fixture set")
    files = {snapshot: (folder / snapshot).read_bytes() for _, snapshot in TREATMENT}
    sources = manifest.get("sources", [])
    if not isinstance(sources, list) or len(sources) != len(TREATMENT):
        raise ConfigurationError("Delegated source membership changed")
    for source, (expected_path, snapshot) in zip(sources, TREATMENT):
        if not isinstance(source, dict) or source.get("path") != expected_path or source.get("snapshot") != snapshot:
            raise ConfigurationError("Delegated source membership changed")
        if source.get("sha256") != digest(files[snapshot]) or source.get("blob_sha") != git_blob(files[snapshot]):
            raise ConfigurationError("Delegated source snapshot identity changed")
        if _git(root, "show", str(manifest.get("source_commit")) + ":" + expected_path) != files[snapshot]:
            raise ConfigurationError("Frozen delegated source differs from its selected commit")
    identity = {"profile": PROFILE, "source_hashes": {name: digest(data) for name, data in files.items()}, "inputs": hashes}
    if manifest.get("condition_version") != digest(json.dumps(identity, sort_keys=True)):
        raise ConfigurationError("Frozen delegated condition version changed")
    if (folder / "prompts/delegated-v1.txt").read_text() != condition_prompt(files) or (folder / "prompts/baseline.txt").read_text() != PREAMBLE:
        raise ConfigurationError("Frozen prompts differ from the declared condition composition")
    actual_tasks = sorted(str(path.relative_to(folder)) for path in (folder / "tasks").glob("*.txt"))
    if actual_tasks != task_names:
        raise ConfigurationError("Frozen delegated task membership changed")
    client = OfflineClient(Settings("eval", None, "offline", 0, 128, False))
    calls = []
    for name in task_names:
        task = folder / name
        request = task.read_text()
        for condition in (CONDITION, "baseline"):
            system = (folder / "prompts" / (condition + ".txt")).read_text()
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--offline-smoke", action="store_true")
    parser.add_argument("--record", required=True, help="Fresh YYYY-MM-DD/RUN_ID beneath docs/evaluations")
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parents[1]
        result = prepare(root, args.record) if args.prepare else offline_smoke(root, args.record)
    except (ConfigurationError, ValueError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
