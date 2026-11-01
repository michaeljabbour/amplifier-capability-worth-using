"""New delegated-v1 boundaries; no provider, private cohort or historical writes."""
from __future__ import annotations

import copy
import io
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import card_contract
import delegated
import prompts
from providers import ConfigurationError, Settings, ProviderError
from source_selection import SOURCE_FILES

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


def card():
    return {"schema_version": "usefulness-card/v1", "card_id": "fictional-score-1",
            "tool": "Fictional agenda helper", "date": "2026-11-01",
            "round": {"mode": "score", "index": 1, "budget": None},
            "user": {"id": "coordinator", "who": "Volunteer coordinator in a repair club",
                     "job": "Plan a weekly meeting", "cost": "unknown", "status": "assumed"},
            "criteria": {name: {"rating": "Solid", "evidence": "Claimed", "claimed_basis": "walkthrough",
                                 "evidence_refs": ["fictional-first-run.log"], "line": "Fictional builder-run walkthrough"}
                         for name in card_contract.CRITERIA},
            "zone": {"stranger_ready": "not-met", "worth_using": "not-met", "holding_back": list(card_contract.CRITERIA[:5])},
            "return_check": {"who": "outside user not yet recruited", "when": "not scheduled", "counts_as": "unprompted return"},
            "cut": [], "assumptions": ["User and cost await the builder"], "questions": ["Who outside the team can try it?"]}


def observed_card(grade="Seen"):
    result = card()
    for item in result["criteria"].values():
        item.update(evidence=grade, evidence_refs=["O1"])
        item.pop("claimed_basis")
    result["zone"] = {"stranger_ready": "met", "worth_using": "met" if grade == "Repeated" else "not-met",
                      "holding_back": [] if grade == "Repeated" else ["Return"]}
    record = {"actor": "outside", "observed_use": True, "user_id": "coordinator", "date": "2026-10-27",
              "criteria": list(card_contract.CRITERIA), "detail": "Fictional record of specific use without builder help",
              "unprompted_return": grade == "Repeated"}
    return result, {"O1": record}


