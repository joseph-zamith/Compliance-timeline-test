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
  3. Rédaction découpée en petits appels — le gateway coupe toute requête à
     300 s exactement (mesuré, voir automation/tools/gateway_cap_probe.py),
     parfois en le déguisant en finish_reason="stop", donc aucun appel ne doit
     générer plus de quelques milliers de tokens :
       a. triage (Sonnet) : sélection des items + faits clés, sans prose ;
       b. rédaction par item (Haiku) : summary/detail, ~300 tokens par appel,
          retry unitaire, repli sur les faits clés si échec (le run continue) ;
       c. propositions EN (Sonnet), puis traduction FR par carte (Haiku) —
          la version FR est construite par copie de l'EN, donc la parité
          des ids/champs est garantie par construction.
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

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

CONTENT_MARKER = "===CONTENT==="
PROPOSALS_EN_MARKER = "===PROPOSALS_EN==="
PROPOSALS_FR_MARKER = "===PROPOSALS_FR==="
END_MARKER = "===END==="

# Structured (not markdown-string) so Python can render the annex table itself —
# the model only needs to say which rows moved and why, never re-emit the whole
# register as text (that was a major source of unnecessary output length).
STANDARDS_REGISTER = [
    {"source": "EU Commission", "reference": "EU 2017/745", "title": "MDR", "watch_for": "Simplification proposal (2025/0404) progress"},
    {"source": "EU Commission", "reference": "EU 2016/679", "title": "GDPR", "watch_for": "Changes (rare)"},
    {"source": "EU Commission", "reference": "EU 2024/1689", "title": "AI Act", "watch_for": "Application timeline; Digital Omnibus deferrals"},
    {"source": "EU Commission", "reference": "EU 2021/2226 + amendments", "title": "eIFU", "watch_for": "Amendment scope"},
    {"source": "AFNOR", "reference": "NF EN ISO 13485:2016/A11", "title": "QMS", "watch_for": "Revision progress"},
    {"source": "AFNOR", "reference": "NF EN ISO 14971:2019/A11", "title": "Risk management", "watch_for": "Any revision signal"},
    {"source": "AFNOR", "reference": "NF EN 62304/A1", "title": "Software lifecycle", "watch_for": "Edition 2 progress (MAJOR when it lands)"},
    {"source": "AFNOR", "reference": "NF EN 62366/A1", "title": "Usability", "watch_for": "Changes (rare)"},
    {"source": "IEC", "reference": "IEC 82304-1", "title": "Health software safety", "watch_for": "Any announcement"},
    {"source": "ISO", "reference": "ISO 15223-1/-2, ISO 20417", "title": "Labeling/symbols", "watch_for": "Amendments, symbol transitions"},
    {"source": "ISO", "reference": "ISO/TR 24971", "title": "Risk mgmt guidance", "watch_for": "Changes"},
    {"source": "ISO", "reference": "ISO 27001/27701/27017/27018", "title": "Info security", "watch_for": "Changes"},
    {"source": "ANS", "reference": "HDS", "title": "Health data hosting", "watch_for": "Referential evolution"},
    {"source": "BSI", "reference": "C5", "title": "Cloud compliance", "watch_for": "Changes"},
    {"source": "ISO", "reference": "ISO 14155", "title": "Clinical investigation", "watch_for": "Edition status"},
    {"source": "EU Commission", "reference": "MDCG 2019-11", "title": "Software qualification", "watch_for": "New revision"},
    {"source": "EU Commission", "reference": "MDCG 2025-6", "title": "MDR/IVDR vs AI Act", "watch_for": "Updates"},
    {"source": "EU Commission", "reference": "MDCG 2025-4", "title": "MDSW on platforms", "watch_for": "Updates"},
    {"source": "EU Commission", "reference": "MDCG 2019-16", "title": "Cybersecurity", "watch_for": "New revision"},
    {"source": "IMDRF", "reference": "SaMD WG / N12, N81, N88", "title": "SaMD framework, ML", "watch_for": "New or closing drafts"},
    {"source": "CEN-CENELEC", "reference": "prEN 18286", "title": "AI Act QMS standard", "watch_for": "Publication targeted Q4 2026"},
]


def _standards_register_for_prompt() -> str:
    """Compact reference table given to the model so it can spot which rows
    moved this week — NOT meant to be reproduced verbatim in the output."""
    lines = ["| Reference | Title | Watch for |", "|---|---|---|"]
    for row in STANDARDS_REGISTER:
        lines.append(f"| {row['reference']} | {row['title']} | {row['watch_for']} |")
    return "\n".join(lines)


FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def format_date_fr(d: date) -> str:
    """French date formatting without relying on the runner's locale (which
    would otherwise silently produce English month names, e.g. '21 July
    2026', on a French-audience email)."""
    return f"{d.day} {FR_MONTHS[d.month - 1]} {d.year}"


def compute_week_label(today: date) -> str:
    """Rolling 7-day window ending today, e.g. '15-21 juillet 2026'."""
    start = today - timedelta(days=6)
    if start.month == today.month:
        return f"{start.day}-{today.day} {FR_MONTHS[today.month - 1]} {today.year}"
    return f"{format_date_fr(start)} au {format_date_fr(today)}"


PRIORITY_LABELS = {"critical": "CRITIQUE", "high": "ELEVE", "medium": "MOYEN"}
PRIORITY_COLORS = {"critical": "#e8850c", "high": "#e8850c", "medium": "#ff9500"}
STATUS_LABELS = {
    "new": "NOUVEAU", "in-force": "EN VIGUEUR", "draft": "PROJET", "ongoing": "EN COURS",
    "final": "FINAL", "withdrawn": "RETIRE",
}
REGION_LABELS = {"eu": "UE et international", "uk": "Royaume-Uni", "us": "Etats-Unis", "other": "Autres regions"}


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


def replay_content() -> bool:
    """Test-only: reuse the last real content-call output committed at
    automation/state/debug_last_content_output.txt instead of calling the
    model again. Zero cost, zero wait — useful to iterate on everything
    downstream (validation, write_outputs, email rendering) without re-running
    the LLM. Requires that file to already exist in the checkout (it's
    committed unconditionally by commit_state_for_qa, even in dry runs)."""
    return os.environ.get("REPLAY_CONTENT", "").lower() == "true"


def replay_proposals() -> bool:
    """Same as replay_content(), for automation/state/debug_last_proposals_output.txt."""
    return os.environ.get("REPLAY_PROPOSALS", "").lower() == "true"


def skip_sonar() -> bool:
    """Test-only escape hatch: skip the 8 Perplexity Sonar queries (real
    money, unlike LiteLLM/Claude calls which REPLAY_CONTENT already avoids).
    Combined with REPLAY_CONTENT=true + REPLAY_PROPOSALS=true, this makes a
    full end-to-end run (including a real email send) genuinely zero-cost —
    useful to test things unrelated to content (email formatting, SMTP,
    recipients) without touching any paid API."""
    return os.environ.get("SKIP_SONAR", "").lower() == "true"


# ---------------------------------------------------------------------------
# Step 1: config, recipients, existing data
# ---------------------------------------------------------------------------

def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict:
    """Un modèle par étape du pipeline. Les étapes de décision (triage,
    propositions) restent sur Sonnet ; les étapes mécaniques (prose d'un item
    à partir de faits déjà choisis, traduction de 3 champs) descendent sur
    Haiku (~3x moins cher, ~2x plus rapide). `writing_model` sert de fallback
    pour compat avec l'ancien config.json à deux champs."""
    cfg = load_json(AUTOMATION_DIR / "config.json", {})
    writing_default = cfg.get("writing_model", "vercel/anthropic-claude-sonnet-4.5")
    haiku_default = "vercel/anthropic-claude-haiku-4.5"
    return {
        "research_model": cfg.get("research_model", "vercel/perplexity-sonar"),
        "writing_model": writing_default,
        "triage_model": cfg.get("triage_model", writing_default),
        "item_model": cfg.get("item_model", haiku_default),
        "proposals_model": cfg.get("proposals_model", writing_default),
        "translate_model": cfg.get("translate_model", haiku_default),
    }


def load_recipients() -> list:
    data = load_json(AUTOMATION_DIR / "recipients.json", {"recipients": []})
    recipients = data.get("recipients", [])
    if not recipients:
        fail("automation/recipients.json ne contient aucun destinataire.")
    return recipients


# ---------------------------------------------------------------------------
# Persistent anti-repetition archive (known_topics.json)
#
# Replaces comparing against last_email.html (one HTML snapshot, mostly
# markup, only one week deep — weak signal) with a structured, ever-growing
# registry of every topic the pipeline has ever reported, updated (not
# overwritten) on every successful run. Far more reliable for the model to
# parse, and it remembers further back than one week.
# ---------------------------------------------------------------------------

KNOWN_TOPICS_PATH = STATE_DIR / "known_topics.json"


