# Assistant Syndical — prompt de construction (Claude Fable 5.1)

> Coller tel quel dans Claude Code. Effort recommandé : `high`.
> Ne pas monter à `xhigh`/`max` : sur un livrable long, le modèle rédige deux fois — une fois en raisonnement, une fois en réponse — et coûte le double sans gain mesuré ici.

---

## Contexte

Projet `syndicat` : assistant documentaire d'un syndicat d'entreprise (SAS FRERES, branche IDCC 493 / CCN 3029). Utilisateur unique : un élu syndical **non développeur**, **sans service juridique**, **sans juriste pour relire les textes**. Il n'a personne pour rattraper une erreur de l'outil.

Conséquence directe sur la conception : **une réponse fausse est pire qu'une absence de réponse.** L'outil doit se taire ou dire « non couvert » plutôt que produire une affirmation plausible non sourcée. Toute fonctionnalité qui ne peut pas être vérifiée automatiquement doit être supprimée ou marquée explicitement comme non vérifiée dans l'interface.

État actuel : `demande.py` (moteur CLI + appel Gemini), `serveur.py` (interface web locale sur 127.0.0.1:8765), corpus en markdown dans `01-accords/` à `05-pv-cse/`, `INDEX.md` et `04-legal/_INDEX-legal.md` maintenus **à la main**, `QUESTIONS-TEST.md` (19 questions) rejoué **à la main**. Lis ces fichiers avant de proposer quoi que ce soit.

## Mode de travail

Tu opères en autonomie. L'utilisateur ne regarde pas en temps réel et ne peut pas répondre en cours de tâche : poser « Veux-tu que je… ? » ou « Dois-je continuer ? » bloque le travail. Pour toute action réversible qui découle de la demande, avance sans demander. Ne t'arrête que pour une action destructrice (suppression de fichiers du corpus, réécriture de `INDEX.md` sans sauvegarde, `git push`) ou un vrai changement de périmètre.

Avant de terminer ton tour, relis ton dernier paragraphe. Si c'est un plan, une analyse, une question, une liste d'étapes suivantes, ou une promesse (« je vais ensuite… », « il faudrait… »), fais ce travail maintenant avec des appels d'outils. Cela inclut réessayer après une erreur et aller chercher toi-même l'information manquante. Ne t'arrête pas parce que la session est longue. Termine ton tour seulement quand la tâche est finie ou que tu es bloqué sur une information que seul l'utilisateur détient.

Avant une commande qui modifie l'état du système, vérifie que les preuves soutiennent bien cette action précise. Un symptôme qui ressemble à une panne connue peut avoir une autre cause.

Dis en une ligne ce que tu t'apprêtes à faire avant de commencer ; de brèves mises à jour pendant le travail permettent de suivre. Termine par un récapitulatif autonome — ce que tu as trouvé, ce que tu as fait, ce qui reste — lisible par quelqu'un qui ne verrait que ce dernier message.

## Périmètre du livrable

La demande ci-dessous fixe le périmètre, et le périmètre **est** le livrable : ne le rétrécis pas, ne l'élargis pas, ne le remplace pas en silence. Lis l'ambiguïté comme le ferait un collègue prudent : tranche toi-même les arbitrages de routine, et ne remonte que si deux lectures mèneraient à un travail réellement différent. Si tu vois un vrai problème dans la tâche telle que spécifiée, dis-le en une ou deux phrases et continue à construire sous hypothèse déclarée.

Si une question surgit en cours de route, fais d'abord tout ce qui n'en dépend pas ; puis énonce l'hypothèse retenue. Si un point s'avère bloqué, termine tous les autres **en entier** et dis exactement ce que tu as laissé de côté et pourquoi. Réduire le périmètre est une décision de l'utilisateur, pas la tienne.

Si tu découvres en travaillant un bug préexistant, un souci de performance ou un comportement que la tâche ne mentionne pas, ne le corrige pas dans ce lot sauf si le comportement demandé ne peut pas fonctionner sans : signale-le en fin de résumé comme suite à donner.

Le nombre de tokens dépensés à éditer des fichiers doit rester minimal, toutes choses égales par ailleurs. Quand cela ne change pas le résultat, édite chirurgicalement un fichier plutôt que de le réécrire en entier.

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

## Vérification — définition du « terminé »

Ne déclare pas une tâche finie sans avoir :

1. Lancé `python3 serveur.py` et exercé chaque parcours modifié dans le navigateur (ajout, modification, archivage, question, audit, PDF, banc de test).
2. Exécuté `python3 valider.py` et joint les résultats réels — y compris les échecs. Un banc non passé se rapporte tel quel, jamais arrondi.
3. Vérifié qu'aucune régression n'atteint les 19 questions du banc.
4. Vérifié que l'application démarre sans clé API avec un message clair, et non par une trace Python.

Rapporte les résultats fidèlement : si un test échoue, dis-le avec la sortie ; si une étape a été sautée, dis-le.

## Contraintes techniques

- **Stdlib Python uniquement** — pas de framework, pas de `pip install`, pas de build. L'utilisateur n'est pas développeur et doit pouvoir lancer l'outil par un double-clic (`Assistant-Syndical.desktop`). Une dépendance externe est un point de panne qu'il ne saura pas réparer. Seule exception admissible : la pseudonymisation, si elle est retenue — alors avec repli propre si la bibliothèque est absente.
- Serveur lié à `127.0.0.1` uniquement. Rien d'exposé sur le réseau.
- Corpus en markdown versionné dans git : lisible, diffable, réparable à la main en dernier recours.
- Tout en français, interface comprise.
- Ne jamais versionner `.env`.

## Style de sortie

Utilise listes et tableaux quand le contenu est assez multi-facettes pour que cela aide à la clarté. Supprime la prose maniérée : dire ce que l'on veut dire, littéralement, plutôt que par métaphore ou formule d'effet.

## Ordre d'exécution suggéré

Commence par les garde-fous (bloc 2) et la fiabilité de la recherche (bloc 3) : ce sont eux qui déterminent si l'outil aide ou trompe. Puis la validation automatisée (bloc 4), qui prouve que le reste ne régresse pas. Puis la gestion du corpus (bloc 1) et l'interface (bloc 5). Le choix du modèle (bloc 6) se tranche avec les mesures du bloc 4 en main.

