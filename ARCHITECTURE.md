# Architecture Document — MDSW Compliance Timeline

## Overview

The Compliance Timeline is a regulatory watch system for Medical Device Software (MDSW) manufacturers. It consists of three subsystems:

1. **Public Timeline** — An interactive web page displaying regulatory milestones from 2026 to 2030
2. **Back Office** — An admin interface for managing card visibility, comments, and reviewing AI-generated proposals
3. **Automated Regulatory Watch** — A weekly cron job that researches regulatory changes, sends a branded email report, and proposes timeline updates

All three subsystems share data through a Git repository hosted on GitHub, deployed as a static site via GitHub Pages, with browser-local state managed through localStorage.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS (local machine)                     │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  launchd Agent (com.theodo.regulatory-watch)         │   │
│  │  Triggers: Every Friday 08:00 CET                    │   │
│  │  Runs: ~/.claude/regulatory-watch/run.sh             │   │
│  └──────────────┬───────────────────────────────────────┘   │
│                 │                                            │
│                 ▼                                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Claude Code CLI (--print --dangerously-skip-perms)  │   │
│  │  Prompt: ~/.claude/regulatory-watch/prompt.md        │   │
│  │                                                      │   │
│  │  1. WebSearch + WebFetch (12 sources, 21 queries)    │   │
│  │  2. Build HTML email (Theodo HealthTech branding)    │   │
│  │  3. Send via gws gmail CLI                           │   │
│  │  4. Read data.json, generate proposals.json          │   │
│  │  5. git push to GitHub                               │   │
│  └──────┬──────────────────┬────────────────────────────┘   │
│         │                  │                                 │
│         ▼                  ▼                                 │
│   ┌──────────┐    ┌──────────────────┐                      │
│   │ gws CLI  │    │ Git repo (local) │                      │
│   │ (Gmail)  │    │ ~/.claude/       │                      │
│   └──────────┘    │  regulatory-     │                      │
│         │         │  watch/repo/     │                      │
│         ▼         └────────┬─────────┘                      │
│   5 recipients             │                                 │
│   @theodo.com              │ git push                        │
└────────────────────────────┼────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                         GitHub                               │
│                                                             │
│  nicolasbertrand-QARA/Compliance-timeline (main branch)     │
│  ├── index.html          (public timeline)                  │
│  ├── admin.html          (back office)                      │
│  ├── data.json           (milestone data, source of truth)  │
│  ├── proposals.json      (AI-generated change proposals)    │
│  ├── logo.png            (Theodo HealthTech logo)           │
│  ├── reports/            (archived markdown reports)        │
│  ├── automation/         (cron prompt + shell script)       │
│  └── .github/workflows/pages.yml                            │
│                                                             │
│  GitHub Actions: Deploy to GitHub Pages on push to main     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Pages (CDN)                        │
│                                                             │
│  nicolasbertrand-qara.github.io/Compliance-timeline/        │
│  ├── /              → index.html (public timeline)          │
│  ├── /admin.html    → back office                           │
│  ├── /data.json     → fetched by both pages at runtime      │
│  └── /proposals.json → fetched by both pages at runtime     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    User's Browser                            │
│                                                             │
│  localStorage (same origin: *.github.io/Compliance-timeline)│
│  ├── rw_hidden_cards        (card IDs hidden from timeline) │
│  ├── rw_approved_proposals  (approved proposal IDs)         │
│  ├── rw_rejected_proposals  (rejected proposal IDs)         │
│  ├── rw_deleted_cards       (card IDs from delete proposals)│
│  └── rw_comments            (cardId → comment text map)     │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Public Timeline (`index.html`)

**Purpose:** Display regulatory milestones in a filterable, interactive timeline for MDSW stakeholders.

**Data flow on page load:**
```
fetch(data.json) → base milestones
fetch(proposals.json) → pending proposals
localStorage(rw_approved_proposals) → approved IDs
localStorage(rw_deleted_cards) → deleted card IDs
localStorage(rw_hidden_cards) → hidden card IDs
localStorage(rw_comments) → card comments

Displayed = (base - deleted + approved_adds/updates) - hidden
```

**Key features:**
- **3-state topic filters** (sidebar, sticky on scroll):
  - Click once → show only this topic (active)
  - Click again → hide this topic (excluded, strikethrough)
  - Click again → reset to all
  - Multiple topics can be active/excluded simultaneously
  - "Other Regions" excluded by default
