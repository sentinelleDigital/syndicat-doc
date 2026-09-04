# Assistant Syndical — prompt de construction (Claude Opus 5)

> Coller tel quel dans Claude Code. Réflexion activée (défaut). Effort : `high` pour l'ensemble ; `xhigh` acceptable sur les blocs multi-fichiers (1 et 3).
> Ne pas désactiver la réflexion : à coût comparable, réflexion activée en effort `low` donne de meilleurs résultats que réflexion désactivée.

---

## Contexte

Projet `syndicat` : assistant documentaire d'un syndicat d'entreprise (SAS FRERES, branche IDCC 493 / CCN 3029). Utilisateur unique : un élu syndical **non développeur**, **sans service juridique**, **sans juriste pour relire les textes**. Il n'a personne pour rattraper une erreur de l'outil.

Conséquence directe sur la conception : **une réponse fausse est pire qu'une absence de réponse.** L'outil doit se taire ou dire « non couvert » plutôt que produire une affirmation plausible non sourcée. Toute fonctionnalité qui ne peut pas être vérifiée automatiquement doit être supprimée ou marquée explicitement comme non vérifiée dans l'interface.

État actuel : `demande.py` (moteur CLI + appel Gemini), `serveur.py` (interface web locale sur 127.0.0.1:8765), corpus en markdown dans `01-accords/` à `05-pv-cse/`, `INDEX.md` et `04-legal/_INDEX-legal.md` maintenus **à la main**, `QUESTIONS-TEST.md` (19 questions) rejoué **à la main**. Lis ces fichiers avant de proposer quoi que ce soit.

## Périmètre et jugement

Livre ce qui est demandé, au périmètre voulu. Tranche toi-même les arbitrages de routine, et ne remonte que si deux lectures de la demande mèneraient à un travail réellement différent. Si la demande te paraît erronée ou qu'une meilleure approche existe, dis-le en une phrase et poursuis la tâche telle qu'elle est demandée, plutôt que de la rétrécir, l'élargir ou la transformer en silence. Termine la tâche entière, et arrête-toi avant les actions clairement au-delà de ce qui est demandé.

Si tu découvres en travaillant un bug préexistant, un souci de performance ou un comportement que la tâche ne mentionne pas, ne le corrige pas dans ce lot sauf si le comportement demandé ne peut pas fonctionner sans : signale-le en fin de résumé comme suite à donner.

Ne t'arrête pas pour demander la permission d'une étape que cette demande couvre déjà. L'utilisateur ne regarde pas en temps réel. Ne t'arrête que pour une action destructrice — suppression de fichiers du corpus, réécriture de `INDEX.md` sans sauvegarde, `git push` — ou un vrai changement de périmètre.

## Délégation

Ne délègue à un sous-agent que pour un volet réellement indépendant et volumineux. Ce projet tient en deux fichiers Python et un corpus local : la quasi-totalité du travail se fait plus vite en direct. Ne délègue pas ce que tu peux finir en quelques appels d'outils, et n'utilise pas de sous-agent pour vérifier ton propre travail. Si un seul agent suffit, n'en lance pas plusieurs.

## Communication pendant le travail

Avant ton premier appel d'outil, dis en une phrase ce que tu vas faire. Pendant le travail, ne donne une brève mise à jour que si tu trouves quelque chose d'important ou que tu changes de direction. En terminant, commence par le résultat : la première phrase doit répondre « qu'est-ce qui s'est passé » ou « qu'est-ce que tu as trouvé », le détail vient après.

Ne corrige une affirmation antérieure que si l'erreur change le code, les conclusions ou les décisions de l'utilisateur. Énonce la correction simplement et brièvement, puis continue. Pour une bévue sans conséquence, corrige et passe à la suite sans le signaler.

## Ce qu'il faut construire

### 1. Gestion du corpus depuis l'interface (ajouter / modifier / supprimer)

L'utilisateur ne doit **jamais** avoir à ouvrir un terminal ni à éditer un `.md` à la main.

