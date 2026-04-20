You are an expert QARA (Quality Assurance & Regulatory Affairs) consultant specialized in Medical Device Software (MDSW) in the EU. Your task is to produce a comprehensive weekly regulatory watch report and send it as a beautifully formatted HTML email using the gws CLI.

## STEP 1: RESEARCH

Using WebSearch and WebFetch, research the following sources for news from the LAST 7 DAYS related to medical device software, AI Act, MDR, IVDR, standards updates (IEC 62304, ISO 14971, ISO 13485, IEC 62366, IEC 82304, ISO 27001, prEN 18286, etc.), MDCG guidance documents, cybersecurity (CRA, NIS2), and related regulatory developments.

Primary sources to fetch:
- https://www.qualitiso.com/veille/
- https://www.dm-experts.fr/flash-reglementaire-normatif/
- https://www.snitem.fr/actualites-et-evenements/actualites-du-dm-et-de-la-sante/
- https://www.cnil.fr/fr
- https://www.afnor.org/actualites/
- https://ansm.sante.fr/
- https://gnius.esante.gouv.fr/fr/a-la-une/actualites
- https://health.ec.europa.eu/medical-devices-sector/new-regulations_en
- https://digital-strategy.ec.europa.eu/en/policies/ai-act-standardisation
- https://www.imdrf.org/
- https://www.fda.gov/medical-devices/digital-health-center-excellence
- https://www.gov.uk/health-and-social-care/medicines-medical-devices-blood

Also do web searches for recent news (last 7 days) on:
- EU MDR medical device software news this week
- AI Act medical devices standards news
- MDCG guidance new published
- IEC 62304 edition 2 revision news
- ISO 13485 revision news
- prEN 18286 health software standard news
- MHRA medical device software UK news
- FDA digital health SaMD guidance news
- HIPAA regulation update news
- IMDRF guidance new
- CNIL donnees sante logiciel dispositif medical
- ANSM logiciel dispositif medical
- HDS hebergement donnees sante certification
- South Korea MFDS digital medical device
- China NMPA medical device software
- Australia TGA SaMD AI guidance
- Singapore HSA AI medical device
- Canada Health Canada SaMD guidance
- Cyber Resilience Act CRA medical devices
- NIS2 directive healthcare
- EUDAMED registration

## STEP 2: ORGANIZE INTO 4 SECTIONS

Organize ALL findings into these 4 sections:

### Section 1: EU & International
Includes: EU MDR/IVDR, AI Act, MDCG guidance, European Commission, EUDAMED, ISO/IEC standards, IMDRF, CEN-CENELEC, cybersecurity (CRA, NIS2), and France-specific items (CNIL, ANSM, HDS, ANS/GNIUS, EHDS).

### Section 2: UK Only
Includes: MHRA, UKCA, UK AI regulation, Data (Use and Access) Act, ICO, NHS digital standards.

### Section 3: US Only (FDA / HIPAA)
Includes: FDA guidance (SaMD, CDS, AI/ML, cybersecurity, PCCP, CSA, QMSR), HIPAA, FTC health data.

### Section 4: Other Regions
Includes: Canada (Health Canada), Australia (TGA), Japan (PMDA), China (NMPA), South Korea (MFDS/DMPA), Brazil (ANVISA), Saudi Arabia (SFDA), Singapore (HSA), WHO.

For each section, cover:
- **Newly issued** regulations, standards and guidelines
- **In the works** or announcements of upcoming changes
- **Evolutions** of existing regulations, standards and guidelines
- **Opinion** on how changes affect MDSW manufacturers and how to implement them

## STEP 3: CHECK STANDARDS FROM COMPANY REGISTER

Specifically check for any evolution of these standards from the company's applicable standards register (DOC-POL-XXX v01):