- **Card variants:** Critical (navy background), Highlight (gold background), Normal (plain)
- **Comments:** Displayed inline as `"comment text"  Nicolas Bertrand`
- **Source links:** All card titles are hyperlinks to source URLs
- **Staggered entrance animation** with 40ms per card (capped at 500ms), respects `prefers-reduced-motion`
- **Keyboard accessible:** `:focus-visible` gold ring on all interactive elements

**Technology:** Vanilla HTML/CSS/JS. No build step. Poppins font (Google Fonts). OKLCH color system tinted toward HealthTech yellow hue (90).

**Card ID convention:** `{date}__{title_slug_first_40_chars}` — used across all components as the stable identifier.

### 2. Back Office (`admin.html`)

**Purpose:** Admin interface for curating the public timeline.

**Three functional areas:**

#### A. Proposals (tabbed)
- **Pending tab:** Unreviewed proposals with Approve/Reject buttons
- **Archived tab:** Decided proposals with status badge and Undo button
- Proposal types: ADD (green), UPDATE (amber), DELETE (red)
- UPDATE proposals show a diff view (old → new for each changed field)
- Each proposal includes a `reason` field explaining why it was suggested

#### B. Milestones Table
- Toggle switches to show/hide each card on the public timeline
- Search bar filtering by title, description, or topic
- "Show all" / "Hide all" bulk actions
- NEW/UPDATED indicators on cards from approved proposals

#### C. Comments Column
- Inline text input per milestone row
- Saves on blur or Enter keypress
- Empty comment = no display on public page

**State persistence:** All admin decisions are stored in localStorage on the same GitHub Pages origin, immediately reflected on the public timeline.

### 3. Automated Regulatory Watch

**Trigger:** macOS launchd agent, every Friday at 08:00 CET.

**Execution chain:**
```
launchd → run.sh → claude CLI → (research + email + proposals + git push)
```

**Components:**

| File | Location | Purpose |
|------|----------|---------|
| `com.theodo.regulatory-watch.plist` | `~/Library/LaunchAgents/` | launchd schedule definition |
| `run.sh` | `~/.claude/regulatory-watch/` | Shell wrapper, sets env vars, invokes Claude CLI |
| `prompt.md` | `~/.claude/regulatory-watch/` | Full prompt defining the 5-step workflow |
| `repo/` | `~/.claude/regulatory-watch/` | Persistent local clone of the GitHub repo |
| `last_run.log` | `~/.claude/regulatory-watch/` | Output log of the most recent run |

**Prompt workflow (5 steps):**

1. **Research** — Fetch 12 primary web sources + 21 targeted web searches covering EU MDR/IVDR, AI Act, standards (IEC/ISO), cybersecurity (CRA, NIS2), France (CNIL, ANSM, HDS), UK (MHRA), US (FDA, HIPAA), and other regions
2. **Organize** — Structure findings into 4 sections (EU & International, UK, US, Other Regions) with newly issued items, in-progress items, evolutions, and impact opinions
3. **Standards check** — Monitor 25+ standards from the company register (DOC-POL-XXX v01) for any changes
4. **Email** — Build a Theodo HealthTech branded HTML email and send to 5 recipients via `gws gmail`
5. **Timeline update** — Pull the repo, compare research findings with existing `data.json`, generate `proposals.json` with ADD/UPDATE/DELETE proposals, push to GitHub

**Email recipients:** nicolas.bertrand, thomas.walter, clemence.faulcon, manon.thiberge, louise.balague @theodo.com

---

## Data Model

### `data.json` — Milestones (source of truth)

```json
[
  {
    "d": "2026-05-28",        // ISO date for sorting
    "l": "28 May 2026",       // Human-readable date label
    "y": 2026,                // Year (for grouping)
    "t": "EUDAMED — First 4 Modules Mandatory",  // Title
    "x": "Description text...",                    // Description
    "u": "https://source-url",                     // Source URL
    "tp": ["mdr"],            // Topics (1 or more)
    "tg": ["critical"],       // Tags (priority/status)
    "v": "c"                  // Visual variant: c=critical, h=highlight, n=normal
  }
]
```

