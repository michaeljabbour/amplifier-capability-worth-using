"""Versioned neutral-control selection and immutable run freezes; no transport."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess

CONTROL_TEXT = "placebo.snapshot.txt"
CONTROL_METADATA = "control-selection.snapshot.json"
CONTROL_CORPUS = "control-corpus.snapshot.txt"
CONTROL_REGISTRY = "control-registry.snapshot.json"
CONTROL_SNAPSHOTS = (CONTROL_TEXT, CONTROL_METADATA, CONTROL_CORPUS, CONTROL_REGISTRY)


class ControlError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def validate_length(treatment, text):
    words = len(treatment.split())
    if not words:
        raise ControlError("A nonempty frozen treatment is required")
    difference = (len(text.split()) - words) / words
    if abs(difference) > 0.05:
        raise ControlError("Placebo and frozen treatment differ by more than five percent in words")
    return difference


@dataclass(frozen=True)
class Control:
    text: str
    metadata: dict
    corpus: bytes
    registry: bytes
    treatment: str


def _entry(registry, treatment):
    matches = [entry for entry in registry["controls"]
               if entry["treatment_sha256"] == digest(treatment)]
    if len(matches) != 1:
        raise ControlError("No unique versioned neutral control matches this treatment; author and freeze a new control version")
    return matches[0]


def _derive(treatment, registry_bytes, corpus):
    """Recompute the selection; self-consistent metadata alone is not proof."""
    registry = json.loads(registry_bytes)
    entry = _entry(registry, treatment)
    if digest(corpus) != entry["corpus_sha256"]:
        raise ControlError("Versioned neutral-control corpus hash mismatch")
    text = corpus.decode().strip()
    if entry["selection"] == "prefix_complete_sentence":
        words = len(treatment.split())
        if len(text.split()) < words:
            raise ControlError("Generic placebo corpus is shorter than the treatment")
        text = " ".join(text.split()[:words])
        if "." in text:
            text = text.rsplit(".", 1)[0] + "."
    elif entry["selection"] != "whole":
        raise ControlError("Unknown frozen control selection policy")
    difference = validate_length(treatment, text)
    metadata = dict(entry, protocol_version=registry["protocol_version"],
                    registry_path="evals/controls/index.json",
                    registry_sha256=digest(registry_bytes), control_sha256=digest(text),
                    treatment_words=len(treatment.split()), control_words=len(text.split()),
                    word_difference_fraction=difference)
    return Control(text, metadata, corpus, registry_bytes, treatment)


def select_current_control(root, treatment):
    root = Path(root).resolve()
    registry_path = root / "evals/controls/index.json"
    registry_bytes = registry_path.read_bytes()
    entry = _entry(json.loads(registry_bytes), treatment)
    path = root / entry["corpus_path"]
    if path.is_symlink() or not path.resolve().is_relative_to(root / "evals/controls"):
        raise ControlError("Control corpus must be a contained regular file")
    return _derive(treatment, registry_bytes, path.read_bytes())


def freeze_control(folder, control):
    folder = Path(folder)
    inputs = {CONTROL_TEXT: control.text.encode(), CONTROL_CORPUS: control.corpus,
              CONTROL_REGISTRY: control.registry,
              CONTROL_METADATA: (json.dumps(control.metadata, sort_keys=True, indent=2) + "\n").encode()}
    for name, data in inputs.items():
        path = folder / name
        if path.exists() and path.read_bytes() != data:
            raise ControlError("Frozen neutral-control input changed: " + name + "; select a fresh run ID")
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in inputs.items():
        path = folder / name
        if not path.exists():
            path.write_bytes(data)


def read_frozen_control(folder, treatment, expected_metadata):
    folder = Path(folder)
    if not isinstance(expected_metadata, dict):
        raise ControlError("Historical execution requires a verifiable frozen neutral control; analysis remains available")
    if not all((folder / name).is_file() for name in CONTROL_SNAPSHOTS):
        raise ControlError("Historical execution lacks its frozen neutral control; analysis remains available")
    metadata = json.loads((folder / CONTROL_METADATA).read_text())
    text = (folder / CONTROL_TEXT).read_text()
    if metadata != expected_metadata:
        raise ControlError("Frozen neutral-control metadata differs from the recorded manifest")
    if metadata.get("treatment_sha256") != digest(treatment):
        raise ControlError("Frozen neutral control belongs to another treatment version")
    if metadata.get("control_sha256") != digest(text):
        raise ControlError("Frozen neutral-control bytes differ from their recorded hash")
    control = _derive(treatment, (folder / CONTROL_REGISTRY).read_bytes(),
                      (folder / CONTROL_CORPUS).read_bytes())
    if control.metadata != metadata or control.text != text:
        raise ControlError("Frozen neutral-control selection differs from its pinned corpus/registry")
    return control


def control_for_sources(root, sources):
    """Worth Using replay selects the record's own control or stops explicitly."""
    treatment = sources.skill + "\n\n" + sources.rubric
    if sources.selection_mode == "historical_record":
        from source_selection import record_path
        folder = record_path(Path(root), sources.selected_record)
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        return read_frozen_control(folder, treatment, manifest.get("placebo_control"))
    return select_current_control(root, treatment)


def committed_control_errors(root, control, commit, *, check_checkout=True):
    """Derive the exact control again from Git objects before any live request."""
    errors, pinned = [], {}
    for path_key, hash_key, raw in (("corpus_path", "corpus_sha256", control.corpus),
                                    ("registry_path", "registry_sha256", control.registry)):
        relative = control.metadata[path_key]
        result = subprocess.run(["git", "-C", str(root), "show", str(commit) + ":" + relative],
                                capture_output=True, check=False)
        if result.returncode or result.stdout != raw or digest(raw) != control.metadata[hash_key]:
            errors.append(relative + " differs from the selected Git commit; commit the control version before live calls")
        pinned[path_key] = result.stdout
        if check_checkout and (Path(root) / relative).read_bytes() != raw:
            errors.append(relative + " changed after control selection; restart with a fresh record")
    if not errors:
        derived = _derive(control.treatment, pinned["registry_path"], pinned["corpus_path"])
        if derived.text != control.text or derived.metadata != control.metadata:
            errors.append("Selected neutral control differs from its Git-pinned registry/corpus derivation")
    return errors
