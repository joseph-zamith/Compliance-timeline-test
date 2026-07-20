#!/usr/bin/env python3
"""
Veille réglementaire hebdomadaire — MDSW / AI Act (Theodo HealthTech)

Remplace l'ancienne automatisation macOS (voir automation/legacy-macos/).
Conçu pour tourner sur un runner GitHub Actions, sans dépendance à une
machine ou un compte personnel : tout ce qui a besoin d'être configurable
(destinataires, modèles IA) vit dans des fichiers JSON versionnés, et les
secrets (clés API, mot de passe email) viennent des variables d'environnement
injectées par le workflow depuis les secrets GitHub.

Étapes :
  1. Charger la config (modèles, destinataires) et les données existantes.
  2. Recherche : fetch direct (HTTP simple) des sources fixes + requêtes
     Perplexity Sonar via LiteLLM pour la largeur de couverture.
  3. Rédaction : un appel à Claude (via LiteLLM) qui trie, rédige (règles
     éditoriales FR ci-dessous) et génère les propositions EN + FR.
  4. Validation stricte du JSON produit — on n'écrit/pousse RIEN si c'est
     invalide, pour ne jamais casser le site public.
  5. Envoi du mail (corps concis + rapport complet en pièce jointe).
  6. Mise à jour de l'état anti-répétition + commit/push git.

Variables d'environnement attendues (fournies par le workflow GitHub Actions) :
  LITELLM_API_KEY     - clé API LiteLLM (https://llm-gateway.m33.tech)
  GMAIL_ADDRESS       - adresse Gmail dédiée à l'envoi
  GMAIL_APP_PASSWORD  - mot de passe d'application Gmail (SMTP)
  GITHUB_TOKEN        - fourni automatiquement par GitHub Actions (permissions: contents: write)
  DRY_RUN             - "true" pour tout générer sans envoyer/pousser (test)
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTOMATION_DIR = REPO_ROOT / "automation"
STATE_DIR = AUTOMATION_DIR / "state"
ARCHIVE_DIR = STATE_DIR / "archive"

LITELLM_BASE_URL = "https://llm-gateway.m33.tech"

VALID_TOPICS = ["mdr", "ai", "standards", "cyber", "france", "uk", "us", "other", "data"]
VALID_TAGS = ["critical", "high", "medium", "new", "in-force", "draft", "proposed"]
VALID_VARIANTS = ["c", "h", "n"]

FIXED_SOURCES = [
    "https://www.qualitiso.com/veille/",
    "https://www.dm-experts.fr/flash-reglementaire-normatif/",
    "https://www.snitem.fr/actualites-et-evenements/actualites-du-dm-et-de-la-sante/",
    "https://www.cnil.fr/fr",
    "https://www.afnor.org/actualites/",
    "https://ansm.sante.fr/",
    "https://gnius.esante.gouv.fr/fr/a-la-une/actualites",
    "https://health.ec.europa.eu/medical-devices-sector/new-regulations_en",
    "https://digital-strategy.ec.europa.eu/en/policies/ai-act-standardisation",
    "https://www.imdrf.org/",
    "https://www.fda.gov/medical-devices/digital-health-center-excellence",
    "https://www.gov.uk/health-and-social-care/medicines-medical-devices-blood",
]

EMAIL_MARKER = "===EMAIL_BODY==="
REPORT_MARKER = "===FULL_REPORT==="
PROPOSALS_EN_MARKER = "===PROPOSALS_EN==="
PROPOSALS_FR_MARKER = "===PROPOSALS_FR==="
END_MARKER = "===END==="

STANDARDS_REGISTER = """
| Source | Reference | Title | Watch for |
|---|---|---|---|
| EU Commission | EU 2017/745 | MDR | Simplification proposal (2025/0404) progress |
| EU Commission | EU 2016/679 | GDPR | Changes (rare) |
| EU Commission | EU 2024/1689 | AI Act | Application timeline; Digital Omnibus deferrals |
| EU Commission | EU 2021/2226 + amendments | eIFU | Amendment scope |
| AFNOR | NF EN ISO 13485:2016/A11 | QMS | Revision progress |
| AFNOR | NF EN ISO 14971:2019/A11 | Risk management | Any revision signal |
| AFNOR | NF EN 62304/A1 | Software lifecycle | Edition 2 progress (MAJOR when it lands) |
| AFNOR | NF EN 62366/A1 | Usability | Changes (rare) |
| IEC | IEC 82304-1 | Health software safety | Any announcement |
| ISO | ISO 15223-1/-2, ISO 20417 | Labeling/symbols | Amendments, symbol transitions |
| ISO | ISO/TR 24971 | Risk mgmt guidance | Changes |
| ISO | ISO 27001/27701/27017/27018 | Info security | Changes |
| ANS | HDS | Health data hosting | Referential evolution |
| BSI | C5 | Cloud compliance | Changes |
| ISO | ISO 14155 | Clinical investigation | Edition status |
| EU Commission | MDCG 2019-11 | Software qualification | New revision |
| EU Commission | MDCG 2025-6 | MDR/IVDR vs AI Act | Updates |
| EU Commission | MDCG 2025-4 | MDSW on platforms | Updates |
| EU Commission | MDCG 2019-16 | Cybersecurity | New revision |
| IMDRF | SaMD WG / N12, N81, N88 | SaMD framework, ML | New or closing drafts |
| CEN-CENELEC | prEN 18286 | AI Act QMS standard | Publication targeted Q4 2026 |
"""


def log(msg: str) -> None:
    print(f"[weekly_watch] {msg}", flush=True)


def fail(msg: str) -> None:
    log(f"ERREUR FATALE: {msg}")
    sys.exit(1)


def is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").lower() == "true"


def skip_fixed_sources() -> bool:
    """Test-only escape hatch: skip the ~12 fixed-source HTTP fetches (already
    validated separately) to iterate faster on the writing model. Sonar
    research still runs, so there's still real content to write from."""
    return os.environ.get("SKIP_FIXED_SOURCES", "").lower() == "true"


