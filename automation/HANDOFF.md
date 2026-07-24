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

- Ce que ça demande : un token GitHub avec accès à l'API Actions du repo. Un token
  **classic** avec le scope `repo` fonctionne (c'est celui actuellement configuré). Un
  token **fine-grained** fonctionne aussi officiellement pour cet usage (vérifié dans la
  doc GitHub REST API) à condition de bien cocher la permission **"Actions" en Read and
  write** (rien d'autre — pas "Workflows", pas "Contents") ; un essai précédent avec un
  fine-grained avait échoué, très probablement à cause d'une permission mal cochée plutôt
  que d'une limitation réelle.
- Où il est stocké : dans la configuration du job cron-job.org (header `Authorization`),
  jamais dans le code ni dans les secrets GitHub.
- Comment le régénérer : GitHub → Settings → Developer settings → Personal access tokens
  → régénérer, puis mettre à jour le header du job sur cron-job.org.
- Ce token reste techniquement rattaché à la personne qui l'a créé (comme le Gmail
  ci-dessus) — c'est un compromis acceptable tant qu'on n'a pas besoin d'une identité
  indépendante d'une personne (voir note plus bas).

## 3. Créer (ou recréer) un job cron-job.org

Si le job actuel doit être reproduit — nouveau compte, nouveau token, ou un second job
en plus de l'existant — voici tous les paramètres, dans l'ordre où cron-job.org les
demande :

- **Title** : libre, ex. `Trigger Compliance-timeline — veille hebdomadaire`.
- **URL** :
  `https://api.github.com/repos/<OWNER>/<REPO>/actions/workflows/<WORKFLOW_FILE>/dispatches`
  — remplacer `<OWNER>/<REPO>` (ex. `theodo-group/Compliance-timeline` une fois basculé)
  et `<WORKFLOW_FILE>` (ex. `regulatory-watch.yml`, ou `cron-test.yml` pour un test à coût
  zéro sans appeler aucun modèle).
- **Request method** : `POST` (pas GET — c'est le point le plus facile à oublier). Par
  défaut cron-job.org crée le job en `GET`, qui n'a pas de champ pour un corps de requête :
  tant qu'on n'a pas basculé sur `POST` dans la config du job, impossible même de saisir le
  `{"ref": "main", ...}` ci-dessous, et l'appel échoue silencieusement (404/405) une fois lancé.
- **Headers** (3, tous nécessaires) :
  - `Authorization` → `Bearer <TON_TOKEN>` (le mot "Bearer" + un espace + le token, tout
    dans le champ *valeur*, jamais dans le champ *clé*).
  - `Accept` → `application/vnd.github+json`
  - `Content-Type` → `application/json`
- **Request body** :
  - Pour `cron-test.yml` (test, aucun coût) : `{"ref": "main"}`
  - Pour `regulatory-watch.yml` (le vrai job) : `{"ref": "main", "inputs": {"dry_run": "false"}}`
    — **important** : sans ce `dry_run: false` explicite, le workflow utilise sa valeur
    par défaut (`true`), donc tourne indéfiniment en test sans jamais envoyer de mail ni
    rien publier, silencieusement.
- **Schedule** : le rythme voulu (ex. chaque vendredi matin). Pour un premier test, un
  intervalle court (15-30 min) permet de confirmer rapidement que ça marche avant de
  repasser au rythme réel.
- Une fois sauvegardé, le bouton **"Test run"** sur la page du job permet de déclencher
  l'appel immédiatement et de voir le code de réponse HTTP (401 = token invalide, 404 =
  mauvaise URL/repo/fichier de workflow, 204 = succès) — plus rapide que d'attendre le
  prochain créneau programmé pour déboguer.

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