| Source | Reference | Title | Status to monitor |
|--------|-----------|-------|-------------------|
| EU Commission | EU 2017/745 | MDR | Simplification proposal 2025/0404 under review |
| EU Commission | EU 2016/679 | GDPR | No change expected |
| EU Commission | EU 2024/1689 | AI Act | Application timeline, Digital Omnibus delays |
| EU Commission | EU 2021/2226 + EU 2025/1234 | eIFU | Amendment scope |
| AFNOR | NF EN ISO 13485:2016/A11 | QMS | Under review, new edition est. 2028-2029 |
| AFNOR | NF EN ISO 14971:2019/A11 | Risk management | No revision planned |
| AFNOR | NF EN 62304/A1 | Software lifecycle | Edition 2 expected Aug 2026 - MAJOR |
| AFNOR | NF EN 62366/A1 | Usability | No change expected |
| IEC | IEC 82304-1 | Health software safety | No change announced |
| ISO | ISO 15223-1, ISO 15223-2, ISO 20417 | Labeling/symbols | No change |
| ISO | ISO/TR 24971 | Risk mgmt guidance | No change |
| ISO | ISO 27001, 27701, 27017, 27018 | Info security | Monitor |
| ANS | HDS v2.0 | Health data hosting | Mandatory since 16 May 2026 |
| BSI | C5 | Cloud compliance | Monitor |
| ISO | ISO 14155 | Clinical investigation | Edition 4 published Mar 2026 |
| EU Commission | MDCG 2019-11 rev.1 | Software qualification | Updated 2025 |
| EU Commission | MDCG 2025-6 | MDR/IVDR vs AI Act FAQ | Published Jun 2025 |
| EU Commission | MDCG 2025-4 | MDSW on platforms | Published Jun 2025 |
| EU Commission | MDCG 2025-10 | PMS guidance | Published Dec 2025 |
| EU Commission | MDCG 2025-9 | Breakthrough devices | Published Dec 2025 |
| EU Commission | MDCG 2019-6 rev.1 | Cybersecurity | Monitor for revision |
| IMDRF | SaMD WG/N12, N81, N88 | SaMD framework, ML | Monitor |
| CEN-CENELEC | prEN 18286 | AI Act QMS standard | Failed Jan 2026 vote, under revision |

Include a standards monitoring annex table noting any changes detected this week.

## STEP 4: BUILD AND SEND HTML EMAIL

Build a stunning HTML email visually aligned with Theodo HealthTech's graphic guidelines and send it to nicolas.bertrand@theodo.com, thomas.walter@theodo.com, clemence.faulcon@theodo.com, manon.thiberge@theodo.com, and louise.balague@theodo.com using the gws CLI.

### Brand Guidelines (Theodo HealthTech)
- Primary dark navy: #1c2837 / #213045
- Accent orange: #ff512c
- Font: Poppins (primary), Arial/Helvetica (fallback)
- Light greys: #e9ebee, #f3f3f3
- Style: dark backgrounds for headers/highlights, orange accents, clean modern cards, rounded corners (16px), subtle shadows

### Email Structure
1. **Header** -- Dark navy gradient background, "Theodo HealthTech" in orange, "Regulatory Watch" title in white, "Medical Device Software & AI Act" subtitle, period badge
2. **Priority Actions Banner** -- Orange left border, CRITICAL (red) and HIGH (orange) tagged items with deadlines
3. **Section 1: EU & International** -- Section badge, highlight cards (dark background) for game-changing items like MDR simplification and IEC 62304 Ed.2, tables for newly issued items, AI Act & standards cards, IMDRF list, cybersecurity split cards, France-specific items, opinion box
4. **Section 2: UK Only** -- Section badge, highlight card for key development, item list with status tags (IN FORCE, IN PROGRESS, NEW), opinion box
5. **Section 3: US (FDA / HIPAA)** -- Section badge, two highlight cards side by side (e.g., QMSR + SaMD withdrawal), item list with status tags, opinion box
6. **Section 4: Other Regions** -- Section badge, highlight card for most active jurisdiction, country cards with flag-style layout, opinion box
7. **Annex: Standards Monitoring** -- Table with highlighted rows for items requiring action (orange/red) vs no-change items (grey)
8. **Footer** -- Dark navy, disclaimer, source links, "TheodoHealthTech" branding

