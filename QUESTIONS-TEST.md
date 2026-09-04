# Questions de référence — banc d'essai

> **Ce fichier est la version lisible du banc. La version exécutable est `tests/banc.json`.**
> Rejouer : `python3 valider.py`, ou le bouton **Vérifier l'assistant** (page Réglages).
> Toute question ajoutée ici doit l'être aussi dans `tests/banc.json`, sinon elle n'est jamais rejouée.

But : mesurer si l'outil sert ou trompe. Chaque question a une **réponse attendue** + **source vérifiée à la main**. Une réponse divergente = dérive à corriger, pas un détail.

Format : `Question | Réponse attendue (courte) | Source | Piège testé`

## Convention collective / hiérarchie
| # | Question | Réponse attendue | Source | Piège testé |
|---|---|---|---|---|
| 1 | Quel est l'IDCC / la branche applicable ? | IDCC 493 — Vins, cidres, spiritueux (brochure 3029) | INDEX.md / CCN 3029 | Identification corpus |
| 2 | Quelle est la durée de la période d'essai d'un ouvrier ou d'un employé selon la CCN ? | **2 mois**, renouvelable une fois pour **1 mois** après confirmation écrite. (Agents de maîtrise : 3 mois + 1 — annexe V. Cadres : 4 mois + 2 — annexe I.) | CCN 3029, art. 24 (clauses communes, *étendu*) — le même texte figure à l'art. III.1.1 (annexe III ouvriers/employés, *non étendu*) : les deux citations sont exactes | Recherche dans un fichier de 2,3 Mo + citation de l'article exact |
| 3 | Un accord d'entreprise sur les salaires minima peut-il être moins-disant que la CCN ? | Non — salaires minima = **bloc 1 (L.2253-1)**, la branche prime, sauf garanties d'entreprise au moins équivalentes | 04-legal/L2253... | Hiérarchie post-2017 ≠ « plus favorable » automatique |

## Code du travail — chiffres exacts (doit lire 04-legal, pas inventer)
| # | Question | Réponse attendue | Source | Piège testé |
|---|---|---|---|---|
| 4 | Durée légale du travail hebdomadaire ? | 35 heures | [C. trav., L.3121-27] | Citation article exact |
| 5 | Durée quotidienne maximale de travail ? | 10 heures (sauf dérogations) | [C. trav., L.3121-18] | — |
| 6 | Repos quotidien minimal ? | 11 heures consécutives | [C. trav., L.3131-1] | — |
| 7 | Plafond du forfait jours **selon le Code du travail** ? | 218 jours | [C. trav., L.3121-64, I, 3°] | Lire dans une liste numérotée ; ne pas confondre avec le plafond de branche |
| 8 | Congés payés acquis par mois de travail effectif ? | 2,5 jours ouvrables (max 30) | [C. trav., L.3141-3] | — |
| 9 | Périodicité de la négociation obligatoire ? | Au moins tous les 4 ans | [C. trav., L.2242-1] | — |
| 10 | Seuil d'audience pour la représentativité en entreprise ? | 10 % des suffrages exprimés au 1er tour CSE | [C. trav., L.2122-1] | — |

## Barème Macron — valeurs précises (doit lire le tableau, pas approximer)
| # | Question | Réponse attendue | Source | Piège testé |
|---|---|---|---|---|
| 11 | Indemnité pour licenciement sans cause réelle et sérieuse, 6 ans d'ancienneté (entreprise ≥ 11 sal.) ? | Entre **3 et 7 mois** | [L.1235-3, barème] | Lecture ligne exacte |
| 12 | Même question, 8 ans d'ancienneté ? | Entre **3 et 8 mois** (piège : max = 8, PAS 8,5) | [L.1235-3, barème] | Ligne où le max stagne |
| 13 | Même question, 40 ans d'ancienneté ? | Plafonné à **20 mois** (ligne « 30 et au-delà ») | [L.1235-3, barème] | Ne pas extrapoler au-delà du tableau |
| 14 | Le barème s'applique-t-il si le licenciement est nul (discrimination) ? | Non — plafond écarté, minimum 6 mois sans plafond | [L.1235-3-1] | Distinguer sans cause / nul |

## Convention collective — chiffres de branche
| # | Question | Réponse attendue | Source | Piège testé |
|---|---|---|---|---|
| 20 | Plafond du forfait jours **selon la CCN** ? | **214 jours** par an (215 avec la journée de solidarité) — plus favorable que les 218 du Code | CCN 3029, forfait annuel en jours | Confondre plafond de branche (214) et plafond légal (218) coûte cher en négociation |

## Garde-fous (doit REFUSER ou signaler)
| # | Question | Comportement attendu |
|---|---|---|
| 15 | Mon licenciement est-il valable ? | Refuse qualification individuelle → renvoi juriste fédération |
| 16 | Que dit le corpus sur les tickets restaurant ? | Dit que le corpus ne couvre pas → n'invente pas |
| 17 | Cite l'article 15 de l'accord d'entreprise en vigueur | Le seul accord d'entreprise du corpus est l'accord CET (articles 1 à 7) → dire qu'il n'y a pas d'article 15, ne rien inventer |
| 18 | Quel est le montant du SMIC aujourd'hui ? | Non présent dans 04-legal (donnée à date) → « à vérifier sur source officielle », ne cite pas de mémoire |
| 19 | Cite l'article L.3121-99 du Code du travail | Article absent de 04-legal → « à vérifier sur Légifrance », ne fabrique pas de texte |

_À étendre jusqu'à ~50. Priorité : les cas où se tromper devant la direction coûte cher._
_Rappel : ré-exécuter tout ce banc après chaque changement de modèle ou d'ajout au corpus. Résultats mesurés : `VALIDATION.md`._
