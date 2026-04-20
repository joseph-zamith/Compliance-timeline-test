# Architecture Document — MDSW Compliance Timeline

## Overview

The Compliance Timeline is a bilingual (EN/FR) regulatory watch system for Medical Device Software (MDSW) manufacturers. It consists of three subsystems:

1. **Public Timeline** — Two interactive web pages (English + French) displaying regulatory milestones from 2026 to 2030
2. **Back Office** — A single admin interface managing both languages: card visibility, bilingual comments, and AI-generated proposal review
3. **Automated Regulatory Watch** — A weekly cron job that researches regulatory changes, sends a branded email report, and generates bilingual timeline update proposals

All three subsystems share data through a Git repository hosted on GitHub, deployed as a static site via GitHub Pages, with browser-local state managed through localStorage on a single origin.

---

## System Architecture

![System Architecture](system-overview.png)

---

## Bilingual Architecture

The EN and FR timelines are parallel but share a single admin workflow:

### What's shared (one action applies to both languages)
- **Card visibility** (`rw_hidden_cards`) — hide a card once, hidden on both EN and FR
- **Proposal approval/rejection** (`rw_approved_proposals`, `rw_rejected_proposals`) — approve once in admin, the approved card appears on both timelines (in the correct language)
- **Card deletion** (`rw_deleted_cards`) — delete once, gone from both
- **Stable card IDs** — every card has an `id` field (e.g. `2026-05-28--eudamed-first-4-modules-mandatory`) that is identical in `data.json` and `data-fr.json`

### What's separate per language
- **Data files** — `data.json` (English content) and `data-fr.json` (French content), same structure and same `id` fields
- **Proposal files** — `proposals.json` (English) and `proposals-fr.json` (French), same proposal IDs and card IDs, different title/description/date labels
- **Comments** — `rw_comments` (EN) and `rw_comments_fr` (FR), managed via two text inputs per row in the back office

### How it all connects

![Bilingual Data Flow](bilingual-flow.png)

### Stable ID Convention

All card IDs use the format: `{YYYY-MM-DD}--{lowercase-english-slug}`

- Double dash `--` separator (not double underscore)
- Derived from the English title, max 50 chars
- Generated once, never changes
- Same ID in `data.json`, `data-fr.json`, `proposals.json`, `proposals-fr.json`
- The `cardId()` function in JS returns `m.id` when present, falling back to the legacy `date__title_slug` format

---

## Component Details

### 1. English Timeline (`index.html`)

**URL:** `https://nicolasbertrand-qara.github.io/Compliance-timeline/`

**Data flow on page load:**
```
fetch(data.json) → 37 base milestones (EN)
fetch(proposals.json) → pending proposals (EN)
localStorage(rw_approved_proposals) → approved proposal IDs
localStorage(rw_deleted_cards) → deleted card IDs
localStorage(rw_hidden_cards) → hidden card IDs
localStorage(rw_comments) → EN comments

Displayed = (base - deleted + approved_adds/updates) - hidden
```

![Merge Logic](merge-logic.png)

**Key features:**
- **3-state topic filters** (sidebar, sticky on scroll):
  - Click once → show only this topic (active)
  - Click again → hide this topic (excluded, strikethrough)
  - Click again → reset to all
  - Multiple topics can be active/excluded simultaneously
  - "Other Regions" excluded by default
- **Card variants:** Critical (navy background), Highlight (gold background), Normal (plain)
- **Comments:** Displayed inline as `"comment text"  Nicolas Bertrand`
- **Source links:** All card titles are hyperlinks with subtle underline (grey at rest, gold on hover)
- **Staggered entrance animation** with 40ms per card (capped at 500ms), respects `prefers-reduced-motion`
- **Keyboard accessible:** `:focus-visible` gold ring on all interactive elements
- **One-time migration script** clears legacy localStorage keys on first visit after ID system changes

**Technology:** Vanilla HTML/CSS/JS. No build step. Poppins font (Google Fonts). OKLCH color system tinted toward HealthTech yellow hue (90).

### 2. French Timeline (`fr.html`)