def skip_content_call() -> bool:
    """Test-only escape hatch: skip the (slower) email+report model call and
    feed the proposals call directly from the raw research blob instead. Lets
    us iterate quickly on the proposals prompt/JSON validation without paying
    for and waiting on the content call each time. Never use outside testing —
    email_body will be a placeholder, unusable for a real send."""
    return os.environ.get("SKIP_CONTENT_CALL", "").lower() == "true"


# ---------------------------------------------------------------------------
# Step 1: config, recipients, existing data
# ---------------------------------------------------------------------------

def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict:
    cfg = load_json(AUTOMATION_DIR / "config.json", {})
    return {
        "research_model": cfg.get("research_model", "vercel/perplexity-sonar"),
        "writing_model": cfg.get("writing_model", "vercel/anthropic-claude-sonnet-4.5"),
    }


def load_recipients() -> list:
    data = load_json(AUTOMATION_DIR / "recipients.json", {"recipients": []})
    recipients = data.get("recipients", [])
    if not recipients:
        fail("automation/recipients.json ne contient aucun destinataire.")
    return recipients


def load_last_email() -> str:
    path = STATE_DIR / "last_email.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "(aucune édition précédente — première exécution)"


def get_litellm_client() -> OpenAI:
    api_key = os.environ.get("LITELLM_API_KEY")
    if not api_key:
        fail("LITELLM_API_KEY manquant (secret GitHub Actions non configuré).")
    # read=90 : chaque lecture réseau attend au plus 90s de nouvelles données.
    # Tant que le flux avance (même lentement, un long rapport par ex.), chaque
    # lecture réussit et le compteur repart à zéro — seul un vrai blocage
    # (rien reçu pendant 90s d'affilée) déclenche une erreur.
    timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)
    return OpenAI(api_key=api_key, base_url=LITELLM_BASE_URL, timeout=timeout)


# ---------------------------------------------------------------------------
# Step 2: research — fixed sources (Playwright) + Perplexity Sonar
# ---------------------------------------------------------------------------