class SemanticTests(unittest.TestCase):
    def test_walkthrough_remains_claimed_and_does_not_reach_zone(self):
        value = card()
        before = copy.deepcopy(value)
        self.assertEqual(card_contract.semantic_errors(value), [])
        self.assertEqual(value, before)
        value["zone"]["stranger_ready"] = "met"
        self.assertTrue(any("stranger_ready" in x for x in card_contract.semantic_errors(value)))

    def test_score_has_null_budget_but_can_identify_repeated_scores(self):
        value = card()
        value["round"]["budget"] = 3
        self.assertTrue(any("null" in x for x in card_contract.semantic_errors(value)))
        value["round"] = {"mode": "score", "index": 2, "budget": None}
        self.assertEqual(card_contract.semantic_errors(value), [])

    def test_coach_needs_positive_explicit_budget_and_index_within_it(self):
        for index, budget in [(1, None), (1, 0), (4, 3), (True, 3), (1, True), (1.5, 3)]:
            with self.subTest(index=index, budget=budget):
                value = card(); value["round"] = {"mode": "coach", "index": index, "budget": budget}
                self.assertTrue(card_contract.semantic_errors(value))
        value = card(); value["round"] = {"mode": "coach", "index": 3, "budget": 3}
        self.assertEqual(card_contract.semantic_errors(value), [])

    def test_unknown_mode_and_impossible_date_fail(self):
        value = card(); value["round"]["mode"] = "autonomous"
        self.assertTrue(any("mode" in x for x in card_contract.semantic_errors(value)))
        value = card(); value["date"] = "2026-02-30"
        self.assertTrue(any("date" in x for x in card_contract.semantic_errors(value)))

    def test_builder_or_agent_use_never_satisfies_seen(self):
        value, records = observed_card()
        for actor in ["builder", "agent", "unknown"]:
            with self.subTest(actor=actor):
                records["O1"]["actor"] = actor
                self.assertEqual(len(card_contract.semantic_errors(value, records)), 6)

    def test_supplied_outside_record_is_specific_dated_and_user_matched(self):
        value, records = observed_card()
        self.assertEqual(card_contract.semantic_errors(value, records), [])
        for field, invalid in [("date", "last week"), ("detail", ""), ("user_id", "different-user"), ("observed_use", False), ("criteria", None)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(records); changed["O1"][field] = invalid
                self.assertTrue(card_contract.semantic_errors(value, changed))

    def test_outside_record_covers_only_its_named_criteria(self):
        value, records = observed_card(); records["O1"]["criteria"] = ["Fit"]
        errors = card_contract.semantic_errors(value, records)
        self.assertEqual(len(errors), 5)
        self.assertFalse(any(x.startswith("Fit:") for x in errors))

    def test_repeated_requires_unprompted_return(self):
        value, records = observed_card("Repeated")
        self.assertEqual(card_contract.semantic_errors(value, records), [])
        records["O1"]["unprompted_return"] = False
        self.assertEqual(len(card_contract.semantic_errors(value, records)), 6)

    def test_met_zones_cannot_still_list_a_blocker(self):
        value, records = observed_card("Repeated")
        value["zone"]["holding_back"] = ["Return"]
        self.assertTrue(any("holding_back" in e for e in card_contract.semantic_errors(value, records)))

    def test_previous_card_identity_and_index_are_not_silently_rewritten(self):
        previous = card(); value = card(); value.update(card_id="fictional-score-2", previous_card_id=previous["card_id"])
        value["round"]["index"] = 2
        before = copy.deepcopy(previous)
        self.assertEqual(card_contract.semantic_errors(value, previous=previous), [])
        self.assertEqual(previous, before)
        value["user"]["id"] = "other"
        self.assertTrue(any("same tool and user" in x for x in card_contract.semantic_errors(value, previous=previous)))

    def test_malformed_previous_context_returns_errors_instead_of_crashing(self):
        for previous in [[], {"user": [], "round": {}}, {"user": {}, "round": {"index": "one"}}, {"user": {}, "round": None}]:
            with self.subTest(previous=previous):
                self.assertTrue(card_contract.semantic_errors(card(), previous=previous))


@unittest.skipUnless(Draft202012Validator, "Existing jsonschema tool unavailable; no dependency is installed")
class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((HERE.parent / "skills/worth-using/references/usefulness-card.schema.json").read_text())
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def test_valid_claimed_and_recorded_cards(self):
        self.assertEqual(list(self.validator.iter_errors(card())), [])
        self.assertEqual(list(self.validator.iter_errors(observed_card("Repeated")[0])), [])

    def test_negative_modes_budgets_and_indices(self):
        for mode, index, budget in [("score", 1, 2), ("coach", 1, None), ("coach", 1, 0), ("score", 0, None), ("score", True, None), ("coach", 1, True), ("wrong", 1, None)]:
            with self.subTest(mode=mode, index=index, budget=budget):
                value = card(); value["round"] = {"mode": mode, "index": index, "budget": budget}
                self.assertTrue(list(self.validator.iter_errors(value)))

    def test_no_aggregate_or_unauthorized_growth_fields(self):
        for key in ["overall_score", "growth_card", "authorized"]:
            value = card(); value[key] = 1
            self.assertTrue(list(self.validator.iter_errors(value)))
        value = card(); value["criteria"].pop("Trust")
        self.assertTrue(list(self.validator.iter_errors(value)))

    def test_walkthrough_refs_and_evidence_basis_constraints(self):
        value = card(); value["criteria"]["Fit"]["evidence_refs"] = []
        self.assertTrue(list(self.validator.iter_errors(value)))
        value = card(); value["criteria"]["Fit"]["evidence"] = "Seen"
        self.assertTrue(list(self.validator.iter_errors(value)))

    def test_complete_zone_has_no_remaining_blockers(self):
        value, _ = observed_card("Repeated")
        value["zone"]["holding_back"] = ["Return"]
        self.assertTrue(list(self.validator.iter_errors(value)))


class TreatmentFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="worth-delegated-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for source in dict(SOURCE_FILES + delegated.TREATMENT):
            path = self.root / source; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((HERE.parent / source).read_bytes())
        (self.root / "evals").mkdir()
        for name in ["delegated-fixtures.json"]:
            shutil.copyfile(HERE / name, self.root / "evals" / name)
        shutil.copyfile(HERE.parent / "docs/DELEGATED-EVALUATION.md", self.root / "docs/DELEGATED-EVALUATION.md")
        self.git("init", "-q")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(self.root), *args], stderr=subprocess.PIPE)

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Fictional Contract Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--no-gpg-sign", "-qm", "fixture")


