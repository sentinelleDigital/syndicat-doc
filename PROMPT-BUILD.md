# Prompt de construction — Assistant Syndical v2

> **Quoi :** prompt à coller à Claude Code (Fable 5.1) pour finir le système.
> **Pourquoi ce fichier :** ta demande initiale était juste — mais trop courte pour être exécutable sans approximation. Un prompt vague produit un système vague ; c'est exactement le risque que tu veux éliminer.
> **Structure :** §A = prompt à copier-coller. §B = ce que j'ai corrigé et pourquoi. §C = corrections du prompt *runtime* (celui envoyé à Gemini, distinct du prompt de build).

---

# §A — Prompt à copier-coller

Déplacé dans **`PROMPT-FABLE-5-1.md`** — fichier autonome, à coller tel quel dans Claude Code (effort `high`).
Ce fichier-ci ne garde que l'analyse (§B et §C) pour éviter deux copies divergentes du prompt.

---

# §B — Ce que j'ai corrigé dans ta demande, et pourquoi

| Ta formulation | Problème | Correction |
|---|---|---|
| « complète ce système de manière expert » | Aucun critère d'arrêt : le modèle ne sait pas quand c'est fini. | Périmètre en 7 blocs numérotés + section « définition du terminé » vérifiable. |
| « rien ne doit être approximatif » | Consigne morale, non applicable. Un modèle ne peut pas « décider » de ne pas se tromper. | Traduit en garde-fous **en code** : vérification des citations, allowlist `04-legal/`, affichage des sources consultées, banc automatisé. |
| « tout doit être vérifié et validé » | Vérifié par qui ? Validé contre quoi ? | Banc de test exécutable + rapport + bouton de vérification dans l'interface. |
| « bonne interface utilisateur » | Non mesurable. | Public décrit (élu, non-dev, sous stress) + exigences concrètes (navigation, historique, erreurs en français, accessibilité). |
| « ajouter, supprimer, mettre à jour depuis l'interface » | Bon point, mais « supprimer » est dangereux sur un corpus juridique. | CRUD complet, mais suppression = archivage vers `_ABROGES/` + journal d'audit + restauration. |
| « assistant expert sans faille » | Impossible à tenir ; pousse le modèle à masquer ses incertitudes plutôt qu'à les afficher. | Inversé : l'outil doit **rendre visible** ce qu'il ne sait pas (badges, « non couvert », sources consultées, corpus périmé). |
| — (absent) | Ta demande ne disait pas au modèle de finir sans redemander la permission. | Bloc « Mode de travail » repris du patron Fable 5.1 « Terminez la tâche entière » — c'est ce bloc qui évite les « Dois-je continuer ? ». |
| — (absent) | Rien n'empêchait l'élargissement du périmètre ni la réécriture de fichiers entiers. | Blocs « Périmètre du livrable » et édition chirurgicale (patrons Fable 5.1 correspondants). |

**Patrons Fable 5.1 appliqués :** effort `high` par défaut ; autonomie et achèvement de tâche ; périmètre = livrable ; limitation des corrections et tests non demandés ; édition ciblée plutôt que réécriture ; mises à jour de progression destinées à l'utilisateur ; règle de formatage positive (listes quand elles aident) au lieu d'une interdiction ; suppression de la prose maniérée.

**Patron volontairement écarté :** les sous-agents. Sur ce projet (deux fichiers Python, corpus local), la délégation coûte plus qu'elle ne rapporte.

---

# §C — Corrections du prompt *runtime* (envoyé à Gemini)

Distinct du §A. Les patrons Fable 5.1 sont propres à Claude ; `demande.py` appelle Gemini. Ce qui suit s'applique quel que soit le modèle.

Défauts des `SYSTEM_QUESTION` / `SYSTEM_AUDIT` actuels :

1. **Aucune ancre de non-réponse.** « Si l'information n'est pas dans les documents, dis-le » est une consigne faible face à un modèle qui a du droit du travail en mémoire. Ajouter une contrainte de forme vérifiable : *toute phrase affirmant une règle doit se terminer par une référence entre crochets ; une phrase sans crochets est interdite.* Un contrôle en code peut alors la détecter.
2. **Pas d'ordre de priorité entre les sources fournies.** Le modèle reçoit `INDEX.md`, `04-legal/`, passages CCN, document audité, dans un même bloc. Indiquer explicitement la préséance : ordre public > bloc L.2253 applicable > accord > usage.
3. **La règle L.2253 est énoncée sans procédure.** Remplacer par une séquence : (1) identifier la matière, (2) déterminer le bloc, (3) citer L.2253-1/2/3, (4) conclure. Une procédure numérotée est bien mieux suivie qu'un principe.
4. **`SYSTEM_AUDIT` impose 6 sections mais aucune règle de remplissage à vide.** Ajouter : une section sans élément dans le corpus s'écrit « non couvert par le corpus » — jamais comblée par du raisonnement général.
5. **`temperature: 0.2` en mode question** : passer à `0`. Aucune créativité souhaitable sur de la restitution sourcée.
6. **Aucune consigne sur l'incertitude.** Ajouter : en cas de doute entre deux lectures d'un texte, exposer les deux et dire laquelle le corpus soutient — plutôt que de trancher silencieusement.

Ces six points sont à appliquer dans `demande.py` ; ils sont couverts par le bloc 2 de `PROMPT-FABLE-5-1.md`.