def fetch_fixed_sources() -> str:
    """Fetch the ~12 fixed regulatory-watch sources with a plain HTTP request.
    Confirmed during migration: all these sources are server-rendered (their
    real content is present in the raw HTML), so no headless browser is
    needed — a simple request + text extraction is enough and much faster."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    }
    chunks = []
    for url in FIXED_SOURCES:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            # Cap per-source length to keep the writing-model prompt manageable — a
            # smaller prompt also reduces the model's tendency to try to cover
            # everything at length (see CONTENT_SYSTEM_PROMPT hard length budget).
            chunks.append(f"--- SOURCE: {url} ---\n{text[:2500]}")
        except Exception as e:  # noqa: BLE001 - one bad source must not kill the run
            log(f"Fetch échoué pour {url}: {e}")
            chunks.append(f"--- SOURCE: {url} ---\n(fetch échoué: {e})")
    return "\n\n".join(chunks)


SONAR_QUERIES = [
    "EU MDR IVDR medical device software regulatory news this week",
    "AI Act medical devices standards news MDCG guidance published this week",
    "IEC 62304 edition 2 ISO 13485 revision prEN 18286 AI Act QMS standard news this week",
    "EUDAMED registration deadline news this week",
    "CNIL ANSM HDS EHDS health data France medical device news this week",
    "Cyber Resilience Act NIS2 healthcare medical device cybersecurity news this week",
    "IMDRF new guidance SaMD AI medical device this week",
    "MHRA UK SaMD FDA digital health SaMD PCCP news this week",
]


def run_sonar_research(client: OpenAI, model: str) -> str:
    answers = []
    for query in SONAR_QUERIES:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": f"{query}. Focus on developments from the last 7 days only "
                                f"(today is {date.today().isoformat()}). Cite source URLs.",
                }],
            )
            answers.append(f"Q: {query}\n{resp.choices[0].message.content}")
        except Exception as e:  # noqa: BLE001
            log(f"Requête Sonar échouée ({query}): {e}")
    return "\n\n".join(answers)


# ---------------------------------------------------------------------------
# Step 3: writing — one call to the writing model, structured output
# ---------------------------------------------------------------------------

CONTENT_SYSTEM_PROMPT = f"""You are an expert QARA (Quality Assurance & Regulatory Affairs) consultant
specialised in Medical Device Software (MDSW) in the EU, writing for Theodo HealthTech.

## EDITORIAL MANDATE
Audience: busy QARA leads and C-levels. Two-tier output, BOTH bounded — this is a weekly digest,
not an exhaustive dump:
1. Email body: a 2-minute read, 450-650 words (max 700), EU-first, only what moved this week.
2. Full report: attached as HTML, target 1200-2000 words total across all sections. Go deeper
   than the email on items that moved, but do not pad with boilerplate or restate unchanged
   background. If nothing material happened in a region/section this week, one line saying so
   is enough — do not describe it at length anyway.

HARD TECHNICAL CONSTRAINT — this is not a style preference, it is a system limit: your total
output for this call (email HTML + report HTML combined) is capped at roughly 9000 tokens. If
you go over, the call is cut off mid-output and the ENTIRE run fails (nothing gets sent, nothing
gets published). It is always better to under-deliver (shorter items, fewer words per item,
drop a minor item) than to risk running out of budget. Write tightly from the start — 1-2
sentences per item, no throat-clearing, no restating the item you just covered in the email
inside the report. If you notice you are already past 1500 words combined and not yet at the
proposals-adjacent sections, start compressing aggressively.

Language: BOTH outputs are in FRENCH, native register (not translated English). Banned calques:
"actionnable", "re-actionner", "En 60 secondes", "Sur le radar", "atteindre le seuil",
"reprise du stock" (write "rattrapage / enregistrement du stock existant"). Preferred section
headers: "L'essentiel de la semaine", "UE et international", "Hors UE", "Points de vigilance",
"NOTRE AVIS", "Annexe : suivi des normes". No em dashes anywhere, ever.

Principles: EU first. Rest of world only if genuinely major (else one line). Never repeat last
week's items without a material development since — read the previous edition below first.

## STYLE (both email and report)
Brand: dark navy #1c2837 / #213045; accent orange #ff512c; HIGH #e8850c; light greys
#e9ebee / #f3f3f3; font Poppins with Arial/Helvetica fallback; rounded corners (12-16px),
subtle shadows. Inline CSS only, table-based layout, no CSS classes (email-client compatible).
Every item MUST carry a clickable <a href="url"> source link. Tone: factual, action-oriented,
cut adjectives.

## EMAIL BODY STRUCTURE
1. En-tête compact: navy bg, "Theodo HealthTech" in orange, "Veille reglementaire" in white,
   subtitle "Logiciels de dispositifs medicaux et AI Act", date range badge.
