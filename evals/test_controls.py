"""Neutral-control version, immutable replay and no-transport regressions."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import experiment
import prompts
from control_selection import (CONTROL_TEXT, CONTROL_METADATA, CONTROL_CORPUS, CONTROL_REGISTRY, Control, ControlError,
    control_for_sources, digest, freeze_control, read_frozen_control,
    select_current_control, validate_length, committed_control_errors)


class ControlVersionTests(unittest.TestCase):
    def setUp(self):
        self.skill = (ROOT / "skills/worth-using/SKILL.md").read_text()
        self.rubric = (ROOT / "skills/worth-using/references/rubric.md").read_text()
        self.treatment = self.skill + "\n\n" + self.rubric
        self.control = select_current_control(ROOT, self.treatment)
        self.temp = tempfile.TemporaryDirectory(prefix="control-regression-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def bytes(self, folder):
        return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    def test_current_version_retains_fixed_five_percent_bound(self):
        self.assertEqual(self.control.metadata["treatment_sha256"], digest(self.treatment))
        self.assertLessEqual(abs(self.control.metadata["word_difference_fraction"]), .05)
        self.assertNotEqual(self.control.text.strip(), (HERE / "placebo.txt").read_text().strip())
        source = " ".join(["source"] * 100)
        for words in (95, 105):
            validate_length(source, " ".join(["generic"] * words))
        for words in (94, 106):
            with self.assertRaises(ControlError):
                validate_length(source, " ".join(["generic"] * words))

    def test_changed_treatment_never_falls_back_to_length_matched_current_control(self):
        with self.assertRaisesRegex(ControlError, "No unique versioned"):
            select_current_control(ROOT, self.treatment.replace("Worth", "Other", 1))

    def test_changed_corpus_is_rejected_by_frozen_registry_hash(self):
        shutil.copytree(HERE / "controls", self.folder / "evals/controls")
        corpus = self.folder / self.control.metadata["corpus_path"]
        corpus.write_text(corpus.read_text() + "\nAn altered generic sentence.\n")
        with self.assertRaisesRegex(ControlError, "corpus hash mismatch"):
            select_current_control(self.folder, self.treatment)

    def test_control_bytes_and_metadata_tamper_each_fail(self):
        freeze_control(self.folder, self.control)
        text = self.folder / CONTROL_TEXT
        original = text.read_bytes()
        text.write_bytes(original + b" altered")
        with self.assertRaisesRegex(ControlError, "bytes differ"):
            read_frozen_control(self.folder, self.treatment, self.control.metadata)
        text.write_bytes(original)
        metadata = self.folder / CONTROL_METADATA
        value = json.loads(metadata.read_text()); value["control_id"] = "different-control"
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(ControlError, "metadata differs"):
            read_frozen_control(self.folder, self.treatment, self.control.metadata)

    def test_control_is_bound_to_exact_treatment_not_only_length(self):
        freeze_control(self.folder, self.control)
        with self.assertRaisesRegex(ControlError, "another treatment"):
            read_frozen_control(self.folder, self.treatment + "\nChanged.", self.control.metadata)

    def test_freeze_collision_preserves_all_existing_bytes(self):
        freeze_control(self.folder, self.control)
        before = self.bytes(self.folder)
        changed = Control(self.control.text + " altered", copy.deepcopy(self.control.metadata),
                          self.control.corpus, self.control.registry, self.treatment)
        with self.assertRaisesRegex(ControlError, "Frozen neutral-control input changed"):
            freeze_control(self.folder, changed)
        self.assertEqual(self.bytes(self.folder), before)

    def historical(self):
        name = "2026-11-02/example"
        folder = self.folder / "docs/evaluations" / name
        folder.mkdir(parents=True)
        sources = SimpleNamespace(skill=self.skill, rubric=self.rubric,
            selection_mode="historical_record", selected_record=name)
        return folder, sources

    def test_legacy_historical_execution_without_control_stops_without_writes(self):
        folder, sources = self.historical()
        (folder / "manifest.json").write_text('{"status":"retained-old-record"}')
        before = self.bytes(self.folder)
        with self.assertRaisesRegex(ControlError, "verifiable frozen neutral control"):
            control_for_sources(self.folder, sources)
        self.assertEqual(self.bytes(self.folder), before)

    def test_historical_execution_uses_its_verified_control_without_current_corpus(self):
        folder, sources = self.historical()
        freeze_control(folder, self.control)
        (folder / "manifest.json").write_text(json.dumps({"placebo_control": self.control.metadata}))
        # No current evals/controls directory exists in this isolated replay root.
        self.assertEqual(control_for_sources(self.folder, sources), self.control)

    def test_coherent_selected_text_metadata_and_manifest_tamper_fails_before_recorder(self):
        folder, sources = self.historical()
        freeze_control(folder, self.control)
        changed = self.control.text.replace("helpful", "careful", 1)
        self.assertNotEqual(changed, self.control.text)
        metadata = copy.deepcopy(self.control.metadata)
        metadata["control_sha256"] = digest(changed)
        metadata["control_words"] = len(changed.split())
        metadata["word_difference_fraction"] = (len(changed.split()) - len(self.treatment.split())) / len(self.treatment.split())
        (folder / CONTROL_TEXT).write_text(changed)
        (folder / CONTROL_METADATA).write_text(json.dumps(metadata))
        manifest = {"placebo_control": metadata}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        before = self.bytes(folder)
        with self.assertRaisesRegex(ControlError, "pinned corpus/registry"):
            control_for_sources(self.folder, sources)
        with patch.object(experiment, "Recorder") as recorder:
            with self.assertRaisesRegex(ControlError, "pinned corpus/registry"):
                experiment.run_experiment(ROOT, folder, manifest, [], self.skill, self.rubric,
                                          SimpleNamespace(pilot=True), None)
            recorder.assert_not_called()
        self.assertEqual(self.bytes(folder), before)

    def test_coherent_corpus_registry_change_cannot_pass_original_git_pin(self):
        shutil.copytree(HERE / "controls", self.folder / "evals/controls")
        corpus = self.folder / self.control.metadata["corpus_path"]
        corpus.write_text(corpus.read_text().replace("helpful", "careful", 1))
        registry = self.folder / "evals/controls/index.json"
        value = json.loads(registry.read_text())
        value["controls"][0]["corpus_sha256"] = digest(corpus.read_bytes())
        registry.write_text(json.dumps(value))
        changed = select_current_control(self.folder, self.treatment)
        def original_git(argv, **kwargs):
            path = argv[-1].split(":", 1)[1]
            raw = self.control.registry if path == self.control.metadata["registry_path"] else self.control.corpus
            return SimpleNamespace(returncode=0, stdout=raw)
        with patch("control_selection.subprocess.run", side_effect=original_git):
            errors = committed_control_errors(ROOT, changed, "a" * 40, check_checkout=False)
        self.assertTrue(errors)
        self.assertTrue(all("differs from the selected Git commit" in error for error in errors))

    def test_nested_live_pilot_reads_top_level_freeze_before_recorder(self):
        freeze_control(self.folder, self.control)
        manifest = {"placebo_control": self.control.metadata, "conditions": ["skill", "baseline", "placebo"],
            "prompt_hashes": {c: experiment.digest(prompts.condition_prompt(c, self.skill, self.rubric, self.control.text))
                              for c in ("skill", "baseline", "placebo")}}
        class ReachedRecorder(Exception):
            pass
        with patch.object(experiment, "Recorder", side_effect=ReachedRecorder) as recorder:
            with self.assertRaises(ReachedRecorder):
                experiment.run_experiment(ROOT, self.folder, manifest, [], self.skill, self.rubric,
                                          SimpleNamespace(pilot=True), None)
            self.assertEqual(recorder.call_args.args[0], self.folder / "pilot/live")
        # Reaching the recorder in the real nested run_phase proves the top-level
        # freeze was found; no recorder or transport was constructed by this test.

    def test_tampered_pilot_control_stops_before_recorder_or_manifest_write(self):
        freeze_control(self.folder, self.control)
        (self.folder / CONTROL_TEXT).write_text("Altered control.")
        before = self.bytes(self.folder)
        with patch.object(experiment, "Recorder", side_effect=AssertionError("No transport allowed")) as recorder:
            with self.assertRaisesRegex(ControlError, "bytes differ"):
                experiment.run_experiment(ROOT, self.folder, {"placebo_control": self.control.metadata}, [],
                    self.skill, self.rubric, SimpleNamespace(pilot=True), None)
            recorder.assert_not_called()
        self.assertEqual(self.bytes(self.folder), before)


if __name__ == "__main__":
    unittest.main()
