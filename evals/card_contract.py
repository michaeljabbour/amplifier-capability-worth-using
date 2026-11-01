"""Cross-field and supplied-record checks for usefulness-card/v1.

JSON Schema checks structure. These checks cover relationships that ordinary JSON
Schema cannot compare. Record metadata is supplied evidence, not a verification
that a real person used a real tool; this module reads no links and makes no calls.
"""
from __future__ import annotations

from datetime import date

CRITERIA = ("Job", "First value", "Fit", "Outcome", "Trust", "Return")


def _positive_integer(value):
    return type(value) is int and value >= 1


def semantic_errors(card, records=None, previous=None):
    """Return errors without modifying the card or its evidence records."""
    errors = []
    if not isinstance(card, dict):
        return ["Card must be an object"]
    round_ = card.get("round", {})
    if not isinstance(round_, dict):
        return ["round must be an object"]
    mode, index, budget = (round_.get(k) for k in ("mode", "index", "budget"))
    if mode not in ("score", "coach"):
        errors.append("round.mode must be score or coach")
    if not _positive_integer(index):
        errors.append("round.index must be a positive integer, not a boolean")
    if mode == "score" and budget is not None:
        errors.append("Score cards require a null round.budget")
    if mode == "coach":
        if not _positive_integer(budget):
            errors.append("Coach cards require an explicit positive integer round.budget")
        elif _positive_integer(index) and index > budget:
            errors.append("round.index exceeds the agreed round.budget")
    try:
        value = card.get("date", "")
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (TypeError, ValueError):
        errors.append("date must be a real ISO calendar date")
    if previous is not None:
        if not isinstance(previous, dict):
            errors.append("Previous card must be an object")
        else:
            previous_user, previous_round = previous.get("user"), previous.get("round")
            current_user = card.get("user")
            if card.get("previous_card_id") != previous.get("card_id"):
                errors.append("previous_card_id does not identify the supplied previous card")
            if not isinstance(previous_user, dict) or not isinstance(current_user, dict):
                errors.append("Current and previous user must be objects")
            elif (card.get("tool"), current_user.get("id")) != (previous.get("tool"), previous_user.get("id")):
                errors.append("Previous card must describe the same tool and user.id")
            if not isinstance(previous_round, dict) or not _positive_integer(previous_round.get("index")):
                errors.append("Previous round.index must be a positive integer")
            elif _positive_integer(index) and index <= previous_round["index"]:
                errors.append("A later card must have a later round.index")
    records = records or {}
    if not isinstance(records, dict):
        return errors + ["Evidence records must be an object keyed by reference"]
    user = card.get("user", {})
    if not isinstance(user, dict):
        return errors + ["user must be an object"]
    criteria = card.get("criteria", {})
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        return errors + ["criteria must contain exactly the six independent criteria"]
    for name, criterion in criteria.items():
        if not isinstance(criterion, dict):
            errors.append(name + ": criterion must be an object")
            continue
        grade = criterion.get("evidence")
        refs = criterion.get("evidence_refs", [])
        if not isinstance(refs, list):
            errors.append(name + ": evidence_refs must be a list")
            continue
        if grade not in ("Seen", "Repeated"):
            continue
        matching = []
        for ref in refs:
            record = records.get(ref, {}) if isinstance(ref, str) else {}
            if not isinstance(record, dict):
                continue
            try:
                dated = date.fromisoformat(record.get("date", "")).isoformat() == record.get("date")
            except (ValueError, TypeError):
                dated = False
            supported = record.get("criteria", [])
            if (record.get("actor") == "outside" and record.get("observed_use") is True
                    and record.get("user_id") == user.get("id")
                    and isinstance(supported, list) and name in supported and dated
                    and isinstance(record.get("detail"), str) and record["detail"].strip()):
                matching.append(record)
        if not matching:
            errors.append(name + ": " + str(grade) + " needs a matching dated record of specific outside-team use")
        elif grade == "Repeated" and not any(r.get("unprompted_return") is True for r in matching):
            errors.append(name + ": Repeated needs recorded unprompted return")
    ready = all(criteria[c].get("rating") == "Solid" and criteria[c].get("evidence") in ("Seen", "Repeated") for c in CRITERIA[:5] if isinstance(criteria[c], dict))
    ready = ready and all(isinstance(criteria[c], dict) for c in CRITERIA[:5])
    returned = ready and criteria["Return"].get("rating") == "Solid" and criteria["Return"].get("evidence") == "Repeated" if isinstance(criteria["Return"], dict) else False
    zone = card.get("zone", {})
    if isinstance(zone, dict):
        if zone.get("stranger_ready") != ("met" if ready else "not-met"):
            errors.append("zone.stranger_ready contradicts the independent criteria")
        if zone.get("worth_using") != ("met" if returned else "not-met"):
            errors.append("zone.worth_using contradicts ratings or unprompted-return evidence")
        if zone.get("stranger_ready") == zone.get("worth_using") == "met" and zone.get("holding_back"):
            errors.append("zone.holding_back must be empty when both zones are met")
    return errors
