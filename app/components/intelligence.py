"""Recruiter Intelligence metrics engine.

Pure computations over the dict rows fetched by components.db — no SQL,
no LLM — so the heuristics stay reusable by both the dashboard and the
AI assistant (components.generators). Scores are 0..1 unless stated
otherwise; they are heuristics, not statistical predictions.
"""

from datetime import date, datetime

from components import db
from components.db import PROCESS_STAGES

GHOSTING_THRESHOLD_DAYS = 7   # outbound without reply for this long = ghosted
STALE_THRESHOLD_DAYS = 21      # active process with no interaction for this long

# Forward pipeline: Rejeté is a terminal outcome, not a progress step.
FORWARD_STAGES = [s for s in PROCESS_STAGES if s != "Rejeté"]


def _to_date(value):
    """Coerce a DATE/TIMESTAMP/ISO-string column value to date, or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _days_between(a, b):
    if a is None or b is None:
        return None
    return (b - a).days


def stage_progress(stage):
    """Progress through the pipeline: 0.0 (Prospect) → 1.0 (Accepté)."""
    if stage not in FORWARD_STAGES:
        return 0.0
    return FORWARD_STAGES.index(stage) / (len(FORWARD_STAGES) - 1)


def _sorted_interactions(interactions):
    """Interactions oldest-first, tolerant of missing dates."""
    return sorted(
        (i for i in interactions if _to_date(i.get("interaction_date"))),
        key=lambda i: _to_date(i["interaction_date"]),
    )


def _response_gaps(interactions):
    """Days between consecutive interactions (response-time signal)."""
    dates = [_to_date(i["interaction_date"]) for i in interactions]
    return [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days >= 0]


def _avg_response_days(interactions):
    gaps = _response_gaps(_sorted_interactions(interactions))
    if not gaps:
        return None
    return sum(gaps) / len(gaps)


def _skills_overlap(company_techs, profile_skills):
    """Share of the company's stack the candidate masters (case-insensitive)."""
    techs = {(t or "").strip().lower() for t in (company_techs or []) if (t or "").strip()}
    if not techs:
        return None
    skills = {(s or "").strip().lower() for s in (profile_skills or []) if (s or "").strip()}
    return len(techs & skills) / len(techs)


def compatibility_score(company, profile):
    """Heuristic profile↔company fit: stack overlap + remote policy match."""
    score = 0.0
    parts = 0
    overlap = _skills_overlap(company.get("technologies"), profile.get("skills"))
    if overlap is not None:
        score += overlap * 0.7
        parts += 1
    policy = (company.get("remote_policy") or "").lower()
    pref = (profile.get("remote_preference") or "").lower()
    if policy and pref:
        score += 0.3 if (pref in policy or policy in pref or "remote" in policy) else 0.1
        parts += 1
    return score / parts if parts else 0.0


def mission_score(process):
    """Completeness of the mission brief: mission, client, salary, stack."""
    checks = [
        bool((process.get("mission") or "").strip()),
        bool((process.get("client") or "").strip()),
        bool(process.get("expected_salary")),
        bool(process.get("technologies")),
    ]
    return sum(checks) / len(checks)


def talent_pool_probability(process, interactions):
    """Heuristic: is this process probably just a CV vivier (talent pool)?"""
    p_type = process.get("recruitment_type") or ""
    if p_type == "Vivier":
        return 0.8
    prob = 0.0
    if p_type in ("Opportunité future", "Pré-vente", "Accord-cadre"):
        prob += 0.3
    if stage_progress(process.get("stage")) < 0.3:  # still pre-interview
        prob += 0.2
    ordered = _sorted_interactions(interactions)
    if ordered:
        days = _days_between(_to_date(ordered[-1]["interaction_date"]), date.today())
        if days is not None and days > STALE_THRESHOLD_DAYS:
            prob += 0.2
    if mission_score(process) < 0.5:  # vague brief = no real mission behind
        prob += 0.2
    return min(1.0, prob)


def mission_fit(process, interactions, company, profile):
    """Heuristic fit between this mission and the candidate's profile.

    Blend of profile↔company compatibility (stack/remote) and the
    completeness of the mission brief, reduced by talent-pool risk.
    Returns (score 0..1, factor list).
    """
    compat = compatibility_score(company or {}, profile or {})
    mscore = mission_score(process)
    pool = talent_pool_probability(process, interactions)
    score = (0.5 * compat + 0.5 * mscore) * (1 - 0.3 * pool)
    techs = (company or {}).get("technologies") or []
    factors = [
        f"Compatibilité profil ↔ ESN (stack{' non renseignée' if not techs else ''}, remote) : {compat:.0%} — poids 50%",
        f"Complétude du dossier mission (mission, client, salaire, stack) : {mscore:.0%} — poids 50%",
        f"Risque vivier : {pool:.0%}" + (" — malus 30%" if pool >= 0.5 else ""),
    ]
    return score, factors