**URL:** `https://nicolasbertrand-qara.github.io/Compliance-timeline/fr.html`

Identical structure and features to the English timeline, with these differences:

| Aspect | English (`index.html`) | French (`fr.html`) |
|--------|----------------------|-------------------|
| Data file | `data.json` | `data-fr.json` |
| Proposals file | `proposals.json` | `proposals-fr.json` (falls back to `proposals.json`) |
| Comments key | `rw_comments` | `rw_comments_fr` |
| UI labels | English (Topics, Showing, milestones...) | French (Thèmes, Affichés, jalons...) |
| Tag labels | CRITICAL, HIGH, IN FORCE... | CRITIQUE, ÉLEVÉ, EN VIGUEUR... |
| Topic labels | Standards, Cybersecurity, Other Regions... | Normes, Cybersécurité, Autres régions... |
| Page title | MDSW Regulatory Timeline 2026–2030 | Timeline Réglementaire MDSW 2026–2030 |

All admin decisions (hide, approve, reject, delete) are shared via the same localStorage keys.

### 3. Back Office (`admin.html`)

**URL:** `https://nicolasbertrand-qara.github.io/Compliance-timeline/admin.html`

**Purpose:** Single admin interface managing both EN and FR timelines.

**Three functional areas:**

#### A. Proposals (tabbed)
- **Pending tab:** Unreviewed proposals with Approve/Reject buttons. Count badge shows remaining.
- **Archived tab:** Decided proposals with status badge (Approved/Rejected) and Undo button.
- Proposal types: ADD (green), UPDATE (amber), DELETE (red)
- UPDATE proposals show a diff view (old → new for each changed field)
- Each proposal includes a `reason` field explaining why the cron suggested it
- One approval/rejection applies to both EN and FR timelines

![Proposal Lifecycle](proposal-lifecycle.png)

#### B. Milestones Table
- Toggle switches to show/hide each card (applies to both languages)
- Search bar filtering by title, description, or topic
- "Show all" / "Hide all" bulk actions
- NEW/UPDATED indicators on cards from approved proposals

#### C. Bilingual Comments Column
- **Two text inputs per milestone row:**
  - Top: `Add an EN comment...` → saves to `rw_comments`
  - Bottom: `Commentaire en FR...` → saves to `rw_comments_fr`
- Saves on blur or Enter keypress
- EN comment appears on English timeline, FR comment on French timeline
- Empty comment = nothing displayed

**State persistence:** All admin decisions stored in localStorage on the same GitHub Pages origin. Approval, rejection, hide, and delete decisions are shared across languages. Comments are per-language.

### 4. Automated Regulatory Watch

**Trigger:** macOS launchd agent, every Friday at 08:00 CET.

**Execution chain:**
```
launchd → run.sh → claude CLI → (research + email + proposals EN/FR + git push)
```

**Components:**

| File | Location | Purpose |
|------|----------|---------|
| `com.theodo.regulatory-watch.plist` | `~/Library/LaunchAgents/` | launchd schedule (Friday 8am, 4h catch-up) |
| `run.sh` | `~/.claude/regulatory-watch/` | Shell wrapper, env vars, invokes Claude CLI |
| `prompt.md` | `~/.claude/regulatory-watch/` | Full prompt defining the 5-step workflow |
| `repo/` | `~/.claude/regulatory-watch/` | Persistent local clone of the GitHub repo |
| `last_run.log` | `~/.claude/regulatory-watch/` | Output log of the most recent run |

**Prompt workflow (5 steps):**