2. "L'essentiel de la semaine": 3-5 one-line bullets, or one honest line if the week was quiet.
3. Priority banner (conditional): only if a genuine new/imminent deadline or CRITIQUE/ELEVE item.
4. "UE et international": up to 6 items, bold headline + 1-2 sentences + status tag + source link.
   Status tags: NOUVEAU, EN VIGUEUR, PROJET, EN COURS, FINAL, RETIRE, INCHANGE.
   Priority tags: CRITIQUE, ELEVE, MOYEN.
5. "Hors UE": one compact block, max 3 items, one line each, or "Aucune evolution notable
   hors UE cette semaine."
6. "Points de vigilance": max 3 one-liners, standing items with a deadline within ~60 days.
7. Pied de page: navy, note that the full report is attached, link to
   https://theodo-group.github.io/Compliance-timeline/admin.html, disclaimer, Theodo HealthTech branding.

## FULL REPORT STRUCTURE (attachment, bounded — see word target above)
Same branding. Section 1 EU & International. Section 2 UK. Section 3 US. Section 4 Other
regions — each section: only items with a genuine development this week, in enough detail to
act on (what changed, why it matters, deadline if any, source link); skip or one-line anything
unchanged. Standards monitoring annex using this register, but ONLY list rows that moved this
week with what changed; for everything else, a single closing line: "Aucun changement cette
semaine sur les autres normes suivies." (do not reprint the full register every week):
{STANDARDS_REGISTER}

## OUTPUT FORMAT — respect EXACTLY, nothing else before/after
{EMAIL_MARKER}
<the email body HTML>
{REPORT_MARKER}
<the full report HTML>
{END_MARKER}
"""

PROPOSALS_SYSTEM_PROMPT = f"""You are an expert QARA (Quality Assurance & Regulatory Affairs) consultant
producing structured timeline-update proposals for Theodo HealthTech's public MDSW regulatory
timeline. You are given this week's full regulatory-watch report (already written) and the
existing timeline milestones. Your only job here is to turn genuinely material developments
from the report into ADD/UPDATE/DELETE proposals — do not re-research, do not add anything not
already in the report below.

## RULES
Only genuinely material developments (typically 2-8 items total; skip cosmetic or non-material
changes — most weeks do NOT need 8). Stable id format: "YYYY-MM-DD--lowercase-english-slug"
(double dash, max 50 chars), identical between EN and FR. Valid topics: {VALID_TOPICS}.
Valid tags: {VALID_TAGS}. Valid variants: {VALID_VARIANTS} (c=critical/navy, h=highlight/gold,
n=normal). Action value must be lowercase: "add", "update", or "delete" — never uppercase.
FR proposals: IDENTICAL id/action/existing_id/card.id/card.d/card.y/card.u/card.tp/card.tg/card.v;
translate card.t, card.x, card.l only (reason stays in English). Keep "reason" and "x" (card
description) concise — 1-2 sentences, not a paragraph.

## OUTPUT FORMAT — respect EXACTLY, nothing else before/after
{PROPOSALS_EN_MARKER}
{{"generated": "YYYY-MM-DD", "proposals": [...]}}
{PROPOSALS_FR_MARKER}
{{"generated": "YYYY-MM-DD", "proposals": [...]}}
{END_MARKER}
"""


def run_model_call(
    client: OpenAI, model: str, system_prompt: str, user_content: str, label: str,
    max_tokens: int = 16000,
) -> str:
    """Shared streaming call used for both the content call (email+report) and
    the proposals call. Splitting these into two smaller requests (instead of
    one call producing all four sections) keeps each call's total generation
    time comfortably under the gateway's apparent hard cap on request
    duration — the cause of the earlier finish_reason=None cutoffs.

    max_tokens is deliberately kept much lower than the model's real ceiling:
    it acts as a hard, deterministic backstop so a call that ignores the
    length guidance in the prompt fails fast and clearly (finish_reason=
    "length", caught below) instead of silently running into the gateway's
    duration cutoff."""
    # Streaming : le flux avance token par token. Le timeout "read" configuré
    # sur le client (voir get_litellm_client) protège contre un vrai blocage
    # sans jamais couper un rapport long qui progresse normalement.
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            stream=True,
        )
        chunks = []
        finish_reason = None
        total_chars = 0
        last_progress_log = time.monotonic()
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                chunks.append(delta)
                total_chars += len(delta)
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
            now = time.monotonic()
            if now - last_progress_log > 15:
                log(f"  ... {label} toujours en cours, {total_chars} caractères reçus jusqu'ici.")
                last_progress_log = now
    except httpx.ReadTimeout:
        fail(f"Modèle bloqué ({label}) : aucune donnée reçue pendant plus de 90s.")

    content = "".join(chunks)
    log(f"{label} terminé — finish_reason={finish_reason}, longueur={len(content)} caractères.")
    if finish_reason == "length":
        log(
            f"  ATTENTION ({label}) : coupé par max_tokens={max_tokens}, pas par le modèle "
            f"lui-même — le contenu est probablement incomplet (pas de marqueur de fin)."
        )
    return content


def save_debug_output(raw: str, kind: str) -> None:
    """Always persist the raw model output so a failed run can be inspected
    via the workflow artifact — never fail blind."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"debug_last_{kind}_output.txt").write_text(raw, encoding="utf-8")


