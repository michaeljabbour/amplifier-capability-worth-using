"""Source-version and configuration regressions; no network or empirical data."""
from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import providers
import run as runner
import source_selection as selection


class SourceVersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="source-regression-", dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commit = "a" * 40
        self.original = {}
        for source_path, snapshot in selection.SOURCE_FILES:
            data = (HERE.parent / source_path).read_bytes()
            path = self.root / source_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.original[source_path] = data
        (self.root / "evals").mkdir()
        shutil.copytree(HERE / "controls", self.root / "evals/controls")
        for name in ("PROTOCOL.md", "judge_rubric.md", "placebo.txt"):
            shutil.copyfile(HERE / name, self.root / "evals" / name)
        self.git = patch.object(selection, "_git", side_effect=self.git_read)
        self.git.start()
        self.addCleanup(self.git.stop)

    def git_read(self, root, *args):
        if args[0] == "rev-parse":
            return (self.commit + "\n").encode()
        if args[0] == "show":
            return self.original.get(args[1].split(":", 1)[1])
        raise AssertionError("Unexpected Git operation: " + repr(args))

    def frozen_record(self, name="2026-10-23/original"):
        folder = selection.record_path(self.root, name)
        sources = selection.load_sources(self.root)
        selection.freeze_sources(folder, sources)
        return folder, sources

    def test_checkout_default_and_historical_replay_are_explicitly_distinct(self):
        folder, original = self.frozen_record()
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        path = self.root / "skills/worth-using/SKILL.md"
        path.write_bytes(path.read_bytes() + b"\nCorrected synthetic source version.\n")
        current = selection.load_sources(self.root)
        historical = selection.load_sources(self.root, "2026-10-23/original")
        self.assertNotEqual(current.version, historical.version)
        self.assertEqual(historical.skill, original.skill)
        self.assertIn("Corrected synthetic", current.skill)
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_historical_snapshot_tampering_fails(self):
        folder, _ = self.frozen_record()
        (folder / "rubric.snapshot.md").write_text("Synthetic altered snapshot.")
        with self.assertRaisesRegex(providers.ConfigurationError, "Frozen source bytes differ"):
            selection.load_sources(self.root, "2026-10-23/original")

    def test_live_gate_ignores_generated_files_but_rejects_uncommitted_treatment(self):
        sources = selection.load_sources(self.root)
        (self.root / "evals/generated-test-output.json").write_text('{"is_empirical": false}')
        self.assertEqual(selection.committed_source_errors(self.root, sources), [])
        path = self.root / "skills/worth-using/references/rubric.md"
        path.write_bytes(path.read_bytes() + b"\nUncommitted synthetic edit.\n")
        changed = selection.load_sources(self.root)
        self.assertTrue(any("differs from the selected Git commit" in e for e in selection.committed_source_errors(self.root, changed)))
        self.assertTrue(any("changed after source selection" in e for e in selection.committed_source_errors(self.root, sources)))

    def test_live_gate_requires_actual_commit_object(self):
        sources = selection.load_sources(self.root)
        with patch.object(selection, "_git", return_value=None):
            self.assertIn("unavailable locally", selection.committed_source_errors(self.root, sources)[0])

    def test_status_pointer_change_preserves_frozen_context_and_identity(self):
        folder, sources = self.frozen_record()
        original_bytes = (folder / "BENCHMARK.snapshot.md").read_bytes()
        path = self.root / "docs/BENCHMARK.md"
        text = path.read_text()
        import re
        path.write_text(re.sub(r"(?m)^\*\*Status:.*$", "**Status: Synthetic later record pointer.**", text))
        current = selection.load_sources(self.root)
        self.assertEqual(sources.identity, current.identity)
        frozen = selection.freeze_sources(folder, current)
        self.assertEqual(frozen.files["BENCHMARK.snapshot.md"], original_bytes)
        path.write_text(path.read_text() + "\nA changed synthetic benchmark requirement.\n")
        with self.assertRaises(providers.ConfigurationError):
            selection.freeze_sources(folder, selection.load_sources(self.root))

    def test_safe_record_names_reject_traversal_and_symlink_escape(self):
        for bad in ("../escape", "2026-10-23/../../escape", "2026-10-23/.hidden", "20261023/run", "2026-10-23/a b"):
            with self.subTest(record=bad), self.assertRaises(providers.ConfigurationError):
                selection.record_path(self.root, bad)
        base = self.root / "docs/evaluations/2026-10-23"
        base.mkdir(parents=True)
        outside = self.root / "elsewhere"
        outside.mkdir()
        (base / "escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(providers.ConfigurationError):
            selection.record_path(self.root, "2026-10-23/escape")

    def test_family_declarations_missing_equal_and_distinct(self):
        with patch.dict("os.environ", {}, clear=True):
            families, errors = selection.model_families()
            self.assertEqual(len(errors), 2)
            self.assertIsNone(families["eval"]["model_family"])
        with patch.dict("os.environ", {"EVAL_MODEL_FAMILY": "  Example   Family ", "JUDGE_MODEL_FAMILY": "example family"}, clear=True):
            _, errors = selection.model_families()
            self.assertEqual(len(errors), 1)
        with patch.dict("os.environ", {"EVAL_MODEL_FAMILY": "Family A", "JUDGE_MODEL_FAMILY": "Family B"}, clear=True):
            families, errors = selection.model_families()
            self.assertEqual(errors, [])
            self.assertEqual(families["judge"]["model_family_basis"], "operator_declared_not_api_verified")

    def test_manifest_identity_records_families_and_blocks_collision_before_writes(self):
        args = SimpleNamespace(date="2026-10-23", conditions="skill,baseline", pilot=False,
                               offline_smoke=False, seeds=3, bootstrap=10000, run_id=None)
        configs = [providers.Settings(role, "synthetic-" + role, "openai", .2, 1000, False)
                   for role in ("eval", "judge", "simulator")]
        sources = selection.load_sources(self.root)
        with patch.object(runner, "ROOT", self.root), patch.dict("os.environ", {
                "EVAL_MODEL_FAMILY": "Family A", "JUDGE_MODEL_FAMILY": "Family B"}, clear=True):
            first = runner.make_manifest(args, configs, ["skill", "baseline", "placebo"], ["f01"], sources, "confirmatory")
            self.assertTrue(first["run_id"].startswith("v-" + sources.version[:12]))
            with patch.dict("os.environ", {"JUDGE_MODEL_FAMILY": "Family C"}):
                second = runner.make_manifest(args, configs, ["skill", "baseline", "placebo"], ["f01"], sources, "confirmatory")
        self.assertNotEqual(first["run_id"], second["run_id"])
        output = selection.record_path(self.root, "2026-10-23/explicit")
        output.mkdir(parents=True)
        runner.write_json(output / "manifest.json", first)
        sentinel = (output / "manifest.json").read_bytes()
        with self.assertRaises(providers.ConfigurationError):
            runner.guard_record(output, second)
        self.assertEqual((output / "manifest.json").read_bytes(), sentinel)

    def test_analysis_reads_selected_record_before_checkout_or_model_validation(self):
        output, sources = self.frozen_record()
        manifest = {"status": "blocked_before_live_pilot", "source_commit": self.commit,
                    "models": {"eval": {"model": None}, "judge": {"model": None}},
                    "conditions": ["skill", "baseline", "placebo"], "fixture_list": [], "seeds": [],
                    "completed_empirical_trials": 0}
        runner.write_json(output / "manifest.json", manifest)
        (self.root / "skills/worth-using/SKILL.md").unlink()
        shutil.rmtree(self.root / "evals/controls")  # Analysis must not select a current control.
        args = SimpleNamespace(date="2026-10-23", run_id=None, analyze=True, record="2026-10-23/original",
                               source_record=None, pilot=False, offline_smoke=False, validate=False, bootstrap=20)
        with patch.object(runner, "ROOT", self.root), patch.object(runner, "parse_args", return_value=args), \
             patch.object(runner, "settings_for", side_effect=AssertionError("Current model settings must not be consulted")), \
             patch("reporting.write_reports") as reports, patch.object(runner, "update_benchmark_status"), \
             patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(runner.main(), 0)
        self.assertEqual(reports.call_args.args[1], output)
        self.assertEqual((output / "SKILL.snapshot.md").read_text(), sources.skill)

    def test_nested_benchmark_pointer_is_relative_to_docs(self):
        output = selection.record_path(self.root, "2026-10-23/example")
        with patch.object(runner, "ROOT", self.root):
            runner.update_benchmark_status(output, {"completed_empirical_trials": 0})
        self.assertIn("evaluations/2026-10-23/example/REPORT.md", (self.root / "docs/BENCHMARK.md").read_text())


if __name__ == "__main__":
    unittest.main()
