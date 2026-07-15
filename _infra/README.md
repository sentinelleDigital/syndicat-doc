# Infra — proxy LiteLLM (failover 2 clés Groq)

But : OpenCode ne bascule pas seul entre 2 clés. LiteLLM le fait automatiquement.

## 1. Installer LiteLLM (une fois)
```
pip install "litellm[proxy]"
```

## 2. Mettre les 3 secrets dans .env (jamais versionné)
```
cp .env.example .env
# puis édite .env et mets tes 2 clés Groq + un LITELLM_MASTER_KEY inventé
```
`LITELLM_MASTER_KEY` = mot de passe local du proxy (invente-le, ex: `sk-syndicat-2026`).
`.env` est ignoré par git (voir .gitignore). LiteLLM le charge tout seul ; OpenCode via `run.sh`.

## 3. Lancer le proxy (terminal dédié, à laisser tourner)
```
cd /home/petje-linux/syndicat
~/.venv-litellm/bin/litellm --config _infra/litellm.config.yaml
```
→ charge .env automatiquement, écoute sur http://localhost:4000

## 4. Vérifier le failover
```
curl http://localhost:4000/health -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```
Doit lister 2 deployments `groq-llama-70b` sains.

## 5. Utiliser OpenCode (autre terminal)
```
cd /home/petje-linux/syndicat && ./run.sh
```
`run.sh` charge .env puis lance opencode (OpenCode ne lit pas .env seul).
opencode.json pointe déjà sur le proxy (`groq-proxy/groq-llama-70b`).
Requête unique : `./run.sh run "Durée légale hebdomadaire ? Cite l'article."`

## Comment le failover marche
- 2 deployments, même `model_name` → LiteLLM répartit les requêtes.
- Clé qui renvoie 429 (quota/rate-limit) → mise en cooldown 60 s, requêtes routées sur l'autre clé.
- `num_retries: 3` → une requête qui échoue est retentée automatiquement (sur l'autre clé) avant de remonter une erreur. C'est ça, le « sans bug ».

## Si tu ne veux PAS lancer un proxy en permanence
Alternative légère, mais **switch manuel** (pas automatique) : voir la note en bas.
Deux providers Groq directs dans opencode.json, tu changes via `/models` quand une clé est épuisée.
Dis-le et je bascule la config sur cette option.
