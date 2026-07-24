# Handoff — reprendre la veille réglementaire

Deux secrets font tourner cette automatisation. Si la personne qui les a créés quitte le
projet, il suffit de régénérer ces deux-là — rien d'autre n'est rattaché à une personne en
particulier.

## 1. Mot de passe d'application Gmail

Utilisé par `weekly_watch.py` pour envoyer le mail hebdomadaire (`GMAIL_ADDRESS` /
`GMAIL_APP_PASSWORD`).

- Où il est stocké : secrets du repo GitHub (Settings → Secrets and variables → Actions).
- Comment le régénérer : dans les paramètres du compte Gmail dédié au projet
  (Sécurité → Mots de passe des applications), révoquer l'ancien, en créer un nouveau,
  mettre à jour le secret `GMAIL_APP_PASSWORD` sur GitHub.

## 2. Token GitHub pour le déclenchement externe (cron-job.org)

GitHub Actions ne garantit pas un déclenchement à l'heure pile pour un `schedule:` cron
(voir la doc officielle : délais possibles, voire abandon du run en cas de forte charge).
Le déclenchement fiable du job hebdomadaire passe donc par [cron-job.org](https://cron-job.org),
qui appelle l'API GitHub (`workflow_dispatch`) à heure fixe.

- Ce que ça demande : un Personal Access Token GitHub **fine-grained**, scopé uniquement
  au repo de la veille réglementaire, avec la permission **"Actions" en Read and write**
  (rien d'autre — pas "Workflows", pas "Contents").
- Où il est stocké : dans la configuration du job cron-job.org (header `Authorization`),
  jamais dans le code ni dans les secrets GitHub.
- Comment le régénérer : GitHub → Settings → Developer settings → Personal access tokens
  → Fine-grained tokens → régénérer, puis mettre à jour le header du job sur cron-job.org.
- Ce token reste techniquement rattaché à la personne qui l'a créé (comme le Gmail
  ci-dessus) — c'est un compromis acceptable tant qu'on n'a pas besoin d'une identité
  indépendante d'une personne (voir note plus bas).

## Note : pourquoi pas une GitHub App ?

Une GitHub App réglerait le problème de dépendance à une personne pour le token GitHub,
mais elle ne résout pas le vrai problème du moment (déclenchement fiable à l'heure) : son
utilisation demande de signer un JWT et d'échanger un token d'installation à chaque appel,
ce qu'un simple service comme cron-job.org ne peut pas faire tout seul — il faudrait un
bout de code intermédiaire, qui aurait lui-même besoin d'un déclencheur fiable pour
tourner. Ça vaudra le coup d'y revenir si le token fine-grained devient un vrai problème
opérationnel, pas avant.

## Autres tâches de migration en attente

Voir aussi les tâches encore ouvertes avant la bascule en production complète : migrer
l'envoi de mail vers une boîte Workspace Theodo dédiée, basculer le dépôt de
`joseph-zamith/Compliance-timeline-test` vers `theodo-group/Compliance-timeline` avec les
vrais secrets, étendre `automation/recipients.json` au-delà d'une seule adresse de test.