def _fail_missing_markers(raw: str, markers: list, debug_filename: str, what: str) -> None:
    for marker in markers:
        log(f"Marqueur {marker} présent: {marker in raw}")
    log(f"Aperçu du début de la réponse (500 car.): {raw[:500]!r}")
    log(f"Aperçu de la fin de la réponse (500 car.): {raw[-500:]!r}")
    fail(
        f"Sortie du modèle ({what}) mal formée : marqueurs de section introuvables. "
        f"Voir automation/state/{debug_filename} (artefact du run) pour la sortie complète."
    )


def split_content_sections(raw: str) -> dict:
    save_debug_output(raw, "content")
    pattern = re.escape(EMAIL_MARKER) + r"(.*?)" + re.escape(REPORT_MARKER) + r"(.*?)" + re.escape(END_MARKER)
    m = re.search(pattern, raw, re.DOTALL)
    if not m:
        _fail_missing_markers(
            raw, [EMAIL_MARKER, REPORT_MARKER, END_MARKER],
            "debug_last_content_output.txt", "email + rapport",
        )
    email_body, full_report = (s.strip() for s in m.groups())
    return {"email_body": email_body, "full_report": full_report}


def split_proposals_sections(raw: str) -> dict:
    save_debug_output(raw, "proposals")
    pattern = re.escape(PROPOSALS_EN_MARKER) + r"(.*?)" + re.escape(PROPOSALS_FR_MARKER) + r"(.*?)" + re.escape(END_MARKER)
    m = re.search(pattern, raw, re.DOTALL)
    if not m:
        _fail_missing_markers(
            raw, [PROPOSALS_EN_MARKER, PROPOSALS_FR_MARKER, END_MARKER],
            "debug_last_proposals_output.txt", "propositions",
        )
    proposals_en_raw, proposals_fr_raw = (s.strip() for s in m.groups())
    return {"proposals_en_raw": proposals_en_raw, "proposals_fr_raw": proposals_fr_raw}


# ---------------------------------------------------------------------------
# Step 4: strict validation — never push something that could break the site
# ---------------------------------------------------------------------------

def validate_proposals_json(raw: str, label: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"JSON {label} invalide ({e}). Rien n'est écrit/poussé.")

    if not isinstance(parsed, dict) or "proposals" not in parsed or "generated" not in parsed:
        fail(f"JSON {label} : structure racine invalide (attendu generated + proposals).")

    for p in parsed["proposals"]:
        # Le modèle sort parfois "ADD"/"UPDATE"/"DELETE" en majuscule (ambigu dans le
        # prompt) — on normalise ici plutôt que de dépendre uniquement de la casse
        # respectée par le modèle. p["action"] est réécrit en place, donc le reste
        # du pipeline (validate_existing_ids, etc.) voit toujours la version normalisée.
        action = str(p.get("action", "")).lower()
        if action not in ("add", "update", "delete"):
            log(f"Proposition problématique ({label}): {json.dumps(p, ensure_ascii=False)[:1000]}")
            fail(f"JSON {label} : action invalide sur la proposition {p.get('id')}.")
        p["action"] = action
        if "id" not in p or "reason" not in p:
            log(f"Proposition problématique ({label}): {json.dumps(p, ensure_ascii=False)[:1000]}")
            fail(f"JSON {label} : proposition sans id ou reason.")
        card = p.get("card")
        if card:
            if any(t not in VALID_TOPICS for t in card.get("tp", [])):
                log(f"Proposition problématique ({label}): {json.dumps(p, ensure_ascii=False)[:1000]}")
                fail(f"JSON {label} : topic invalide dans {p['id']}.")
            if any(t not in VALID_TAGS for t in card.get("tg", [])):
                log(f"Proposition problématique ({label}): {json.dumps(p, ensure_ascii=False)[:1000]}")
                fail(f"JSON {label} : tag invalide dans {p['id']}.")
            if card.get("v") not in VALID_VARIANTS:
                log(f"Proposition problématique ({label}): {json.dumps(p, ensure_ascii=False)[:1000]}")
                fail(f"JSON {label} : variant invalide dans {p['id']}.")
        if p["action"] in ("update", "delete") and not p.get("existing_id"):
            log(f"Proposition problématique ({label}): {json.dumps(p, ensure_ascii=False)[:1000]}")
            fail(f"JSON {label} : action {p['action']} sans existing_id ({p['id']}).")

    return parsed


