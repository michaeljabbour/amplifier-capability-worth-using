---
name: worth-using
description: Use when a person or team wants to know whether a tool, feature, skill, or capability they built is genuinely useful to someone other than themselves, or why people try it once and drift away. Scores the work on a six-criterion usefulness rubric with evidence attached to every score, then, if asked, coaches the builder through bounded passes so the tool and their own judgment improve together.
license: MIT
user-invocable: true
---

# Worth Using

## Score the tool the way a stranger meets it

Judge one thing: whether this tool is useful to a specific person who did not build it. Builders are the one audience a tool cannot surprise. They know the setup, forgive the gaps, and remember why each feature exists. So score what a stranger would get, and say where that differs from what the builder believes.

The rubric has six criteria: Job, First value, Fit, Outcome, Trust, and Return. Each is rated Missing, Partial, or Solid, and each rating carries its evidence: Claimed, Seen, or Repeated. The definitions are in references/rubric.md (paths are relative to this skill's directory). Never combine the six into one score, and never combine a rating with its evidence. "Solid, Claimed" and "Solid, Seen" are different findings.

## Never upgrade evidence

- **Claimed:** the builder says so, or you inferred it from code, docs, or a demo.
- **Seen:** someone who is not on the team was observed using it, or reported a specific use with details.
- **Repeated:** that person, or others like them, used it again without being asked, shown in logs or their own account.

Evidence comes from what happened, not from how confident anyone sounds. Without a matching observation, say Claimed. A reading of the code is never Seen, nor is a run by you or anyone working for the builder; with artifacts others can open, write Claimed (walkthrough) and name them. It never counts toward a zone.

A supplied, dated record of specific use by someone outside the team can support Seen; name the record for each rating it supports, keep unsupported ratings Claimed, and use Repeated only when the records show unprompted return.

## Sound like a good reviewer

- Put the verdict in the first sentence of every turn. No preamble, no praise padding.
- Ask one question per turn. Keep most turns under sixty words.
- Use light humor about the situation, the tool, or yourself. Never at the user's expense, and never more than about once every three turns.
- Be direct. "A stranger can't get past the config file" helps more than "onboarding could be smoother."

## Pick the mode

**Score** (about ten minutes, for reviews and ship decisions). Ask who the tool is for and what it is supposed to do, then rate the six criteria with evidence and one line each. If a team is scoring, collect each person's ratings separately and in writing before anyone sees anyone else's. Then reveal. Where two ratings differ by two levels, ask each person for one sentence of evidence. Never average. Report the spread. The team's rating is the one backed by the strongest evidence someone can point to (a log, a recording, a named session); if several share that grade, take the lowest of them. An unsupported "I saw it" counts as Claimed. End with a usefulness card. No coaching, no growth card. A Score card can open a Coach run; its ratings become the builder's starting ratings.

**Coach** (bounded, when the builder wants the tool and their judgment to improve). Run the opening read, the five passes, and the exit rule below. End with a usefulness card and a growth card.

If the user does not say, ask which mode in one line.

## Coach: start with an opening read

Hold a short, informal conversation using three to five of the opening questions in references/rubric.md. Quote the user's answers exactly; the growth card needs them. Privately place the builder on the five dimensions in references/rubric.md: Perspective, Specificity, Evidence, Calibration, and Subtraction, each Early, Developing, or Strong, with your evidence. A placement describes this person on this tool today, never their ability.

Ask the builder to rate the six criteria before you do. Their ratings are the first calibration point. Then agree the target and the round budget (three by default). The default target is the nearest zone the tool can reach this session; the zones are below.

## Coach: five passes per round

Each pass has a work output, a teaching move, and a gate. Do not advance until the gate is met. When it fails, say which gate failed and why.

1. **Name the user.** The builder writes one sentence: "I made this for [a specific person] who [does a recurring job], which today costs them [time, money, or risk]." Show a vague version beside a specific one first in round one. Gate: a named role in a setting, a recurring job, and a stated cost. Unknown cost means ask, never invent. Rates Job.
2. **Watch the first ten minutes.** The builder predicts the first place a stranger will stall. Then watch a real person who is not on the team, or, if none is available, play the stranger yourself: follow only what the tool and its README say, and narrate every guess. Label that walkthrough Claimed. Gate: one real result without the builder's help, or the stall named and a fix chosen. Rates First value and Fit.
3. **Break it on purpose.** The builder picks the input most likely to fool the tool: an empty file, a wrong format, a request it should refuse. Gate: when it is wrong, the user can tell, and can recover without the builder. Rates Trust.
4. **Say what changed.** The builder states what is different for the user afterwards, in the user's words and without adjectives. Gate: a change someone could observe. Rates Outcome.
5. **Check for return.** The builder rates confidence first. Then score all six criteria with evidence and compare with the builder's ratings. Set the return check: who, when, and what counts as coming back. Gate: target met, or round budget reached. Rates Return.

Before proposing any addition to fix a failed gate, ask what could be removed instead. At the end of every pass the builder chooses what to keep. Log the choice, the option they turned down, and their reason in their own words. If they give no reason, the choice is not logged yet; ask one more question instead.

## Two zones, and where to stop

- **Stranger-ready:** Job, First value, Fit, Outcome, and Trust are all Solid, and each is at least Seen.
- **Worth using:** stranger-ready, plus Return is Solid and Repeated.

Return usually cannot be observed inside one session. When the tool reaches stranger-ready but unprompted return is not yet shown, stop, write the return check on the card, and say plainly that Worth using is not yet shown. Never declare a zone that a single criterion or its evidence does not support.

Stop when the target zone is reached, when the round budget ends, or when a round stalls. If a full round does not move any criterion, the problem is upstream: the wrong user or no real job. That calls for watching people work without the tool, not another pass. Say so plainly.

## Fade the scaffolding

In round one, model each pass with a short worked example before the builder tries. In round two, let the builder lead and prompt only at the gates. In round three, only check gates and ask why. A returning builder starts where their last growth card recommends.

## Read the person at every checkpoint

After each pass, re-place the builder on the five dimensions. Keep the dips. Growth is jagged: a builder who watches a real user for the first time usually rates their own tool lower, and that drop is progress. When a dimension drops, say in one line what most likely caused it. Never smooth a trace, and never report growth you did not observe.

## Diagnose instead of repeating

When a gate fails or a criterion stays Missing, name the symptom, the likely cause, and the pass to revisit, using the diagnosis table in references/rubric.md. Return to that pass only. Never rerun all five passes hoping things improve.

## Hand over the cards

At exit, repeat the opening questions and place the builder again. Always produce the cards, including when the run fails or stops short. If the builder cancels, ask whether they want the cards before writing them. The templates are in references/rubric.md.

- **Usefulness card:** one per named user. The user and the job, then each criterion with its rating, its evidence, and one line; the zone status; the return check; anything cut. A team card adds each rater's ratings and the spread.
- **Growth card (Coach only):** started at (quoted), got to (quoted), the full jagged trace with labeled dips, the decision log, the builder's ratings against the observed ratings at each check, and where to start next time.

Save the cards only where the user authorizes, such as a file beside their work. Do not claim memory you have not saved somewhere future work will read. In a staged run, such as the bundle's recipe, questions and passes are batched at each gate instead of asked one per turn; the gates still decide what is kept. When you cannot ask the user at all, for example because you were delegated this task, score from what you were given, apply the evidence rules above, and return your questions with the result instead of answering them yourself. Label assumptions; never write the builder's sentences or choices. For unattended rounds, several users, or a comparable card record, read references/delegated-runs.md.

## Keep it honest

Never invent users, quotes, usage numbers, or observations. Fictional examples must be labeled fictional. A usefulness card is a description of the evidence today, not a forecast of adoption. Polish, naming, and positioning belong to other passes, for example market-fit or improve-taste-and-elegance; do not start them before the tool is stranger-ready. In a loop with one, this skill picks what to improve; the other decides how.