1. **Research** — Fetch 12 primary web sources + 21 targeted web searches covering EU MDR/IVDR, AI Act, standards (IEC/ISO), cybersecurity (CRA, NIS2), France (CNIL, ANSM, HDS), UK (MHRA), US (FDA, HIPAA), and other regions
2. **Organize** — Structure findings into 4 sections (EU & International, UK, US, Other Regions) with newly issued items, in-progress items, evolutions, and impact opinions
3. **Standards check** — Monitor 25+ standards from the company register (DOC-POL-XXX v01)
4. **Email** — Build Theodo HealthTech branded HTML email, send to 5 recipients via `gws gmail`
5. **Timeline update:**
   - 5a: `git pull` the repo
   - 5b: Read `data.json` (existing milestones with stable IDs)
   - 5c: Generate proposals comparing research vs existing data. Each proposal card must include a `card.id` field in `YYYY-MM-DD--english-slug` format. `existing_id` for update/delete must match the `id` field from data.json.
   - 5d: Write `proposals.json` (English)
   - 5e: Write `proposals-fr.json` (French translations of the same proposals, identical `id`, `card.id`, `existing_id` fields, translated `card.t`, `card.x`, `card.l`)
   - 5f: `git push` both files

**Email recipients:** nicolas.bertrand, thomas.walter, clemence.faulcon, manon.thiberge, louise.balague @theodo.com

---

## Data Model

### `data.json` / `data-fr.json` — Milestones (source of truth)

Both files contain the same 37 milestones with identical `id` fields. Content differs by language.

```json
[
  {
    "id": "2026-05-28--eudamed-first-4-modules-mandatory",
    "d": "2026-05-28",
    "l": "28 May 2026",           // EN: "28 May 2026" / FR: "28 mai 2026"
    "y": 2026,
    "t": "EUDAMED — First 4...",  // EN title / FR title
    "x": "Description...",        // EN desc / FR desc
    "u": "https://source-url",    // Same in both
    "tp": ["mdr"],                // Same in both
    "tg": ["critical"],           // Same in both
    "v": "c"                      // Same in both
  }
]
```

**Valid values:**
- `tp` (topics): `mdr`, `ai`, `standards`, `cyber`, `france`, `uk`, `us`, `other`, `data`
- `tg` (tags): `critical`, `high`, `medium`, `new`, `in-force`, `draft`, `proposed`
- `v` (variant): `c` (navy card), `h` (gold card), `n` (plain)

### `proposals.json` / `proposals-fr.json` — AI-Generated Change Proposals

Both files have the same structure and identical proposal IDs. Card content differs by language.

```json
{
  "generated": "2026-04-25",
  "proposals": [
    {
      "id": "proposal-2026-04-25-001",        // Same in EN and FR
      "action": "add|update|delete",
      "reason": "Explanation (English in both files)",
      "card": {
        "id": "2026-04-25--some-english-slug", // Same in EN and FR
        "d": "2026-04-25",
        "l": "25 Apr 2026",                    // EN label / FR label
        "t": "English Title",                  // EN title / FR title
        "x": "English description",            // EN desc / FR desc
        ...
      },
      "existing_id": "2026-05-28--eudamed-first-4-modules-mandatory"
                      // For update/delete: stable ID from data.json
    }
  ]
}
```

### localStorage Keys

| Key | Type | Shared? | Used By | Purpose |
|-----|------|---------|---------|---------|
| `rw_hidden_cards` | `string[]` (stable IDs) | EN + FR | All 3 pages | Cards hidden from both timelines |
| `rw_approved_proposals` | `string[]` (proposal IDs) | EN + FR | All 3 pages | Approved proposals applied to both |
| `rw_rejected_proposals` | `string[]` (proposal IDs) | EN + FR | Admin | Rejected proposals (archived tab) |
| `rw_deleted_cards` | `string[]` (stable IDs) | EN + FR | All 3 pages | Cards removed from both timelines |
| `rw_comments` | `object` (stableId → string) | EN only | EN + Admin | English comments |
| `rw_comments_fr` | `object` (stableId → string) | FR only | FR + Admin | French comments |
| `rw_migrated_to_stable_ids` | `string` (version) | All | All 3 pages | One-time migration flag |

---

## Deployment

**Hosting:** GitHub Pages (static site, no server)

**Deployment trigger:** Any push to `main` branch triggers the GitHub Actions workflow (`.github/workflows/pages.yml`).