def _topic_key(title: str) -> str:
    """Normalise a title into a stable matching key — lowercase, accents and
    punctuation stripped, whitespace collapsed. Approximate on purpose: exact
    fuzzy matching isn't worth the complexity here, this only needs to catch
    the same topic reworded slightly week to week."""
    import unicodedata
    normalized = unicodedata.normalize("NFKD", title or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug[:80]


def load_known_topics() -> list:
    if KNOWN_TOPICS_PATH.exists():
        try:
            return json.loads(KNOWN_TOPICS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("(non bloquant) known_topics.json illisible — anti-répétition redémarre à vide pour ce run.")
    return []


def build_known_topics_digest(topics: list, limit: int = 150) -> str:
    """Compact one-liner-per-topic digest for the content prompt — title,
    last known status, and when it was last reported. Capped to the most
    recently-seen N topics so this can't grow unbounded over months/years."""
    if not topics:
        return "(aucune édition précédente — première exécution)"
    ordered = sorted(topics, key=lambda t: t.get("last_seen", ""), reverse=True)[:limit]
    lines = [
        f"- {t.get('title')} (statut: {t.get('last_status', '?')}, vu le {t.get('last_seen', '?')})"
        for t in ordered
    ]
    return "\n".join(lines)


def merge_known_topics(topics: list, items: list, today_str: str) -> list:
    """Fold this run's items into the persistent registry: update the
    matching entry's last_status/last_seen if the topic was already known,
    else append it as new. Never deletes — the registry only ever grows.

    Matches on title-key first, falling back to source_url — a topic whose
    title gets reworded slightly week to week (very possible, titles are
    freshly generated each run, not pulled from a fixed canonical source)
    will still often share the same source_url, catching what the title-only
    match would miss."""
    by_key = {t["key"]: t for t in topics if "key" in t}
    by_url = {t["source_url"]: t for t in topics if t.get("source_url")}
    for item in items:
        key = _topic_key(item.get("title", ""))
        url = item.get("source_url", "")
        if not key:
            continue
        existing = by_key.get(key) or (by_url.get(url) if url else None)
        if existing:
            existing["last_status"] = item.get("status", existing.get("last_status"))
            existing["last_seen"] = today_str
            if url:
                existing["source_url"] = url
                by_url[url] = existing
            by_key[key] = existing
        else:
            new_entry = {
                "key": key,
                "title": item.get("title", ""),
                "last_status": item.get("status", "ongoing"),
                "source_url": url,
                "first_seen": today_str,
                "last_seen": today_str,
            }
            by_key[key] = new_entry
            if url:
                by_url[url] = new_entry
            topics.append(new_entry)
    return topics


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

            # Extract real article links BEFORE stripping tags for the text
            # dump below. Without this, the model only ever sees this page's
            # own URL in its context and cites that generic landing page for
            # every item sourced from it, instead of the specific article —
            # confirmed in practice (every item from a given fixed source
            # pointing to the same "/veille/" listing URL).
            source_domain = urlparse(url).netloc
            seen_links = set()
            links = []
            for a in soup.find_all("a", href=True):
                label = a.get_text(strip=True)
                if not label or len(label) < 12:
                    continue  # skips nav items like "Accueil", icons, etc.
                href = urljoin(url, a["href"])
                if not href.startswith("http") or urlparse(href).netloc != source_domain:
                    continue  # keep only specific pages on this same source
                if href in seen_links:
                    continue
                seen_links.add(href)
                links.append(f"- {label[:120]} -> {href}")
            links_blob = "\n".join(links[:30])

            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            # Cap per-source length to keep the writing-model prompt manageable — a
            # smaller prompt also reduces the model's tendency to try to cover
            # everything at length (see TRIAGE_SYSTEM_PROMPT hard item cap).
            chunk = f"--- SOURCE: {url} ---\n{text[:2500]}"
            if links_blob:
                chunk += (
                    f"\n\nLiens specifiques trouves sur cette page (utilise le lien le "
                    f"plus pertinent pour chaque item ci-dessus ; ne cite l'URL de la "
                    f"page elle-meme ({url}) qu'en dernier recours, si aucun lien "
                    f"specifique ne correspond) :\n{links_blob}"
                )
            chunks.append(chunk)
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
    for i, query in enumerate(SONAR_QUERIES, start=1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": f"{query}. Focus on developments from the last 7 days only "
                                f"(today is {date.today().isoformat()}). Cite source URLs.",
                }],
            )
            answer = resp.choices[0].message.content or ""
            answers.append(f"Q: {query}\n{answer}")
            log(f"  Sonar {i}/{len(SONAR_QUERIES)} OK ({len(answer)} caractères) — {query[:60]}")
        except Exception as e:  # noqa: BLE001
            log(f"  Sonar {i}/{len(SONAR_QUERIES)} ÉCHEC — {query[:60]} : {e}")
    return "\n\n".join(answers)


# ---------------------------------------------------------------------------
# Step 3: writing — split into many small calls, each far under the gateway's
# 300s duration cap: triage (selection + key facts, no prose), then one tiny
# prose call per item, then proposals EN, then one tiny translation call per
# proposal card. A cut chunk retries alone; a definitively failed chunk falls
# back gracefully instead of killing the run.
# ---------------------------------------------------------------------------

TRIAGE_SYSTEM_PROMPT = f"""You are an expert QARA (Quality Assurance & Regulatory Affairs) consultant
specialised in Medical Device Software (MDSW) in the EU, working for Theodo HealthTech.

## YOUR JOB — TRIAGE ONLY, NO PROSE
You are the FIRST stage of a pipeline: you SELECT and STRUCTURE this week's material
developments; a separate stage writes the editorial prose from your output, one item at a
time, WITHOUT seeing the research. So produce ONLY the JSON skeleton below — no HTML, no
summary sentences, no editorial prose. For each item, give factual "key_facts" bullets
(exact dates, actors, references, deadlines, what precisely changed, concrete next step if
obvious) precise and self-sufficient enough that a writer who has never seen the research
can write the item from them alone.

## EDITORIAL MANDATE
Audience: busy QARA leads and C-levels. This is a weekly digest, not an exhaustive dump, but be
substantive on anything that genuinely moved. EU first; other regions only if genuinely major
(else skip or one line). This EU-first rule applies to the detailed body (the "items" list),
NOT to "essentiel": that field is read first, by everyone, and must reflect whatever mattered
most this week regardless of region — you are given the full research for every region below, so
scan all of it (not just EU material) before writing "essentiel". If the single biggest
development of the week happened outside the EU, it belongs in "essentiel" even though the rest
of the email body stays EU-focused. Never repeat a previously-reported topic without a material
development since — the structured archive of previously reported topics is given below, check it
before writing (it goes back further than just last week, so check it rather than assuming
something is new just because you haven't personally seen it this run).

STANDING ITEM WITH NO CHANGE THIS WEEK: if a topic already in the previously-reported archive has no
material development since, DO NOT create an item for it and do not mention it in "essentiel" —
leave it out of the body entirely. It is only eligible for a one-liner in "points_vigilance", and
only if its next deadline falls within roughly 60 days. Silence on an unchanged topic is correct,
not a gap to fill.

REGION TAGGING — "eu" is broader than EU institutions: international/global standards bodies
(IMDRF, ISO, IEC) whose work feeds directly into EU compliance (e.g. MDR-referenced harmonized
standards, IMDRF guidance that shapes MDCG documents) belong in region "eu", framed through "what
this means for an EU manufacturer" — not in "uk"/"us"/"other". Reserve "uk"/"us"/"other" for
genuinely country-specific regulatory action (MHRA, FDA, TGA, etc.) that does not automatically
apply in the EU.

CRITICAL — temporal accuracy: today's date is given below. Before describing any item, compare
its date/deadline to today. If the date is in the FUTURE, describe it as upcoming/scheduled
("entrera en vigueur le...", "sera publié le...") — never as already done ("est entré en
vigueur", "a été publié") just because it's in this week's source material. Source material
(including the existing timeline milestones) legitimately includes future-dated items; your job
is to report their status accurately, not to imply they already happened.

Language: the reader-facing fields you write ("essentiel", "points_vigilance", "title") are in
FRENCH, native register (not translated English). Banned calques: "actionnable", "re-actionner",
"En 60 secondes", "Sur le radar", "atteindre le seuil", "reprise du stock" (write "rattrapage /
enregistrement du stock existant"). No em dashes anywhere, ever. "essentiel" may stay
compact/headline-style; "points_vigilance" must be complete French sentences with their
articles. "key_facts" are working notes for the next stage, not reader-facing: any language,
but every fact must be dated and attributed.

## STANDARDS REGISTER (for reference — do not reproduce this table; only report rows that
genuinely moved this week, by their exact "reference" string, in standards_changed)
{_standards_register_for_prompt()}

## JSON SCHEMA — every field below is required unless marked optional
{{
  "essentiel": ["3-5 short one-line highlights spanning ALL regions this week (EU, UK, US, other) — not EU-only, or one honest line if quiet. Each bullet covers a DISTINCT fact: never two bullets about the same development, even worded differently"],
  "priority_banner": "one line, ONLY if a genuine new/imminent CRITIQUE or ELEVE deadline exists, else null",
  "items": [
    {{
      "region": "eu | uk | us | other",
      "title": "short French headline, no HTML",
      "key_facts": ["3-6 factual bullets: what exactly changed, exact dates, actors, references, deadlines, concrete next step if obvious — self-sufficient, the writer sees ONLY these"],
      "priority": "critical | high | medium",
      "status": "new | in-force | draft | ongoing | final | withdrawn",
      "source_label": "short source name, e.g. CNIL",
      "source_url": "https://..."
    }}
  ],
  "points_vigilance": ["max 3 items, each a complete French sentence with articles (not a telegraphic fragment): standing items with a deadline within ~60 days"],
  "standards_changed": [
    {{"reference": "must exactly match a 'reference' from the register above", "note": "what changed this week, 1 sentence"}}
  ]
}}

## EXAMPLE ITEM — this is the key_facts precision to match (dated, attributed, self-sufficient)
{{
  "region": "eu",
  "title": "MDCG 2025-9 : nouvelles lignes directrices sur les logiciels autonomes",
  "key_facts": [
    "European Commission published a revised MDCG 2025-9 on 15 July 2026 (source: MDCG page)",
    "Scope: qualification of standalone software as medical devices under MDR",
    "New: use-case-based analysis grid replaces qualification by declared intended purpose alone",
    "Impact: files combining several functions must re-examine classification",
    "Deadline pressure: re-examination needed before any Q3 2026 submission"
  ],
  "priority": "high",
  "status": "new",
  "source_label": "MDCG",
  "source_url": "https://health.ec.europa.eu/example-mdcg-2025-9"
}}

Guidance on "items": typically 4-10 items total across all regions combined (fewer on a quiet
week, more on a busy one — do not force a count). HARD CAP: never exceed 20 items — beyond
that, keep the 20 most impactful. This cap is editorial (email readability), not technical:
each item costs you only a few key_facts lines, so never shorten key_facts to fit more items
in. Order does not matter, the region field handles sorting. Every item needs a real,
clickable source_url — when the source material includes a "Liens specifiques trouves sur
cette page" list, use the specific article link from it, not the source's generic
homepage/listing URL (that generic URL is only a fallback for items where no specific link
matches).

## OUTPUT FORMAT
Output the JSON object and NOTHING else — no markers, no markdown code fences, no text
before the opening brace or after the closing brace.
"""

