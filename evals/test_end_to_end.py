"""Two-fixture integration test using synthetic transport only.

Nothing here is a model result. Every generated record lives in a temporary
directory beneath evals, is marked by a synthetic-only sentinel, and is removed.
No requests reach a model provider or the network.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import experiment
import metrics
import prompts
import providers
from control_selection import select_current_control, freeze_control


def synthetic_judgment(packet):
    """Fixed schema fixture, deliberately no extracted ratings or advice claim."""
    return {
        "quality": {name: {"score": 3, "reason": "Synthetic test data; no model was judged."}
                    for name in ["usefulness", "honesty", "actionability"]},
        "verdict_first": [
            {"message_index": message["message_index"], "value": None,
             "first_sentence": "Synthetic transport response.",
             "reason": "Synthetic test data; this is not a substantive review."}
            for message in packet["transcript"] if message["role"] == "assistant"
        ],
        "rating_annotations": [],
        "trap": {"named": None, "message_index": None, "span": None,
                 "reason": "Synthetic test data; no diagnosis was measured."},
        "zone": {"claimed_level": None, "message_index": None, "span": None,
                 "reason": "Synthetic test data; no zone was declared."},
        "false_alarms": [],
        "team": {"ratings_preserved": None, "spread_reported": None, "averaged": None,
                 "strongest_evidence_rule_applied": None, "ties_go_lower": None,
                 "reason": "Synthetic test data; team behavior was not measured."},
        "coach": {"explicit_stop": None, "completed_rounds": None,
                  "full_rerun_after_failed_gate": None, "subtraction_episodes": [],
                  "invented_growth": None, "planted_pressure_resisted": None,
                  "reason": "Synthetic test data; coaching behavior was not measured."},
        "uncertainties": ["All responses in this integration test are canned transport data."],
    }


class SyntheticClient:
    """Has the APIClient interface but no transport implementation."""
    requests = []

    def __init__(self, cfg):
        self.cfg = cfg

    def complete(self, messages, seed):
        self.requests.append({"role": self.cfg.role, "messages": copy.deepcopy(messages), "seed": seed})
        if self.cfg.role == "eval":
            payload = {"reply": "Synthetic transport response. This canned text establishes no behavioral result.",
                       "done": True}
        elif self.cfg.role == "simulator":
            supplied = json.loads(messages[-1]["content"])
            payload = {"messages": [supplied["persona"]["pressure"]] +
                       ["I am considering the fictional application already described."] * 10}
        else:
            supplied = json.loads(messages[-1]["content"])
            payload = ({"valid": True, "unsupported_events": []}
                       if "script" in supplied else synthetic_judgment(supplied))
        return {
            "content": json.dumps(payload), "provider": "synthetic_transport_test",
            "model_requested": self.cfg.model, "model_returned": self.cfg.model,
            "request_id": "synthetic-request", "system_fingerprint": None,
            "temperature": self.cfg.temperature, "max_tokens": self.cfg.max_tokens,
            "seed_requested": seed, "seed_sent": seed, "seed_supported": False,
            "latency_seconds": 0.0,
            "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0},
            "estimated_uncached_cost_usd": None, "finish_reason": "stop", "is_empirical": False,
        }


class TwoFixturePipelineTests(unittest.TestCase):
    def test_complete_pipeline_is_paired_blinded_resumable_and_confined(self):
        SyntheticClient.requests = []
        temp_path = None
        with tempfile.TemporaryDirectory(prefix="synthetic-pipeline-", dir=HERE) as temporary:
            temp_path = Path(temporary)
            test_root = temp_path / "repository"
            eval_dir = test_root / "evals"
            eval_dir.mkdir(parents=True)
            output = temp_path / "SYNTHETIC-TEST-ONLY"
            output.mkdir()
            (temp_path / "SYNTHETIC-TEST-ONLY.json").write_text(json.dumps({
                "is_empirical": False,
                "purpose": "Deleted integration-test transport records; never research observations."}))

            # Freeze local copies so other work in the shared checkout cannot
            # change the run's source hash while the resume assertion executes.
            for source in HERE.glob("*.py"):
                shutil.copyfile(source, eval_dir / source.name)
            for name in ["PROTOCOL.md", "judge_rubric.md", "placebo.txt"]:
                shutil.copyfile(HERE / name, eval_dir / name)
            ids = ["f01", "f06"]
            source_key = json.loads((HERE / "fixtures" / "key.json").read_text())
            key = {"fixtures": {identifier: source_key["fixtures"][identifier] for identifier in ids}}
            (eval_dir / "fixtures").mkdir()
            (eval_dir / "fixtures" / "key.json").write_text(json.dumps(key))
            for identifier in ids:
                shutil.copytree(HERE / "fixtures" / identifier, eval_dir / "fixtures" / identifier)

            # This test does not depend on the main persona/team authoring task.
            # These tiny synthetic cards exist only inside the deleted test tree.
            persona = {"id": "synthetic-persona", "fictional": True,
                       "opening": "Help me consider this fictional application.",
                       "pressure": "Can we use my enthusiasm as sufficient support?"}
            team = {"id": "synthetic-team", "fictional": True,
                    "submissions_by_fixture": {
                        identifier: [{"name": "Synthetic rater " + letter,
                                      "submission": "My opinion is not an additional observation."}
                                     for letter in ["A", "B", "C"]]
                        for identifier in ids}}
            (eval_dir / "personas.json").write_text(json.dumps({"personas": [persona]}))
            (eval_dir / "teams.json").write_text(json.dumps({"teams": [team]}))

            skill = (ROOT / "skills/worth-using/SKILL.md").read_text()
            rubric = (ROOT / "skills/worth-using/references/rubric.md").read_text()
            control = select_current_control(ROOT, skill + "\n\n" + rubric)
            placebo = control.text
            freeze_control(output, control)
            configs = [providers.Settings(role, "synthetic-" + role + "-v1", "openai", 0.2, 1000, False)
                       for role in ["eval", "judge", "simulator"]]
            conditions = ["skill", "baseline", "placebo"]
            manifest = {
                "placebo_control": control.metadata,
                "models": {cfg.role: dict(cfg.public(), model_family="synthetic-" + cfg.role,
                                           model_family_basis="operator_declared_not_api_verified") for cfg in configs},
                "source_hashes": {"skill_sha256": experiment.digest(skill),
                                  "rubric_sha256": experiment.digest(rubric)},
                "prompt_hashes": {condition: experiment.digest(prompts.condition_prompt(condition, skill, rubric, placebo))
                                  for condition in conditions},
                "conditions": conditions, "seed_base": 41001,
                "tasks": ["score", "team", "coach"], "coach_max_agent_turns": 12,
                "is_empirical": False,
            }

            def dossier(identifier):
                folder = eval_dir / "fixtures" / identifier
                meta = json.loads((folder / "dossier.json").read_text())
                text = "\n\n".join((folder / name).read_text()
                                   for name in ["README.md", "pitch.md", "first_session.md", "usage.csv"])
                return meta, text

            original_write, original_append = experiment.write_json, experiment.append
            writes = []

            def confined_write(path, value):
                self.assertTrue(Path(path).resolve().is_relative_to(output.resolve()))
                writes.append(Path(path))
                original_write(path, value)

            def confined_append(path, value):
                self.assertTrue(Path(path).resolve().is_relative_to(output.resolve()))
                writes.append(Path(path))
                original_append(path, value)

            with patch.object(experiment, "APIClient", SyntheticClient), \
                 patch.object(experiment, "write_json", confined_write), \
                 patch.object(experiment, "append", confined_append), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("Network prohibited in synthetic test")), \
                 patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network prohibited in synthetic test")):
                trials, judgments, rows = experiment.run_phase(
                    test_root, output, manifest, configs, skill, rubric, ids, [41001], dossier)
                self.assertEqual(len(trials), 18)
                self.assertEqual(len(judgments), 36)
                self.assertEqual(len(rows), 18)
                self.assertTrue(all(trial["status"] == "complete" for trial in trials))
                self.assertTrue(all(judgment["status"] == "complete" for judgment in judgments))
                self.assertEqual(len(SyntheticClient.requests), 58)

                for identifier in ids:
                    for task in manifest["tasks"]:
                        group = [trial for trial in trials if trial["fixture_id"] == identifier and trial["task"] == task]
                        self.assertEqual(len(group), 3)
                        self.assertEqual(len({trial["initial_user_sha256"] for trial in group}), 1)
                        self.assertEqual(len({tuple(call["seed_requested"] for call in trial["calls"]) for trial in group}), 1)
                        self.assertEqual(len({json.dumps([m["content"] for m in trial["messages"] if m["role"] == "user"])
                                              for trial in group}), 1)
                for row in rows:
                    self.assertEqual(row["rating_coverage"], 0)
                    self.assertEqual(row["semantic_rating_coverage"], 0)
                    self.assertIsNone(row["evidence_upgrades_per_10_rated"])
                    self.assertIsNone(row["evidence_upgrades_confirmed"])
                    self.assertIsNone(row["evidence_upgrades_confirmed_per_10_rated"])

                by_id = {trial["run_id"]: trial for trial in trials}
                for judgment in judgments:
                    ledger = json.loads((output / "blinding_maps" / (judgment["blind_id"] + ".json")).read_text())
                    trial = by_id[judgment["run_id"]]
                    for index, message in enumerate(trial["messages"]):
                        self.assertEqual(metrics.restore_text(ledger["message_" + str(index)]), message["content"])
                    self.assertEqual(metrics.restore_text(ledger["dossier"]), dossier(trial["fixture_id"])[1])
                    masked = json.loads((output / "blinded" / ("pass" + str(judgment["repeat"])) /
                                         (judgment["blind_id"] + ".json")).read_text())
                    self.assertNotIn("condition", masked)
                    self.assertNotIn("run_id", masked)
                    self.assertNotIn("model", masked)
                    self.assertNotIn("replacements", masked)

                calls = experiment.read_jsonl(output / "calls.jsonl")
                self.assertTrue(all(call["is_empirical"] is False for call in calls))
                before_resume = len(SyntheticClient.requests)
                resumed = experiment.run_phase(test_root, output, manifest, configs, skill, rubric, ids, [41001], dossier)
                self.assertEqual(len(resumed[0]), 18)
                self.assertEqual(len(SyntheticClient.requests), before_resume)
                changed_family = copy.deepcopy(manifest)
                changed_family["models"]["judge"]["model_family"] = "synthetic-different-declaration"
                with self.assertRaises(providers.ConfigurationError):
                    experiment.run_phase(test_root, output, changed_family, configs, skill, rubric, ids, [41001], dossier)
                self.assertEqual(len(SyntheticClient.requests), before_resume)
                self.assertTrue(writes)

            self.assertFalse((test_root / "docs" / "evaluations").exists())
        self.assertIsNotNone(temp_path)
        self.assertFalse(temp_path.exists(), "Synthetic records must be deleted after the test")


if __name__ == "__main__":
    unittest.main()
