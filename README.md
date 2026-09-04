# syndicat-doc — Assistant documentaire syndical

Outil interne d'un syndicat (branche **IDCC 493** — vins, cidres, spiritueux, CCN 3029).
Répond aux questions du personnel et produit des audits croisés (accord × convention
collective × Code du travail), en **citant systématiquement la source** et en
**refusant d'inventer**.

Corpus figé et local, cerveau distant (Gemini). Le corpus ne quitte pas la machine :
seuls les passages retenus et la question sont envoyés au modèle.

> **Une réponse fausse est pire qu'une absence de réponse.** L'outil préfère dire
> « non couvert » plutôt que produire une affirmation plausible non sourcée.

---

## Installation

Rien à compiler, aucune dépendance : **python3** et une **clé Gemini gratuite**.

1. Clé API Gemini (gratuit, sans carte) : https://aistudio.google.com/apikey
2. La déposer dans `.env` :
   ```bash
   cp .env.example .env
   # éditer .env :  GEMINI_API_KEY=ta_cle
   ```

`.env` n'est jamais versionné. Sans clé, l'interface démarre quand même et affiche
la marche à suivre — elle ne plante pas.

## Lancement

**Double-clic sur l'icône « Assistant Syndical »** (ou `./lancer.sh`). Le navigateur
s'ouvre sur `http://127.0.0.1:8765` (port suivant si celui-ci est occupé). Tout reste
local : rien n'est exposé sur le réseau. Fermer la fenêtre du terminal arrête l'outil.

L'interface a cinq pages :

| Page | À quoi elle sert |
|---|---|
| **Question** | Question courte, réponse sourcée en flux, contrôles automatiques affichés |
| **Audit** | Croisement d'un document avec la CCN et le Code du travail, export PDF |
| **Corpus** | Ajouter / modifier / archiver un document, journal et restauration |
| **Historique** | Les questions déjà posées, consultables et exportables |
| **Réglages** | Choix du modèle et bouton **Vérifier l'assistant** (banc de 19 questions) |

## Ce que l'outil vérifie tout seul

Ces contrôles sont **en code**, pas seulement dans le prompt — une consigne se
contourne, un contrôle non :

- **Citations** : chaque référence produite (`L.3121-27`, `art. 24`, nom de fichier)
  est recherchée littéralement dans ce qui a été envoyé au modèle. Introuvable →
  badge « référence non vérifiée » dans la réponse, jamais masqué.
- **Code du travail hors `04-legal/`** : un article cité qui n'est pas dans les
  extraits vérifiés porte la mention « à vérifier sur Légifrance ».
- **Question individuelle** (« mon licenciement est-il valable ? ») : détectée
  **avant** l'appel au modèle → renvoi vers un juriste de la fédération.
- **Fraîcheur** : un extrait légal vérifié il y a plus de 6 mois affiche un bandeau
  « à re-vérifier ».
- **Statut `projet`** : un document non signé n'est jamais présenté comme applicable.
- **Sources consultées** : la liste des passages réellement envoyés au modèle est
  dépliable sous chaque réponse. On ne peut pas vérifier une réponse sans être
  juriste, mais on voit si l'outil a ouvert le bon article.

## Gestion du corpus — sans terminal

Tout se fait depuis la page **Corpus** :

- **Ajouter** : déposer un `.md`, `.txt` ou `.pdf`. Un PDF est converti en texte et
  **affiché pour relecture avant enregistrement** (une extraction ratée ferait un
  corpus faux sans que personne ne le voie). L'original est conservé dans `_sources/`.
  Métadonnées obligatoires : titre, statut, date de signature, date d'effet, source —
  sans elles, le document n'entre pas.
- **Modifier** : métadonnées et texte, avec **aperçu du diff** avant enregistrement.
- **Archiver** : jamais de suppression. Le document part dans `_ABROGES/` sous le nom
  `_REMPLACE-PAR-<fichier>`, après confirmation en deux temps.
- **Journal** (`_journal/`) : chaque écriture est enregistrée avec l'état antérieur.
  Un bouton restaure cet état.