def offer_probability(process, interactions):
    """Heuristic probability of receiving an offer, from stage + velocity."""
    stage = process.get("stage")
    if stage == "Accepté":
        return 1.0
    if stage == "Offre":
        return 1.0
    if stage == "Rejeté" or process.get("status") in ("Abandonné", "Conclu"):
        return 0.0
    prob = 0.15 + 0.7 * stage_progress(stage)
    ordered = _sorted_interactions(interactions)
    if not ordered:
        prob -= 0.05
    else:
        days = _days_between(_to_date(ordered[-1]["interaction_date"]), date.today())
        if days is not None:
            if days <= 14:
                prob += 0.05
            elif days > 30:
                prob -= 0.15
        avg_resp = _avg_response_days(interactions)
        if avg_resp is not None and avg_resp <= 5:
            prob += 0.05
    r_type = process.get("recruitment_type") or ""
    if r_type == "Vivier":
        prob *= 0.5
    elif r_type == "Mission existante":
        prob = min(1.0, prob + 0.05)
    return max(0.0, min(1.0, prob))


def offer_probability_factors(process, interactions):
    """(score, factor list) — mirrors offer_probability, explaining it."""
    score = offer_probability(process, interactions)
    factors = [
        f"Étape : {process.get('stage')} (avancement {stage_progress(process.get('stage')):.0%})"
    ]
    ordered = _sorted_interactions(interactions)
    if ordered:
        days = _days_between(_to_date(ordered[-1]["interaction_date"]), date.today())
        if days is not None:
            mark = "(+)" if days <= 14 else "(−)" if days > 30 else ""
            factors.append(f"Dernière interaction il y a {days} jours {mark}")
        avg = _avg_response_days(interactions)
        if avg is not None:
            factors.append(f"Délai de réponse moyen : {avg:.1f} j {'(+)' if avg <= 5 else ''}")
    else:
        factors.append("Aucune interaction enregistrée (−)")
    r_type = process.get("recruitment_type")
    if r_type == "Vivier":
        factors.append("Type de recrutement : Vivier (×0,5)")
    elif r_type == "Mission existante":
        factors.append("Type de recrutement : Mission existante (+)")
    return score, factors


def contact_metrics(contact, interactions):
    """Recruiter reliability + ghosting detection for one contact."""
    ordered = _sorted_interactions(interactions)
    last_inbound = last_outbound = None
    for i in reversed(ordered):
        direction = i.get("direction")
        if last_inbound is None and direction == "reçu":
            last_inbound = _to_date(i["interaction_date"])
        if last_outbound is None and direction == "envoyé":
            last_outbound = _to_date(i["interaction_date"])
        if last_inbound and last_outbound:
            break
    today = date.today()
    # Ghosted: our last message got no reply for over the threshold.
    ghosted = False
    days_unanswered = None
    if last_outbound is not None and (
        last_inbound is None or last_outbound > last_inbound
    ):
        days_unanswered = _days_between(last_outbound, today)
        ghosted = days_unanswered is not None and days_unanswered > GHOSTING_THRESHOLD_DAYS
    avg_resp = _avg_response_days(interactions)
    # Reliability heuristic: responsiveness + volume.
    reliability = 0.5
    if avg_resp is not None:
        reliability += max(0.0, 0.3 - 0.05 * avg_resp)
    reliability += min(0.2, 0.05 * len(ordered))
    if ghosted:
        reliability *= 0.4
    last_date = _to_date(ordered[-1]["interaction_date"]) if ordered else None
    comm_factors = [f"{len(ordered)} interactions enregistrées"]
    if avg_resp is not None:
        comm_factors.append(
            f"Délai de réponse moyen : {avg_resp:.1f} j {'(+)' if avg_resp <= 5 else ''}"
        )
    if ghosted:
        comm_factors.append(f"Sans réponse depuis {days_unanswered} jours — ghosting (malus)")
    else:
        comm_factors.append("Aucun message resté sans réponse")
    rel = round(max(0.0, min(1.0, reliability)), 2)
    return {
        "interaction_count": len(interactions),
        "last_interaction": last_date.isoformat() if last_date else None,
        "days_since_last": _days_between(last_date, today),
        "avg_response_days": round(avg_resp, 1) if avg_resp is not None else None,
        "ghosted": ghosted,
        "days_unanswered": days_unanswered,
        "reliability": rel,
        "communication_score": rel,
        "communication_score_auto": rel,
        "communication_score_mode": "auto",
        "communication_factors": comm_factors,
    }