ITEM_WRITE_SYSTEM_PROMPT = """You are an expert QARA (Quality Assurance & Regulatory Affairs)
consultant writing Theodo HealthTech's weekly regulatory digest (audience: busy QARA leads and
C-levels). You receive ONE item as JSON: region, title, priority, status, source, and factual
"key_facts" bullets selected by an editor. Write the French prose for this single item.

## RULES
- FRENCH, native register (not translated English). Banned calques: "actionnable",
  "re-actionner", "atteindre le seuil", "reprise du stock". No em dashes anywhere, ever.
- Complete, grammatical sentences: every noun needs its article ("le", "la", "les", "des",
  "du"), normal connectors ("qui", "donc", "avant de"). Dropping articles on regulatory noun
  phrases is a common mistake — avoid it:
  WRONG: "MDCG 2026-4 finalise juin 2026 clarifie gestion SSCP dans EUDAMED."
  RIGHT: "Le MDCG 2026-4, finalise en juin 2026, clarifie la gestion des SSCP dans EUDAMED."
- Tone: factual, action-oriented. Cut marketing/filler adjectives ("innovant", "majeur",
  "crucial") — do NOT cut articles, prepositions, or connecting words.
- Temporal accuracy: compare every date in key_facts to today's date (given in the input).
  A FUTURE date is described as upcoming ("entrera en vigueur le...", "sera publié le..."),
  never as already done.
- Use ONLY the facts provided — never invent numbers, dates, or details absent from key_facts.

## OUTPUT — a single JSON object, nothing else, no markdown code fences
{"summary": "1-2 sentences for the email — what changed, so what",
 "detail": "3-6 sentences for the report — what changed, why it matters, concrete next step for a QARA lead"}
"""

TRANSLATE_SYSTEM_PROMPT = """You translate regulatory timeline card fields from English to
French. Input: a JSON object {"t": "...", "x": "...", "l": "..."} (title, one-sentence
description, short date label).

Rules: native French register, no calques, no em dashes. Keep acronyms and references (MDCG,
EUDAMED, MDR, prEN 18286...) unchanged. "l" is a short date label — French format with the
month in lowercase: "23 May 2026" -> "23 mai 2026", "Aug 2026" -> "août 2026", "Q4 2026" ->
"T4 2026".

OUTPUT: the same JSON object with the three field values translated, nothing else, no markdown
code fences.
"""

PROPOSALS_SYSTEM_PROMPT = f"""You are an expert QARA (Quality Assurance & Regulatory Affairs) consultant
producing structured timeline-update proposals for Theodo HealthTech's public MDSW regulatory
timeline. You are given this week's full regulatory-watch report (already written) and the
existing timeline milestones. Your only job here is to turn genuinely material developments
from the report into ADD/UPDATE/DELETE proposals — do not re-research, do not add anything not
already in the report below.

## RULES
Only genuinely material developments (typically 2-8 items total; skip cosmetic or non-material
changes — most weeks do NOT need 8). HARD CAP: never exceed 10 proposals total, even in an
exceptionally active week — this is a length constraint, not a quality target. If more than 10
items are genuinely material, keep the 10 most impactful (biggest regulatory/business impact,
nearest deadlines first) and drop the rest entirely rather than including them in shortened form.
It is far better to fully complete 10 well-formed proposals than to start an 11th and run out of
room. Keep "reason" and card "x" tight (1-2 short sentences, no padding) so the JSON stays compact
regardless of item count. Stable id format: "YYYY-MM-DD--lowercase-english-slug"
(double dash, max 50 chars), identical between EN and FR. Valid topics: {VALID_TOPICS}.
Valid tags: {VALID_TAGS}. Valid variants: {VALID_VARIANTS} (c=critical/navy, h=highlight/gold,
n=normal). Action value must be lowercase: "add", "update", or "delete" — never uppercase.

CHOOSING THE ACTION — the timeline is a CHRONOLOGY, not a status board: each card is a
milestone that happened (or is scheduled) at its date. Use "update" ONLY to correct or refresh
the SAME milestone: status/tag change (e.g. draft -> in-force once its date has passed), date
shift, corrected or added deadline, tightened wording. NEVER repurpose an existing card to
describe a NEW development: if something new happened (new publication, new decision, new
package), propose "add" with its own date and leave the old milestone intact. Litmus test: if
your new "x" description contradicts or replaces the SUBJECT of the old one instead of refining
it, it must be an "add". One development = one proposal: never fold several distinct
developments into a single card's description. When updating, preserve the informative content
of the existing description (module lists, references, requirements like SRN) and change only
what actually changed — extend, don't erase.

EVERY proposal object, whatever the action, MUST have BOTH a top-level "id" field AND a
top-level "reason" field — these two are never optional, never skip either one even when it
feels redundant with "card":
- action="add": "id" is a brand new stable slug (format above); no "existing_id". "reason"
  explains why this is being added (can echo card.x, that's fine).
- action="update" or "delete": "id" MUST be set to the EXACT SAME VALUE as "existing_id" (repeat
  it — do not omit "id" just because the item already exists). "existing_id" must match an id
  already present in the existing timeline milestones given below. "reason" explains what
  changed / why it's being removed.

Produce ENGLISH ONLY — the French version is generated separately by a translation stage,
never by you. Keep "reason" and "x" (card description) concise — 1-2 sentences, not a
paragraph.

## EXAMPLE — every field shown here is mandatory on every proposal, copy this exact shape
{{
  "generated": "2026-07-20",
  "proposals": [
    {{
      "action": "add",
      "id": "2026-07-20--example-new-guidance-published",
      "reason": "New MDCG guidance clarifies X, directly affects MDSW classification.",
      "card": {{
        "id": "2026-07-20--example-new-guidance-published", "d": "2026-07-20", "l": "20 Jul 2026",
        "y": 2026, "t": "Example New Guidance Published", "x": "One-sentence description of the change.",
        "u": "https://example.org/source", "tp": ["mdr"], "tg": ["new", "high"], "v": "h"
      }}
    }},
    {{
      "action": "update",
      "id": "2026-05-28--eudamed-first-4-modules-mandatory",
      "existing_id": "2026-05-28--eudamed-first-4-modules-mandatory",
      "reason": "Deadline confirmed, status moved from proposed to in-force.",
      "card": {{
        "id": "2026-05-28--eudamed-first-4-modules-mandatory", "d": "2026-05-28", "l": "28 May 2026",
        "y": 2026, "t": "EUDAMED - First 4 Modules Mandatory", "x": "Updated status: now in mandatory use.",
        "u": "https://example.org/source", "tp": ["mdr"], "tg": ["critical", "in-force"], "v": "c"
      }}
    }}
  ]
}}

## OUTPUT FORMAT
Output a single JSON object {{"generated": "YYYY-MM-DD", "proposals": [...]}} and NOTHING
else — no markers, no markdown code fences, no text before or after the JSON.
"""