def validate_id_parity(proposals_en: dict, proposals_fr: dict) -> None:
    ids_en = {p["id"] for p in proposals_en["proposals"]}
    ids_fr = {p["id"] for p in proposals_fr["proposals"]}
    if ids_en != ids_fr:
        fail(
            "Parité EN/FR rompue — ids présents dans un fichier mais pas l'autre: "
            f"{ids_en.symmetric_difference(ids_fr)}"
        )


def validate_existing_ids(proposals: dict, data_json: list) -> None:
    known_ids = {m["id"] for m in data_json if "id" in m}
    for p in proposals["proposals"]:
        if p["action"] in ("update", "delete") and p["existing_id"] not in known_ids:
            fail(f"existing_id inconnu dans data.json: {p['existing_id']} (proposition {p['id']}).")


def validate_unique_ids(proposals: dict, label: str) -> None:
    ids = [p["id"] for p in proposals["proposals"]]
    if len(ids) != len(set(ids)):
        fail(f"JSON {label} : id de proposition dupliqué dans le même lot.")


# ---------------------------------------------------------------------------
# Step 5: send email
# ---------------------------------------------------------------------------

def send_email(email_body_html: str, full_report_html: str, recipients: list) -> None:
    import base64
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_password:
        fail("GMAIL_ADDRESS / GMAIL_APP_PASSWORD manquant (secrets GitHub Actions).")

    today_str = date.today().strftime("%d %B %Y")
    outer = MIMEMultipart("mixed")
    outer["To"] = ", ".join(recipients)
    outer["Subject"] = f"Veille reglementaire (focus UE) - Logiciels DM & AI Act - {today_str}"
    outer["From"] = gmail_address

    body = MIMEMultipart("alternative")
    plain_text = (
        "REGULATORY WATCH - EU focus - MDSW & AI Act\n"
        "Voir le corps HTML pour le detail. Rapport complet en piece jointe.\n\n"
        "--\nTheodo HealthTech | Regulatory Watch"
    )
    body.attach(MIMEText(plain_text, "plain"))
    body.attach(MIMEText(email_body_html, "html"))
    outer.attach(body)

    att = MIMEApplication(full_report_html.encode("utf-8"), _subtype="html")
    date_slug = date.today().strftime("%Y-%m-%d")
    att.add_header("Content-Disposition", "attachment", filename=f"Regulatory-Watch-Full-Report-{date_slug}.html")
    outer.attach(att)

    if is_dry_run():
        log("DRY_RUN actif : email non envoyé (généré avec succès).")
        return

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_password)
        server.sendmail(gmail_address, recipients, outer.as_string())
    log(f"Email envoyé à {len(recipients)} destinataire(s).")


# ---------------------------------------------------------------------------
# Step 6: persist state + git commit/push
# ---------------------------------------------------------------------------

def write_outputs(proposals_en: dict, proposals_fr: dict, email_body_html: str) -> None:
    (REPO_ROOT / "proposals.json").write_text(json.dumps(proposals_en, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPO_ROOT / "proposals-fr.json").write_text(json.dumps(proposals_fr, ensure_ascii=False, indent=2), encoding="utf-8")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "last_email.html").write_text(email_body_html, encoding="utf-8")
    date_slug = date.today().strftime("%Y-%m-%d")
    (ARCHIVE_DIR / f"email-{date_slug}.html").write_text(email_body_html, encoding="utf-8")


