"""Closed-world fixture integrity checks, independent of model performance."""
from __future__ import annotations

import csv
from collections import Counter
import json
from pathlib import Path
import re

from metrics import CRITERIA, EVIDENCE_RANK, RATING_RANK, resolve_team_ratings
from control_selection import control_for_sources
from source_selection import load_sources, git_blob

EXPECTED_TRAPS = {"setup_wall", "silent_failure", "two_jobs", "unsupported_quote", "prompted_return", "clean"}


def validate_suite(root: Path, *, full=True, sources=None):
    errors = []
    key = json.loads((root / "evals/fixtures/key.json").read_text())
    fixtures = key["fixtures"]
    counts = Counter(x["main_trap"] for x in fixtures.values())
    if full and (set(counts) != EXPECTED_TRAPS or any(n != 2 for n in counts.values()) or len(fixtures) != 12):
        errors.append("Full suite must contain exactly two of each of the six categories")
    per_fixture = []
    for fixture_id, expected in sorted(fixtures.items()):
        folder = root / "evals/fixtures" / fixture_id
        metadata = json.loads((folder / "dossier.json").read_text())
        if metadata.get("fictional") is not True or metadata.get("fixture_id") != fixture_id:
            errors.append(fixture_id + ": public identity/fictional label mismatch")
        if set(metadata) & {"main_trap", "zone", "criteria", "observations", "team_expected", "trap_aliases"}:
            errors.append(fixture_id + ": oracle fields in public metadata")
        texts = []
        for name in ["README.md", "pitch.md", "first_session.md", "usage.csv"]:
            path = folder / name
            if not path.is_file():
                errors.append(fixture_id + ": absent " + name)
                continue
            text = path.read_text()
            texts.append(text)
            if "fictional" not in text.lower():
                errors.append(fixture_id + ": missing fictional label in " + name)
        public = "\n".join(texts)
        ids = set(re.findall(r"\bO\d{2,}\b", public))
        for observation in expected.get("observations", {}):
            if observation not in ids:
                errors.append(fixture_id + ": private observation not present publicly: " + observation)
        with (folder / "usage.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        weeks = {int(r["week"]) for r in rows}
        if weeks != set(range(1, 7)):
            errors.append(fixture_id + ": usage log must cover weeks 1-6")
        for row in rows:
            if int(row["weekly_opens"]) < 0 or int(row.get("unprompted_opens", 0)) > int(row["weekly_opens"]):
                errors.append(fixture_id + ": inconsistent weekly open counts")
        if set(expected.get("criteria", {})) != set(CRITERIA):
            errors.append(fixture_id + ": expected six independent criteria")
        for name, value in expected.get("criteria", {}).items():
            if value["rating"] not in RATING_RANK or value["evidence"] not in EVIDENCE_RANK:
                errors.append(fixture_id + ": invalid rating/evidence labels")
            if any(oid not in expected["observations"] for oid in value.get("observation_ids", [])):
                errors.append(fixture_id + ": unknown observation in " + name)
        prerequisites = all(expected["criteria"][c]["rating"] == "Solid" and EVIDENCE_RANK[expected["criteria"][c]["evidence"]] >= 1 for c in CRITERIA[:5])
        zone = "worth_using" if prerequisites and expected["criteria"]["Return"]["rating"] == "Solid" and expected["criteria"]["Return"]["evidence"] == "Repeated" else ("stranger_ready" if prerequisites else "not_ready")
        if expected["zone"] != zone:
            errors.append(fixture_id + ": zone contradicts its criterion key")
        if expected["main_trap"] == "clean" and any(x["rating"] == "Missing" for x in expected["criteria"].values()):
            errors.append(fixture_id + ": clean control has a Missing oracle rating")
        per_fixture.append({"id": fixture_id, "category": expected["main_trap"], "public_observations": len(ids), "usage_rows": len(rows), "weeks": sorted(weeks)})
    if full:
        personas = json.loads((root / "evals/personas.json").read_text())
        teams = json.loads((root / "evals/teams.json").read_text())
        if isinstance(personas, dict):
            personas = personas["personas"]
        if isinstance(teams, dict):
            teams = teams["teams"]
        if len(personas) != 4 or any(not x.get("fictional") or not x.get("pressure") for x in personas):
            errors.append("Exactly four fictional personas with fixed pressure moments are required")
        if len(teams) != 3:
            errors.append("Exactly three team cards are required")
        for team in teams:
            if not team.get("fictional") or len(team.get("raters", [])) != 3:
                errors.append(team["id"] + ": team needs three fictional raters")
            for fixture_id, expected in fixtures.items():
                submissions = team.get("submissions_by_fixture", {}).get(fixture_id, [])
                if len(submissions) != 3:
                    errors.append(team["id"] + "/" + fixture_id + ": three submissions required")
                    continue
                if any(set(r["ratings"]) != set(CRITERIA) for r in submissions):
                    errors.append(team["id"] + "/" + fixture_id + ": incomplete rater card")
                resolved = resolve_team_ratings(submissions, expected)
                oracle = expected.get("team_expected", {}).get(team["id"], {}).get("ratings", {})
                for criterion in CRITERIA:
                    if not oracle.get(criterion) or any(resolved[criterion][f] != oracle[criterion][f] for f in ["rating", "evidence"]):
                        errors.append(team["id"] + "/" + fixture_id + ": team oracle mismatch on " + criterion)
    sources = sources or load_sources(root)
    for item in sources.provenance["sources"]:
        if git_blob(sources.files[item["snapshot"]]) != item["blob_sha"]:
            errors.append("Selected source bytes differ: " + item["snapshot"])
    source = sources.skill + "\n\n" + sources.rubric
    try:
        placebo = control_for_sources(root, sources).text
    except ValueError as exc:
        errors.append(str(exc))
        placebo = None  # Missing/mismatched controls never fall back to another version.
    return {"status": "passed" if not errors else "failed", "is_empirical": False,
            "fixtures": per_fixture, "category_counts": dict(sorted(counts.items())),
            "source_selection": sources.selection_mode, "source_version": sources.version,
            "source_words": len(source.split()), "placebo_words": len(placebo.split()) if placebo is not None else None, "errors": errors}
