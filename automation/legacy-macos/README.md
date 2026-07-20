# Legacy — ancienne automatisation macOS (dépréciée)

Ces deux fichiers (`run.sh`, `weekly-report-prompt.md`) sont l'ancienne veille automatisée, telle qu'elle tournait avant migration :

- Déclenchée par `launchd` sur un Mac personnel, tous les vendredis 8h CET.
- Exécutait Claude Code CLI en mode non-interactif (`claude --print --dangerously-skip-permissions`), authentifié via la session personnelle du Mac.
- Envoyait le mail via `gws gmail`, un CLI Google Workspace lié au compte Gmail personnel de l'opérateur.
- Chemins locaux en dur (`/Users/nicolasbertrand/.claude/regulatory-watch/...`).
- Liste de destinataires codée en dur dans le prompt.

**Remplacé par** `automation/weekly_watch.py` + `.github/workflows/regulatory-watch.yml` :

- Tourne sur GitHub Actions (aucune machine à laisser allumée), planifié le vendredi.
- Recherche via Perplexity Sonar + fetch direct de sources fixes (Playwright), au lieu de l'outil `WebSearch` de Claude Code (qui ne fonctionne pas à travers la passerelle LiteLLM de Theodo — testé et confirmé pendant la migration).
- Rédaction via Claude (Sonnet 4.5 par défaut) appelé via LiteLLM, modèle configurable depuis le back office (`automation/config.json`).
- Envoi de mail via SMTP (compte Gmail dédié au projet, mot de passe d'application), pas de compte personnel.
- Destinataires dans `automation/recipients.json`, modifiables sans toucher au code.
- Push git via le `GITHUB_TOKEN` fourni automatiquement par GitHub Actions, pas de PAT personnel.

Ces fichiers sont conservés uniquement pour référence historique — ils ne tournent plus.