**URL structure:**
- English timeline: `https://nicolasbertrand-qara.github.io/Compliance-timeline/`
- French timeline: `https://nicolasbertrand-qara.github.io/Compliance-timeline/fr.html`
- Back office: `https://nicolasbertrand-qara.github.io/Compliance-timeline/admin.html`

**Weekly update flow:**
```
Friday 8am: Cron runs
  → Sends email to 5 recipients
  → Pushes proposals.json + proposals-fr.json to GitHub
  → GitHub Actions deploys to Pages

User opens admin.html
  → Sees proposals in "Pending" tab
  → Approves/rejects each proposal
  → Decision stored in localStorage (one action, both languages)

User visits EN timeline → sees approved EN cards + EN comments
User visits FR timeline → sees approved FR cards + FR comments
Both timelines respect the same hide/delete decisions
```

---

## Design System

**Brand:** Theodo HealthTech

| Token | Value | Usage |
|-------|-------|-------|
| Gold (primary) | `oklch(85% 0.17 90)` / `#ffc800` | CTAs, active states, critical tags, year rules |
| Navy (dark) | `oklch(24% 0.07 260)` / `#12305d` | Header, footer, critical cards, dark UI |
| Orange (secondary) | `oklch(62% 0.22 30)` / `#ff512c` | Used sparingly as secondary accent |
| Neutrals | Tinted toward hue 90 (yellow) | Surfaces, borders, text |

**Typography:** Poppins (Google Fonts). Weight 500 for headings, 400 for body.

**Logo:** White "theodo." + gold "HealthTech" on transparent background (`logo.png`), cropped from official brand asset.

**Compliance with Impeccable design guidelines:**
- OKLCH color system with tinted neutrals
- No border-left accent stripes (BAN 1)
- No gradient text (BAN 2)
- No glassmorphism
- `:focus-visible` keyboard accessibility
- `prefers-reduced-motion` respected
- Minimum 12px text size
- `font-variant-numeric: tabular-nums` on data
- `max-width: 65ch` on descriptions
- Staggered entrance animation (ease-out-expo, capped at 500ms)
- Hover transitions use ease-in-out for state toggles

---

## File Map

![File Map](file-map.png)

**Local only (not in repo):**

| Path | Purpose |
|------|---------|
| `~/.claude/regulatory-watch/prompt.md` | Active prompt (source of truth for cron) |
| `~/.claude/regulatory-watch/run.sh` | Active shell script |
| `~/.claude/regulatory-watch/repo/` | Persistent local git clone |
| `~/.claude/regulatory-watch/last_run.log` | Latest run output |
| `~/Library/LaunchAgents/com.theodo.regulatory-watch.plist` | launchd schedule definition |

---

## Limitations and Known Constraints

1. **localStorage is per-browser, per-device.** Admin decisions (hide/show, comments, proposal approvals) do not sync across browsers or devices. Only one person should manage the back office, or decisions will diverge.

2. **No authentication.** The admin page is publicly accessible at `/admin.html`. Security through obscurity only.

3. **Cron requires Mac to be on.** The launchd agent only fires when the Mac is powered on and the user is logged in. `StartCalendarIntervalAllowedDelay` allows a 4-hour catch-up window after sleep/wake.

4. **gws auth token expiration.** The `gws` CLI OAuth token may expire or require re-authentication (RAPT challenges). If the email step fails, the rest of the workflow (proposals) still completes.

5. **Proposal accumulation.** `proposals.json` and `proposals-fr.json` are overwritten each week. Old proposals that were neither approved nor rejected are lost when the next batch is generated. The archived tab preserves decisions in localStorage but the proposal details are gone once the JSON is replaced.

6. **Single-font design.** Impeccable guidelines recommend font pairing, but the Theodo HealthTech brand exclusively uses Poppins. Acknowledged brand-compliance exception.

7. **Comments are per-language but not enforced.** A user can add an EN comment without a FR comment (or vice versa). The back office shows both fields but doesn't require both to be filled.

8. **Migration script versioning.** The `rw_migrated_to_stable_ids` flag uses a version number. Any future schema change to localStorage requires bumping this version to force a re-migration, which clears all user decisions. This is a destructive operation.
