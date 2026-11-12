"""LLM document generators for the career workspace.

All calls go through the Unity Gateway Chat Completions API (same pattern as
components/resume.py). Each generator returns Markdown text ready to be
displayed in the app and persisted in the documents table.
"""

import re

import requests

from components.auth import get_host_and_token

LLM_MODEL = "system.ai.meta-llama-3-3-70b-instruct"


def _llm(system: str, user: str, temperature: float = 0.4) -> str:
    """One Gateway chat completion, cleaned of code fences."""
    host, token = get_host_and_token()
    resp = requests.post(
        f"{host}/ai-gateway/mlflow/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        },
        timeout=180,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return re.sub(r"```(?:markdown)?", "", content).strip()


def _profile_text(profile: dict) -> str:
    """Flatten the structured profile into text the LLM can reason on."""
    lines = []
    if profile.get("name"):
        lines.append(f"Nom : {profile['name']}")
    if profile.get("current_title"):
        lines.append(f"Titre actuel : {profile['current_title']}")
    if profile.get("experience"):
        lines.append(f"Expérience : {profile['experience']}")
    if profile.get("location"):
        lines.append(f"Localisation : {profile['location']}")
    if profile.get("phone"):
        lines.append(f"Téléphone : {profile['phone']}")
    if profile.get("summary"):
        lines.append(f"Résumé : {profile['summary']}")
    if profile.get("motivations"):
        lines.append(f"Motivations : {profile['motivations']}")
    if profile.get("skills"):
        lines.append(f"Compétences techniques : {', '.join(profile['skills'])}")
    if profile.get("soft_skills"):
        lines.append(f"Soft skills : {', '.join(profile['soft_skills'])}")
    if profile.get("languages"):
        langs = ", ".join(
            f"{l.get('name')} ({l.get('level')})" for l in profile["languages"] if l.get("name")
        )
        lines.append(f"Langues : {langs}")
    for exp in profile.get("experiences") or []:
        lines.append(
            f"- Expérience : {exp.get('title')} chez {exp.get('company')} "
            f"({exp.get('start_date')}–{exp.get('end_date')}) : {exp.get('description')}"
        )
    for edu in profile.get("education") or []:
        lines.append(f"- Formation : {edu.get('degree')}, {edu.get('school')} ({edu.get('year')})")
    for cert in profile.get("certifications") or []:
        lines.append(f"- Certification : {cert.get('name')} — {cert.get('issuer')} ({cert.get('year')})")
    return "\n".join(lines) or "Profil vide."


def generate_tailored_cv(profile: dict, job_title: str, job_description: str = "") -> str:
    """A tailored CV (Markdown) for a target position."""
    system = (
        "Tu es un expert de la rédaction de CV à la française. Tu rédiges un CV "
        "en Markdown, clair et professionnel, adapté à l'offre visée. Structure : "
        "# Prénom NOM, titre recherché, coordonnées ; ## Profil ; ## Expériences "
        "professionnelles (puces à l'action, orientées résultats) ; ## Formation ; "
        "## Compétences (regroupées) ; ## Langues ; ## Certifications. "
        "N'invente aucune expérience : tu reformules uniquement le contenu fourni, "
        "en mettant en avant ce qui correspond à l'offre. Réponds uniquement avec le CV."
    )
    user = (
        f"Profil du candidat :\n{_profile_text(profile)}\n\n"
        f"Offre visée : {job_title}\n{job_description or '(pas de description fournie)'}"
    )
    return _llm(system, user, temperature=0.3)


def generate_followup_email(profile: dict, application: dict) -> str:
    """A polite follow-up email (mail de relance) for a pending application."""
    system = (
        "Tu es un coach en recherche d'emploi. Tu rédiges des mails de relance "
        "courtois et concis en français (150 mots maximum) : objet du mail, "
        "salutation, rappel du poste et de la date de candidature, 1-2 arguments "
        "de valeur tirés du profil, demande poliment du point d'avancement, "
        "formule de politesse. N'invente rien sur le processus de recrutement. "
        "Réponds uniquement avec le mail (avec 'Objet :' en première ligne)."
    )
    user = (
        f"Profil du candidat :\n{_profile_text(profile)}\n\n"
        f"Candidature à relancer : {application.get('title') or 'Poste'} chez "
        f"{application.get('company') or 'entreprise non précisée'} "
        f"(candidature envoyée le {application.get('applied_date') or 'date inconnue'}, "
        f"statut actuel : {application.get('status') or 'En cours'})"
    )
    return _llm(system, user, temperature=0.5)


def generate_interview_prep(profile: dict, application: dict) -> str:
    """Interview preparation guide: HR + technical questions and model answers."""
    system = (
        "Tu es un coach en préparation d'entretiens d'embauche. À partir du profil "
        "et de l'offre, produis un guide d'entretien structuré en Markdown :\n"
        "## Entretien RH\n5 questions probables, chacune avec une réponse modèle "
        "personnalisée (3-4 phrases) fondée UNIQUEMENT sur le profil fourni.\n"
        "## Entretien technique\n5 questions techniques probables liées aux "
        "compétences du profil et à l'offre, chacune avec les points clés d'une "
        "bonne réponse.\n## Questions à poser au recruteur\n3 questions.\n"
        "## Pièges à éviter\n3 conseils spécifiques.\n"
        "N'invente pas d'expérience absente du profil. Réponds uniquement avec le guide."
    )
    user = (
        f"Profil du candidat :\n{_profile_text(profile)}\n\n"
        f"Offre / poste : {application.get('title') or 'Poste'} chez "
        f"{application.get('company') or 'entreprise non précisée'}\n"
        f"Description : {application.get('description') or application.get('title') or ''}"
    )
    return _llm(system, user, temperature=0.4)