**`INDEX.md` est généré**, jamais écrit à la main : c'est une sortie calculée à partir
des métadonnées de chaque document. Un index tenu à la main dérive du corpus réel —
c'était la première source d'erreur silencieuse.

## Validation

```bash
python3 valider.py                       # modèle courant
python3 valider.py --modele gemini-flash-latest
python3 valider.py --compare gemini-flash-lite-latest gemini-flash-latest
```

Ou, sans terminal : bouton **Vérifier l'assistant** (page Réglages).

Le banc exécutable est `tests/banc.json` (19 questions, version lisible dans
`QUESTIONS-TEST.md`). L'évaluation est mécanique — expressions régulières sur la
réponse et vérification des articles cités. **Aucun modèle ne juge un autre modèle.**
Résultats mesurés : `VALIDATION.md`.

## Ligne de commande

```bash
python3 demande.py "quelle est la durée légale hebdomadaire ?"
python3 demande.py --audit --doc 06-cet/cet.md "cet accord est-il conforme ?"
python3 demande.py --audit --pdf rapport.html --doc 06-cet/cet.md "conforme ?"
```

## Organisation du corpus

```
01-accords/               accords d'entreprise (un dossier par sujet)
02-reglement-interieur/   règlement intérieur
03-convention-collective/ CCN 3029 (volumineuse — lue par sections titrées)
04-legal/                 extraits Code du travail, texte verbatim + daté
05-pv-cse/                PV de CSE — EXCLU en code de tout envoi au modèle
06-cet/                   accord d'entreprise compte épargne-temps
_ABROGES/                 documents remplacés (jamais cités)
_sources/                 originaux déposés (PDF) — non lus par l'assistant
_journal/                 journal des écritures + états antérieurs
_historique/              questions posées (local, non versionné)
_templates/               interface web + gabarit du rapport PDF
INDEX.md                  état du corpus — GÉNÉRÉ, ne pas éditer
tests/banc.json           banc de validation exécutable
```

Tout dossier nommé `NN-sujet` est découvert automatiquement : ajouter une catégorie
ne demande aucune modification du code.

## Choix du modèle

Le modèle se change dans **Réglages**, avec l'arbitrage écrit en clair : gratuit et
plus faible, ou payant et plus fiable. Après tout changement, relancer
« Vérifier l'assistant » — un modèle non mesuré est un modèle dont on ignore le taux
d'erreur. Les mesures comparées sont dans `VALIDATION.md`.

## Confidentialité

- **Accords, RI, CCN, Code du travail = publics** → envoi au modèle sans souci.
- **`05-pv-cse/` est exclu en code** de tout envoi au modèle (`corpus.DOSSIERS_NOMINATIFS`).
- Avant l'envoi d'un document joint, l'interface avertit explicitement que
  **le document part chez Google** et propose de masquer les données personnelles
  détectées (noms, matricules, adresses, téléphones, courriels, n° de sécurité
  sociale), en **affichant ce qu'elle a masqué**.
- Cette détection est **heuristique et non exhaustive** : ce qu'elle ne voit pas part
  en clair. Aucune bibliothèque de pseudonymisation n'est installée. Pour une pièce
  nominative, relire soi-même avant de la joindre.

## Limites connues

- **Sans mémoire** : chaque question doit être auto-portante. « Et pour 8 ans ? »
  seul est ambigu — reformuler complètement. (L'historique est consultable, mais il
  n'est pas envoyé au modèle.)
- **Recherche par mots-clés et sections** : améliorée (accents, pluriels, synonymes,
  reconnaissance des numéros d'article, découpage par article), mais non garantie à
  100 %. Le banc de test et la liste « Sources consultées » sont les garde-fous.
- **Extraction PDF** : couvre les PDF texte, pas les PDF scannés (aucun OCR). Une
  extraction quasi vide est signalée comme telle.
- **Le modèle par défaut est le plus faible de la gamme** (quota gratuit le plus
  large). Voir `VALIDATION.md` pour ce que cela coûte en exactitude.

## Ce que l'outil ne fait pas

Il n'est pas juriste. Il ne qualifie **jamais** un cas individuel et renvoie vers un
juriste de la fédération. Toute référence destinée à un contentieux doit être
revérifiée sur Légifrance.
