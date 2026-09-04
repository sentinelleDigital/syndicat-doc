# Validation de l'assistant

**Fichier généré par `python3 valider.py`.** Banc de 20 questions (`tests/banc.json`).
Une ligne dont la colonne « Banc » diffère a été mesurée sur une version antérieure du banc : elle n'est pas comparable aux autres.
Évaluation mécanique : expressions régulières sur la réponse + vérification des articles cités. Aucun modèle ne juge un autre modèle.

## Résultats par modèle

| Modèle | Conforme | Écarts | Non mesurées | Banc | Durée | Mesuré le |
|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | 20/20 | 0 | 0 | 2026-09-04b | 431.0 s | 2026-09-04T13:24:29 |
| `gemini-flash-lite-latest` | 20/20 | 0 | 0 | 2026-09-04b | 431.3 s | 2026-09-04T13:17:18 |

Un modèle absent de ce tableau n'a pas été mesuré. Sur le palier gratuit, le quota journalier d'un modèle peut s'épuiser au milieu d'un banc : les questions concernées sont comptées « non mesurées », jamais « conformes ».

## Détail des écarts

### `gemini-3.5-flash-lite` — 20/20

Aucun écart.

### `gemini-flash-lite-latest` — 20/20

Aucun écart.


## Recommandation

**Modèle recommandé : `gemini-flash-lite-latest`** — 20/20 sur le banc (gratuit — quota le plus large).
À égalité de score avec `gemini-3.5-flash-lite` : on garde celui dont le quota gratuit est le plus large, puisque la mesure ne montre aucune différence de justesse sur ce banc.

Portée de cette preuve : 20 questions. Un score parfait ici ne veut pas dire que le modèle ne se trompe jamais — il veut dire qu'il ne se trompe pas sur les pièges déjà identifiés. Chaque erreur rencontrée en usage réel devrait devenir une question de plus dans `tests/banc.json`.

## Comment rejouer

```bash
python3 valider.py                       # modèle courant
python3 valider.py --modele gemini-flash-latest
python3 valider.py --compare gemini-flash-lite-latest gemini-flash-latest
```

Ou, sans terminal : bouton **Vérifier l'assistant** dans l'interface (page Réglages).
