# Architecture Document — MDSW Compliance Timeline

## Overview

The Compliance Timeline is a bilingual (EN/FR) regulatory watch system for Medical Device Software (MDSW) manufacturers. It consists of three subsystems:

1. **Public Timeline** — Two interactive web pages (English + French) displaying regulatory milestones from 2026 to 2030
2. **Back Office** — A single admin interface managing both languages: card visibility, bilingual comments, tag editing, and AI-generated proposal review
3. **Automated Regulatory Watch** — A weekly cron job that researches regulatory changes, sends a branded email report, and generates bilingual timeline update proposals

All admin decisions are persisted in `decisions.json` within the GitHub repo, making them available across all devices and users. The timelines fetch this file alongside their data to render the curated view.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     macOS (local machine)                     │
│                                                               │
│  launchd Agent (com.theodo.regulatory-watch)                  │
│  Triggers: Every Friday 08:00 CET                             │
│                      │                                        │
│                      ▼                                        │
│  Claude Code CLI (--print --dangerously-skip-permissions)     │
│  Prompt: ~/.claude/regulatory-watch/prompt.md                 │
│                                                               │
│  Step 1-3: Research 12 sources + 21 web searches              │
│  Step 4:   Build HTML email → gws gmail → 5 recipients        │
│  Step 5a-d: Read data.json, generate proposals.json (EN)      │
│  Step 5e:   Generate proposals-fr.json (FR translations)      │
│  Step 5f:   git push proposals.json + proposals-fr.json       │
└──────────────────────┬───────────────────────────────────────┘
                       │ git push
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  GitHub: nicolasbertrand-QARA/Compliance-timeline             │
│                                                               │
│  Static files (deployed to Pages):                            │
│  ├── index.html           (EN timeline)                       │
│  ├── fr.html              (FR timeline)                       │
│  ├── admin.html           (back office)                       │
│  ├── data.json            (37 EN milestones)                  │
│  ├── data-fr.json         (37 FR milestones)                  │
│  ├── proposals.json       (EN proposals from cron)            │
│  ├── proposals-fr.json    (FR proposals from cron)            │
│  ├── decisions.json       (shared admin state ← GitHub API)   │
│  ├── logo.png             (Theodo HealthTech logo)            │
│  └── .github/workflows/pages.yml                              │
│                                                               │
│  GitHub Actions: Deploy to Pages on push to main              │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  GitHub Pages CDN                                             │
│  nicolasbertrand-qara.github.io/Compliance-timeline/          │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │ EN       │  │ FR       │  │ Admin    │                    │
│  │ timeline │  │ timeline │  │ back     │                    │
│  │          │  │          │  │ office   │                    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                    │
│       │              │              │                          │
│       │   fetch      │   fetch      │  fetch + GitHub API     │
│       ▼              ▼              ▼  (read SHA, PUT update) │
│  data.json      data-fr.json   data.json                     │
│  proposals.json proposals-fr   proposals.json                 │
│  decisions.json decisions.json decisions.json                 │
└──────────────────────────────────────────────────────────────┘
```

### decisions.json — The Cross-Device State Store

```
┌─────────────────────────────────────────────────────────────┐
│  decisions.json (committed to repo via GitHub API)           │
│                                                              │
│  {                                                           │
│    "hidden_cards":        [...],   ← shared EN + FR          │
│    "approved_proposals":  [...],   ← shared EN + FR          │
│    "rejected_proposals":  [...],   ← shared EN + FR          │
│    "deleted_cards":       [...],   ← shared EN + FR          │
│    "comments":            {...},   ← EN comments only        │
│    "comments_fr":         {...},   ← FR comments only        │
│    "tag_overrides":       {...},   ← shared EN + FR          │
│    "approval_dates":      {...}    ← shared EN + FR          │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘

Admin writes via GitHub Contents API:
  PUT /repos/{owner}/{repo}/contents/decisions.json
  Authorization: token {PAT}
  Body: { message, content (base64), sha }

Timelines read via simple fetch:
  GET https://...github.io/.../decisions.json
```

---

## Bilingual Architecture

### What's shared (one action applies to both languages)
- **Card visibility** (`hidden_cards`) — hide once, hidden on both EN and FR
- **Proposal approval/rejection** (`approved_proposals`, `rejected_proposals`) — approve once, applies to both
- **Card deletion** (`deleted_cards`) — delete once, gone from both
- **Tag overrides** (`tag_overrides`) — change tag once, reflected on both
- **Stable card IDs** — every card has an `id` field (e.g. `2026-05-28--eudamed-first-4-modules-mandatory`) identical in both data files

### What's separate per language
- **Data files** — `data.json` (EN) and `data-fr.json` (FR), same `id` fields
- **Proposal files** — `proposals.json` (EN) and `proposals-fr.json` (FR), same proposal IDs
- **Comments** — `comments` (EN) and `comments_fr` (FR) within decisions.json

### Approval flow across languages

```
Admin approves proposal "proposal-2026-04-25-001"
  │
  │  decisions.json updated via GitHub API
  │  (approved_proposals += "proposal-2026-04-25-001")
  │
  ├──→ EN timeline fetches proposals.json
  │    finds matching proposal ID → merges English card
  │
  └──→ FR timeline fetches proposals-fr.json
       finds matching proposal ID → merges French card
```

### Stable ID Convention

Format: `{YYYY-MM-DD}--{lowercase-english-slug}`

- Double dash `--` separator
- Derived from the English title, max 50 chars
- Same ID in `data.json`, `data-fr.json`, `proposals.json`, `proposals-fr.json`
- `cardId()` returns `m.id` when present, falls back to legacy format

---

## Component Details

### 1. English Timeline (`index.html`)

**URL:** `https://nicolasbertrand-qara.github.io/Compliance-timeline/`

**Data flow on page load:**
```
fetch(data.json)       → 37 base milestones (EN)
fetch(proposals.json)  → pending proposals (EN)
fetch(decisions.json)  → admin decisions (shared)

Merge:
  base milestones
  - deleted_cards
  + approved add/update proposals
  → apply tag_overrides
  → apply hidden_cards filter
  → apply topic filter (3-state toggles)
  → apply recency filter (all / last week / last month)
  → render with EN comments
```

**Key features:**
- **3-state topic filters** (sidebar, sticky): show only / exclude / reset
- **Recency filter** (Added): All / Last week / Last month
- **"Other Regions" excluded by default**
- **Card variants:** Critical (navy), Highlight (gold), Normal (plain)
- **Comments:** `"comment text"  Nicolas Bertrand`
- **Source links:** Card titles underlined, gold on hover
- **Staggered entrance animation** (40ms/card, capped 500ms)
- **Keyboard accessible:** `:focus-visible` gold ring

### 2. French Timeline (`fr.html`)

**URL:** `https://nicolasbertrand-qara.github.io/Compliance-timeline/fr.html`

Same structure as EN. Differences:

| Aspect | EN | FR |
|--------|----|----|
| Data | `data.json` | `data-fr.json` |
| Proposals | `proposals.json` | `proposals-fr.json` |
| Comments | `decisions.comments` | `decisions.comments_fr` |
| UI labels | Topics, Showing, milestones | Thèmes, Affichés, jalons |
| Tags | CRITICAL, HIGH, IN FORCE | CRITIQUE, ÉLEVÉ, EN VIGUEUR |
| Recency | Added, Last week, Last month | Ajouté, Semaine dernière, Mois dernier |
| Title | MDSW Regulatory Timeline | Timeline Réglementaire MDSW |

### 3. Back Office (`admin.html`)

**URL:** `https://nicolasbertrand-qara.github.io/Compliance-timeline/admin.html`

**Authentication:** GitHub Personal Access Token (repo scope) entered in the top bar. Stored in browser localStorage (never sent anywhere except GitHub API).

**How it works:**
1. On load: fetches `decisions.json` via GitHub API (gets file content + SHA)
2. Admin makes changes (approve, reject, hide, comment, tag edit)
3. Each change updates in-memory `decisions` object
4. Pushes updated `decisions.json` to GitHub via Contents API (PUT with SHA)
5. GitHub Actions deploys → all users see changes on next page load

**Three functional areas:**

#### A. Proposals (tabbed)
- **Pending tab:** Unreviewed proposals with Approve/Reject buttons
- **Archived tab:** Decided proposals with Undo button
- Types: ADD (green), UPDATE (amber), DELETE (red)
- UPDATE shows diff view; each proposal has a `reason` field
- One approval/rejection applies to both EN and FR

#### B. Milestones Table
- Toggle switches to show/hide cards (shared across languages)
- Search bar filtering
- "Show all" / "Hide all" bulk actions

#### C. Bilingual Comments + Tag Editor
- Two comment inputs per row: `Add an EN comment...` / `Commentaire en FR...`
- Click any tag badge → dropdown of all available tags → select to override

### 4. Automated Regulatory Watch

**Trigger:** macOS launchd, every Friday 08:00 CET.

**Chain:** `launchd → run.sh → Claude CLI → research + email + proposals + git push`

**Prompt workflow (5 steps):**
1. **Research** — 12 web sources + 21 searches (EU, UK, US, other regions)
2. **Organize** — 4 sections with items, evolutions, opinions
3. **Standards check** — 25+ standards from DOC-POL-XXX v01
4. **Email** — Theodo HealthTech branded HTML via `gws gmail` to 5 recipients
5. **Timeline update:**
   - 5a: git pull
   - 5b: Read data.json (with stable IDs)
   - 5c-d: Generate proposals.json (EN, with `card.id` fields)
   - 5e: Generate proposals-fr.json (FR translations, same IDs)
   - 5f: git push both

**Recipients:** nicolas.bertrand, thomas.walter, clemence.faulcon, manon.thiberge, louise.balague @theodo.com

---

## Data Model

### `data.json` / `data-fr.json` — 37 Milestones

```json
{
  "id": "2026-05-28--eudamed-first-4-modules-mandatory",
  "d": "2026-05-28",
  "l": "28 May 2026",       // FR: "28 mai 2026"
  "y": 2026,
  "t": "EUDAMED — First..", // FR: "EUDAMED — 4 premiers.."
  "x": "Description...",
  "u": "https://source-url",
  "tp": ["mdr"],
  "tg": ["critical"],
  "v": "c"                  // c=navy, h=gold, n=plain
}
```

### `proposals.json` / `proposals-fr.json` — Weekly Proposals

```json
{
  "generated": "2026-04-25",
  "proposals": [{
    "id": "proposal-2026-04-25-001",
    "action": "add|update|delete",
    "reason": "...",
    "card": { "id": "2026-04-25--slug", ... },
    "existing_id": "2026-05-28--eudamed-..."
  }]
}
```

### `decisions.json` — Admin State (cross-device)

```json
{
  "hidden_cards":       ["card-id-1", ...],
  "approved_proposals": ["proposal-id-1", ...],
  "rejected_proposals": ["proposal-id-1", ...],
  "deleted_cards":      ["card-id-1", ...],
  "comments":           { "card-id": "EN comment" },
  "comments_fr":        { "card-id": "FR comment" },
  "tag_overrides":      { "card-id": "high" },
  "approval_dates":     { "proposal-id": "2026-04-25" }
}
```

Written by the admin via GitHub Contents API. Read by timelines via simple fetch.

---

## Deployment

**Hosting:** GitHub Pages (static)

**URLs:**
- EN: `https://nicolasbertrand-qara.github.io/Compliance-timeline/`
- FR: `https://nicolasbertrand-qara.github.io/Compliance-timeline/fr.html`
- Admin: `https://nicolasbertrand-qara.github.io/Compliance-timeline/admin.html`

**Weekly flow:**
```
Friday 8am: Cron runs
  → Email sent to 5 recipients
  → proposals.json + proposals-fr.json pushed → deploy

Admin opens back office
  → Reviews proposals (approve/reject)
  → decisions.json committed via GitHub API → deploy

Any user on any device loads timeline
  → Fetches data + proposals + decisions
  → Sees the curated, consistent view
```

---

## Design System

**Brand:** Theodo HealthTech

| Token | Value | Usage |
|-------|-------|-------|
| Gold | `oklch(85% 0.17 90)` / `#ffc800` | CTAs, active states, tags, year rules |
| Navy | `oklch(24% 0.07 260)` / `#12305d` | Header, footer, critical cards |
| Orange | `oklch(62% 0.22 30)` / `#ff512c` | Secondary accent (sparingly) |
| Neutrals | Tinted toward hue 90 | Surfaces, borders, text |

**Typography:** Poppins. Weight 500 headings, 400 body.

**Impeccable compliance:** OKLCH, no border-left stripes, no gradient text, no glassmorphism, focus-visible, prefers-reduced-motion, min 12px, tabular-nums, max-width 65ch.

---

## File Map

```
GitHub Repo: nicolasbertrand-QARA/Compliance-timeline
├── index.html              # EN timeline
├── fr.html                 # FR timeline
├── admin.html              # Back office (GitHub API writes)
├── data.json               # 37 EN milestones
├── data-fr.json            # 37 FR milestones (same IDs)
├── proposals.json          # EN proposals (weekly cron)
├── proposals-fr.json       # FR proposals (weekly cron)
├── decisions.json          # Admin state (cross-device)
├── logo.png                # Theodo HealthTech logo
├── *.png                   # Mermaid architecture diagrams
├── ARCHITECTURE.md          # This document
├── reports/April_2026.md   # First regulatory watch report
├── automation/
│   ├── weekly-report-prompt.md
│   └── run.sh
└── .github/workflows/pages.yml

Local only:
~/.claude/regulatory-watch/
├── prompt.md               # Active cron prompt
├── run.sh                  # Active script
├── repo/                   # Local git clone
└── last_run.log

~/Library/LaunchAgents/
└── com.theodo.regulatory-watch.plist
```

---

## Limitations

1. **GitHub API rate limits.** Unauthenticated: 60 req/hr. With PAT: 5,000 req/hr. Each admin action = 1 PUT. Unlikely to hit limits in normal use.

2. **Deploy delay.** After decisions.json is committed, GitHub Pages takes ~30s to deploy. Other users won't see changes until the next deploy completes.

3. **No authentication on the admin page.** Anyone with the URL can view it. But writing requires a valid GitHub PAT, so only token holders can make changes.

4. **Cron requires Mac to be on.** 4-hour catch-up window via `StartCalendarIntervalAllowedDelay`.

5. **gws auth token expiration.** May require re-authentication for email sending.

6. **Proposals overwritten weekly.** Undecided proposals are lost when the next batch arrives.

7. **Single-font design.** Poppins only (Theodo HealthTech brand requirement).

8. **Comments are per-language but not enforced.** Admin can add EN comment without FR (or vice versa).