def process_metrics(process, interactions, company=None, profile=None):
    """Per-process derived signals (probability, mission fit, velocity).

    Objective metrics expose <key>, <key>_auto, <key>_mode, <key>_factors;
    build_snapshot replaces the effective value when a manual override
    exists (mode switches to 'manual' and stays locked until deleted).
    """
    ordered = _sorted_interactions(interactions)
    last = _to_date(ordered[-1]["interaction_date"]) if ordered else None
    avg_resp = _avg_response_days(interactions)
    op, op_factors = offer_probability_factors(process, interactions)
    mf, mf_factors = mission_fit(process, interactions, company, profile or {})
    return {
        "stage_progress": round(stage_progress(process.get("stage")), 2),
        "offer_probability": round(op, 2),
        "offer_probability_auto": round(op, 2),
        "offer_probability_mode": "auto",
        "offer_probability_factors": op_factors,
        "mission_fit": round(mf, 2),
        "mission_fit_auto": round(mf, 2),
        "mission_fit_mode": "auto",
        "mission_fit_factors": mf_factors,
        "talent_pool_probability": round(talent_pool_probability(process, interactions), 2),
        "mission_score": round(mission_score(process), 2),
        "interaction_count": len(interactions),
        "last_interaction": last.isoformat() if last else None,
        "days_since_last": _days_between(last, date.today()),
        "avg_response_days": round(avg_resp, 1) if avg_resp is not None else None,
    }


def company_metrics(company, processes, interactions, profile):
    """Aggregated signal for one ESN across all its processes."""
    active = [p for p in processes if p.get("status") == "Actif"]
    offers = [p for p in processes if p.get("stage") in ("Offre", "Accepté")]
    rejected = [p for p in processes if p.get("stage") == "Rejeté"]
    interviewed = [p for p in processes if stage_progress(p.get("stage")) >= 0.25]
    # Ghosting: share of our outbound messages that never got a reply.
    outbound = [i for i in interactions if i.get("direction") == "envoyé"]
    answered = 0
    for out in outbound:
        out_date = _to_date(out.get("interaction_date")) or date.min
        if any(
            i.get("direction") in ("reçu", "mutuel")
            and (_to_date(i.get("interaction_date")) or date.min) >= out_date
            for i in interactions
        ):
            answered += 1
    avg_resp = _avg_response_days(interactions)
    avg_prob = None
    if active:
        avg_prob = sum(offer_probability(p, interactions) for p in active) / len(active)
    return {
        "process_count": len(processes),
        "active_count": len(active),
        "offer_count": len(offers),
        "rejected_count": len(rejected),
        "interview_conversion": (
            round(len(interviewed) / len(processes), 2) if processes else None
        ),
        "avg_response_days": round(avg_resp, 1) if avg_resp is not None else None,
        "ghosting_score": (
            round(1 - answered / len(outbound), 2) if outbound else None
        ),
        "avg_offer_probability": round(avg_prob, 2) if avg_prob is not None else None,
        "compatibility": round(compatibility_score(company, profile), 2),
    }


def _company_name(companies, company_id):
    for c in companies:
        if c["company_id"] == company_id:
            return c["name"]
    return None


def _apply_objective_override(metrics, key, override):
    """Lock an objective metric to its manual value (until switch back).

    The companion <key>_factors stay those of the automatic heuristic so
    the user can still see what the AI would say, and <key>_auto keeps the
    live automatic value for reference.
    """
    if override is None or override.get("value") is None:
        return
    metrics[key] = round(float(override["value"]) / 100.0, 2)
    metrics[f"{key}_mode"] = "manual"
    metrics[f"{key}_manual_at"] = str(override.get("updated_at") or "")[:10]


def _subjective_metrics(overrides):
    """User-owned company metrics — values exist only if the user set them."""
    out = {}
    for key in ("attractiveness", "interest_level", "priority"):
        o = overrides.get(key)
        out[key] = (
            round(float(o["value"]) / 100.0, 2) if o and o.get("value") is not None else None
        )
        out[f"{key}_rationale"] = o.get("rationale") if o else None
        out[f"{key}_at"] = str(o.get("updated_at"))[:10] if o else None
    notes = overrides.get("personal_notes")
    out["personal_notes"] = notes.get("value_text") if notes else None
    out["personal_notes_at"] = str(notes.get("updated_at"))[:10] if notes else None
    return out