class TreatmentTests(TreatmentFixture, unittest.TestCase):
    def test_complete_new_prompt_and_all_four_materials_are_frozen(self):
        result = delegated.prepare(self.root, "2026-11-01/new")
        folder = self.root / "docs/evaluations/2026-11-01/new"
        self.assertEqual(result["schema_version"], delegated.PROFILE)
        self.assertEqual(result["conditions"], ["delegated-v1", "baseline"])
        self.assertEqual(result["api_calls"], 0)
        self.assertFalse(result["is_empirical"])
        text = (folder / "prompts/delegated-v1.txt").read_text()
        for _, snapshot in delegated.TREATMENT:
            self.assertIn((folder / snapshot).read_text(), text)
        self.assertEqual((folder / "prompts/baseline.txt").read_text(), prompts.PREAMBLE)
        for task in (folder / "tasks").glob("*.txt"):
            self.assertNotIn("expected_checks", task.read_text())
        for name, digest in result["file_hashes"].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)

    def test_historical_condition_bytes_and_names_are_unchanged(self):
        self.assertEqual(prompts.condition_prompt("skill", "S", "R", "P"), prompts.PREAMBLE + "\n\nS\n\nR")
        self.assertEqual(prompts.condition_prompt("baseline", "S", "R", "P"), prompts.PREAMBLE)
        self.assertEqual(prompts.condition_prompt("placebo", "S", "R", "P"), prompts.PREAMBLE + "\n\nP")
        with self.assertRaises(ValueError):
            prompts.condition_prompt("delegated-v1", "S", "R", "P")

    def test_changed_reference_or_schema_gets_a_distinct_condition_version(self):
        first = delegated.prepare(self.root, "2026-11-01/first")
        folder = self.root / "docs/evaluations/2026-11-01/first"
        before = {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
        path = self.root / delegated.TREATMENT[2][0]; path.write_text(path.read_text() + "\nSynthetic changed reference.\n")
        self.commit(); second = delegated.prepare(self.root, "2026-11-01/second")
        self.assertNotEqual(first["condition_version"], second["condition_version"])
        path = self.root / delegated.TREATMENT[3][0]; value = json.loads(path.read_text()); value["$comment"] = "Synthetic changed schema"; path.write_text(json.dumps(value))
        self.commit(); third = delegated.prepare(self.root, "2026-11-01/third")
        self.assertNotEqual(second["condition_version"], third["condition_version"])
        self.assertEqual(before, {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()})

    def test_dirty_or_missing_extra_cannot_silently_use_legacy(self):
        path = self.root / delegated.TREATMENT[2][0]
        path.write_text(path.read_text() + "\nUncommitted change.\n")
        with self.assertRaisesRegex(ConfigurationError, "differs"):
            delegated.prepare(self.root, "2026-11-01/dirty")
        self.assertFalse((self.root / "docs/evaluations/2026-11-01/dirty").exists())
        path.unlink()
        with self.assertRaisesRegex(ConfigurationError, "requires"):
            delegated.prepare(self.root, "2026-11-01/missing")

    def test_existing_or_unsafe_record_never_overwritten(self):
        delegated.prepare(self.root, "2026-11-01/one")
        folder = self.root / "docs/evaluations/2026-11-01/one"
        manifest = (folder / "manifest.json").read_bytes()
        with self.assertRaises(ConfigurationError):
            delegated.prepare(self.root, "2026-11-01/one")
        self.assertEqual((folder / "manifest.json").read_bytes(), manifest)
        with self.assertRaises(ConfigurationError):
            delegated.prepare(self.root, "../escape")

    def test_offline_condition_uses_frozen_pair_and_never_reports_empirical_trials(self):
        delegated.prepare(self.root, "2026-11-01/smoke")
        folder = self.root / "docs/evaluations/2026-11-01/smoke"
        original_manifest = (folder / "manifest.json").read_bytes()
        result = delegated.offline_smoke(self.root, "2026-11-01/smoke")
        self.assertEqual(result["completed_transport_probes"], 6)
        self.assertEqual(result["completed_empirical_trials"], 0)
        self.assertEqual(result["provider_api_calls"], 0)
        self.assertFalse(result["is_empirical"])
        self.assertTrue(all(c["envelope_valid"] for c in result["calls"]))
        self.assertEqual(len({c["response"]["content"] for c in result["calls"]}), 1)
        for task in {c["task"] for c in result["calls"]}:
            self.assertEqual(len({c["user_prompt_sha256"] for c in result["calls"] if c["task"] == task}), 1)
        self.assertEqual((folder / "manifest.json").read_bytes(), original_manifest)
        with self.assertRaises(ConfigurationError):
            delegated.offline_smoke(self.root, "2026-11-01/smoke")

    def test_tampered_frozen_extra_fails_before_offline_probe(self):
        delegated.prepare(self.root, "2026-11-01/tampered")
        folder = self.root / "docs/evaluations/2026-11-01/tampered"
        (folder / "delegated-runs.snapshot.md").write_text("Changed frozen material")
        with self.assertRaisesRegex(ConfigurationError, "changed"):
            delegated.offline_smoke(self.root, "2026-11-01/tampered")
        self.assertFalse((folder / "offline-smoke").exists())

    def test_unregistered_task_cannot_expand_the_frozen_probe_set(self):
        delegated.prepare(self.root, "2026-11-01/extra")
        folder = self.root / "docs/evaluations/2026-11-01/extra"
        (folder / "tasks/extra.txt").write_text("Unregistered task")
        with self.assertRaisesRegex(ConfigurationError, "membership"):
            delegated.offline_smoke(self.root, "2026-11-01/extra")
        self.assertFalse((folder / "offline-smoke").exists())

    def test_manifest_cannot_omit_a_changed_prompt_under_the_old_version(self):
        delegated.prepare(self.root, "2026-11-01/omitted")
        folder = self.root / "docs/evaluations/2026-11-01/omitted"
        manifest = json.loads((folder / "manifest.json").read_text())
        del manifest["file_hashes"]["prompts/delegated-v1.txt"]
        (folder / "manifest.json").write_text(json.dumps(manifest))
        (folder / "prompts/delegated-v1.txt").write_text("Changed prompt")
        with self.assertRaisesRegex(ConfigurationError, "membership"):
            delegated.offline_smoke(self.root, "2026-11-01/omitted")
        self.assertFalse((folder / "offline-smoke").exists())

    def test_changed_prompt_hash_cannot_keep_old_condition_version(self):
        delegated.prepare(self.root, "2026-11-01/version")
        folder = self.root / "docs/evaluations/2026-11-01/version"
        prompt = folder / "prompts/delegated-v1.txt"; prompt.write_text("Changed prompt")
        manifest = json.loads((folder / "manifest.json").read_text())
        manifest["file_hashes"]["prompts/delegated-v1.txt"] = delegated.digest(prompt.read_bytes())
        (folder / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ConfigurationError, "version"):
            delegated.offline_smoke(self.root, "2026-11-01/version")
        self.assertFalse((folder / "offline-smoke").exists())


class FakeTransport:
    """Injected only: never constructs an HTTP request or reads credentials."""
    def __init__(self, *, fail_at=None, content=None, callback=None):
        self.calls = []
        self.fail_at = fail_at
        self.content = content
        self.callback = callback

    def complete(self, messages, seed):
        self.calls.append(copy.deepcopy(messages))
        if self.callback:
            self.callback(len(self.calls))
        if len(self.calls) == self.fail_at:
            raise ProviderError("Synthetic transport rejection")
        return {"content": self.content or json.dumps({"reply": "Synthetic collected response, not a model result", "done": True}),
                "model_requested": "fixture-model", "model_returned": "fixture-model-returned", "provider": "synthetic-test",
                "usage": {"input_tokens": 3, "output_tokens": 2}, "is_empirical": False}


class CollectorTests(TreatmentFixture, unittest.TestCase):
    """Exercise the same collector used by the CLI, with no provider requests."""
    def prepared(self):
        delegated.prepare(self.root, "2026-11-01/collect")
        return self.root / "docs/evaluations/2026-11-01/collect"

    def test_collector_executes_both_actual_frozen_conditions_with_paired_tasks(self):
        folder = self.prepared(); before = (folder / "manifest.json").read_bytes(); client = FakeTransport()
        result = delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        self.assertEqual(result["status"], "collection-complete")
        self.assertEqual(result["collector_version"], delegated.COLLECTOR_VERSION)
        self.assertEqual(result["attempted_calls"], 6)
        self.assertEqual(result["completed_trials"], 6)
        self.assertEqual(result["completed_empirical_trials"], 0)
        self.assertFalse(result["is_empirical"])
        for index in range(0, 6, 2):
            self.assertEqual(client.calls[index][1], client.calls[index + 1][1])
            for _, snapshot in delegated.TREATMENT:
                self.assertIn((folder / snapshot).read_text(), client.calls[index][0]["content"])
            self.assertEqual(client.calls[index + 1][0]["content"], prompts.PREAMBLE)
        self.assertTrue(all(c["response"]["model_returned"] == "fixture-model-returned" for c in result["calls"]))
        self.assertEqual((folder / "manifest.json").read_bytes(), before)

    def test_call_budget_and_existing_collection_fail_before_any_transport(self):
        folder = self.prepared(); client = FakeTransport()
        for budget in [None, True, 0, 5]:
            with self.subTest(budget=budget), self.assertRaises(ConfigurationError):
                delegated.collect(self.root, "2026-11-01/collect", client, max_calls=budget)
        self.assertEqual(client.calls, [])
        self.assertFalse((folder / "collections").exists())
        delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        fresh = FakeTransport()
        with self.assertRaises(ConfigurationError):
            delegated.collect(self.root, "2026-11-01/collect", fresh, max_calls=6)
        self.assertEqual(fresh.calls, [])

    def test_corrupted_freeze_fails_before_any_transport(self):
        folder = self.prepared(); client = FakeTransport()
        (folder / "prompts/delegated-v1.txt").write_text("Changed frozen treatment")
        with self.assertRaises(ConfigurationError):
            delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        self.assertEqual(client.calls, [])

    def test_moving_or_unavailable_source_ref_never_reaches_transport(self):
        folder = self.prepared(); original = json.loads((folder / "manifest.json").read_text())
        for value in ["HEAD", "main", "a" * 40, None]:
            with self.subTest(source_commit=value):
                manifest = copy.deepcopy(original); manifest["source_commit"] = value
                (folder / "manifest.json").write_text(json.dumps(manifest))
                client = FakeTransport()
                with self.assertRaises(ConfigurationError):
                    delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
                self.assertEqual(client.calls, [])

    def test_provider_error_is_retained_without_retry_or_automatic_resume(self):
        folder = self.prepared(); client = FakeTransport(fail_at=2)
        result = delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        self.assertEqual(result["status"], "collection-stopped-on-error")
        self.assertEqual(result["attempted_calls"], 2)
        self.assertEqual(result["completed_trials"], 1)
        self.assertEqual(result["calls"][1]["status"], "transport-error")
        self.assertTrue((folder / "collections/trial-1/RESULT.json").exists())

    def test_invalid_envelope_does_not_become_a_completed_trial(self):
        self.prepared(); client = FakeTransport(content="not an envelope")
        result = delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        self.assertEqual(result["status"], "collection-has-incomplete-responses")
        self.assertEqual(result["completed_trials"], 0)
        self.assertEqual(result["completed_empirical_trials"], 0)
        self.assertEqual(result["attempted_calls"], 6)

    def test_inputs_are_captured_before_transport_and_not_reread_between_trials(self):
        folder = self.prepared(); original = (folder / "prompts/delegated-v1.txt").read_text()
        def change_parent(index):
            if index == 1:
                (folder / "prompts/delegated-v1.txt").write_text("Concurrent change after capture")
        client = FakeTransport(callback=change_parent)
        result = delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        self.assertEqual(result["completed_trials"], 6)
        self.assertTrue(all(client.calls[i][0]["content"] == original for i in [0, 2, 4]))
        captured = folder / "collections/trial-1/captured-inputs/prompts/delegated-v1.txt"
        self.assertEqual(captured.read_text(), original)

    def test_collection_path_cannot_follow_an_external_symlink(self):
        folder = self.prepared(); elsewhere = self.root / "elsewhere"; elsewhere.mkdir()
        (folder / "collections").symlink_to(elsewhere, target_is_directory=True)
        client = FakeTransport()
        with self.assertRaises(ConfigurationError):
            delegated.collect(self.root, "2026-11-01/collect", client, max_calls=6)
        self.assertEqual(client.calls, [])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_cli_collect_uses_normal_transport_interface_without_test_network(self):
        folder = self.prepared(); client = FakeTransport(); cfg = Settings("eval", "fixture-model", "openai", 0, 100, False)
        with patch.object(delegated, "ROOT", self.root), patch.object(delegated, "settings_for", return_value=cfg), \
             patch.object(delegated, "APIClient", return_value=client) as factory, \
             patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-not-a-real-key"}, clear=True), \
             patch("sys.stdout", new_callable=io.StringIO):
            code = delegated.main(["--collect", "--record", "2026-11-01/collect", "--max-calls", "6"])
        self.assertEqual(code, 0)
        factory.assert_called_once_with(cfg)
        self.assertEqual(len(client.calls), 6)
        result = json.loads((folder / "collections/trial-1/RESULT.json").read_text())
        self.assertEqual(result["completed_empirical_trials"], 0)
        self.assertEqual(result["configuration"]["model"], "fixture-model")

    def test_cli_missing_budget_or_credentials_never_constructs_transport(self):
        self.prepared(); cfg = Settings("eval", "fixture-model", "openai", 0, 100, False)
        with patch.object(delegated, "ROOT", self.root), patch.object(delegated, "settings_for", return_value=cfg), \
             patch.object(delegated, "APIClient") as factory, patch.dict("os.environ", {}, clear=True), \
             patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(delegated.main(["--collect", "--record", "2026-11-01/collect"]), 2)
            self.assertEqual(delegated.main(["--collect", "--record", "2026-11-01/collect", "--max-calls", "6"]), 2)
        factory.assert_not_called()

    def test_cli_transport_failure_returns_nonzero_and_keeps_partial_outcome(self):
        folder = self.prepared(); client = FakeTransport(fail_at=2); cfg = Settings("eval", "fixture-model", "openai", 0, 100, False)
        with patch.object(delegated, "ROOT", self.root), patch.object(delegated, "settings_for", return_value=cfg), \
             patch.object(delegated, "APIClient", return_value=client), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-not-a-real-key"}, clear=True), \
             patch("sys.stdout", new_callable=io.StringIO):
            code = delegated.main(["--collect", "--record", "2026-11-01/collect", "--max-calls", "6"])
        self.assertEqual(code, 2)
        result = json.loads((folder / "collections/trial-1/RESULT.json").read_text())
        self.assertEqual(result["attempted_calls"], 2)
        self.assertEqual(result["completed_trials"], 1)
        self.assertTrue(result["calls"][1]["billing_or_server_execution_unknown"])


if __name__ == "__main__":
    unittest.main()