class ChunkCallError(Exception):
    """Un petit appel LLM a échoué (timeout, coupure, JSON invalide) après
    épuisement de ses retries. C'est l'APPELANT qui décide de la suite : fail()
    dur pour les étapes indispensables (triage, propositions EN), repli
    gracieux pour les étapes par morceau (prose d'un item, traduction d'une
    carte) — un morceau perdu ne doit jamais tuer tout le run."""


def run_model_call(
    client: OpenAI, model: str, system_prompt: str, user_content: str, label: str,
    max_tokens: int = 16000,
) -> tuple:
    """Shared low-level streaming call. Returns (content, finish_reason);
    raises ChunkCallError on a stalled stream instead of exiting, so callers
    (call_json) can retry just this chunk.

    max_tokens is deliberately kept much lower than the model's real ceiling:
    it acts as a hard, deterministic backstop so a call that ignores the
    length guidance in the prompt fails fast and clearly (finish_reason=
    "length") instead of silently running into the gateway's 300s duration
    cutoff (measured — see automation/tools/gateway_cap_probe.py; note the
    gateway sometimes disguises that cutoff as finish_reason="stop", so JSON
    validity downstream is the only reliable truncation detector)."""
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
        raise ChunkCallError(f"Modèle bloqué ({label}) : aucune donnée reçue pendant plus de 90s.")

    content = "".join(chunks)
    log(f"{label} terminé — finish_reason={finish_reason}, longueur={len(content)} caractères.")
    if finish_reason == "length":
        log(
            f"  ATTENTION ({label}) : coupé par max_tokens={max_tokens}, pas par le modèle "
            f"lui-même — le contenu est probablement incomplet."
        )
    return content, finish_reason


