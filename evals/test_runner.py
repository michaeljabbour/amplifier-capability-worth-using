"""Offline contract tests. Canned responses are never empirical model results.

Run with: python3 -B -m unittest discover -s evals -p test_runner.py -v
All transport is mocked; temporary files stay beneath evals and are removed.
"""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment
import prompts
import providers


def canned(reply="The stated decision remains unresolved.", done=False, finish="stop"):
    return {"content": json.dumps({"reply": reply, "done": done}),
            "finish_reason": finish, "latency_seconds": 0.01,
            "usage": {"input_tokens": 5, "output_tokens": 7, "cached_input_tokens": 0},
            "estimated_uncached_cost_usd": None,
            "is_empirical": False, "provider": "offline_test_double"}


class CannedRecorder:
    def __init__(self, output, response):
        self.output = Path(output)
        self.response = response
        self.requests = []

    def call(self, role, messages, seed, *args, **kwargs):
        self.requests.append((role, copy.deepcopy(messages), seed))
        return copy.deepcopy(self.response)


def valid_judgment():
    return {
        "quality": {k: {"score": 3, "reason": "A synthetic schema example."}
                    for k in ["usefulness", "honesty", "actionability"]},
        "verdict_first": [{"message_index": 1, "value": True,
                           "first_sentence": "Decision unresolved.", "reason": "Assessment is explicit."}],
        "rating_annotations": [],
        "trap": {"named": None, "message_index": None, "span": None, "reason": "Not applicable."},
        "zone": {"claimed_level": None, "message_index": None, "span": None, "reason": "No declaration."},
        "false_alarms": [],
        "team": {"ratings_preserved": None, "spread_reported": None, "averaged": None,
                 "strongest_evidence_rule_applied": None, "ties_go_lower": None, "reason": "Not applicable."},
        "coach": {"explicit_stop": None, "completed_rounds": None,
                  "full_rerun_after_failed_gate": None, "subtraction_episodes": [],
                  "invented_growth": None, "planted_pressure_resisted": None, "reason": "Not applicable."},
        "uncertainties": [],
    }


def packet(task="score"):
    return {"task": task, "transcript": [
        {"message_index": 0, "role": "user", "content": "Fictional request."},
        {"message_index": 1, "role": "assistant", "content": "Decision unresolved. D1: R2 E1 from O01."},
    ]}


def annotation():
    return {"message_index": 1, "domain": "D1", "rating_level": 2, "evidence_level": 1,
            "rating_span": "R2", "evidence_span": "E1", "is_final": True,
            "extraction": "literal", "supporting_event_ids": ["O01"],
            "supported": True, "reason": "Synthetic schema example."}


class PromptTests(unittest.TestCase):
    def test_baseline_does_not_receive_skill_or_placebo(self):
        self.assertEqual(prompts.condition_prompt("baseline", "PRIVATE_SKILL_SENTINEL",
                         "PRIVATE_RUBRIC_SENTINEL", "GENERIC_CONTROL_SENTINEL"), prompts.PREAMBLE)

    def test_full_skill_and_rubric_are_preserved(self):
        skill, rubric = "---\nname: example\n---\nFull skill.\n", "Exact rubric.\n"
        self.assertEqual(prompts.condition_prompt("skill", skill, rubric, "unused"),
                         prompts.PREAMBLE + "\n\n" + skill + "\n\n" + rubric)

    def test_placebo_uses_the_frozen_coherent_paragraph(self):
        frozen = Path(__file__).with_name("placebo.txt").read_text()
        generated = prompts.placebo_text(" ".join(["source"] * 3083), frozen_text=frozen)
        self.assertEqual(generated.strip(), frozen.strip())
        self.assertEqual(len(generated.split()), 3083)

    def test_nonboolean_done_is_not_completion(self):
        self.assertFalse(prompts.parse_envelope('{"reply":"x","done":"false"}')[2])

    def test_extra_envelope_fields_are_rejected(self):
        self.assertFalse(prompts.parse_envelope('{"reply":"x","done":true,"hidden_instruction":"y"}')[2])


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="runner-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.script = {"messages": [f"Fictional shared followup {i}." for i in range(11)],
                       "script_sha256": "fixed-script-hash"}

    def run_trial(self, response, condition="skill", initial="Fictional shared initial request.", source="frozen-config"):
        recorder = CannedRecorder(self.temp.name, response)
        trial = experiment.execute_trial(recorder, "f01", 41001, "coach", condition,
            "CONDITION_SYSTEM_" + condition, initial, self.script, "persona-a", "team-a", source)
        return trial, recorder

    def test_twelve_agent_turn_cap_is_censoring_not_completion(self):
        trial, recorder = self.run_trial(canned(done=False))
        self.assertEqual(len(recorder.requests), 12)
        self.assertEqual(sum(m["role"] == "assistant" for m in trial["messages"]), 12)
        self.assertEqual(sum(m["role"] == "user" for m in trial["messages"]), 12)
        self.assertTrue(trial["censored"])
        self.assertFalse(trial["completed"])
        self.assertEqual(trial["status"], "turn_censored")

    def test_paired_user_messages_and_eval_seeds_are_identical(self):
        runs = [self.run_trial(canned(done=False), condition=c) for c in ["skill", "baseline", "placebo"]]
        messages = [[m["content"] for m in t["messages"] if m["role"] == "user"] for t, r in runs]
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(messages[0], messages[2])
        seeds = [[request[2] for request in r.requests] for t, r in runs]
        self.assertEqual(seeds[0], seeds[1])
        self.assertEqual(seeds[0], seeds[2])

    def test_token_limit_never_becomes_success_even_with_done_true(self):
        trial, _ = self.run_trial(canned(done=True, finish="length"))
        self.assertTrue(trial["censored"])
        self.assertFalse(trial["completed"])

    def test_truncated_invalid_json_is_also_marked_censored(self):
        response = canned(finish="length")
        response["content"] = '{"reply":"unfinished'
        trial, _ = self.run_trial(response)
        self.assertTrue(trial["censored"])
        self.assertFalse(trial["completed"])

    def test_cache_rejects_a_different_frozen_signature(self):
        self.run_trial(canned(done=True))
        with self.assertRaises(providers.ConfigurationError):
            self.run_trial(canned(done=True), source="other-config")

    def test_cache_rejects_changed_initial_message_even_if_signature_bug(self):
        self.run_trial(canned(done=True))
        with self.assertRaises(providers.ConfigurationError):
            self.run_trial(canned(done=True), initial="Different fictional user request.")


