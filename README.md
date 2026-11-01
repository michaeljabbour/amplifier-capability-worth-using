# Worth Using

[Open the guide and get the skill](https://michaeljabbour.github.io/amplifier-capability-worth-using/).

A usefulness rubric with a coach. It scores whether a tool, feature, skill, or capability is genuinely useful to someone who didn't build it, on six plain criteria, with evidence attached to every rating. If you want, it then coaches you through a short, bounded loop so the tool and your own judgment improve together. It does not flatter the tool, fix it for you, or turn usefulness into one number.

Every tool is useful to the person who built it. That's the one audience it can't surprise. Worth Using judges the tool the way a stranger meets it.

This project pairs the [`worth-using` skill](skills/worth-using/SKILL.md) and its [rubric reference](skills/worth-using/references/rubric.md) with an explanatory static website that includes a ten-minute scorer. The [benchmark plan](docs/BENCHMARK.md) sets the bar the skill has to clear; it has not been run yet.

## First use

Bring a tool and one person it should help. Leave with six separate ratings, each tied to its evidence, and a practical gap to work on next.

```sh
git clone https://github.com/michaeljabbour/amplifier-capability-worth-using.git
cd amplifier-capability-worth-using
python3 scripts/capability.py install --dest ~/.agents/skills
```

Requires Git and Python 3.11+. Use the skills directory supported by your agent. Ask for Worth Using in a new session and supply one real task. The [install guide](docs/INSTALL.md) explains the complete ZIP alternative and safe updates.

## The rubric

Six criteria, each rated Missing, Partial, or Solid for one named user:

| Criterion | The question |
| --- | --- |
| Job | Who is it for, and what recurring job does it do for them? |
| First value | Can a stranger get one real result alone, in their first session? |
| Fit | Does it meet them where they already work, with what they already have? |
| Outcome | What is different for them afterwards, in their words? |
| Trust | When it's wrong, can they tell, and recover? |
| Return | Do they come back without being asked? |

Every rating carries its evidence: **Claimed** (the builder says so, or it was inferred from code, docs, or a demo), **Seen** (someone not on the team was observed using it, or reported a specific use with details), or **Repeated** (that person, or others like them, used it again without being asked, shown in logs or their own account). Evidence is never upgraded, and the six are never added up. A run of the tool by the builder, or by an agent working for them, stays Claimed; with artifacts it is labeled Claimed (walkthrough).

Two zones mark where to stop. **Stranger-ready**: Job, First value, Fit, Outcome, and Trust are Solid and at least Seen. **Worth using**: stranger-ready, plus Return is Solid and Repeated. Return usually takes days to show, so a session ends at stranger-ready with a return check: who, when, and what counts as coming back.

## The film

A 57-second film explains the idea with one fictional example: a meeting-summary bot everyone "loves," until a stranger feeds it an empty meeting. It plays on the [site](https://michaeljabbour.github.io/amplifier-capability-worth-using/#film) and lives at `site/assets/worth-using-film.mp4` with English captions.

## Use the skill

Give an agent the skill and the tool: a repo, a README, a demo, or a paragraph. Say who it's for. Then pick a mode:

- **Score** (about ten minutes). The rubric alone, for reviews and ship decisions. Ends with a usefulness card.
- **Coach** (bounded). An opening read of you, then five passes: Name the user, Watch the first ten minutes, Break it on purpose, Say what changed, Check for return. You rate first, predict first, and choose. Three rounds at most. Ends with a usefulness card and a growth card.

If your tool supports reusable skills, copy the `skills/worth-using/` directory (`SKILL.md` plus `references/`) according to that tool's instructions. Keep the relative `references/` path intact.

### For teams

Agree the user and the job in one sentence. Then everyone rates the six criteria alone, in writing, before anyone sees anyone else's. Reveal together. Where two ratings differ by two levels, each person gives one sentence of evidence. Don't average: record the spread, and take the rating backed by the strongest evidence someone can point to, the lower one if tied. The disagreements are the agenda for the next real user you watch.

### In Amplifier

This repository is also an Amplifier bundle (`worth-using`). Add its behavior to your current host:

```bash
amplifier bundle add "git+https://github.com/michaeljabbour/amplifier-capability-worth-using@main#subdirectory=behaviors/worth-using.yaml" --app
```

For a local checkout that stays in step with your edits, use `file:///<path-to-checkout>/behaviors/worth-using.yaml` instead. Remove with `amplifier bundle remove worth-using-behavior --app`. Start a new session, then:

- **Skill:** `/worth-using`, or ask for it by name. Nothing loads until it is used.
- **Mode:** `/useful` sets a reviewing posture for the session: verdict first, one question per turn, every file edit asks you first. `/mode off` leaves it.
- **Recipe:** `@worth-using:recipes/worth-using-round.yaml` runs one bounded coaching round that pauses for your answers at each gate, then writes a usefulness card and a growth card to `.worth-using/` in your working directory. It never edits your tool.

The skill is registered through `tool-skills`. If no other bundle in your host configures skill sources, Amplifier stops scanning its default skill directories (`.amplifier/skills` in the workspace and `~/.amplifier/skills`); add them to your own skills configuration if you need them. Don't also keep a hand-copied `worth-using` in `~/.amplifier/skills`, or two copies will compete.

Example requests:

> Use worth-using to score this CLI for core-facility staff who check sample sheets every Monday. Score only. Tell me where a stranger stalls.

> Three of us are reviewing this bot before we ship it wider. Use worth-using in team mode: collect our ratings separately first, then show the spread.

> People try this once and never come back. Use worth-using to coach me. I want to see where my own judgment is off, not just the tool.

See [a worked example](docs/EXAMPLES.md), dips included.

## Local development

The site follows the family's small Python static-builder approach: HTML, CSS, and JavaScript with no backend or runtime dependencies. Use Python 3.11 or later; no package installation is required.

From the project directory:

```sh
python3 scripts/build.py
python3 scripts/check.py
node --check site/site.js   # optional JavaScript syntax check; needs Node.js
python3 -m http.server 8000 --bind 127.0.0.1 --directory _site
```

Open <http://127.0.0.1:8000> in your browser. Stop the server with `Ctrl+C`. Re-run the build after source changes. `_site/` is generated output.

The build reads the criteria, evidence grades, opening questions, dimensions, teaching moves, and diagnosis rows straight from the rubric reference, and the benchmark rows from `docs/BENCHMARK.md`, so the page never forks the method. It also applies the zone rule to each fictional run. The check verifies local links and fragments, that the page and downloads match the canonical skill byte for byte, and the ZIP contents. See [site details](site/README.md).

The Pages workflow builds and checks `_site/` on pushes to `main`, then publishes only that static output. It uses GitHub's official actions pinned to fixed commits and needs no project secrets.

## Project contents

- `skills/worth-using/SKILL.md`: the method.
- `skills/worth-using/references/rubric.md`: the six criteria, evidence grades, zones, team scoring, opening questions, builder dimensions, teaching moves, diagnosis table, card templates, and voice examples.
- `skills/worth-using/references/delegated-runs.md`: walkthrough evidence, runs with nobody to ask, one card per user, round-to-round comparison, and pairing with a refinement skill.
- `skills/worth-using/references/usefulness-card.schema.json`: an optional machine-readable usefulness card, one per user, so successive rounds can be compared.
- `bundle.md`, `behaviors/worth-using.yaml`: the Amplifier bundle and its installable behavior.
- `modes/useful.md`: the `/useful` mode.
- `recipes/worth-using-round.yaml`: one staged, human-gated coaching round.
- `docs/EXAMPLES.md`: a fictional worked run with both cards.
- `docs/BENCHMARK.md`: the tests the skill has to pass. Not yet run.
- `scripts/build.py`, `scripts/check.py`: dependency-free build and integrity checks.
- `site/`: page template, metadata, styles, local assets, and interaction code.
- `_site/`: generated website and downloadable skill assets.

## Limits

This is a structured review and coaching aid, not a usability study, an analytics product, or a substitute for watching people use your tool. A usefulness card describes the evidence today; it does not forecast adoption. Builder placements describe one person on one tool on one day; two careful reviewers may disagree, and none of it measures talent. The site's scorer runs entirely in your browser and stores nothing. The examples on the site and in the docs are invented.

## License and provenance

MIT; see [LICENSE](LICENSE). The family theme snapshot keeps its own [MIT notice](site/theme/LICENSE). The page follows the Amplifier Smart Tools family site as a design and implementation reference.


## Portable capability and ownership

Find what helps a stranger, with proof behind every rating.

Read the [installation guide](docs/INSTALL.md) for the supported local path and [consolidation record](docs/CONSOLIDATION.md) for ownership and evidence limits. Canonical catalog name: **Worth Using**; repository: `amplifier-capability-worth-using`.

## Repository migration

This repository was renamed from `amplifier-skill-worth-using` to `amplifier-capability-worth-using`. Existing installed method names, bundle aliases and native interfaces stay the same. See the [migration guide](https://michaeljabbour.github.io/migration/) and [repository map](https://michaeljabbour.github.io/migration/mapping.json) for source URL updates.

## Delegated evaluation condition

The [delegated-v1 protocol](docs/DELEGATED-EVALUATION.md) freezes the skill, rubric, delegated guide and card schema together. Its preparation and canned offline transport checks run without provider calls; they are conformance evidence, not a behavioral result. Historical evaluation conditions and frozen records remain separate.