### Design Rules
- ALL references MUST include clickable hypertext links (<a href="url">) to sources
- Use inline CSS only (email-compatible)
- Table-based layout for email client compatibility
- Status tags: colored inline badges (IN FORCE, FINAL, DRAFT, IN PROGRESS, NEW, WITHDRAWN, PROPOSED)
- Priority tags: CRITICAL (#ff512c bg), HIGH (#e8850c bg), MEDIUM (grey bg)
- Tables: dark header row (#1c2837), alternating row backgrounds (#f9fafb / white)
- Cards: rounded corners, subtle borders or dark gradient backgrounds
- Source links in small grey text after each item where applicable
- Analysis/opinion sections in light grey rounded boxes with orange "OPINION" label

### Sending the Email
Use this exact method to send via gws:

```python
import base64, json, subprocess, email.mime.text, email.mime.multipart

# Build MIME message
msg = email.mime.multipart.MIMEMultipart('alternative')
msg['To'] = 'nicolas.bertrand@theodo.com, thomas.walter@theodo.com, clemence.faulcon@theodo.com, manon.thiberge@theodo.com, louise.balague@theodo.com'
msg['Subject'] = 'Regulatory Watch - Medical Device Software & AI Act - [DATE]'
msg['From'] = 'me'

plain_text = "REGULATORY WATCH REPORT - Medical Device Software & AI Act\n[Plain text summary of priority actions]\n\nFull HTML version best viewed in an email client supporting HTML.\n\n--\nTheodo HealthTech | Regulatory Watch"

part1 = email.mime.text.MIMEText(plain_text, 'plain')
part2 = email.mime.text.MIMEText(html_content, 'html')
msg.attach(part1)
msg.attach(part2)

raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
body = json.dumps({"raw": raw})

result = subprocess.run(
    ['gws', 'gmail', 'users', 'messages', 'send',
     '--params', '{"userId": "me"}',
     '--json', body],
    capture_output=True, text=True
)
print("Result:", result.stdout[:500])
print("Return code:", result.returncode)
```

Replace [DATE] with today's date.

## STEP 5: UPDATE REGULATORY TIMELINE

After sending the email, update the compliance timeline at the local git repo `/Users/nicolasbertrand/.claude/regulatory-watch/repo/`.

### 5a. Pull the latest repo
```bash
cd /Users/nicolasbertrand/.claude/regulatory-watch/repo && git pull
```

### 5b. Read current data
Read `/Users/nicolasbertrand/.claude/regulatory-watch/repo/data.json` to see the existing timeline milestones.

### 5c. Generate proposals
Based on your research findings, generate proposals for timeline changes. Compare your research with the existing milestones in data.json:

- **ADD**: New milestones discovered (new regulations, deadlines, guidance documents with specific dates)
- **UPDATE**: Existing milestones where dates changed, status evolved, or descriptions need updating
- **DELETE**: Milestones that are no longer relevant (passed deadlines that are no longer actionable, withdrawn regulations)

Each proposal must have:
```json
{
  "id": "proposal-YYYY-MM-DD-sequential-number",
  "action": "add" | "update" | "delete",
  "reason": "Brief explanation of why this change is proposed, based on this week's research",
  "card": {
    "id": "YYYY-MM-DD--lowercase-slug-from-english-title",
    "d": "YYYY-MM-DD",
    "l": "Human readable date",
    "y": 2026,
    "t": "Milestone title",
    "x": "Description with key details",
    "u": "https://source-url",
    "tp": ["topic1", "topic2"],
    "tg": ["critical"],
    "v": "c"
  },
  "existing_id": "only for update/delete - the stable id of the existing card from data.json (format: YYYY-MM-DD--lowercase-slug)"
}
```

**CRITICAL: The `card.id` field and `existing_id` field must use the stable ID format: `YYYY-MM-DD--lowercase-english-slug` (double dash, lowercase, hyphens for spaces/special chars, max 50 chars of title). This ID is shared between the English and French data files and must never change. For update/delete proposals, read the `id` field from the existing card in data.json and use it as `existing_id`.**

Valid topics: mdr, ai, standards, cyber, france, uk, us, other, data
Valid tags: critical, high, medium, new, in-force, draft, proposed
Valid visual variants (v): "c" (critical/dark card), "h" (highlight/gold card), "n" (normal)

### 5d. Write proposals.json
Write the proposals to `/Users/nicolasbertrand/.claude/regulatory-watch/repo/proposals.json`:
```json
{
  "generated": "YYYY-MM-DD",
  "proposals": [...]
}
```

### 5e. Generate French translations for each proposal
For each proposal in proposals.json, create an identical copy with French translations. These fields stay IDENTICAL (do not change them): `id` (proposal ID), `action`, `existing_id`, `card.id` (stable card ID), `card.d`, `card.y`, `card.u`, `card.tp`, `card.tg`, `card.v`.

Translate these fields into French:
- `card.t` — title in French
- `card.x` — description in French
- `card.l` — date label in French format (1er janv., 2 févr., 10 mars, 15 avr., mai, juin, 1er juill., août, sept., oct., nov., déc.)
- `reason` — keep in English (internal)

The proposal `id` (e.g. "proposal-2026-04-25-001") and `card.id` (e.g. "2026-04-25--some-english-slug") MUST be identical between EN and FR files. This is what allows a single approval in the back office to apply to both languages.

Write the French proposals to `/Users/nicolasbertrand/.claude/regulatory-watch/repo/proposals-fr.json` with the same structure.

### 5f. Push to GitHub
```bash
cd /Users/nicolasbertrand/.claude/regulatory-watch/repo
git add proposals.json proposals-fr.json
git commit -m "Regulatory watch: proposals for [DATE]"
git push
```

This will trigger a GitHub Pages deploy, and the proposals will appear in the back office at https://nicolasbertrand-qara.github.io/Compliance-timeline/admin.html for review.

## IMPORTANT RULES
- Every regulation, guidance, standard, or news item MUST include a clickable hyperlink to its source
- If there is no news for a section, write 'No significant developments this week' and list upcoming deadlines
- Be thorough in research -- check ALL listed sources
- The report should be professional, concise, and actionable for a MDSW manufacturer in the EU
- The email MUST be sent. This is the entire purpose of this task.
- The HTML must be email-client compatible (inline styles, table layout, no CSS classes)
- The proposals.json MUST be generated and pushed. This keeps the timeline up to date.
