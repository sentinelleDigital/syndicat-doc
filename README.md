# syndicat-doc — Assistant documentaire syndical

Outil interne d'un syndicat (branche **IDCC 493** — vins, cidres, spiritueux, CCN 3029).
Répond aux questions du personnel et produit des audits croisés (accord × convention
collective × Code du travail), en **citant systématiquement la source** et en
**refusant d'inventer**.

Corpus figé et local, cerveau distant (Gemini). Le corpus ne quitte pas la machine :
seul le passage pertinent + la question sont envoyés au modèle.

---

## Installation

Rien à compiler. Il faut seulement **python3** (déjà présent) et une **clé Gemini gratuite**.

1. Clé API Gemini (gratuit, sans carte) : https://aistudio.google.com/apikey
2. La déposer dans `.env` :
   ```bash
   cp .env.example .env
   # éditer .env :  GEMINI_API_KEY=ta_cle
   ```

`.env` n'est jamais versionné (voir `.gitignore`).

---

## Utilisation

### Mode question (défaut) — question d'un salarié / élu
```bash
python3 demande.py "quelle est la durée légale hebdomadaire ?"
python3 demande.py "combien de repos entre deux journées de travail ?"
```
Réponse courte, chaque affirmation citée `[C. trav., L.xxxx]` ou `[CCN 3029, art. X]`.
Modèle : `gemini-flash-latest` (gratuit).

### Mode audit — croisement de documents
```bash
# audit sur le corpus général
python3 demande.py --audit "conformité du forfait jours entre Code du travail et CCN ?"

# audit d'un document précis
python3 demande.py --audit --doc 01-accords/forfait/accord.md "cet accord est-il conforme ?"
```
Produit une analyse structurée : synthèse, tableau des risques, analyse détaillée,
hiérarchie des normes, recommandations, sources.

### Mode audit → PDF
```bash
python3 demande.py --audit --pdf rapport.html --doc 01-accords/forfait/accord.md "conforme ?"
```
Écrit `rapport.html` (stylé). L'ouvrir dans un navigateur → **Ctrl+P → Enregistrer en PDF**.

---

## Organisation du corpus

```
01-accords/               accords d'entreprise EN VIGUEUR (un dossier par sujet)
02-reglement-interieur/   règlement intérieur
03-convention-collective/ CCN 3029 (volumineuse — lue par extraits ciblés)
04-legal/                 extraits Code du travail, texte verbatim + daté
05-pv-cse/                PV de CSE (À PSEUDONYMISER avant d'ajouter — voir Confidentialité)
_ABROGES/                 documents remplacés (jamais cités)
_sources/                 originaux (PDF, .txt) — non lus par l'outil
_templates/               gabarit du rapport PDF
INDEX.md                  état du corpus (source de vérité)
AGENTS.md                 règles de l'assistant
QUESTIONS-TEST.md         banc de 19 questions de validation
demande.py                l'outil
```

## Ajouter un document

1. Poser le fichier dans le bon dossier (le convertir en `.md` s'il est en PDF).
2. Mettre à jour `INDEX.md` (une ligne : quoi, statut, date).
3. Pour un extrait de Code du travail : copier le **texte verbatim** depuis
   [code.travail.gouv.fr](https://code.travail.gouv.fr) avec en-tête daté, puis
   mettre à jour `04-legal/_INDEX-legal.md`.

L'outil **scanne automatiquement tous les dossiers du corpus** (`01-accords`, `02-reglement-interieur`,
`03-convention-collective`, `04-legal`) — aucun code à toucher, jamais de document en dur. Un accord
ou RI court est envoyé entier ; la CCN (volumineuse) est lue par passages ciblés. `05-pv-cse`,
`_ABROGES` et `_sources` sont exclus (nominatif / abrogé / originaux).

## Validation

Rejouer le banc après tout changement (modèle, corpus, règles) :
```bash
python3 demande.py "durée légale hebdomadaire ?"
```
Voir `QUESTIONS-TEST.md` pour les 19 questions et leurs réponses attendues.
Une réponse divergente = dérive à corriger avant tout usage réel.

---

## Confidentialité

- **Accords, RI, CCN, Code du travail = publics** → envoi au modèle sans souci.
- **PV de CSE / cas individuels = données personnelles** → **pseudonymiser avant**
  (noms, matricules) ou ne pas ingérer. Ne jamais envoyer de nominatif au modèle en clair.

## Limites connues

- **Sans mémoire** : chaque question doit être auto-portante (« et pour 8 ans ? » seul
  est ambigu). Reformuler complètement.
- **CCN par mots-clés** : l'extraction de la convention collective est par mots-clés.
  Fiable sur les tests, non garantie à 100 % ; le banc de test reste le garde-fou.
- **Gemini Pro** n'est pas sur le tier gratuit (quota 0) : tout tourne sur Flash. Pour
  passer à Pro (meilleur raisonnement, payant) : `export GEMINI_MODEL_AUDIT=gemini-pro-latest`.

## Ce que l'outil ne fait pas

Il n'est pas juriste. Il ne qualifie **jamais** un cas individuel (« mon licenciement
est-il valable ? ») et renvoie vers un juriste de la fédération. Toute référence
destinée à un contentieux doit être revérifiée sur Légifrance.
