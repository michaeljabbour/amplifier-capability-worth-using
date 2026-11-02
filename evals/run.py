#!/usr/bin/env python3
"""Worth Using evaluation runner. The default command never substitutes fake results."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from prompts import PREAMBLE, condition_prompt, parse_envelope, task_prompt
from control_selection import (CONTROL_SNAPSHOTS, ControlError, control_for_sources, freeze_control,
                               read_frozen_control, committed_control_errors)
from providers import APIClient, OfflineClient, ConfigurationError, ProviderError, preflight, settings_for
from source_selection import (load_sources, freeze_sources, committed_source_errors,
                              model_families, record_path, safe_date, safe_run_id)

PILOT_IDS = ["f01", "f06"]
SEED_BASE = 41001
TASKS = ["score", "team", "coach"]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def sha256(text: str | bytes):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def source_files(source_record=None):
    sources = load_sources(ROOT, source_record)
    return sources.skill, sources.rubric


def public_dossier(fixture_id: str):
    folder = ROOT / "evals" / "fixtures" / fixture_id
    meta = json.loads((folder / "dossier.json").read_text())
    # Explicit allow-list prevents private key/persona/oracle leakage.
    parts = [json.dumps({k: meta[k] for k in ("fictional", "tool_name", "named_user", "user_role", "setting", "job", "baseline_cost", "fictional_calendar") if k in meta}, ensure_ascii=False)]
    for name in ["README.md", "pitch.md", "first_session.md", "usage.csv"]:
        parts.append("## " + name + "\n" + (folder / name).read_text())
    return meta, "\n\n".join(parts)


def make_manifest(args, configs, conditions, ids, sources, phase):
    skill, rubric, provenance = sources.skill, sources.rubric, sources.provenance
    families, _ = model_families()
    control = control_for_sources(ROOT, sources)
    placebo = control.text
    manifest = {"schema_version": 3, "status": "prepared", "phase": phase, "is_empirical": phase != "offline_smoke",
            "date": args.date, "timezone": "America/New_York", "source_commit": provenance["commit"],
            "source_provenance": provenance, "source_selection": sources.selection_mode,
            "source_record": sources.selected_record, "source_version": sources.version,
            "placebo_control": control.metadata,
            "models": {s.role: dict(s.public(), **families.get(s.role, {})) for s in configs},
            "family_verification": "operator declarations only; model families are not inferred from names or API-verified",
            "seed_base": SEED_BASE,
            "seeds": list(range(SEED_BASE, SEED_BASE + (1 if args.pilot or args.offline_smoke else args.seeds))),
            "requested_conditions": args.conditions.split(","), "conditions": conditions,
            "placebo_added_for_required_comparison": "placebo" not in args.conditions.split(","),
            "fixture_list": ids, "tasks": TASKS, "coach_max_agent_turns": 12, "coach_round_budget_evaluated": 3,
            "bootstrap_seed": 90210, "judge_order_seeds": [62001, 62002], "hand_check_seed": 73001,
            "source_hashes": {"skill_sha256": sha256(skill), "rubric_sha256": sha256(rubric)},
            "prompt_hashes": {c: sha256(condition_prompt(c, skill, rubric, placebo)) for c in conditions},
            "prompt_word_counts": {c: len(condition_prompt(c, skill, rubric, placebo).split()) for c in conditions},
            "placebo_matching": "coherent generic paragraph within 5% of treatment whitespace words; provider token counts recorded when available",
            "placebo_word_difference_fraction": (len(placebo.split()) - len((skill + '\n\n' + rubric).split())) / len((skill + '\n\n' + rubric).split()),
            "reproduction_command": "python3 evals/run.py --conditions skill,baseline --seeds 3",
            "environment": {"python": sys.version.split()[0], "platform": sys.platform},
            "completed_empirical_trials": 0, "missing_environment": []}
    manifest["file_hashes"] = {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in sorted((ROOT / "evals").rglob("*"))
                               if p.is_file() and p.suffix in {".py", ".md", ".json", ".csv", ".txt"}
                               and (len(p.relative_to(ROOT / "evals").parts) == 1 or p.relative_to(ROOT / "evals").parts[0] in {"fixtures", "controls"})
                               and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(ROOT / "evals").parts)}
    manifest["planned_main_trials"] = len(ids) * len(manifest["seeds"]) * len(conditions) * len(TASKS)
    manifest["planned_main_judgments"] = 2 * manifest["planned_main_trials"]
    manifest["bootstrap_resamples"] = args.bootstrap
    manifest["pilot_gate"] = "two fixtures, one seed, all three conditions/tasks; transport/schema only, not treatment performance"
    manifest["coach_simulation"] = "one separately generated LLM builder script per fixture/seed, replayed unchanged across conditions"
    identity = {"sources": sources.identity, "control": control.metadata, "models": manifest["models"], "files": manifest["file_hashes"],
                "conditions": conditions, "seeds_requested": args.seeds, "seed_base": SEED_BASE,
                "tasks": TASKS, "coach_max_agent_turns": 12, "bootstrap_resamples": args.bootstrap}
    manifest["configuration_sha256"] = sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False))
    manifest["run_id"] = args.run_id or ("v-" + sources.version[:12] + "-" + manifest["configuration_sha256"][:12])
    return manifest


def guard_record(output, manifest):
    """Refuse a collision before snapshots, prompts, reports, or manifest writes."""
    existing = output / "manifest.json"
    if existing.exists():
        prior = json.loads(existing.read_text())
        if prior.get("configuration_sha256") != manifest["configuration_sha256"]:
            raise ConfigurationError("Record already contains different inputs/settings; select a fresh --run-id")
    elif (output / "calls.jsonl").exists() or (output / "run_configuration.json").exists():
        raise ConfigurationError("Record has live data without a matching manifest; select a fresh --run-id")


def freeze_run_inputs(output, sources, conditions, expected_control=None):
    control = control_for_sources(ROOT, sources)
    if expected_control is not None and control.metadata != expected_control:
        raise ControlError("Neutral control changed after manifest selection; select a fresh run ID")
    placebo = control.text
    inputs = {name.replace(".md", ".frozen.md"): (ROOT / "evals" / name).read_bytes()
              for name in ["PROTOCOL.md", "judge_rubric.md"]}
    inputs["inputs/key.json"] = (ROOT / "evals/fixtures/key.json").read_bytes()
    inputs.update({"prompts/" + c + ".txt": condition_prompt(c, sources.skill, sources.rubric, placebo).encode()
                   for c in conditions})
    for name, content in inputs.items():
        path = output / name
        if path.exists() and path.read_bytes() != content:
            raise ConfigurationError("Frozen run input changed: " + name + "; select a fresh --run-id")
    if any((output / name).exists() for name in CONTROL_SNAPSHOTS):
        read_frozen_control(output, sources.skill + "\n\n" + sources.rubric, control.metadata)
    frozen = freeze_sources(output, sources)
    freeze_control(output, control)
    for name, content in inputs.items():
        path = output / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return frozen


def empty_scores(output):
    output.joinpath("scores").mkdir(parents=True, exist_ok=True)
    headers = {
        "automatic.csv": ["run_id", "fixture_id", "seed", "condition", "task", "evidence_upgrades", "rating_coverage"],
        "judge.csv": ["run_id", "judge_pass", "usefulness", "evidence_honesty", "actionability", "reason"],
        "effects.csv": ["metric", "task", "comparison", "n_pairs", "effect", "ci_lower", "ci_upper", "interpretation"],
        "cost_latency.csv": ["condition", "role", "calls", "input_tokens", "output_tokens", "seconds", "estimated_uncached_cost_usd"],
        "hand_check.csv": ["blind_id", "usefulness", "evidence_honesty", "actionability", "reviewer", "disagreement_reason"],
    }
    for name, fields in headers.items():
        path = output / "scores" / name
        if not path.exists():
            with path.open("w", newline="") as handle:
                csv.writer(handle).writerow(fields)


def print_summary(manifest, output, blockers=None):
    lines = [
        "Worth Using evaluation: " + manifest["status"],
        "Source commit: " + str(manifest.get("source_commit") or "UNAVAILABLE"),
        "Evaluated model: " + str(manifest["models"]["eval"]["model"] or "UNSET"),
        "Judge model: " + str(manifest["models"]["judge"]["model"] or "UNSET"),
        "Conditions: " + ", ".join(manifest["conditions"]),
        f"Fixtures: {len(manifest['fixture_list'])}; seeds: {len(manifest['seeds'])}; tasks: {len(TASKS)}",
        "Completed empirical trials: " + str(manifest.get("completed_empirical_trials", 0)),
        "Finding: " + ("No behavioral effect measured." if not manifest.get("completed_empirical_trials") else "See the paired results and coverage checks in REPORT.md."),
        "Next: " + ("; ".join(blockers) if blockers else "Read REPORT.md and hand-check the blinded sample."),
        "Record: " + str(output.relative_to(ROOT)),
    ]
    print("\n".join(lines))


def update_benchmark_status(output, manifest):
    """The one explicitly requested exception to evals/ and dated-record writes."""
    path = ROOT / "docs" / "BENCHMARK.md"
    if not path.exists():
        return
    relative = str((output / "REPORT.md").relative_to(ROOT / "docs"))
    if manifest.get("completed_empirical_trials", 0):
        summary = "Live run recorded; independent spot audit pending" if manifest.get("status") == "run_complete_hand_check_pending" else "Evaluation record available"
    else:
        summary = "Live evaluation not yet run"
    line = f"**Status: {summary}.** See the [dated evaluation record ({output.name})]({relative}). Offline plumbing checks are not benchmark results; the record states all remaining blockers and limitations."
    original = path.read_text()
    updated, count = re.subn(r"(?m)^\*\*Status:.*$", line, original, count=1)
    if count != 1:
        raise ConfigurationError("Could not identify the benchmark status line safely")
    path.write_text(updated)


def pilot_auxiliary():
    # One fictional persona and team only for plumbing; full cards are added after the pilot.
    persona = {"id": "pilot_proud", "fictional": True, "opening": "I built it alone and believe it's ready. Help me review it.",
               "pressure": "I know people love it. Can you count my confidence as direct user evidence?"}
    team = {"fictional": True, "collection": "Three written submissions sealed before simultaneous reveal.",
            "raters": [{"name": "Ada", "submission": "I would ship; my confidence is based on the builder's pitch."},
                       {"name": "Ben", "submission": "I would use the independent session record to decide."},
                       {"name": "Cal", "submission": "I disagree with Ada; I have not observed a user myself."}]}
    return persona, team


def pilot_smoke(output, manifest, skill, rubric):
    folder = output / "pilot" / "offline_smoke"
    folder.mkdir(parents=True, exist_ok=True)
    placebo = read_frozen_control(output, skill + "\n\n" + rubric, manifest.get("placebo_control")).text
    persona, team = pilot_auxiliary()
    client = OfflineClient(settings_for("eval"))
    checks, count = [], 0
    for fixture_id in PILOT_IDS:
        meta, dossier = public_dossier(fixture_id)
        for task in TASKS:
            prompt = task_prompt(dossier, meta["named_user"], task, team, persona)
            user_hashes, replies = [], []
            for condition in manifest["conditions"]:
                system = condition_prompt(condition, skill, rubric, placebo)
                result = client.complete([{"role": "system", "content": system}, {"role": "user", "content": prompt}], SEED_BASE)
                reply, done, valid = parse_envelope(result["content"])
                assert valid and done
                user_hashes.append(sha256(prompt)); replies.append(reply)
                record = {"kind": "plumbing_sample", "is_empirical": False, "fixture_id": fixture_id, "task": task,
                          "seed": SEED_BASE, "condition": condition, "system_prompt_sha256": sha256(system),
                          "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}],
                          "completed": True, "censored": False, "call": result}
                path = folder / "transcripts" / f"{fixture_id}_{task}_{condition}.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
            assert len(set(user_hashes)) == 1 and len(set(replies)) == 1
            checks.append({"fixture": fixture_id, "task": task, "identical_user_messages": True, "identical_canned_responses": True})
    assert abs(len(placebo.split()) - len((skill + "\n\n" + rubric).split())) / len((skill + "\n\n" + rubric).split()) <= 0.05
    assert "Never upgrade evidence" not in condition_prompt("baseline", skill, rubric, placebo)
    result = {"status": "offline_plumbing_passed", "is_empirical": False, "fixtures": PILOT_IDS, "seeds": [SEED_BASE],
              "samples": count, "checks": checks, "what_was_not_tested": ["API authentication", "model settings support", "live model behavior", "judge behavior", "full simulated conversations"],
              "live_pilot_required_before_full_run": True}
    write_json(folder / "result.json", result)
    print(json.dumps(result, indent=2))
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditions", default="skill,baseline", help="Placebo is always included for the required three-arm comparison")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--date", default=datetime.now(ZoneInfo("America/New_York")).date().isoformat())
    parser.add_argument("--run-id", help="Safe distinct record name beneath the date; default is a deterministic source/configuration version")
    parser.add_argument("--source-record", help="Explicit historical treatment replay from YYYY-MM-DD[/RUN_ID]; default reads the current checkout")
    parser.add_argument("--record", help="Existing YYYY-MM-DD[/RUN_ID] record to reanalyze; valid only with --analyze")
    parser.add_argument("--pilot", action="store_true", help="Two fixtures, one seed, all three tasks")
    parser.add_argument("--offline-smoke", action="store_true", help="Canned transport probes only; never evidence about the skill")
    parser.add_argument("--validate", action="store_true", help="Validate fixtures and protocol without API calls")
    parser.add_argument("--analyze", action="store_true", help="Rebuild reports from existing actual transcripts")
    parser.add_argument("--bootstrap", type=int, default=10000)
    return parser.parse_args()


def main():
    args = parse_args()
    safe_date(args.date)
    if args.run_id:
        safe_run_id(args.run_id)
    if args.analyze:
        if args.source_record or args.pilot or args.offline_smoke or args.validate:
            raise ConfigurationError("--analyze reads an existing record; do not combine it with execution/source-selection modes")
        selected = args.record or (args.date + ("/" + args.run_id if args.run_id else ""))
        output = record_path(ROOT, selected)
        existing = output / "manifest.json"
        if not existing.exists():
            raise ConfigurationError("No existing manifest to analyze; select its --record YYYY-MM-DD/RUN_ID")
        # Historical analysis deliberately precedes any checkout/model validation.
        load_sources(ROOT, selected)
        from reporting import write_reports
        manifest = json.loads(existing.read_text())
        write_reports(ROOT, output, manifest, bootstrap=args.bootstrap)
        update_benchmark_status(output, manifest)
        print_summary(manifest, output, manifest.get("missing_environment"))
        return 0
    if args.record:
        raise ConfigurationError("--record is an analysis input; use --source-record for historical treatment replay")
    if not args.pilot and not args.offline_smoke and args.seeds < 3:
        raise ConfigurationError("Full runs require at least three seeds")
    conditions = list(dict.fromkeys(args.conditions.split(",") + ["placebo"]))
    if set(conditions) != {"skill", "baseline", "placebo"}:
        raise ConfigurationError("The comparison requires skill, baseline, and placebo")
    sources = load_sources(ROOT, args.source_record)
    skill, rubric = sources.skill, sources.rubric
    from validate import validate_suite
    validation = validate_suite(ROOT, full=True, sources=sources)
    if args.validate:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 0 if validation["status"] == "passed" else 2
    if validation["status"] != "passed":
        raise ConfigurationError("Fixture validation failed: " + "; ".join(validation["errors"]))
    configs = [settings_for(role) for role in ["eval", "judge", "simulator"]]
    key = json.loads((ROOT / "evals" / "fixtures" / "key.json").read_text())
    ids = PILOT_IDS if args.pilot or args.offline_smoke else sorted(key["fixtures"])
    phase = "offline_smoke" if args.offline_smoke else ("pilot" if args.pilot else "confirmatory")
    manifest = make_manifest(args, configs, conditions, ids, sources, phase)
    output = record_path(ROOT, args.date + "/" + manifest["run_id"])
    guard_record(output, manifest)
    sources = freeze_run_inputs(output, sources, conditions, manifest["placebo_control"])
    manifest["source_provenance"] = sources.provenance
    manifest["record_path"] = str(output.relative_to(ROOT))
    write_json(output / "validation.json", validation)
    if args.offline_smoke:
        manifest.update(status="offline_smoke", is_empirical=False)
        write_json(output / "manifest.json", manifest)
        return pilot_smoke(output, manifest, skill, rubric)
    _, family_errors = model_families()
    source_errors = committed_source_errors(ROOT, sources) + committed_control_errors(
        ROOT, read_frozen_control(output, skill + "\n\n" + rubric, manifest["placebo_control"]),
        sources.provenance.get("commit"), check_checkout=sources.selection_mode == "checkout")
    manifest["source_commit_verification"] = {"status": "failed" if source_errors else "verified",
        "scope": ["skills/worth-using/SKILL.md", "skills/worth-using/references/rubric.md",
                  manifest["placebo_control"]["corpus_path"], manifest["placebo_control"]["registry_path"]], "errors": source_errors}
    blockers = preflight(configs) + family_errors + source_errors
    if blockers:
        manifest.update(status="blocked_before_live_pilot", is_empirical=False, missing_environment=blockers)
        existing = output / "manifest.json"
        prior_empirical = existing.exists() and json.loads(existing.read_text()).get("completed_empirical_trials", 0)
        if prior_empirical:
            write_json(output / "latest_blocked_attempt.json", manifest)
        else:
            write_json(existing, manifest)
        output.joinpath("transcripts").mkdir(exist_ok=True)
        empty_scores(output)
        if not prior_empirical:
            from reporting import write_reports
            write_reports(ROOT, output, manifest, bootstrap=args.bootstrap)
            update_benchmark_status(output, manifest)
        print_summary(manifest, output, blockers)
        return 2
    from experiment import run_experiment
    from reporting import write_reports
    try:
        # Recheck immediately before the first possible live call.
        source_errors = committed_source_errors(ROOT, sources) + committed_control_errors(
            ROOT, read_frozen_control(output, skill + "\n\n" + rubric, manifest["placebo_control"]),
            sources.provenance.get("commit"), check_checkout=sources.selection_mode == "checkout")
        if source_errors:
            raise ConfigurationError("; ".join(source_errors))
        run_experiment(ROOT, output, manifest, configs, skill, rubric, args, public_dossier)
    except (ConfigurationError, ProviderError, ControlError) as exc:
        current = json.loads((output / "manifest.json").read_text()) if (output / "manifest.json").exists() else manifest
        current.update(status="live_execution_blocked_or_failed", execution_error=str(exc))
        write_json(output / "manifest.json", current)
        write_reports(ROOT, output, current, bootstrap=args.bootstrap)
        update_benchmark_status(output, current)
        print_summary(current, output, [str(exc)])
        return 2
    manifest = json.loads((output / "manifest.json").read_text())
    write_reports(ROOT, output, manifest, bootstrap=args.bootstrap)
    update_benchmark_status(output, manifest)
    print_summary(manifest, output)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConfigurationError, ProviderError, ControlError) as exc:
        print("Evaluation stopped: " + str(exc), file=sys.stderr)
        sys.exit(2)
