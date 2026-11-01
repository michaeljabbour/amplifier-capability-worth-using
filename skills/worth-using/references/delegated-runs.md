# Delegated and repeated runs

Read this when nobody can answer your questions, when you score the same tool round after round, or when a harness needs a card it can compare. The rules in SKILL.md and rubric.md still hold; this only says how to keep them without a builder in the room.

## Walkthrough evidence

A Claimed rating names what it rests on: the builder's word, a reading (code, docs, or a demo), or a walkthrough. A walkthrough is a run of the real tool by the builder or by an agent working for them, following only what a stranger would have, with artifacts someone else can open: screenshots, transcripts, logs. Write it "Claimed (walkthrough: first-run.png, session.log)".

It is the strongest Claimed, and still Claimed. Whoever ran it is on the team, so it never becomes Seen and never counts toward a zone. What it adds is movement a reading cannot show: a round that fixes a stall can take First value from Partial to Solid at Claimed (walkthrough), with the artifacts to check. Only someone outside the team moves the grade.

For an interface, capture the same states each round, for example a first visit with no data, a normal session, and an error, at the screen sizes the user actually has. A walkthrough that changes its conditions between rounds cannot show movement.

## When nobody can answer

- State each assumption in one line and label it Assumed: the user, the job, the cost, the target. An assumed user is still one specific person in a setting.
- Never write the builder's sentences for them: the job sentence, the outcome in their words, opening answers, or the reason behind a keep. Mark each "awaiting builder". A gate that needs one is not met.
- Propose keeps and cuts; do not log them as the builder's choices.
- Skip the growth card. It describes a builder you did not observe; say so on the usefulness card.
- Return the questions you would have asked, one line each, most decisive first, with the card.

## Several users

One card per named user. When a tool serves several users or roles, score each separately with its own job and evidence. Never merge or average their ratings; a criterion can be Solid for one and Missing for another, and that difference is a finding.

## Round after round

- Compare cards for the same tool and user, round against round. Never rewrite an earlier card; a drop stays on the record.
- Pick the next thing to improve: the criterion blocking the target zone with the lowest rating, then the weakest evidence, then the earliest in the list, since later criteria rest on earlier ones.
- Fix it at the pass the diagnosis table names, then rescore from a fresh walkthrough, not from the change you just made.
- If a round moves nothing, stop. The usual cause is upstream, as SKILL.md says.
- Stopping at stranger-ready needs Seen. An unattended loop can reach "Solid, Claimed (walkthrough)" on every criterion and still not be stranger-ready. Say so, and name who should try it next.

## Pairing with a refinement skill

This rubric decides what to improve: the weakest criterion, for one named user. A refinement or craft skill decides how to make that change well. Run this one first, hand over the criterion, the user, and the evidence, then rescore after the change. Polish that serves no blocking criterion still waits until stranger-ready.

## A card another agent can compare

When a harness or another agent will store or compare cards, write each card to [usefulness-card.schema.json](usefulness-card.schema.json) as well as in words. It carries the same fields as the card template, plus the claimed basis, artifact references, assumptions, and returned questions. It refuses a zone the ratings and evidence do not support, and Seen or Repeated without a named record. Validation is conformance, not evidence that the tool is useful.