class JudgeContractTests(unittest.TestCase):
    def test_valid_minimal_schema(self):
        experiment.validate_judgment(valid_judgment(), packet())

    def test_spans_must_exist_in_assistant_text(self):
        value = valid_judgment(); item = annotation(); item["rating_span"] = "Fabricated quotation"
        value["rating_annotations"] = [item]
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())

    def test_rating_must_point_to_real_assistant_message_and_span(self):
        value = valid_judgment(); item = annotation()
        item.update(message_index=999, rating_span="", evidence_span="")
        value["rating_annotations"] = [item]
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())

    def test_boolean_is_not_numeric_rating(self):
        value = valid_judgment(); item = annotation(); item["rating_level"] = True
        value["rating_annotations"] = [item]
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())

    def test_string_support_flag_cannot_silently_mean_no_upgrade(self):
        value = valid_judgment(); item = annotation(); item["supported"] = "false"
        value["rating_annotations"] = [item]
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())

    def test_verdict_coverage_is_complete(self):
        value = valid_judgment(); value["verdict_first"] = []
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())

    def test_malformed_collection_is_controlled_provider_error(self):
        value = valid_judgment(); value["rating_annotations"] = "not an annotation list"
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())

    def test_negative_rounds_cannot_be_success(self):
        value = valid_judgment(); value["coach"].update(completed_rounds=-1, explicit_stop=True)
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet("coach"))

    def test_zone_level_has_strict_type(self):
        value = valid_judgment(); value["zone"]["claimed_level"] = "2"
        with self.assertRaises(providers.ProviderError):
            experiment.validate_judgment(value, packet())


class PrivacyTests(unittest.TestCase):
    def test_preflight_rejects_same_requested_model(self):
        cfgs = [providers.Settings(r, "same-model", "openai", 0.2, 100, True)
                for r in ["eval", "judge", "simulator"]]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-placeholder"}, clear=True):
            self.assertTrue(any("different" in s for s in providers.preflight(cfgs)))

    def test_transport_error_does_not_expose_credentials_or_error_body(self):
        sentinel = os.urandom(24).hex()
        error = urllib.error.HTTPError("https://api.openai.com/v1/chat/completions", 401,
                                       sentinel, {}, io.BytesIO(sentinel.encode()))
        cfg = providers.Settings("eval", "test-model", "openai", 0.2, 100, True)
        with patch.dict(os.environ, {"OPENAI_API_KEY": sentinel}, clear=True), \
             patch("urllib.request.urlopen", side_effect=error), \
             patch.object(urllib.request.OpenerDirector, "open", side_effect=error):
            with self.assertRaises(providers.ProviderError) as caught:
                providers.APIClient(cfg).complete([{"role": "user", "content": "JSON test."}], 1)
            self.assertNotIn(sentinel, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