**Valid values:**
- `tp` (topics): `mdr`, `ai`, `standards`, `cyber`, `france`, `uk`, `us`, `other`, `data`
- `tg` (tags): `critical`, `high`, `medium`, `new`, `in-force`, `draft`, `proposed`
- `v` (variant): `c` (navy card), `h` (gold card), `n` (plain)

### `proposals.json` — AI-Generated Change Proposals

```json
{
  "generated": "2026-04-18",
  "proposals": [
    {
      "id": "proposal-2026-04-18-001",
      "action": "add|update|delete",
      "reason": "Explanation based on this week's research",
      "card": { /* same shape as data.json entry */ },
      "existing_id": "date__title_slug"  // only for update/delete
    }
  ]
}
```

### localStorage Keys

| Key | Type | Used By | Purpose |
|-----|------|---------|---------|
| `rw_hidden_cards` | `string[]` (card IDs) | Timeline + Admin | Cards hidden from public view |
| `rw_approved_proposals` | `string[]` (proposal IDs) | Timeline + Admin | Approved proposals to apply |
| `rw_rejected_proposals` | `string[]` (proposal IDs) | Admin | Rejected proposals (archived) |
| `rw_deleted_cards` | `string[]` (card IDs) | Timeline + Admin | Cards removed via approved delete proposals |
| `rw_comments` | `object` (cardId → string) | Timeline + Admin | User comments displayed on cards |

---

## Deployment

**Hosting:** GitHub Pages (static site, no server)

**Deployment trigger:** Any push to `main` branch triggers the GitHub Actions workflow (`.github/workflows/pages.yml`) which uploads all files as a Pages artifact.

**URL structure:**
- Public: `https://nicolasbertrand-qara.github.io/Compliance-timeline/`
- Admin: `https://nicolasbertrand-qara.github.io/Compliance-timeline/admin.html`

**Update flow:**
```
Cron pushes proposals.json → GitHub Actions deploys → 
User opens admin → reviews proposals → 
localStorage updated → Timeline reflects changes immediately
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

**Typography:** Poppins (Google Fonts). Weight 500 for headings, 400 for body. Matches the Theodo HealthTech website.

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

---

## File Map

```
Repository: nicolasbertrand-QARA/Compliance-timeline
├── index.html                     # Public timeline (717 lines)
├── admin.html                     # Back office (1058 lines)
├── data.json                      # 37 milestones (source of truth)
├── proposals.json                 # AI-generated proposals (updated weekly)
├── logo.png                       # Theodo HealthTech logo (transparent bg)
├── reports/
│   └── April_2026.md              # First full regulatory watch report
├── automation/
│   ├── weekly-report-prompt.md    # Claude CLI prompt (5-step workflow)
│   └── run.sh                     # Shell wrapper for launchd
└── .github/
    └── workflows/
        └── pages.yml              # GitHub Pages deployment

Local only (not in repo):
~/.claude/regulatory-watch/
├── prompt.md                      # Active prompt (source, copied to repo)
├── run.sh                         # Active shell script
├── repo/                          # Persistent local clone
├── last_run.log                   # Latest run output
├── launchd_stdout.log             # launchd stdout
└── launchd_stderr.log             # launchd stderr

~/Library/LaunchAgents/
└── com.theodo.regulatory-watch.plist  # launchd schedule
```

---

## Limitations and Known Constraints

1. **localStorage is per-browser, per-device.** Admin decisions (hide/show, comments, proposal approvals) do not sync across browsers or devices. Only one person should manage the back office, or decisions will diverge.

2. **No authentication.** The admin page is publicly accessible at `/admin.html`. Security through obscurity only. Consider adding basic auth or moving to a private repo if sensitive.

3. **Cron requires Mac to be on.** The launchd agent only fires when the Mac is powered on and the user is logged in. `StartCalendarIntervalAllowedDelay` allows a 4-hour catch-up window after sleep/wake.

4. **gws auth token expiration.** The `gws` CLI OAuth token may expire or require re-authentication (RAPT challenges). If the email step fails, the rest of the workflow (proposals) still completes.

5. **Proposal accumulation.** `proposals.json` is overwritten each week. Old proposals that were neither approved nor rejected are lost when the next batch is generated. The archived tab preserves decisions in localStorage but the proposal details are gone once `proposals.json` is replaced.

6. **Single-font design.** Impeccable guidelines recommend font pairing, but the Theodo HealthTech brand exclusively uses Poppins. This is an acknowledged brand-compliance exception.
