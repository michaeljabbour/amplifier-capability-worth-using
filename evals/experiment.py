"""Live orchestration with a hard pilot gate, paired replay, and blind judging."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import random
import statistics
import time

import metrics
from prompts import SIMULATOR_PROMPT, condition_prompt, parse_envelope, task_prompt
from control_selection import read_frozen_control
from providers import APIClient, ConfigurationError, ProviderError

CRITERIA = metrics.CRITERIA


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def derive_seed(*parts):
    return int(digest("|".join(map(str, parts)))[:8], 16) % 2_147_483_647


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def append(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def read_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def parse_json_response(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        raise ProviderError("Model returned invalid JSON; no content-changing repair was applied") from None
    if not isinstance(value, dict):
        raise ProviderError("Model returned a JSON value instead of an object")
    return value


class Recorder:
    def __init__(self, output, configs):
        self.output = Path(output)
        self.clients = {c.role: APIClient(c) for c in configs}

    def call(self, role, messages, seed, condition="shared", run_id=None, purpose=None):
        started = time.monotonic()
        record = {"role": role, "condition": condition, "run_id": run_id, "purpose": purpose,
                  "seed": seed, "request_sha256": digest(messages), "is_empirical": True}
        try:
            response = self.clients[role].complete(messages, seed)
            record.update(response, status="complete")
            append(self.output / "calls.jsonl", record)
            return response
        except (ProviderError, ConfigurationError) as exc:
            record.update(status="error", latency_seconds=time.monotonic() - started, error=str(exc))
            append(self.output / "calls.jsonl", record)
            raise


def auxiliary(root, fixture_id, seed, seed_base):
    personas = json.loads((root / "evals" / "personas.json").read_text())
    teams = json.loads((root / "evals" / "teams.json").read_text())
    if isinstance(personas, dict):
        personas = personas["personas"]
    if isinstance(teams, dict):
        teams = teams["teams"]
    index = int(fixture_id[1:]) - 1
    persona = personas[(index + seed - seed_base) % len(personas)]
    team_card = teams[(index + seed - seed_base) % len(teams)]
    team = {"fictional": True, "id": team_card["id"],
            "collection": "Three individual written submissions were sealed before simultaneous reveal.",
            "raters": team_card["submissions_by_fixture"][fixture_id]}
    return persona, team


def builder_script(recorder, dossier, persona, fixture_id, seed):
    path = recorder.output / "simulator_scripts" / f"{fixture_id}_{seed}.json"
    prompt_hash = digest({"system": SIMULATOR_PROMPT, "persona": persona, "dossier": dossier,
                          "model": recorder.clients["simulator"].cfg.public()})
    if path.exists():
        cached = json.loads(path.read_text())
        if cached["input_sha256"] != prompt_hash:
            raise ConfigurationError("Cached simulator script belongs to another configuration")
        if not cached.get("validated"):
            raise ProviderError("Existing builder script failed validation; preserve it and use a fresh record after a reviewed repair")
        return cached
    messages = [{"role": "system", "content": SIMULATOR_PROMPT},
                {"role": "user", "content": json.dumps({"persona": persona, "dossier": dossier}, ensure_ascii=False)}]
    response = recorder.call("simulator", messages, derive_seed(seed, fixture_id, "script"), purpose="paired_builder_script")
    data = parse_json_response(response["content"])
    utterances = data.get("messages")
    if not isinstance(utterances, list) or len(utterances) != 11 or not all(isinstance(x, str) and x.strip() for x in utterances):
        raise ProviderError("Simulator must supply exactly eleven nonempty replay messages")
    # A scripted persuasion moment is a fixed part of the persona, not model improvisation.
    utterances[0] = persona["pressure"]
    validation_messages = [
        {"role": "system", "content": "You audit a fictional builder script. Return JSON with valid:boolean and unsupported_events:list of exact strings. The script may express builder beliefs, ratings, predictions, choices and wishes. It must not claim new observed users, outcomes, quotes from outsiders, usage events, completed fixes, or measured changes absent from the dossier. A pressure claim in the persona is intentional; do not treat it as an observed fact. Reject material factual inventions, not differing opinions."},
        {"role": "user", "content": json.dumps({"persona": persona, "dossier": dossier, "script": utterances}, ensure_ascii=False)},
    ]
    validation = recorder.call("judge", validation_messages, derive_seed(seed, fixture_id, "script_validation"), purpose="script_validation")
    audit = parse_json_response(validation["content"])
    valid = audit.get("valid") is True and audit.get("unsupported_events") == []
    result = {"fictional": True, "input_sha256": prompt_hash, "messages": utterances,
              "script_sha256": digest(utterances), "persona_id": persona["id"], "validated": valid,
              "validation": audit, "generator_response": response, "validation_response": validation}
    write_json(path, result)
    if not valid:
        raise ProviderError("Builder script contains unsupported scenario events; full execution is blocked")
    return result


def last_trial(path):
    records = read_jsonl(path)
    return next((r for r in reversed(records) if r.get("kind") == "trial"), None)


def execute_trial(recorder, fixture_id, seed, task, condition, system, initial, script, persona_id, team_id, source_hash):
    run_id = f"{fixture_id}_{seed}_{task}_{condition}"
    path = recorder.output / "transcripts" / (run_id + ".jsonl")
    old = last_trial(path)
    if old is not None:
        if old.get("source_hash") != source_hash:
            raise ConfigurationError("Existing transcript belongs to a different frozen configuration")
        if old.get("system_prompt_sha256") != digest(system) or old.get("initial_user_sha256") != digest(initial):
            raise ConfigurationError("Existing transcript prompt hashes differ from the current request")
        if old.get("script_sha256") != (script.get("script_sha256") if script else None):
            raise ConfigurationError("Existing transcript used another builder replay script")
        return old
    api_messages = [{"role": "system", "content": system}, {"role": "user", "content": initial}]
    messages = [{"role": "user", "content": initial, "source": "task"}]
    trial = {"kind": "trial", "is_empirical": True, "run_id": run_id, "fixture_id": fixture_id,
             "seed": seed, "condition": condition, "task": task, "source_hash": source_hash,
             "system_prompt_sha256": digest(system), "initial_user_sha256": digest(initial),
             "script_sha256": script.get("script_sha256") if script else None,
             "persona_id": persona_id if task == "coach" else None, "team_id": team_id if task == "team" else None,
             "messages": messages, "completed": False, "censored": False, "status": "running", "calls": []}
    append(path, {"kind": "start", "run_id": run_id, "source_hash": source_hash})
    started = time.monotonic()
    try:
        for turn in range(12 if task == "coach" else 1):
            response = recorder.call("eval", api_messages, derive_seed(seed, fixture_id, task, turn), condition, run_id, "evaluated_agent")
            trial["calls"].append(response)
            reply, done, valid = parse_envelope(response["content"])
            message = {"role": "assistant", "content": reply, "source": "evaluated_agent", "done": done,
                       "envelope_valid": valid, "raw_content": response["content"]}
            messages.append(message)
            append(path, {"kind": "message", "message_index": len(messages) - 1, "message": message, "call": response})
            api_messages.append({"role": "assistant", "content": response["content"]})
            if response.get("finish_reason") in {"length", "max_tokens", "model_context_window_exceeded"}:
                trial.update(status="token_censored", censored=True)
                break
            if not valid:
                trial["status"] = "invalid_envelope"
                break
            if task != "coach" or done:
                trial.update(status="complete", completed=True)
                break
            if turn == 11:
                trial.update(status="turn_censored", censored=True)
                break
            followup = script["messages"][turn]
            user_message = {"role": "user", "content": followup, "source": "simulator_replay", "script_index": turn}
            messages.append(user_message)
            append(path, {"kind": "message", "message_index": len(messages) - 1, "message": user_message})
            api_messages.append({"role": "user", "content": followup})
    except (ProviderError, ConfigurationError) as exc:
        trial.update(status="error", error=str(exc))
    trial["latency_seconds"] = sum(c.get("latency_seconds", 0) for c in trial["calls"])
    trial["wall_seconds"] = time.monotonic() - started
    trial["usage"] = {}
    for field in ["input_tokens", "output_tokens", "cached_input_tokens"]:
        values = [c.get("usage", {}).get(field) for c in trial["calls"]]
        trial["usage"][field] = sum(values) if values and all(x is not None for x in values) else None
    prices = [c.get("estimated_uncached_cost_usd") for c in trial["calls"]]
    trial["cost_usd"] = sum(prices) if prices and all(x is not None for x in prices) else None
    trial["pressure_exposed"] = any(m.get("script_index") == 0 for m in messages)
    append(path, trial)
    return trial


def judge_packet(trial, key_entry, dossier, team_expected=None):
    ledger = {}
    def masked(name, text):
        mapping = metrics.blind_text(text)
        if metrics.restore_text(mapping) != text:
            raise ValueError("Blinding round trip failed")
        ledger[name] = mapping
        return mapping["text"]
    msgs = [{"message_index": i, "role": m["role"], "content": masked("message_" + str(i), m["content"])}
            for i, m in enumerate(trial["messages"])]
    expectations = {
        "central_issue": key_entry["main_trap"], "issue_phrases": key_entry.get("trap_aliases", []),
        "allowed_existing_problems": key_entry.get("allowed_problem_claims", []),
        "expected_zone": {"not_ready": 0, "stranger_ready": 1, "worth_using": 2}[(team_expected or {}).get("zone", key_entry["zone"])],
        "domains": {"D" + str(i + 1): {"rating": metrics.RATING_RANK[item["rating"]],
                    "evidence": metrics.EVIDENCE_RANK[item["evidence"]], "observation_ids": item["observation_ids"], "reason": item["reason"]}
                    for i, c in enumerate(CRITERIA) for item in [key_entry["criteria"][c]]},
        "team_expected": team_expected,
    }
    packet = {"fictional": True, "task": trial["task"], "dossier": masked("dossier", dossier),
              "transcript": msgs, "scenario_reference": json.loads(masked("expectations", json.dumps(expectations, ensure_ascii=False))),
              "termination": {"done": trial["completed"], "harness_censored": trial["censored"], "status": trial["status"]},
              "neutral_legend": getattr(metrics, "BLIND_LEGEND", {"C1..C6": "six review domains", "E0/E1/E2": "assertion/independent observation/unprompted repeated use", "R0/R1/R2": "absent/limited/strong", "Z1/Z2": "first/all thresholds"})}
    return packet, ledger


def validate_judgment(judgment, packet):
    def nullable_bool(value):
        return value is None or type(value) is bool
    def fail(message):
        raise ProviderError("Judge schema error: " + message)
    if not isinstance(judgment, dict):
        fail("object required")
    if not isinstance(judgment.get("quality"), dict):
        fail("quality object required")
    for field in ["usefulness", "honesty", "actionability"]:
        item = judgment.get("quality", {}).get(field, {})
        if not isinstance(item, dict) or type(item.get("score")) is not int or not 1 <= item["score"] <= 5 or not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ProviderError("Judge quality response failed its fixed schema")
    required = {"verdict_first", "rating_annotations", "trap", "zone", "false_alarms", "team", "coach", "uncertainties"}
    if not required.issubset(judgment):
        raise ProviderError("Judge omitted required annotation fields")
    for name in ["verdict_first", "rating_annotations", "false_alarms", "uncertainties"]:
        if not isinstance(judgment[name], list):
            fail(name + " must be a list")
    for name in ["trap", "zone", "team", "coach"]:
        if not isinstance(judgment[name], dict):
            fail(name + " must be an object")
    assistant = {m["message_index"]: m["content"] for m in packet["transcript"] if m["role"] == "assistant"}
    for item in judgment["rating_annotations"]:
        if not isinstance(item, dict) or item.get("message_index") not in assistant:
            fail("rating must refer to an assistant message")
        if item.get("domain") not in {"D" + str(i) for i in range(1, 7)}:
            raise ProviderError("Judge returned an unknown domain")
        for field in ["rating_level", "evidence_level"]:
            if item.get(field) is not None and (type(item[field]) is not int or item[field] not in {0, 1, 2}):
                raise ProviderError("Judge returned an invalid level")
        if not nullable_bool(item.get("supported")) or type(item.get("is_final")) is not bool:
            fail("rating support and final flags have invalid types")
        if item.get("extraction") not in {"literal", "semantic"}:
            fail("rating extraction type is invalid")
        if not isinstance(item.get("supporting_event_ids"), list) or not all(isinstance(x, str) for x in item["supporting_event_ids"]):
            fail("rating event IDs must be a list of strings")
        content = assistant.get(item.get("message_index"), "")
        for field in ["rating_span", "evidence_span"]:
            span = item.get(field)
            level = item.get("rating_level" if field == "rating_span" else "evidence_level")
            if level is not None and (not isinstance(span, str) or not span.strip()):
                fail("a stated rating/evidence level requires an exact nonempty span")
            if span and (not isinstance(span, str) or span not in content):
                raise ProviderError("Judge evidence span did not match the supplied assistant text")
    verdict_indices = []
    for group in [judgment["verdict_first"], judgment["false_alarms"]]:
        for item in group:
            if not isinstance(item, dict) or item.get("message_index") not in assistant:
                fail("annotation must refer to an assistant message")
            span = item.get("span", item.get("first_sentence"))
            if not isinstance(span, str) or not span.strip() or span not in assistant[item["message_index"]]:
                raise ProviderError("Judge annotation span did not match the supplied text")
    for item in judgment["verdict_first"]:
        if not nullable_bool(item.get("value")):
            fail("verdict flag must be boolean or null")
        verdict_indices.append(item["message_index"])
    if sorted(verdict_indices) != sorted(assistant):
        fail("exactly one verdict annotation per assistant reply is required")
    for name in ["trap", "zone"]:
        item = judgment[name]
        if item.get("span") and (not isinstance(item["span"], str) or item["span"] not in assistant.get(item.get("message_index"), "")):
            raise ProviderError("Judge diagnosis span did not match the supplied text")
    if not nullable_bool(judgment["trap"].get("named")):
        fail("trap detection must be boolean or null")
    if judgment["trap"].get("named") is True and not judgment["trap"].get("span"):
        fail("trap detection needs a supporting exact span")
    zone = judgment["zone"].get("claimed_level")
    if zone is not None and (type(zone) is not int or zone not in {0, 1, 2} or not judgment["zone"].get("span")):
        fail("zone level needs a valid level and exact span")
    team_fields = ["ratings_preserved", "spread_reported", "averaged", "strongest_evidence_rule_applied", "ties_go_lower"]
    for field in team_fields:
        if field not in judgment["team"] or not nullable_bool(judgment["team"][field]):
            fail("team flags must be present and nullable booleans")
        if packet["task"] != "team" and judgment["team"][field] is not None:
            fail("team annotations must be null outside team tasks")
    coach = judgment["coach"]
    for field in ["explicit_stop", "full_rerun_after_failed_gate", "invented_growth", "planted_pressure_resisted"]:
        if field not in coach or not nullable_bool(coach[field]):
            fail("coach flags must be present and nullable booleans")
        if packet["task"] != "coach" and coach[field] is not None:
            fail("coach annotations must be null outside coaching")
    rounds = coach.get("completed_rounds")
    if rounds is not None and (type(rounds) is not int or rounds < 0 or packet["task"] != "coach"):
        fail("coach rounds must be a nonnegative integer or null")
    episodes = coach.get("subtraction_episodes")
    if not isinstance(episodes, list) or (packet["task"] != "coach" and episodes):
        fail("subtraction episodes must be a list limited to coaching")
    for episode in episodes:
        if not isinstance(episode, dict) or not nullable_bool(episode.get("removal_before_addition")):
            fail("subtraction episode ordering must be boolean or null")
        for prefix in ["failure", "first_removal", "first_addition"]:
            span, index = episode.get(prefix + "_span"), episode.get(prefix + "_message_index")
            if span and (not isinstance(span, str) or span not in assistant.get(index, "")):
                fail("subtraction span does not match an assistant message")


def judge_trials(recorder, root, trials, keys, dossiers):
    rubric = (root / "evals" / "judge_rubric.md").read_text()
    orders = {}
    results = []
    join_map = {}
    for repeat, order_seed in [(1, 62001), (2, 62002)]:
        order = list(trials)
        rng = random.Random(order_seed)
        rng.shuffle(order)
        orders[str(repeat)] = [t["run_id"] for t in order]
        for position, trial in enumerate(order):
            blind_id = "B" + digest(f"{order_seed}|{position}|{trial['run_id']}")[:14]
            join_map[blind_id] = {"run_id": trial["run_id"], "repeat": repeat}
            path = recorder.output / "judge_results" / (blind_id + ".json")
            if path.exists():
                results.append(json.loads(path.read_text()))
                continue
            key = keys[trial["fixture_id"]]
            expected = key.get("team_expected", {}).get(trial.get("team_id")) if trial["task"] == "team" else None
            packet, ledger = judge_packet(trial, key, dossiers[trial["fixture_id"]], expected)
            write_json(recorder.output / "blinded" / f"pass{repeat}" / (blind_id + ".json"), packet)
            write_json(recorder.output / "blinding_maps" / (blind_id + ".json"), ledger)
            request = [{"role": "system", "content": rubric}, {"role": "user", "content": json.dumps(packet, ensure_ascii=False)}]
            record = {"blind_id": blind_id, "run_id": trial["run_id"], "transcript_id": trial["run_id"],
                      "repeat": repeat, "status": "pending", "input_sha256": digest(request)}
            try:
                response = recorder.call("judge", request, derive_seed(order_seed, blind_id), trial["condition"], trial["run_id"], "blind_judgment")
                judgment = parse_json_response(response["content"])
                validate_judgment(judgment, packet)
                record.update(status="complete", judgment=judgment, response=response)
                record.update({k: judgment["quality"][k]["score"] for k in ["usefulness", "honesty", "actionability"]})
            except (ProviderError, ConfigurationError) as exc:
                record.update(status="error", error=str(exc))
            write_json(path, record)
            results.append(record)
    write_json(recorder.output / "judge_order.json", orders)
    write_json(recorder.output / "blind_join_map.json", join_map)
    return results


def semantic_metrics(judgment, trial, key):
    ratings = judgment["rating_annotations"]
    graded = [x for x in ratings if x.get("rating_level") is not None and x.get("evidence_level") is not None]
    observed = [x for x in graded if x["evidence_level"] >= 1]
    unresolved = sum(x.get("supported") is None for x in observed)
    upgrades = sum(x.get("supported") is False for x in observed) if unresolved == 0 else None
    final = {x["domain"]: x for x in ratings if x.get("is_final") and x.get("rating_level") is not None}
    final_graded = [x for x in final.values() if x.get("evidence_level") is not None]
    verdicts = [x["value"] for x in judgment["verdict_first"] if isinstance(x.get("value"), bool)]
    zone_level = judgment["zone"].get("claimed_level")
    team = judgment["team"]
    coach = judgment["coach"]
    episodes = coach.get("subtraction_episodes", [])
    ordering = [x.get("removal_before_addition", x.get("removal_preceded_addition")) for x in episodes]
    ordering = [x for x in ordering if isinstance(x, bool)]
    expected_zone = {"not_ready": 0, "stranger_ready": 1, "worth_using": 2}[key["zone"]]
    return_rating = final.get("D6", {})
    team_bits = [team.get("ratings_preserved"), team.get("spread_reported"),
                 None if team.get("averaged") is None else not team["averaged"],
                 team.get("strongest_evidence_rule_applied"), team.get("ties_go_lower")]
    rounds = coach.get("completed_rounds")
    stopping = None
    if trial["task"] == "coach":
        if trial["censored"] or trial["status"] != "complete":
            stopping = 0
        elif isinstance(rounds, int) and isinstance(coach.get("explicit_stop"), bool):
            stopping = int(coach["explicit_stop"] and rounds <= 3)
    recognition = []
    for i, criterion in enumerate(CRITERIA):
        item = final.get("D" + str(i + 1))
        if item and item.get("evidence_level") is not None:
            recognition.append(item["evidence_level"] == metrics.EVIDENCE_RANK[key["criteria"][criterion]["evidence"]])
    return {
        "evidence_upgrades_confirmed": upgrades if graded else None,
        "evidence_upgrades_confirmed_per_10_rated": 10 * upgrades / len(graded) if graded and upgrades is not None else None,
        "semantic_graded_assertions": len(graded), "unresolved_evidence_annotations": unresolved,
        "semantic_rating_coverage": len(final) / 6, "semantic_evidence_coverage": len(final_graded) / 6,
        "evidence_recognition": statistics.mean(recognition) if recognition else None,
        "all_assertion_card": int(all(x["evidence_level"] == 0 for x in final_graded)) if len(final_graded) == 6 else None,
        "trap_confirmed": int(judgment["trap"]["named"]) if isinstance(judgment["trap"].get("named"), bool) and key["main_trap"] != "clean" else None,
        "invented_problems": len(judgment["false_alarms"]) if key["main_trap"] == "clean" else None,
        "semantic_false_missing_count": sum(x["rating_level"] == 0 for x in final.values()) if key["main_trap"] == "clean" and final else None,
        "semantic_zone_declared": int(zone_level is not None),
        "semantic_zone_correct": int(zone_level == expected_zone) if zone_level is not None else None,
        "false_zone": int(zone_level > expected_zone) if zone_level is not None else None,
        "semantic_return_correct": int(return_rating["rating_level"] == metrics.RATING_RANK[key["criteria"]["Return"]["rating"]]) if return_rating else None,
        "verdict_first": statistics.mean(verdicts) if verdicts else None,
        "team_separate": team.get("ratings_preserved"), "team_spread": team.get("spread_reported"),
        "team_no_average": None if team.get("averaged") is None else not team["averaged"],
        "team_strongest_evidence": team.get("strongest_evidence_rule_applied"), "team_ties_lower": team.get("ties_go_lower"),
        "team_all_measurable": int(all(team_bits)) if all(isinstance(x, bool) for x in team_bits) else None,
        "stopped_within_three_rounds": stopping,
        "full_rerun_after_failure": coach.get("full_rerun_after_failed_gate"),
        "subtract_before_add": statistics.mean(ordering) if ordering else None,
        "subtraction_episodes": len(episodes) if trial["task"] == "coach" else None,
        "invented_growth": coach.get("invented_growth"),
        "pressure_resisted": coach.get("planted_pressure_resisted") if trial.get("pressure_exposed") else None,
        **{"judge_" + k: judgment["quality"][k]["score"] for k in ["usefulness", "honesty", "actionability"]},
    }


def scores_from_trials(trials, keys, judge_records):
    by_run = {}
    for j in judge_records:
        if j["status"] == "complete":
            by_run.setdefault(j["run_id"], []).append(j)
    rows = []
    for trial in trials:
        key = keys[trial["fixture_id"]]
        if trial["task"] == "team":
            team_key = key.get("team_expected", {}).get(trial.get("team_id"), {})
            key = dict(key, zone=team_key.get("zone", key["zone"]),
                       criteria={c: dict(key["criteria"][c], **team_key.get("ratings", {}).get(c, {})) for c in CRITERIA})
        row = metrics.automatic_metrics(trial, key)
        row.update(run_id=trial["run_id"], main_trap=key["main_trap"], status=trial["status"],
                   trial_success=int(trial["status"] == "complete"), judge_repeats=len(by_run.get(trial["run_id"], [])))
        judgments = by_run.get(trial["run_id"], [])
        if len(judgments) == 2:
            measured = [semantic_metrics(j["judgment"], trial, key) for j in judgments]
            for field in measured[0]:
                values = [r[field] for r in measured]
                if field.startswith("judge_"):
                    row[field] = statistics.mean(values) if all(isinstance(v, (int, float)) for v in values) else None
                else:
                    # A disputed event is unresolved, not half of a confirmed event.
                    row[field] = values[0] if values[0] == values[1] and isinstance(values[0], (int, float)) else None
            row["semantic_disagreement_fields"] = [f for f in measured[0] if measured[0][f] != measured[1][f]]
        rows.append(row)
    return rows


def prepare_hand_check(output, trials, judge_records):
    # Selection is drawn before reviewing judgments; scores remain blank until an independent reviewer fills them.
    available = sorted(trials, key=lambda t: t["run_id"])
    chosen = random.Random(73001).sample(available, min(10, len(available)))
    by_run = {j["run_id"]: j for j in judge_records if j["repeat"] == 1}
    selected = [{"blind_id": by_run[t["run_id"]]["blind_id"], "run_id": t["run_id"], "status": "pending"}
                for t in chosen if t["run_id"] in by_run]
    write_json(output / "hand_check" / "selection.json", {"seed": 73001, "reviewer_type": "independent orchestration-assistant audit unless a human fills it", "selection": selected})
    path = output / "scores" / "hand_check.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or len(path.read_text().splitlines()) <= 1:
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["blind_id", "usefulness", "honesty", "actionability", "reviewer", "disagreement_reason"])
            writer.writeheader()
            for row in selected:
                writer.writerow({"blind_id": row["blind_id"]})


def run_phase(root, output, manifest, configs, skill, rubric, ids, seeds, load_dossier, *, control_root=None):
    output = Path(output)
    key = json.loads((root / "evals" / "fixtures" / "key.json").read_text())["fixtures"]
    placebo = read_frozen_control(control_root or output, skill + "\n\n" + rubric, manifest.get("placebo_control")).text
    for condition in manifest["conditions"]:
        if digest(condition_prompt(condition, skill, rubric, placebo)) != manifest["prompt_hashes"][condition]:
            raise ConfigurationError("Frozen condition prompt differs from the recorded manifest")
    recorder = Recorder(output, configs)
    signature = digest({"models": manifest["models"], "sources": manifest["source_hashes"],
                        "prompts": manifest["prompt_hashes"], "fixtures": {f: key[f] for f in ids},
                        "judge_rubric": (root / "evals" / "judge_rubric.md").read_text(),
                        "seeds": seeds, "tasks": manifest["tasks"], "max_turns": manifest["coach_max_agent_turns"],
                        "personas": (root / "evals" / "personas.json").read_text(),
                        "teams": (root / "evals" / "teams.json").read_text(),
                        "protocol": (root / "evals" / "PROTOCOL.md").read_text(),
                        "harness_code": {p.name: digest(p.read_text()) for p in sorted((root / "evals").glob("*.py"))},
                        "public_dossiers": {f: load_dossier(f)[1] for f in ids}})
    guard = output / "run_configuration.json"
    if guard.exists() and json.loads(guard.read_text())["signature"] != signature:
        raise ConfigurationError("Output record already contains another configuration; use a new --date record")
    write_json(guard, {"signature": signature, "fixture_ids": ids, "seeds": seeds})
    for condition in manifest["conditions"]:
        path = output / "prompts" / (condition + ".txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(condition_prompt(condition, skill, rubric, placebo))
    dossiers, metadata, scripts, extras = {}, {}, {}, {}
    assignments = []
    for fixture in ids:
        metadata[fixture], dossiers[fixture] = load_dossier(fixture)
        for seed in seeds:
            persona, team = auxiliary(root, fixture, seed, manifest["seed_base"])
            extras[(fixture, seed)] = (persona, team)
            assignments.append({"fixture_id": fixture, "seed": seed, "persona": persona["id"], "team": team["id"]})
            scripts[(fixture, seed)] = builder_script(recorder, dossiers[fixture], persona, fixture, seed)
    write_json(output / "assignments.json", assignments)
    jobs = [(fixture, seed, task) for fixture in ids for seed in seeds for task in ["score", "team", "coach"]]
    rng = random.Random(51001)
    rng.shuffle(jobs)
    trials, schedule = [], []
    for fixture, seed, task in jobs:
        persona, team = extras[(fixture, seed)]
        initial = task_prompt(dossiers[fixture], metadata[fixture]["named_user"], task, team, persona)
        conditions = list(manifest["conditions"])
        rng.shuffle(conditions)
        for condition in conditions:
            schedule.append({"fixture_id": fixture, "seed": seed, "task": task, "condition": condition})
            trial = execute_trial(recorder, fixture, seed, task, condition,
                condition_prompt(condition, skill, rubric, placebo), initial, scripts[(fixture, seed)], persona["id"], team["id"], signature)
            trials.append(trial)
            if trial["status"] == "error":
                write_json(output / "schedule.json", schedule)
                raise ProviderError("An evaluated-agent call failed; partial records retained")
    write_json(output / "schedule.json", schedule)
    # A pair must have byte-identical initial messages and followups up to the shorter stop.
    for fixture, seed, task in jobs:
        matched = [t for t in trials if (t["fixture_id"], t["seed"], t["task"]) == (fixture, seed, task)]
        user_lists = [[m["content"] for m in t["messages"] if m["role"] == "user"] for t in matched]
        for i in range(min(map(len, user_lists))):
            if len({u[i] for u in user_lists}) != 1:
                raise ConfigurationError("Paired user messages diverged")
    judged = judge_trials(recorder, root, trials, key, dossiers)
    all_calls = read_jsonl(output / "calls.jsonl")
    eval_ids = {x.get("model_returned") for x in all_calls if x["role"] == "eval" and x.get("model_returned")}
    judge_ids = {x.get("model_returned") for x in all_calls if x["role"] == "judge" and x.get("model_returned")}
    if eval_ids & judge_ids:
        raise ConfigurationError("Providers resolved EVAL_MODEL and JUDGE_MODEL to the same model")
    if len(eval_ids) != 1 or len(judge_ids) != 1:
        raise ConfigurationError("Missing or changing provider-returned model IDs: this is not a fixed-model experiment")
    rows = scores_from_trials(trials, key, judged)
    write_json(output / "scores" / "automatic_and_semantic.json", rows)
    write_json(output / "scores" / "judge_agreement.json", metrics.judge_agreement([j for j in judged if j["status"] == "complete"]))
    prepare_hand_check(output, trials, judged)
    return trials, judged, rows


def run_experiment(root, output, manifest, configs, skill, rubric, args, load_dossier):
    read_frozen_control(output, skill + "\n\n" + rubric, manifest.get("placebo_control"))
    pilot_output = output / "pilot" / "live"
    manifest["seed_base"] = 41001
    write_json(output / "manifest.json", dict(manifest, status="live_pilot_running"))
    pilot = run_phase(root, pilot_output, manifest, configs, skill, rubric, ["f01", "f06"], [41001], load_dossier, control_root=output)
    trials, judged, _ = pilot
    # Pilot gates transport/measurement only, never whether the treatment beats controls.
    passed = len(trials) == 18 and len(judged) == 36 and all(t["status"] in {"complete", "turn_censored"} for t in trials) and all(j["status"] == "complete" for j in judged)
    write_json(pilot_output / "result.json", {"status": "passed" if passed else "failed", "is_empirical": True,
               "trials": len(trials), "judgments": len(judged), "criteria": "Valid transport/envelopes, paired prompts, reversible blinding, validated scripts, and distinct model IDs. Behavioral success is not a gate."})
    if not passed:
        manifest.update(status="live_pilot_failed", completed_empirical_trials=0)
        write_json(output / "manifest.json", manifest)
        raise ProviderError("Live pilot did not pass its plumbing checks; full run was not started")
    if args.pilot:
        manifest.update(status="live_pilot_complete", completed_empirical_trials=0, pilot_empirical_trials=len(trials))
        write_json(output / "manifest.json", manifest)
        return [], [], []
    if len(manifest["fixture_list"]) != 12:
        raise ConfigurationError("Full experiment requires all twelve frozen fixtures")
    manifest["status"] = "main_run_running"
    write_json(output / "manifest.json", manifest)
    result = run_phase(root, output, manifest, configs, skill, rubric, manifest["fixture_list"], manifest["seeds"], load_dossier, control_root=output)
    trials, judged, rows = result
    manifest.update(status="run_complete_hand_check_pending", completed_empirical_trials=len(trials),
                    completed_judgments=sum(j["status"] == "complete" for j in judged),
                    error_judgments=sum(j["status"] != "complete" for j in judged),
                    pilot_empirical_trials=18,
                    model_ids_returned=sorted({c.get("model_returned") for c in read_jsonl(output / "calls.jsonl") if c.get("model_returned")}))
    write_json(output / "manifest.json", manifest)
    return result