def git_commit_and_push() -> None:
    if is_dry_run():
        log("DRY_RUN actif : pas de commit/push.")
        return
    date_slug = date.today().strftime("%Y-%m-%d")
    subprocess.run(["git", "config", "user.name", "regulatory-watch-bot"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=REPO_ROOT, check=True)
    subprocess.run(
        ["git", "add", "proposals.json", "proposals-fr.json", "automation/state"],
        cwd=REPO_ROOT, check=True,
    )
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if result.returncode == 0:
        log("Rien à committer (aucun changement).")
        return
    subprocess.run(
        ["git", "commit", "-m", f"Regulatory watch: proposals for {date_slug}"],
        cwd=REPO_ROOT, check=True,
    )
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
    log("Changements poussés sur main.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log(f"Démarrage — dry_run={is_dry_run()}")
    config = load_config()
    recipients = load_recipients()
    data_json = load_json(REPO_ROOT / "data.json", [])
    last_email = load_last_email()
    client = get_litellm_client()

    log(f"Modèle recherche: {config['research_model']} / rédaction: {config['writing_model']}")

    if skip_fixed_sources():
        log("Recherche — fetch des sources fixes SKIPPÉ (SKIP_FIXED_SOURCES=true, test rapide).")
        fixed_sources_blob = "(sources fixes non interrogées cette fois — SKIP_FIXED_SOURCES actif, test rapide)"
    else:
        log("Recherche — fetch des sources fixes...")
        fixed_sources_blob = fetch_fixed_sources()

    log("Recherche — requêtes Perplexity Sonar...")
    sonar_blob = run_sonar_research(client, config["research_model"])

    research_blob = f"## Sources fixes\n{fixed_sources_blob}\n\n## Recherche Sonar\n{sonar_blob}"

    if skip_content_call():
        log("Rédaction (email + rapport) SKIPPÉE (SKIP_CONTENT_CALL=true, test rapide sur les propositions).")
        content_sections = {
            "email_body": "<!-- SKIP_CONTENT_CALL actif : email non généré, test propositions uniquement -->",
            "full_report": research_blob[:15000],
        }
    else:
        log("Rédaction — appel au modèle (email + rapport)...")
        content_user_content = (
            f"## Previous edition (do not repeat unchanged items)\n{last_email[:6000]}\n\n"
            f"## Fixed-source research\n{research_blob[:18000]}\n\n"
            f"Today's date: {date.today().isoformat()}. Produce the two sections (email body, "
            f"full report) in the exact required format. Remember the hard token budget."
        )
        content_raw = run_model_call(
            client, config["writing_model"], CONTENT_SYSTEM_PROMPT, content_user_content,
            "Rédaction (email + rapport)", max_tokens=9000,
        )
        content_sections = split_content_sections(content_raw)

    log("Rédaction — appel au modèle (propositions)...")
    proposals_user_content = (
        f"## This week's full report (already written — source of truth, do not re-research)\n"
        f"{content_sections['full_report'][:15000]}\n\n"
        f"## Existing timeline milestones (data.json)\n{json.dumps(data_json, ensure_ascii=False)[:15000]}\n\n"
        f"Today's date: {date.today().isoformat()}. Produce the two proposals JSON blocks in "
        f"the exact required format."
    )
    proposals_raw = run_model_call(
        client, config["writing_model"], PROPOSALS_SYSTEM_PROMPT, proposals_user_content,
        "Rédaction (propositions)", max_tokens=5000,
    )
    proposals_sections = split_proposals_sections(proposals_raw)

    sections = {**content_sections, **proposals_sections}

    log("Validation du JSON produit...")
    proposals_en = validate_proposals_json(sections["proposals_en_raw"], "EN")
    proposals_fr = validate_proposals_json(sections["proposals_fr_raw"], "FR")
    validate_unique_ids(proposals_en, "EN")
    validate_unique_ids(proposals_fr, "FR")
    validate_id_parity(proposals_en, proposals_fr)
    validate_existing_ids(proposals_en, data_json)
    validate_existing_ids(proposals_fr, data_json)
    log("JSON valide.")

    send_email(sections["email_body"], sections["full_report"], recipients)
    write_outputs(proposals_en, proposals_fr, sections["email_body"])
    git_commit_and_push()

    log("Terminé avec succès.")


if __name__ == "__main__":
    main()
