# Validation de l'assistant

Sortie de `python3 valider.py` — banc de 19 questions (`tests/banc.json`).
Évaluation mécanique : expressions régulières sur la réponse + vérification des articles cités. Aucun modèle ne juge un autre modèle.

## Résultats par modèle

| Modèle | Conforme | Écarts | Non mesurées | Durée | Mesuré le |
|---|---|---|---|---|---|
| `gemini-flash-lite-latest` | 18/19 | 1 | 0 | 368.6 s | 2026-09-04T12:49:08 |
| `gemini-flash-latest` | 4/4 | 0 | 15 | 130.9 s | 2026-09-04T12:51:19 |

## Détail des écarts

### `gemini-flash-lite-latest` — 18/19

**Q7 — Quel est le nombre maximal de jours travaillés dans une convention de forfait annuel en jours ?**

- Attendu : 218 jours
- Piège testé : lire une valeur dans une liste numérotée
- Écart : attendu, absent de la réponse : \b218\b
- Réponse obtenue : « Le nombre maximal de jours travaillés dans une convention de forfait annuel en jours est fixé à **214 jours par an** (le plafond de 214 jours pouvant être porté à 215 jours avec la journée de solidarité). Justification : * Le contrat de travail fixe le nombre de jours effectivement travaillés qui ne… »

### `gemini-flash-latest` — 4/4

**Q3 — Un accord d'entreprise sur les salaires minima peut-il être moins favorable que la convention de branche ?**

- Attendu : Non. Les salaires minima hiérarchiques relèvent du bloc 1 (L.2253-1) : la branche prime, sauf garanties d'entreprise au moins équivalentes.
- Piège testé : hiérarchie post-2017, pas de « plus favorable » automatique
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q4 — Quelle est la durée légale hebdomadaire du travail ?**

- Attendu : 35 heures par semaine
- Piège testé : citation de l'article exact
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q5 — Quelle est la durée quotidienne maximale de travail effectif ?**

- Attendu : 10 heures, sauf dérogations
- Piège testé : —
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q6 — Quelle est la durée minimale du repos quotidien entre deux journées de travail ?**

- Attendu : 11 heures consécutives
- Piège testé : —
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q7 — Quel est le nombre maximal de jours travaillés dans une convention de forfait annuel en jours ?**

- Attendu : 218 jours
- Piège testé : lire une valeur dans une liste numérotée
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q8 — Combien de jours de congés payés le salarié acquiert-il par mois de travail effectif ?**

- Attendu : 2,5 jours ouvrables par mois, dans la limite de 30 jours ouvrables
- Piège testé : —
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q10 — Quel est le seuil d'audience électorale pour qu'un syndicat soit représentatif dans l'entreprise ?**

- Attendu : 10 % des suffrages exprimés au premier tour des élections du CSE
- Piège testé : —
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q11 — Quel est le montant de l'indemnité pour licenciement sans cause réelle et sérieuse pour un salarié ayant 6 ans d'ancienneté complets, dans une entreprise d'au moins 11 salariés ?**

- Attendu : Entre 3 et 7 mois de salaire brut
- Piège testé : lecture de la ligne exacte du tableau
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q12 — Quel est le montant de l'indemnité pour licenciement sans cause réelle et sérieuse pour un salarié ayant 8 ans d'ancienneté complets, dans une entreprise d'au moins 11 salariés ?**

- Attendu : Entre 3 et 8 mois — le maximum stagne à 8, il n'est pas de 8,5
- Piège testé : ligne où le plafond stagne : extrapoler donnerait 8,5
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q13 — Quel est le montant de l'indemnité pour licenciement sans cause réelle et sérieuse pour un salarié ayant 40 ans d'ancienneté, dans une entreprise d'au moins 11 salariés ?**

- Attendu : Plafonné à 20 mois (ligne « 30 ans et au-delà »)
- Piège testé : ne pas extrapoler au-delà du tableau
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q14 — Le barème d'indemnité de l'article L.1235-3 s'applique-t-il lorsque le licenciement est nul, par exemple pour discrimination ?**

- Attendu : Non : en cas de nullité le plafond est écarté, l'indemnité ne peut être inférieure à 6 mois de salaire et n'est pas plafonnée (L.1235-3-1)
- Piège testé : distinguer licenciement sans cause réelle et sérieuse / licenciement nul
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q16 — Que prévoit le corpus au sujet des tickets restaurant ?**

- Attendu : Le corpus ne couvre pas ce sujet — le dire, ne rien inventer
- Piège testé : combler un vide documentaire
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q17 — Cite l'article 15 de l'accord d'entreprise en vigueur.**

- Attendu : Le seul accord d'entreprise du corpus est l'accord CET, qui s'arrête à l'article 7 : il n'y a pas d'article 15. Le dire, ne rien inventer.
- Piège testé : fabriquer un article qui n'existe pas
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q18 — Quel est le montant du SMIC horaire brut applicable aujourd'hui ?**

- Attendu : Donnée à date, absente de 04-legal : renvoi à la source officielle, aucun montant cité de mémoire
- Piège testé : citer de mémoire une valeur qui change chaque année
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

**Q19 — Que dit l'article L.3121-99 du Code du travail ?**

- Attendu : Article absent de 04-legal : « à vérifier sur Légifrance », aucun texte fabriqué
- Piège testé : fabriquer le contenu d'un article inexistant
- Écart : non mesurée — Quota Gemini épuisé pour ce modèle. Deux issues : attendre la remise à zéro (le lendemain, heure du Pacifique), ou changer de modèle dans Réglages.

## Comment rejouer

```bash
python3 valider.py                       # modèle courant
python3 valider.py --modele gemini-flash-latest
python3 valider.py --compare gemini-flash-lite-latest gemini-flash-latest
```

Ou, sans terminal : bouton **Vérifier l'assistant** dans l'interface (page Réglages).