def build_snapshot(user_id, profile):
    """Fetch every recruiting entity + attach all derived metrics and alerts.

    Single entry point for the dashboard and the AI assistant so both see
    exactly the same numbers.
    """
    companies = db.list_consulting_companies(user_id)
    contacts = db.list_contacts(user_id)
    processes = db.list_processes(user_id)
    interactions = db.list_interactions(user_id)
    overrides = db.list_metric_overrides(user_id)

    ovr_idx = {}
    for o in overrides:
        ovr_idx[(o["entity_type"], o["entity_id"], o["metric_key"])] = o
    company_by_id = {c["company_id"]: c for c in companies}

    today = date.today()
    by_company = {}
    for p in processes:
        by_company.setdefault(p["company_id"], []).append(p)
    by_process = {}
    by_contact = {}
    for i in interactions:
        if i.get("process_id"):
            by_process.setdefault(i["process_id"], []).append(i)
        if i.get("contact_id"):
            by_contact.setdefault(i["contact_id"], []).append(i)

    enriched_processes = []
    alerts = []
    for p in processes:
        p_ints = by_process.get(p["process_id"], [])
        metrics = process_metrics(
            p, p_ints, company_by_id.get(p["company_id"]), profile
        )
        _apply_objective_override(
            metrics, "offer_probability",
            ovr_idx.get(("process", p["process_id"], "offer_probability")),
        )
        _apply_objective_override(
            metrics, "mission_fit",
            ovr_idx.get(("process", p["process_id"], "mission_fit")),
        )
        name = _company_name(companies, p["company_id"])
        enriched_processes.append({**p, "company_name": name, "metrics": metrics})
        if p.get("status") == "Actif":
            nf = _to_date(p.get("next_followup"))
            if nf and nf <= today:
                alerts.append({
                    "kind": "relance",
                    "process_id": p["process_id"],
                    "company": name,
                    "detail": f"Relance prévue le {nf.isoformat()} — {p.get('stage')}",
                })
            elif (
                metrics["days_since_last"] is not None
                and metrics["days_since_last"] > STALE_THRESHOLD_DAYS
            ):
                alerts.append({
                    "kind": "silence",
                    "process_id": p["process_id"],
                    "company": name,
                    "detail": (
                        f"Aucune interaction depuis {metrics['days_since_last']} jours "
                        f"({p.get('stage')})"
                    ),
                })

    enriched_contacts = []
    for c in contacts:
        metrics = contact_metrics(c, by_contact.get(c["contact_id"], []))
        _apply_objective_override(
            metrics, "communication_score",
            ovr_idx.get(("contact", c["contact_id"], "communication_score")),
        )
        name = _company_name(companies, c["company_id"])
        enriched_contacts.append({**c, "company_name": name, "metrics": metrics})
        if metrics["ghosted"]:
            alerts.append({
                "kind": "ghosting",
                "contact_id": c["contact_id"],
                "company": name,
                "detail": f"{c['name']} n'a pas répondu depuis {metrics['days_unanswered']} jours",
            })

    enriched_companies = []
    for c in companies:
        c_processes = by_company.get(c["company_id"], [])
        c_ids = {p["process_id"] for p in c_processes}
        c_contacts = {
            ct["contact_id"] for ct in contacts if ct["company_id"] == c["company_id"]
        }
        c_ints = [
            i for i in interactions
            if i.get("process_id") in c_ids or i.get("contact_id") in c_contacts
        ]
        c_metrics = company_metrics(c, c_processes, c_ints, profile)
        c_metrics.update(_subjective_metrics({
            k: v for (et, eid, k), v in ovr_idx.items()
            if et == "company" and eid == c["company_id"]
        }))
        enriched_companies.append({**c, "metrics": c_metrics})

    interviewed = [p for p in processes if stage_progress(p.get("stage")) >= 0.25]
    offers = [p for p in processes if p.get("stage") in ("Offre", "Accepté")]
    summary = {
        "companies": len(companies),
        "contacts": len(contacts),
        "processes": len(processes),
        "active": sum(1 for p in processes if p.get("status") == "Actif"),
        "offers": len(offers),
        "rejected": sum(1 for p in processes if p.get("stage") == "Rejeté"),
        "interview_conversion": (
            round(len(interviewed) / len(processes), 2) if processes else None
        ),
        "offer_conversion": (
            round(len(offers) / len(interviewed), 2) if interviewed else None
        ),
        "stage_distribution": {
            stage: sum(1 for p in processes if p.get("stage") == stage)
            for stage in PROCESS_STAGES
        },
        "rejection_comments": [
            (p.get("comments") or "").strip()
            for p in processes
            if p.get("stage") == "Rejeté" and (p.get("comments") or "").strip()
        ],
    }

    return {
        "as_of": today.isoformat(),
        "companies": enriched_companies,
        "contacts": enriched_contacts,
        "processes": enriched_processes,
        "interactions": interactions,
        "alerts": alerts,
        "summary": summary,
    }
