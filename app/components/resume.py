"""Resume upload handling: text extraction + automatic skill extraction.

Text extraction strategy:
- Plain text / markdown: read directly.
- PDF: pypdf first (instant, no API); scanned PDFs yield no text, so fall
  back to the ai_parse_document REST endpoint (data URL, base64) which
  handles OCR and complex layouts.
- DOCX / DOC / images: ai_parse_document REST only.

Skill extraction: one LLM call through the Unity Gateway (the same
Chat Completions API the chat tab uses), asked to return strict JSON.
"""

import base64
import io
import json
import re
from pathlib import Path

import requests

from components.auth import get_host_and_token

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

LLM_MODEL = "system.ai.meta-llama-3-3-70b-instruct"


def extract_resume_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from an uploaded resume (TXT/MD/PDF/DOCX/images)."""
    suffix = Path(filename).suffix.lower()

    if suffix in (".txt", ".md"):
        return file_bytes.decode("utf-8", errors="replace")

    if suffix == ".pdf":
        text = _pdf_text_pypdf(file_bytes)
        if text.strip():
            return text
        # Scanned PDF — no embedded text: fall through to AI document parsing.
        return _ai_parse_document(file_bytes, "application/pdf")

    mime = MIME_BY_EXT.get(suffix)
    if mime is None:
        raise ValueError(f"Format de CV non supporté : {suffix or filename}")
    return _ai_parse_document(file_bytes, mime)


def _pdf_text_pypdf(data: bytes) -> str:
    """Best-effort text extraction with pypdf; returns '' on any failure."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _ai_parse_document(data: bytes, mime_type: str) -> str:
    """Parse document bytes via the ai_parse_document REST endpoint (base64
    data URL) and flatten the extracted elements to text."""
    host, token = get_host_and_token()
    encoded = base64.b64encode(data).decode("ascii")
    resp = requests.post(
        f"{host}/api/2.0/ai-functions/ai-parse-document",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": f"data:{mime_type};base64,{encoded}",
            "options": {"version": "2.0"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    parsed = resp.json()
    # error_status is a JSON null on success; a non-empty array marks partial
    # page failures even with HTTP 2xx.
    if parsed.get("error_status"):
        raise RuntimeError(f"Échec du parsing du document : {parsed['error_status']}")
    elements = parsed.get("document", {}).get("elements", [])
    return "\n".join(e.get("content", "") for e in elements if e.get("content"))


_SYSTEM_PROMPT = (
    "Tu es un assistant RH expert. Tu analyses des CV et tu réponds UNIQUEMENT "
    "avec un objet JSON valide, sans texte autour, sans markdown. "
    "Format attendu (toutes les clés doivent être présentes, liste vide si "
    "l'information est absente du CV) :\n"
    "{\n"
    "  \"name\": \"nom complet\",\n"
    "  \"current_title\": \"intitulé de poste actuel\",\n"
    "  \"years_experience\": \"années d'expérience (ex: '5 ans')\",\n"
    "  \"summary\": \"résumé professionnel en 2 phrases\",\n"
    "  \"skills\": [termes courts, techniques et linguistiques],\n"
    "  \"experiences\": [{\"title\": \"poste\", \"company\": \"entreprise\", "
    "\"start_date\": \"AAAA\", \"end_date\": \"AAAA ou 'Présent'\", "
    "\"description\": \"1-2 phrases\"}],\n"
    "  \"education\": [{\"degree\": \"diplôme\", \"school\": \"école/université\", "
    "\"year\": \"AAAA\"}],\n"
    "  \"languages\": [{\"name\": \"Anglais\", \"level\": \"Courant/C1/...\"}],\n"
    "  \"certifications\": [{\"name\": \"certification\", \"issuer\": "
    "\"organisme\", \"year\": \"AAAA\"}]\n"
    "}\n"
    "Les skills doivent être des termes courts (ex: 'Python', 'SQL', "
    "'Spark', 'Docker', 'Anglais'). Respecte exactement les noms de clés."
)

def _normalize_cv_list(raw, fields):
    """Coerce an LLM-returned list of dicts into rows with exactly `fields`."""
    rows = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {f: str(item.get(f) or "").strip() for f in fields}
        if any(row.values()):
            rows.append(row)
    return rows


def extract_profile_from_resume(resume_text: str) -> dict:
    """LLM extraction of a full structured profile (Apec-style) from a CV.

    Returns a dict with keys: skills (list[str]), name, years_experience,
    current_title, summary, experiences, education, languages,
    certifications — missing values are empty.
    """
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
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Analyse ce CV :\n\n" + resume_text[:8000],
                },
            ],
            "temperature": 0,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    data = _load_json_loose(content)
    skills = [
        s.strip()
        for s in (data.get("skills") or [])
        if isinstance(s, str) and s.strip()
    ]
    return {
        "skills": skills,
        "name": str(data.get("name") or ""),
        "years_experience": str(data.get("years_experience") or ""),
        "current_title": str(data.get("current_title") or ""),
        "summary": str(data.get("summary") or ""),
        "experiences": _normalize_cv_list(
            data.get("experiences"),
            ("title", "company", "start_date", "end_date", "description"),
        ),
        "education": _normalize_cv_list(
            data.get("education"), ("degree", "school", "year")
        ),
        "languages": _normalize_cv_list(
            data.get("languages"), ("name", "level")
        ),
        "certifications": _normalize_cv_list(
            data.get("certifications"), ("name", "issuer", "year")
        ),
    }


def _load_json_loose(text: str) -> dict:
    """Parse a JSON object from LLM output, tolerating code fences and prose."""
    text = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