- Page « Corpus » dans `serveur.py` : liste des documents (dossier, titre, statut, date d'effet, date de vérification), avec recherche et filtre par statut.
- **Ajouter** : dépôt de fichier (`.md`, `.txt`, `.pdf`) → formulaire de métadonnées obligatoire (catégorie, titre, statut `projet | en vigueur | abrogé`, date de signature, date d'effet, source). Un document sans métadonnées complètes n'entre pas dans le corpus.
- **Modifier** : édition des métadonnées et du texte, avec aperçu du diff avant enregistrement.
- **Supprimer** : jamais de suppression réelle. Déplacement vers `_ABROGES/` avec renommage `_REMPLACE-PAR-<fichier>` et confirmation explicite en deux temps.
- **`INDEX.md` généré, jamais écrit à la main** : il devient une sortie calculée à partir des métadonnées des fichiers. Un index maintenu manuellement dérive du corpus réel — c'est la première source d'erreur silencieuse à supprimer.
- Le PDF déposé est converti en markdown puis **affiché à l'utilisateur pour validation** avant ingestion (une extraction PDF ratée produit un corpus faux sans que personne ne le voie).
- Journal d'audit append-only (`_journal/`) : qui, quand, quoi, ancienne valeur → nouvelle valeur. Restauration possible depuis le journal.

### 2. Anti-approximation — garde-fous techniques, pas seulement des consignes

Une règle écrite dans un prompt est une intention ; un contrôle en code est une garantie. Chaque règle de fond ci-dessous doit exister **en code**, en plus du prompt.

- **Vérification des citations après génération** : extraire du texte produit chaque référence (`L.xxxx-x`, `art. X`, nom de fichier) et vérifier qu'elle apparaît littéralement dans le contexte envoyé au modèle. Toute citation non retrouvée est signalée **dans la réponse affichée** (badge « ⚠ référence non vérifiée dans le corpus ») — jamais masquée.
- **Aucun article du Code du travail hors `04-legal/`** : si le modèle cite un article absent de `04-legal/`, la réponse porte l'avertissement « à vérifier sur Légifrance » à cet endroit précis.
- **Détection de question individuelle** : classifieur simple (motifs « mon / ma / je / mon licenciement / suis-je ») déclenchant le renvoi vers un juriste de fédération avant même l'appel au modèle.
- **Fraîcheur du corpus** : tout extrait `04-legal/` dont `verifie_le` a plus de 6 mois est affiché avec un bandeau « à re-vérifier » dans toute réponse qui s'en sert.
- **Documents au statut `projet`** : signalés visuellement dans la réponse, jamais présentés comme du droit applicable.

### 3. Fiabilité de la recherche documentaire (le point faible actuel)

`load_filtered()` sélectionne les passages par comptage brut de mots-clés. C'est le maillon qui décide de ce que le modèle voit ; s'il rate le bon article, le modèle répond faux **avec assurance**. À corriger :

- Normalisation : minuscules, accents repliés, pluriels/élisions gérés (`congés`/`conge`, `l'accord`/`accord`).
- Reconnaissance directe des numéros d'article dans la question (`L.3121-64`, `art. 12`) → récupération prioritaire du passage correspondant.
- Extraction par **section titrée** de la CCN plutôt que par paragraphe brut, pour ne pas couper un article en deux.
- Synonymes métier (`RTT`/`réduction du temps de travail`, `CET`/`compte épargne-temps`, `forfait jours`/`forfait annuel en jours`).
- **Affichage à l'utilisateur des passages réellement envoyés au modèle** (section repliable « Sources consultées »). Un utilisateur non juriste ne peut pas vérifier une réponse, mais il peut voir que l'outil n'a pas ouvert le bon article.

### 4. Validation automatisée

`QUESTIONS-TEST.md` est un banc rejoué à la main, donc jamais rejoué.

- Convertir les 19 questions en jeu de test exécutable (`tests/banc.json` : question, réponse attendue, articles devant être cités, comportement attendu pour les garde-fous 15–19).
- `python3 valider.py` exécute le banc, compare, et écrit un rapport lisible : réussites, échecs, écarts de citation.
- Bouton « Vérifier l'assistant » dans l'interface, avec résultat en clair (« 19/19 conforme », ou la liste des écarts). L'utilisateur doit pouvoir contrôler l'outil sans ligne de commande.
- Compléter les questions 2 et les cases « à compléter » du banc en lisant réellement la CCN.

### 5. Interface

Publics : un élu, sous stress, parfois en réunion. Garder le style actuel (sobre, Apple-like, `serveur.py`), et ajouter :

- Navigation claire entre les trois usages : **Question**, **Audit**, **Corpus**.
- Historique local des questions et réponses (fichier local, consultable, exportable) — l'outil est sans mémoire, l'utilisateur ne doit pas l'être.
- Réponse en flux (streaming) ou indicateur de progression réel : un écran figé pendant 30 secondes est lu comme une panne.
- Message d'erreur en français utile (« clé API absente », « quota Gemini épuisé — réessayer demain ou changer de modèle »), jamais une trace technique.
- Export PDF déjà présent : conserver, et ajouter l'export de la réponse simple, pas seulement de l'audit.
- Accessibilité : contraste, taille de police confortable, fonctionnement au clavier seul.

### 6. Exactitude du modèle

`gemini-flash-lite-latest` est le modèle le plus faible de la gamme. Il est utilisé pour du raisonnement juridique où « chaque approximation coûte cher » : c'est une contradiction à traiter explicitement, pas à ignorer.

- Rendre le modèle configurable depuis l'interface (page Réglages), avec l'arbitrage écrit en clair : gratuit/limité vs payant/plus fiable.
- Mesurer le banc de test sur au moins deux modèles et écrire les résultats comparés dans `VALIDATION.md`. Recommander ensuite un modèle sur preuve, pas sur intuition.
- `temperature: 0` pour le mode question (actuellement 0.2 — inutile sur de la restitution sourcée).

### 7. Confidentialité

`README.md` annonce une pseudonymisation Presidio qui n'existe nulle part dans le code.

- Soit l'implémenter (détection noms/matricules/adresses avant envoi, avec confirmation visuelle de ce qui a été masqué), soit retirer la promesse de la documentation. Une garantie de confidentialité fausse est pire qu'aucune garantie.
- Avertissement clair dans l'interface avant tout envoi d'un document joint : « ce document part chez Google ».

## Ce que doit contenir le rapport final

Lance `python3 serveur.py` et exerce dans le navigateur chaque parcours que tu as modifié (ajout, modification, archivage, question, audit, PDF, banc de test). Vérifie aussi que l'application démarre sans clé API sur un message clair, et non sur une trace Python.

Termine par un récapitulatif autonome, lisible par quelqu'un qui ne verrait que ce dernier message :

- Ce qui a été construit, bloc par bloc.
- Le résultat réel de `python3 valider.py` sur le banc des 19 questions — chiffres bruts, échecs inclus. Un banc non passé se rapporte tel quel, jamais arrondi.
- Ce qui a été exercé dans le navigateur et ce qui ne l'a pas été.
- Ce qui reste ouvert ou bloqué, et pourquoi.

Si une partie du périmètre s'avère bloquée, termine toutes les autres en entier et dis exactement ce que tu as laissé de côté. Réduire le périmètre est une décision de l'utilisateur, pas la tienne.

## Contraintes techniques

- **Stdlib Python uniquement** — pas de framework, pas de `pip install`, pas de build. L'utilisateur n'est pas développeur et doit pouvoir lancer l'outil par un double-clic (`Assistant-Syndical.desktop`). Une dépendance externe est un point de panne qu'il ne saura pas réparer. Seule exception admissible : la pseudonymisation, si elle est retenue — alors avec repli propre si la bibliothèque est absente.
- Serveur lié à `127.0.0.1` uniquement. Rien d'exposé sur le réseau.
- Corpus en markdown versionné dans git : lisible, diffable, réparable à la main en dernier recours.
- Tout en français, interface comprise.
- Ne jamais versionner `.env`.

## Style de sortie

Réponses concises. Garde les mises en garde courtes et consacre l'essentiel du message au fond. Listes et tableaux quand le contenu est assez multi-facettes pour que cela aide à la clarté.

Calibre la longueur des documents écrits sur disque (README, `VALIDATION.md`, commentaires) sur ce que la tâche exige : couvre le fond, sans sections de remplissage, résumés redondants ni passages standardisés.

Le nombre de tokens dépensés à éditer des fichiers doit rester minimal, toutes choses égales par ailleurs. Quand cela ne change pas le résultat, édite chirurgicalement un fichier plutôt que de le réécrire en entier.

## Ordre d'exécution suggéré

Commence par les garde-fous (bloc 2) et la fiabilité de la recherche (bloc 3) : ce sont eux qui déterminent si l'outil aide ou trompe. Puis la validation automatisée (bloc 4), qui prouve que le reste ne régresse pas. Puis la gestion du corpus (bloc 1) et l'interface (bloc 5). Le choix du modèle (bloc 6) se tranche avec les mesures du bloc 4 en main.