def _strip_code_fences(text: str) -> str:
    """Le modèle emballe parfois sa sortie dans ```json ... ``` malgré
    l'interdiction explicite — on retire la fence plutôt que d'échouer."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


def call_json(
    client: OpenAI, model: str, system_prompt: str, user_content: str, label: str,
    max_tokens: int, retries: int = 2,
):
    """Petit appel LLM à sortie JSON directe (sans marqueurs), avec retries.

    C'est la brique de base du pipeline découpé : chaque appel génère peu de
    tokens (donc passe loin sous le cap de 300s du gateway), et un appel coupé
    ou mal formé se retry SEUL — on ne re-paye jamais les autres morceaux.
    Considère comme échec : flux bloqué, finish_reason=length, JSON invalide
    (seul détecteur fiable d'une coupure gateway déguisée en "stop"), erreur
    API (429/5xx). Lève ChunkCallError après épuisement des retries."""
    last_error = ""
    for attempt in range(1, retries + 2):
        try:
            raw, finish_reason = run_model_call(
                client, model, system_prompt, user_content,
                f"{label} (essai {attempt})", max_tokens=max_tokens,
            )
            if finish_reason == "length":
                raise ChunkCallError(f"coupé par max_tokens={max_tokens}")
            return json.loads(_strip_stray_markers(_strip_code_fences(raw)))
        except (ChunkCallError, json.JSONDecodeError) as e:
            last_error = f"{type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001 — erreurs API/réseau (429, 5xx...)
            last_error = f"{type(e).__name__}: {e}"
        if attempt <= retries:
            wait = 2 if attempt == 1 else 5
            log(f"  {label}: échec essai {attempt} ({last_error[:200]}) — nouvel essai dans {wait}s.")
            time.sleep(wait)
    raise ChunkCallError(f"{label}: échec après {retries + 1} essais — {last_error[:300]}")


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


def _strip_stray_markers(text: str) -> str:
    """The model sometimes invents its own closing marker (seen in real runs:
    "===END_EMAIL===", "===END_REPORT===") that isn't one of ours. Since our
    marker regex captures everything up to the next REAL marker, any such
    invented marker ends up swallowed into the extracted content and would
    leak into the actual sent email/report. Strip any standalone "===...==="
    line defensively rather than relying on the model never doing this again."""
    return re.sub(r"(?m)^\s*={3,}[A-Za-z0-9_ ]+={3,}\s*$\n?", "", text).strip()


def extract_content_json_raw(raw: str) -> str:
    """Pull the JSON text out from between the markers. Content itself is
    validated/parsed separately by validate_content_json()."""
    save_debug_output(raw, "content")
    pattern = re.escape(CONTENT_MARKER) + r"(.*?)" + re.escape(END_MARKER)
    m = re.search(pattern, raw, re.DOTALL)
    if not m:
        _fail_missing_markers(
            raw, [CONTENT_MARKER, END_MARKER],
            "debug_last_content_output.txt", "contenu (JSON)",
        )
    return _strip_stray_markers(m.group(1))


def split_proposals_sections(raw: str) -> dict:
    save_debug_output(raw, "proposals")
    pattern = re.escape(PROPOSALS_EN_MARKER) + r"(.*?)" + re.escape(PROPOSALS_FR_MARKER) + r"(.*?)" + re.escape(END_MARKER)
    m = re.search(pattern, raw, re.DOTALL)
    if not m:
        _fail_missing_markers(
            raw, [PROPOSALS_EN_MARKER, PROPOSALS_FR_MARKER, END_MARKER],
            "debug_last_proposals_output.txt", "propositions",
        )
    proposals_en_raw, proposals_fr_raw = (_strip_stray_markers(s) for s in m.groups())
    return {"proposals_en_raw": proposals_en_raw, "proposals_fr_raw": proposals_fr_raw}


MAX_ITEMS = 20  # garde-fou éditorial (lisibilité email), plus une contrainte technique


def run_triage(client: OpenAI, model: str, user_content: str) -> dict:
    """Étape 3a : sélection des items + faits clés, sans prose. Indispensable :
    sans triage il n'y a pas de run, donc échec = fail() dur."""
    try:
        triage = call_json(client, model, TRIAGE_SYSTEM_PROMPT, user_content, "Triage", max_tokens=6000)
    except ChunkCallError as e:
        fail(f"Triage impossible : {e}")
    if not isinstance(triage, dict):
        fail("Triage : structure racine invalide (attendu un objet JSON).")
    items = triage.get("items") or []
    if len(items) > MAX_ITEMS:
        log(f"Triage : {len(items)} items dépassent le cap de {MAX_ITEMS} — seuls les {MAX_ITEMS} premiers sont gardés.")
        triage["items"] = items[:MAX_ITEMS]
    return triage


def write_item_prose(client: OpenAI, model: str, items: list, today_str: str) -> None:
    """Étape 3b : un petit appel par item (~300 tokens de sortie, ~10s), qui
    transforme les key_facts en summary/detail. Un item qui échoue après
    retries est publié en repli sur ses faits bruts (avec warning) plutôt que
    de faire échouer le run — c'est tout l'intérêt du découpage."""
    total = len(items)
    for i, item in enumerate(items, start=1):
        payload = {
            k: item.get(k)
            for k in ("region", "title", "priority", "status", "source_label", "source_url", "key_facts")
        }
        user_content = (
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            f"Today's date: {today_str}."
        )
        title_short = str(item.get("title", ""))[:60]
        try:
            written = call_json(
                client, model, ITEM_WRITE_SYSTEM_PROMPT, user_content,
                f"Item {i}/{total} « {title_short} »", max_tokens=700,
            )
            summary = str(written.get("summary") or "").strip()
            detail = str(written.get("detail") or "").strip()
            if not summary:
                raise ChunkCallError("summary vide dans la réponse")
            item["summary"] = summary
            item["detail"] = detail or summary
        except ChunkCallError as e:
            facts = [str(f).strip() for f in (item.get("key_facts") or []) if str(f).strip()]
            fallback = " ".join(facts) or str(item.get("title", ""))
            item["summary"] = " ".join(facts[:2]) or fallback
            item["detail"] = fallback
            log(f"  ATTENTION: rédaction échouée pour « {title_short} » ({e}) — repli sur les faits bruts.")
        # Notes de travail internes : jamais rendues dans l'email/rapport.
        item.pop("key_facts", None)


def prefix_proposal_ids(proposals: dict, today_str: str) -> None:
    """Ids de proposition uniques par lot hebdomadaire : proposal-{date}--{slug}.

    Sans ce préfixe, l'id d'une proposition est l'id de la carte elle-même :
    une proposition re-générée une semaine suivante sur la même carte porte
    alors le même id qu'une proposition déjà présente dans
    decisions.json.approved_proposals/rejected_proposals — et le site public la
    fusionnerait (ou l'enterrerait) automatiquement, SANS repasser par la revue
    humaine du back office. card.id et existing_id, eux, restent stables.
    Idempotent : un id déjà préfixé (replay d'un cache) n'est pas re-préfixé."""
    for p in proposals["proposals"]:
        pid = str(p["id"])
        if not pid.startswith("proposal-"):
            p["id"] = f"proposal-{today_str}--{pid}"


def translate_proposals_fr(client: OpenAI, model: str, proposals_en: dict) -> dict:
    """Étape 3d : version FR construite par COPIE de l'EN — id, action,
    existing_id, card.id/d/y/u/tp/tg/v et reason sont identiques par
    construction (la parité EN/FR n'est plus une promesse du modèle, c'est un
    invariant du code). Seuls card.t/x/l sont traduits, par un mini-appel par
    carte ; une traduction qui échoue garde le texte EN (dégradé acceptable,
    l'admin peut éditer) plutôt que de faire échouer le run."""
    import copy
    proposals_fr = copy.deepcopy(proposals_en)
    with_card = [p for p in proposals_fr["proposals"] if p.get("card")]
    total = len(with_card)
    for i, p in enumerate(with_card, start=1):
        card = p["card"]
        payload = {"t": card.get("t", ""), "x": card.get("x", ""), "l": card.get("l", "")}
        try:
            out = call_json(
                client, model, TRANSLATE_SYSTEM_PROMPT,
                json.dumps(payload, ensure_ascii=False),
                f"Traduction FR {i}/{total}", max_tokens=300,
            )
            for field in ("t", "x", "l"):
                value = str(out.get(field) or "").strip()
                if value:
                    card[field] = value
        except ChunkCallError as e:
            log(f"  ATTENTION: traduction FR échouée pour {p['id']} ({e}) — texte EN conservé.")
    return proposals_fr


# ---------------------------------------------------------------------------
# Step 4: strict validation — never push something that could break the site
# ---------------------------------------------------------------------------

VALID_REGIONS = ["eu", "uk", "us", "other"]
VALID_PRIORITIES = ["critical", "high", "medium"]
VALID_STATUSES = ["new", "in-force", "draft", "ongoing", "final", "withdrawn"]


def validate_content_json(raw: str) -> dict:
    """Structural validation for the content JSON (email/report source
    material). Less safety-critical than proposals (nothing here writes to
    the public data files), but still fails loudly rather than rendering a
    broken email/report from malformed data."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"JSON contenu invalide ({e}). Voir automation/state/debug_last_content_output.txt.")

    if not isinstance(parsed, dict):
        fail("JSON contenu : structure racine invalide (attendu un objet).")

    parsed.setdefault("essentiel", [])
    parsed.setdefault("priority_banner", None)
    parsed.setdefault("items", [])
    parsed.setdefault("points_vigilance", [])
    parsed.setdefault("standards_changed", [])

    if not isinstance(parsed["items"], list):
        fail("JSON contenu : 'items' doit être une liste.")

    valid_reference_set = {row["reference"] for row in STANDARDS_REGISTER}

    for item in parsed["items"]:
        log_item = lambda: log(f"Item problématique: {json.dumps(item, ensure_ascii=False)[:800]}")  # noqa: E731
        if item.get("region") not in VALID_REGIONS:
            log_item()
            fail(f"JSON contenu : region invalide ({item.get('region')!r}) sur un item.")
        if not item.get("title") or not item.get("summary"):
            log_item()
            fail("JSON contenu : item sans title ou summary.")
        # Filet de sécurité : "detail" est censé être la version longue pour le
        # rapport — si le modèle l'a omis (redondant avec summary à ses yeux),
        # on retombe sur summary plutôt que d'échouer sur un champ cosmétique.
        if not item.get("detail"):
            item["detail"] = item["summary"]
        item["priority"] = str(item.get("priority", "medium")).lower()
        if item["priority"] not in VALID_PRIORITIES:
            item["priority"] = "medium"
        item["status"] = str(item.get("status", "ongoing")).lower()
        if item["status"] not in VALID_STATUSES:
            item["status"] = "ongoing"
        if not item.get("source_url"):
            log_item()
            fail("JSON contenu : item sans source_url.")

    for row in parsed["standards_changed"]:
        if row.get("reference") not in valid_reference_set:
            log(f"Standards_changed ignoré (reference inconnue): {json.dumps(row, ensure_ascii=False)[:300]}")
    parsed["standards_changed"] = [
        row for row in parsed["standards_changed"] if row.get("reference") in valid_reference_set
    ]

    return parsed


def build_content_digest(content: dict) -> str:
    """Plain-text digest of the validated content JSON, fed to the proposals
    call as "this week's report" instead of raw HTML. Cheaper and cleaner
    than re-sending the rendered report."""
    lines = []
    if content.get("essentiel"):
        lines.append("## Essentiel de la semaine")
        for line in content["essentiel"]:
            lines.append(f"- {line}")
        lines.append("")
    if content.get("priority_banner"):
        lines.append(f"## Alerte prioritaire\n{content['priority_banner']}\n")
    lines.append("## Items")
    for item in content.get("items", []):
        lines.append(
            f"- [{item.get('region')}] {item.get('title')} "
            f"(priorité={item.get('priority')}, statut={item.get('status')})\n"
            f"  {item.get('detail') or item.get('summary')}\n"
            f"  Source: {item.get('source_label') or item.get('source_url')} — {item.get('source_url')}"
        )
    lines.append("")
    if content.get("points_vigilance"):
        lines.append("## Points de vigilance")
        for p in content["points_vigilance"]:
            lines.append(f"- {p}")
        lines.append("")
    if content.get("standards_changed"):
        lines.append("## Normes modifiées")
        for row in content["standards_changed"]:
            lines.append(f"- {row.get('reference')}: {row.get('note')}")
    return "\n".join(lines)


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
        # Filet de sécurité : pour update/delete, le modèle omet parfois "id" en
        # pensant qu'"existing_id" suffit (vu en test réel). Sémantiquement, pour
        # ces deux actions "id" doit être identique à "existing_id" de toute façon
        # (voir PROPOSALS_SYSTEM_PROMPT) — donc on le déduit plutôt que d'échouer.
        if "id" not in p and action in ("update", "delete") and p.get("existing_id"):
            p["id"] = p["existing_id"]
        # Filet de sécurité : le modèle oublie parfois "reason" (vu en test réel,
        # cas différent du précédent) alors que "card.x" contient une description
        # équivalente — on la réutilise plutôt que d'échouer sur un champ redondant.
        if "reason" not in p and p.get("card", {}).get("x"):
            p["reason"] = p["card"]["x"]
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
# Step 4b: render branded HTML from the validated content JSON — this is now
# entirely Python's job, not the model's. It only ever produces the same
# fixed markup, so there is no risk of malformed HTML, invented markers, or
# runaway length: the model supplies text, this code supplies structure.
# Badges use display:inline-block (not flex) for Outlook compatibility.
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _badge(text: str, bg: str) -> str:
    return (
        f'<span style="display:inline-block; background-color:{bg}; color:#ffffff; '
        f'padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; margin-right:6px;">'
        f'{_esc(text)}</span>'
    )


def _source_link(item: dict) -> str:
    label = _esc(item.get("source_label") or "Source")
    url = item.get("source_url", "")
    return f'<a href="{_esc(url)}" style="color:#ff512c; text-decoration:none;">Source: {label}</a>'


PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2}


def _hors_ue_items(content: dict, limit: int = 3) -> list:
    """Up to `limit` non-EU items (uk/us/other), most urgent first — mirrors
    the legacy rule: "Hors UE" is a short, linked afterthought list, not a
    freeform summary paragraph. Built from the same "items" the model already
    produces, so every entry keeps its real source link."""
    non_eu = [it for it in content.get("items", []) if it.get("region") in ("uk", "us", "other")]
    non_eu.sort(key=lambda it: PRIORITY_RANK.get(it.get("priority"), 2))
    return non_eu[:limit]


def render_email_html(content: dict, week_label: str) -> str:
    essentiel = content.get("essentiel") or ["Aucune évolution notable cette semaine."]
    essentiel_html = "".join(f"<li>{_esc(b)}</li>" for b in essentiel)

    if content.get("priority_banner"):
        banner_html = (
            '<div style="background-color:#fff3e0; border-left:4px solid #e8850c; padding:12px 16px; '
            'border-radius:8px; margin-bottom:24px;">'
            f'<p style="color:#1c2837; font-size:12px; font-weight:600; margin:0;">'
            f'{_esc(content["priority_banner"])}</p></div>'
        )
    else:
        banner_html = (
            '<p style="color:#8a9099; font-size:12px; font-style:italic; margin:0 0 24px 0;">'
            'Aucune nouvelle echeance a traiter cette semaine ; voir les points de vigilance.</p>'
        )

    eu_items = [it for it in content.get("items", []) if it.get("region") == "eu"][:6]
    items_html = ""
    for it in eu_items:
        items_html += (
            '<div style="margin-bottom:20px; padding-bottom:16px; border-bottom:1px solid #e9ebee;">'
            f'<h3 style="color:#ff512c; font-size:13px; font-weight:700; margin:0 0 8px 0;">{_esc(it["title"])}</h3>'
            f'<p style="color:#1c2837; font-size:12px; margin:0 0 8px 0;">{_esc(it["summary"])}</p>'
            f'<div>{_badge(PRIORITY_LABELS.get(it["priority"], "MOYEN"), PRIORITY_COLORS.get(it["priority"], "#ff9500"))}'
            f'{_badge(STATUS_LABELS.get(it["status"], "EN COURS"), "#213045")}</div>'
            f'<p style="margin:8px 0 0 0; font-size:11px;">{_source_link(it)}</p>'
            '</div>'
        )

    hors_ue = _hors_ue_items(content)
    if hors_ue:
        hors_ue_html = ""
        for it in hors_ue:
            hors_ue_html += (
                '<div style="margin-bottom:12px;">'
                f'<p style="color:#1c2837; font-size:12px; margin:0 0 4px 0;">'
                f'<strong>{_esc(it["title"])}</strong> — {_esc(it["summary"])}</p>'
                f'<p style="margin:0; font-size:11px;">{_source_link(it)}</p>'
                '</div>'
            )
    else:
        hors_ue_html = '<p style="font-size:12px; color:#1c2837;">Aucune evolution notable hors UE cette semaine.</p>'

    vigilance = content.get("points_vigilance") or []
    vigilance_html = "".join(f"<li>{_esc(v)}</li>" for v in vigilance)
    vigilance_section = ""
    if vigilance_html:
        vigilance_section = (
            '<h2 style="color:#1c2837; font-size:16px; font-weight:700; margin:24px 0 16px 0; '
            'border-bottom:2px solid #ff512c; padding-bottom:8px;">Points de vigilance</h2>'
            f'<ul style="color:#1c2837; font-size:12px; line-height:1.8; margin:0; padding-left:20px;">{vigilance_html}</ul>'
        )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Veille reglementaire - Semaine du {_esc(week_label)}</title>
</head>
<body style="margin:0; padding:0; font-family:Poppins,Arial,Helvetica,sans-serif; background-color:#f3f3f3;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f3f3;">
<tr><td align="center" style="padding:20px 0;">
<table width="600" cellpadding="0" cellspacing="0" style="background-color:#1c2837; border-radius:12px; margin-bottom:20px;">
<tr><td style="padding:24px 20px;">
<h1 style="color:#ff512c; font-size:24px; margin:0 0 4px 0; font-weight:700;">Theodo HealthTech</h1>
<p style="color:#ffffff; font-size:14px; margin:0 0 12px 0;">Veille reglementaire</p>
<p style="color:#e9ebee; font-size:12px; margin:0;">Logiciels de dispositifs medicaux et AI Act</p>
<div style="background-color:#213045; display:inline-block; padding:4px 12px; border-radius:12px; margin-top:8px;">
<span style="color:#ff512c; font-size:11px; font-weight:600;">{_esc(week_label)}</span>
</div>
</td></tr>
</table>
<table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
<tr><td style="padding:24px;">
<h2 style="color:#1c2837; font-size:16px; font-weight:700; margin:0 0 16px 0; border-bottom:2px solid #ff512c; padding-bottom:8px;">L'essentiel de la semaine</h2>
<ul style="color:#1c2837; font-size:13px; line-height:1.8; margin:0 0 24px 0; padding-left:20px;">{essentiel_html}</ul>
{banner_html}
<h2 style="color:#1c2837; font-size:16px; font-weight:700; margin:0 0 16px 0; border-bottom:2px solid #ff512c; padding-bottom:8px;">UE et international</h2>
{items_html or '<p style="font-size:12px; color:#1c2837;">Aucune evolution notable cette semaine.</p>'}
<h2 style="color:#1c2837; font-size:16px; font-weight:700; margin:24px 0 16px 0; border-bottom:2px solid #ff512c; padding-bottom:8px;">Hors UE</h2>
{hors_ue_html}
{vigilance_section}
</td></tr>
</table>
<table width="600" cellpadding="0" cellspacing="0" style="background-color:#1c2837; border-radius:12px; margin-top:20px;">
<tr><td style="padding:20px; text-align:center;">
<p style="color:#e9ebee; font-size:11px; margin:0 0 8px 0;">Le rapport complet est joint en piece jointe.<br>
<a href="https://theodo-group.github.io/Compliance-timeline/admin.html" style="color:#ff512c; text-decoration:none; font-weight:600;">Consultez la feuille de route complete</a></p>
<p style="color:#b0b5ba; font-size:10px; margin:8px 0 0 0;">Cet email ne constitue pas un conseil juridique. Verifiez auprès de votre counsel avant action.</p>
<p style="color:#ff512c; font-weight:600; font-size:11px; margin:8px 0 0 0;">Theodo HealthTech</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_report_html(content: dict, week_label: str) -> str:
    def region_section(region_key: str, heading: str) -> str:
        items = [it for it in content.get("items", []) if it.get("region") == region_key]
        if not items:
            return f'<h3 style="color:#ff512c; font-size:15px; font-weight:700; margin:24px 0 12px 0;">{heading}</h3><p style="font-size:13px; color:#666;">Aucune evolution notable cette semaine.</p>'
        html = f'<h3 style="color:#ff512c; font-size:15px; font-weight:700; margin:24px 0 12px 0;">{heading}</h3>'
        for it in items:
            html += (
                f'<h4 style="color:#1c2837; font-size:14px; font-weight:700; margin:16px 0 8px 0;">{_esc(it["title"])}</h4>'
                f'<p style="font-size:13px; line-height:1.7; margin:0 0 8px 0;">{_esc(it["detail"])}</p>'
                f'<div>{_badge(PRIORITY_LABELS.get(it["priority"], "MOYEN"), PRIORITY_COLORS.get(it["priority"], "#ff9500"))}'
                f'{_badge(STATUS_LABELS.get(it["status"], "EN COURS"), "#213045")}</div>'
                f'<p style="font-size:12px; margin:8px 0 0 0;">{_source_link(it)}</p>'
            )
        return html

    changed_map = {row["reference"]: row["note"] for row in content.get("standards_changed", [])}
    annex_rows = ""
    unchanged_refs = []
    for row in STANDARDS_REGISTER:
        ref = row["reference"]
        if ref in changed_map:
            annex_rows += (
                '<tr style="border-bottom:1px solid #ddd; background-color:#fff3e0;">'
                f'<td style="padding:8px; font-size:12px;">{_esc(row["source"])}</td>'
                f'<td style="padding:8px; font-size:12px;">{_esc(ref)}</td>'
                f'<td style="padding:8px; font-size:12px;">{_esc(row["title"])}</td>'
                f'<td style="padding:8px; font-size:12px; font-weight:600;">{_esc(changed_map[ref])}</td>'
                '</tr>'
            )
        else:
            unchanged_refs.append(ref)

    unchanged_line = ""
    if unchanged_refs:
        unchanged_line = (
            f'<p style="font-size:11px; color:#b0b5ba; margin-top:16px;">Aucun changement cette semaine sur '
            f'les autres normes suivies ({_esc(", ".join(unchanged_refs))}).</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport complet - Veille QARA {_esc(week_label)}</title>
</head>
<body style="font-family:Poppins,Arial,Helvetica,sans-serif; margin:0; padding:20px; background-color:#f3f3f3; color:#1c2837;">
<div style="max-width:900px; margin:0 auto; background-color:#ffffff; padding:40px; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,0.1);">
<div style="border-bottom:3px solid #ff512c; padding-bottom:16px; margin-bottom:32px;">
<h1 style="color:#ff512c; font-size:28px; margin:0 0 8px 0;">Rapport de Veille Reglementaire</h1>
<p style="color:#666; font-size:13px; margin:0;">Logiciels de dispositifs medicaux, IA et conformite reglementaire<br>Semaine du {_esc(week_label)} | Theodo HealthTech</p>
</div>
<h2 style="color:#1c2837; font-size:20px; font-weight:700; margin:32px 0 20px 0; border-left:4px solid #ff512c; padding-left:12px;">1. UE et international</h2>
{region_section("eu", "Union europeenne")}
<h2 style="color:#1c2837; font-size:20px; font-weight:700; margin:32px 0 20px 0; border-left:4px solid #ff512c; padding-left:12px;">2. Royaume-Uni</h2>
{region_section("uk", "Royaume-Uni")}
<h2 style="color:#1c2837; font-size:20px; font-weight:700; margin:32px 0 20px 0; border-left:4px solid #ff512c; padding-left:12px;">3. Etats-Unis</h2>
{region_section("us", "Etats-Unis")}
<h2 style="color:#1c2837; font-size:20px; font-weight:700; margin:32px 0 20px 0; border-left:4px solid #ff512c; padding-left:12px;">4. Autres regions</h2>
{region_section("other", "Autres regions")}
<h2 style="color:#1c2837; font-size:20px; font-weight:700; margin:32px 0 20px 0; border-left:4px solid #ff512c; padding-left:12px;">5. Annexe : suivi des normes</h2>
<table style="width:100%; border-collapse:collapse; font-size:12px; line-height:1.6;">
<tr style="background-color:#f3f3f3; border-bottom:1px solid #ddd;">
<td style="padding:8px; font-weight:600; color:#1c2837;">Source</td>
<td style="padding:8px; font-weight:600; color:#1c2837;">Reference</td>
<td style="padding:8px; font-weight:600; color:#1c2837;">Titre</td>
<td style="padding:8px; font-weight:600; color:#1c2837;">Changement cette semaine</td>
</tr>
{annex_rows or '<tr><td colspan="4" style="padding:8px; font-size:12px;">Aucun changement cette semaine.</td></tr>'}
</table>
{unchanged_line}
<p style="font-size:11px; color:#b0b5ba; margin-top:24px; padding-top:16px; border-top:1px solid #e9ebee;">
Ce rapport ne constitue pas un conseil juridique. Consultez votre counsel avant action. Theodo HealthTech.
</p>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Step 5: send email
# ---------------------------------------------------------------------------

def send_email(email_body_html: str, full_report_html: str, recipients: list) -> None:
    import base64
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr

    # En DRY_RUN, on ne cherche jamais à envoyer réellement — donc pas besoin
    # d'exiger les identifiants Gmail, qui ne sont pas encore configurés tant
    # que la boîte mail dédiée (tâche #4/#5) n'existe pas.
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not is_dry_run() and (not gmail_address or not gmail_password):
        fail("GMAIL_ADDRESS / GMAIL_APP_PASSWORD manquant (secrets GitHub Actions).")

    today_str = format_date_fr(date.today())
    outer = MIMEMultipart("mixed")
    outer["To"] = ", ".join(recipients)
    outer["Subject"] = f"Veille reglementaire (focus UE) - Logiciels DM & AI Act - {today_str}"
    # Nom d'affichage seulement — l'adresse d'envoi reste celle du compte
    # Gmail authentifié (formataddr ne fait qu'ajouter le nom en clair devant).
    outer["From"] = (
        formataddr(("Regulatory Watch Tower", gmail_address))
        if gmail_address else "(dry-run, adresse non configurée)"
    )

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

def write_outputs(proposals_en: dict, proposals_fr: dict, email_body_html: str, full_report_html: str) -> None:
    (REPO_ROOT / "proposals.json").write_text(json.dumps(proposals_en, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPO_ROOT / "proposals-fr.json").write_text(json.dumps(proposals_fr, ensure_ascii=False, indent=2), encoding="utf-8")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "last_email.html").write_text(email_body_html, encoding="utf-8")
    # Fichier autonome, ouvrable directement dans un navigateur depuis l'artefact
    # du run — sinon le rapport complet ne vit que noyé dans le debug brut.
    (STATE_DIR / "last_full_report.html").write_text(full_report_html, encoding="utf-8")
    date_slug = date.today().strftime("%Y-%m-%d")
    (ARCHIVE_DIR / f"email-{date_slug}.html").write_text(email_body_html, encoding="utf-8")


def _git_push_with_rebase(max_attempts: int = 3) -> None:
    """git push avec rattrapage : si le remote a avancé pendant le run (~6 min
    de LLM pendant lesquelles l'admin peut pousser decisions.json, ou un humain
    n'importe quoi d'autre — vécu le 2026-07-22), un push nu est rejeté
    non-fast-forward. On rebase nos commits par-dessus et on retente.
    --autostash: les fichiers d'état modifiés mais pas encore committés
    (commit_state_for_qa passe après) ne doivent pas bloquer le rebase."""
    for attempt in range(1, max_attempts + 1):
        try:
            subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
            return
        except subprocess.CalledProcessError:
            if attempt == max_attempts:
                raise
            log(f"git push rejeté (essai {attempt}/{max_attempts}) — pull --rebase puis nouvel essai.")
            subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=REPO_ROOT, check=True)


def flag_rewritten_updates(proposals: dict, data_json: list) -> None:
    """Garde-fou déterministe contre le détournement d'un jalon existant : si la
    description proposée en update n'a presque aucun vocabulaire commun avec la
    description actuelle (Jaccard < 0.2), c'est très probablement un NOUVEAU
    développement déguisé en update (règle CHOOSING THE ACTION du prompt non
    respectée). On ne bloque pas — le modèle peut avoir raison — mais on
    préfixe le reason d'un flag visible dans le back office, à côté du diff."""
    by_id = {m["id"]: m for m in data_json if "id" in m}
    for p in proposals["proposals"]:
        if p.get("action") != "update" or not p.get("card"):
            continue
        old = by_id.get(p.get("existing_id"))
        if not old:
            continue
        old_words = set(re.findall(r"[a-zà-ÿ0-9]+", str(old.get("x", "")).lower()))
        new_words = set(re.findall(r"[a-zà-ÿ0-9]+", str(p["card"].get("x", "")).lower()))
        if not old_words or not new_words:
            continue
        overlap = len(old_words & new_words) / len(old_words | new_words)
        if overlap < 0.2:
            p["reason"] = (
                "[REVIEW: description entierement reecrite — verifier que ce n'est pas "
                "un nouveau jalon qui devrait etre un add] " + str(p.get("reason", ""))
            )
            log(
                f"  Proposition {p['id']}: recouvrement de description {int(overlap * 100)}% "
                f"— flag REVIEW ajouté pour la revue admin."
            )


def git_commit_and_push() -> None:
    """Publish site-critical files (proposals.json/-fr.json) — gated behind
    DRY_RUN, since these are what the public site and admin.html actually
    read. Diagnostic/QA files (automation/state: emails, full report,
    debug_last_*_output.txt) are committed separately by
    commit_state_for_qa(), unconditionally, so they're available for visual
    QA and REPLAY_* reruns even during a dry run."""
    if is_dry_run():
        log("DRY_RUN actif : pas de commit/push des propositions (fichiers publics).")
        return
    date_slug = date.today().strftime("%Y-%m-%d")
    subprocess.run(["git", "config", "user.name", "regulatory-watch-bot"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=REPO_ROOT, check=True)
    subprocess.run(
        ["git", "add", "proposals.json", "proposals-fr.json"],
        cwd=REPO_ROOT, check=True,
    )
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if result.returncode == 0:
        log("Rien à committer côté propositions (aucun changement).")
        return
    subprocess.run(
        ["git", "commit", "-m", f"Regulatory watch: proposals for {date_slug}"],
        cwd=REPO_ROOT, check=True,
    )
    _git_push_with_rebase()
    log("Changements poussés sur main.")


def commit_state_for_qa() -> None:
    """Always commit automation/state (emails, full report, debug dumps) —
    regardless of DRY_RUN. These never touch the public site/admin data, so
    there's no safety reason to gate them; keeping them in git (instead of
    only in the ephemeral workflow artifact) is what makes REPLAY_CONTENT /
    REPLAY_PROPOSALS possible on a fresh checkout, and lets you `git pull`
    and open last_email.html / last_full_report.html locally without
    downloading a zip each time."""
    subprocess.run(["git", "config", "user.name", "regulatory-watch-bot"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "add", "-f", "automation/state"], cwd=REPO_ROOT, check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if result.returncode == 0:
        log("Rien à committer côté état/diagnostic (aucun changement).")
        return
    date_slug = date.today().strftime("%Y-%m-%d")
    subprocess.run(
        ["git", "commit", "-m", f"Regulatory watch: état/diagnostic pour {date_slug}"],
        cwd=REPO_ROOT, check=True,
    )
    _git_push_with_rebase()
    log("État/diagnostic (automation/state) poussé sur main.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def safe_commit_state_for_qa() -> None:
    """Best-effort wrapper around commit_state_for_qa(): runs from a `finally`
    block, including after a failed run (fail() raises SystemExit), so debug
    dumps get committed even on failure — that's exactly when REPLAY_CONTENT/
    REPLAY_PROPOSALS are most useful (re-inspect a failing case without
    spending tokens again). Never let a git hiccup here mask the real error."""
    try:
        commit_state_for_qa()
    except Exception as e:  # noqa: BLE001
        log(f"(non bloquant) Échec du commit de automation/state pour QA/replay : {e}")


def main() -> None:
    log(f"Démarrage — dry_run={is_dry_run()}")
    config = load_config()
    recipients = load_recipients()
    data_json = load_json(REPO_ROOT / "data.json", [])
    known_topics = load_known_topics()
    client = get_litellm_client()

    try:
        _run(config, recipients, data_json, known_topics, client)
    finally:
        safe_commit_state_for_qa()

    log("Terminé avec succès.")


def _run(config: dict, recipients: list, data_json: list, known_topics: list, client: OpenAI) -> None:
    log(
        f"Modèles — recherche: {config['research_model']} / triage: {config['triage_model']} / "
        f"items: {config['item_model']} / propositions: {config['proposals_model']} / "
        f"traduction: {config['translate_model']}"
    )

    if skip_fixed_sources():
        log("Recherche — fetch des sources fixes SKIPPÉ (SKIP_FIXED_SOURCES=true, test rapide).")
        fixed_sources_blob = "(sources fixes non interrogées cette fois — SKIP_FIXED_SOURCES actif, test rapide)"
    else:
        log("Recherche — fetch des sources fixes...")
        fixed_sources_blob = fetch_fixed_sources()

    if skip_sonar():
        log("Recherche — requêtes Perplexity Sonar SKIPPÉES (SKIP_SONAR=true, test à coût zéro).")
        sonar_blob = "(recherche Sonar non interrogée cette fois — SKIP_SONAR actif, test à coût zéro)"
    else:
        log("Recherche — requêtes Perplexity Sonar...")
        sonar_blob = run_sonar_research(client, config["research_model"])
        log(f"Recherche Sonar terminée — {len(sonar_blob)} caractères récupérés sur {len(SONAR_QUERIES)} requêtes.")

    # No artificial cap here: input size was never the real constraint (Sonar
    # runs ~13k chars total, fixed sources max out around 30k — both trivial
    # for a model's context window). The old `[:18000]` cut on the
    # concatenation used to silently drop the entire "Recherche Sonar" section
    # (Sources fixes came first and could alone exceed 18k), which is the bug
    # Joseph found. Output length is controlled directly in the prompt (hard
    # item caps, length guidance), not by starving the input.
    research_blob = f"## Sources fixes\n{fixed_sources_blob}\n\n## Recherche Sonar\n{sonar_blob}"

    if replay_content():
        cached = STATE_DIR / "debug_last_content_output.txt"
        if not cached.exists():
            fail(
                "REPLAY_CONTENT=true mais automation/state/debug_last_content_output.txt "
                "n'existe pas dans ce checkout — lance un run réel une fois (sans REPLAY_CONTENT) "
                "pour le générer, il sera committé automatiquement, puis relance en replay."
            )
        log("Rédaction (email + rapport) REJOUÉE depuis le cache (REPLAY_CONTENT=true, aucun appel LLM).")
        content_json_raw = extract_content_json_raw(cached.read_text(encoding="utf-8"))
    elif skip_content_call():
        log("Rédaction (email + rapport) SKIPPÉE (SKIP_CONTENT_CALL=true, test rapide sur les propositions).")
        content_json_raw = json.dumps({
            "essentiel": ["(SKIP_CONTENT_CALL actif — pas de contenu réel généré)"],
            "priority_banner": None, "items": [], "points_vigilance": [],
            "standards_changed": [],
        })
    else:
        log("Rédaction — triage (sélection des items + faits clés, sans prose)...")
        known_topics_digest = build_known_topics_digest(known_topics)
        triage_user_content = (
            f"## Previously reported topics (structured archive — do not repeat unless something "
            f"genuinely changed since)\n{known_topics_digest}\n\n"
            f"## Fixed-source research\n{research_blob}\n\n"
            f"Today's date: {date.today().isoformat()}. Produce the triage JSON object in the "
            f"exact required format."
        )
        triage = run_triage(client, config["triage_model"], triage_user_content)
        items = triage.get("items") or []
        log(f"Triage terminé — {len(items)} item(s) retenu(s). Rédaction de la prose, item par item...")
        write_item_prose(client, config["item_model"], items, date.today().isoformat())
        content_json_raw = json.dumps(triage, ensure_ascii=False)
        # Cache replay conservé au format historique à marqueurs, pour que
        # REPLAY_CONTENT relise l'assemblage final via le même chemin qu'avant.
        save_debug_output(f"{CONTENT_MARKER}\n{content_json_raw}\n{END_MARKER}", "content")

    content = validate_content_json(content_json_raw)
    week_label = compute_week_label(date.today())
    email_body_html = render_email_html(content, week_label)
    full_report_html = render_report_html(content, week_label)

    # Fold this run's items into the persistent anti-repetition archive and
    # write it back — grows every run, never overwritten, so next week's
    # comparison isn't limited to a single previous edition.
    # JAMAIS en dry-run : un test enregistrerait ses items comme "déjà
    # couverts" alors qu'aucun destinataire ne les a reçus, et le vrai run
    # suivant les passerait sous silence (vécu : Swissdamed disparu après
    # deux dry-runs successifs). La mémoire ne reflète que ce qui a été
    # réellement envoyé.
    if is_dry_run():
        log(f"DRY_RUN actif : known_topics.json NON mis à jour ({len(content.get('items', []))} item(s) non enregistrés).")
    else:
        known_topics = merge_known_topics(known_topics, content.get("items", []), date.today().isoformat())
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        KNOWN_TOPICS_PATH.write_text(json.dumps(known_topics, ensure_ascii=False, indent=2), encoding="utf-8")

    if replay_proposals():
        cached = STATE_DIR / "debug_last_proposals_output.txt"
        if not cached.exists():
            fail(
                "REPLAY_PROPOSALS=true mais automation/state/debug_last_proposals_output.txt "
                "n'existe pas dans ce checkout — lance un run réel une fois (sans REPLAY_PROPOSALS) "
                "pour le générer, il sera committé automatiquement, puis relance en replay."
            )
        log("Rédaction (propositions) REJOUÉE depuis le cache (REPLAY_PROPOSALS=true, aucun appel LLM).")
        proposals_sections = split_proposals_sections(cached.read_text(encoding="utf-8"))
        proposals_en = validate_proposals_json(proposals_sections["proposals_en_raw"], "EN")
        proposals_fr = validate_proposals_json(proposals_sections["proposals_fr_raw"], "FR")
    else:
        log("Rédaction — appel au modèle (propositions EN)...")
        content_digest = build_content_digest(content)
        proposals_user_content = (
            f"## This week's content (already written — source of truth, do not re-research)\n"
            f"{content_digest[:15000]}\n\n"
            f"## Existing timeline milestones (data.json)\n{json.dumps(data_json, ensure_ascii=False)}\n\n"
            f"Today's date: {date.today().isoformat()}. Produce the proposals JSON object in "
            f"the exact required format."
        )
        try:
            proposals_en_parsed = call_json(
                client, config["proposals_model"], PROPOSALS_SYSTEM_PROMPT, proposals_user_content,
                "Propositions EN", max_tokens=8000,
            )
        except ChunkCallError as e:
            fail(f"Propositions EN impossibles : {e}")
        proposals_en = validate_proposals_json(json.dumps(proposals_en_parsed, ensure_ascii=False), "EN")
        # Jamais laissé à la main du modèle — c'est une donnée du run, pas du contenu.
        proposals_en["generated"] = date.today().isoformat()
        prefix_proposal_ids(proposals_en, date.today().isoformat())
        flag_rewritten_updates(proposals_en, data_json)
        log("Traduction FR des propositions, carte par carte...")
        proposals_fr = translate_proposals_fr(client, config["translate_model"], proposals_en)
        # Cache replay au format historique 3 marqueurs (état FINAL : ids déjà
        # préfixés, FR déjà traduite) — REPLAY_PROPOSALS le relit tel quel.
        save_debug_output(
            f"{PROPOSALS_EN_MARKER}\n{json.dumps(proposals_en, ensure_ascii=False)}\n"
            f"{PROPOSALS_FR_MARKER}\n{json.dumps(proposals_fr, ensure_ascii=False)}\n{END_MARKER}",
            "proposals",
        )

    log("Validation du JSON produit...")
    # Idempotent — ne re-préfixe pas ce qui l'est déjà ; couvre le replay d'un
    # cache antérieur au préfixage.
    prefix_proposal_ids(proposals_en, date.today().isoformat())
    prefix_proposal_ids(proposals_fr, date.today().isoformat())
    validate_unique_ids(proposals_en, "EN")
    validate_unique_ids(proposals_fr, "FR")
    validate_id_parity(proposals_en, proposals_fr)
    validate_existing_ids(proposals_en, data_json)
    validate_existing_ids(proposals_fr, data_json)
    log("JSON valide.")

    # Publier AVANT d'envoyer : si le push échoue, aucun destinataire n'a
    # encore reçu d'email pointant vers une timeline jamais mise à jour, et on
    # peut relancer le run sans envoyer de doublon (vécu le 2026-07-22 :
    # email parti, push rejeté, run en échec). L'inverse (push ok, email
    # échoué) est bénin : relancer n'aboutit qu'à un commit vide.
    write_outputs(proposals_en, proposals_fr, email_body_html, full_report_html)
    git_commit_and_push()
    send_email(email_body_html, full_report_html, recipients)


if __name__ == "__main__":
    main()
