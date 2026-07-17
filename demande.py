#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demande.py — assistant documentaire syndical.

Deux modes :

  QUESTION (défaut) — réponse courte à une question de salarié/élu :
      python3 demande.py "quelle est la durée légale hebdomadaire ?"

  AUDIT — croise plusieurs documents et produit une analyse structurée :
      python3 demande.py --audit "l'accord X est-il conforme au forfait jours ?"
      python3 demande.py --audit --doc 01-accords/forfait/x.md "conforme ?"
      python3 demande.py --audit --pdf rapport.html --doc ... "conforme ?"

Principe : corpus figé + petit -> on envoie l'essentiel en entier (04-legal),
la CCN est filtrée par mots-clés bornés, et en mode audit on ajoute les
document(s) nommés par --doc. Le modèle cite fichier + article, refuse si non
couvert, ne qualifie jamais un cas individuel.

stdlib uniquement. Lit GEMINI_API_KEY depuis l'environnement ou .env.
"""

import argparse
import json
import os
import re
import sys
import glob
import urllib.request
import urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
LEGAL_DIR = os.path.join(BASE, "04-legal")
INDEX_FILE = os.path.join(BASE, "INDEX.md")
CCN_GLOB = os.path.join(BASE, "03-convention-collective", "*.md")
STYLE_FILE = os.path.join(BASE, "_templates", "rapport-style.html")

MODEL_QUESTION = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
# NB: Gemini Pro n'est PAS sur le free tier (quota 0). On reste sur Flash (gratuit).
# Passe GEMINI_MODEL_AUDIT=gemini-pro-latest si tu actives un plan payant.
MODEL_AUDIT = os.environ.get("GEMINI_MODEL_AUDIT", "gemini-flash-latest")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

CCN_MAX_CHARS = 14000

FR_STOP = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "à",
    "au", "aux", "en", "dans", "pour", "par", "sur", "que", "qui", "quoi",
    "est", "sont", "il", "elle", "je", "tu", "on", "mon", "ma", "mes", "ce",
    "cette", "ces", "se", "sa", "son", "ses", "avec", "pas", "ne", "plus",
    "quel", "quelle", "quels", "quelles", "combien", "comment", "peut", "peux",
    "puis", "dois", "droit", "y", "n", "l", "d", "s", "j", "c", "t", "il",
}


def load_env(path):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_legal():
    parts = []
    for path in sorted(glob.glob(os.path.join(LEGAL_DIR, "*.md"))):
        rel = os.path.relpath(path, BASE)
        parts.append(f"===== FICHIER: {rel} =====\n{read_file(path)}")
    return "\n\n".join(parts)


def load_docs(paths):
    """Charge les documents nommés (--doc) : ce qui est audité."""
    parts = []
    for p in paths:
        full = p if os.path.isabs(p) else os.path.join(BASE, p)
        if not os.path.isfile(full):
            sys.exit(f"Document introuvable : {p}")
        rel = os.path.relpath(full, BASE)
        parts.append(f"===== DOCUMENT AUDITÉ: {rel} =====\n{read_file(full)}")
    return "\n\n".join(parts)


def keywords(question):
    words = re.findall(r"[a-zàâäéèêëïîôöùûüç0-9]{3,}", question.lower())
    return [w for w in words if w not in FR_STOP]


def load_ccn_passages(question, budget=CCN_MAX_CHARS):
    files = glob.glob(CCN_GLOB)
    if not files:
        return ""
    kws = keywords(question)
    if not kws:
        return ""
    text = read_file(files[0])
    rel = os.path.relpath(files[0], BASE)
    paras = re.split(r"\n\s*\n", text)
    hits = []
    for p in paras:
        low = p.lower()
        score = sum(low.count(k) for k in kws)
        if score > 0:
            hits.append((score, p.strip()))
    hits.sort(key=lambda x: x[0], reverse=True)
    out, total = [], 0
    for _, p in hits:
        if total + len(p) > budget:
            break
        out.append(p)
        total += len(p)
    if not out:
        return ""
    return f"===== EXTRAITS CCN ({rel}) — passages contenant les mots-clés =====\n" + "\n\n".join(out)


SYSTEM_QUESTION = """Tu es l'assistant documentaire d'un syndicat (branche IDCC 493).
Tu réponds UNIQUEMENT à partir des documents fournis. Règles STRICTES :

- Cite TOUJOURS le fichier et l'article : ex. [C. trav., L.3121-27], [CCN 3029, art. X].
- Si l'information n'est PAS dans les documents fournis : dis-le clairement
  (« non couvert par le corpus, à vérifier sur Légifrance »). N'invente JAMAIS
  un article, un numéro ou un chiffre.
- Hiérarchie branche/entreprise depuis 2017 : blocs L.2253-1/2/3. Pas de
  « le plus favorable gagne » automatique.
- JAMAIS de qualification juridique d'un cas individuel : renvoie vers un
  juriste de la fédération.
- Style : direct, dense, professionnel mais compréhensible par un salarié.
  Réponse d'abord, justification ensuite, source toujours. Pas de préambule.
"""

SYSTEM_AUDIT = """Tu es l'assistant documentaire d'un syndicat (branche IDCC 493).
Tu produis un RAPPORT D'AUDIT structuré à partir des documents fournis, en
croisant le(s) document(s) audité(s) avec le Code du travail et la convention
collective. Règles STRICTES :

- Cite TOUJOURS fichier + article pour chaque affirmation.
- N'invente RIEN. Si un point n'est pas couvert : « non couvert, à vérifier ».
- Hiérarchie 2017 : blocs L.2253-1/2/3 (pas de faveur automatique).
- JAMAIS de qualification d'un cas individuel.

Structure OBLIGATOIRE du rapport :
1. Synthèse (5 lignes max : conforme / problèmes / urgence)
2. Tableau des risques (colonnes : Point | Norme de référence | Niveau : conforme/moyen/élevé)
3. Analyse détaillée (par point : ce que dit le document / exigence Code / exigence CCN / écart)
4. Hiérarchie des normes appliquée
5. Recommandations concrètes, priorisées
6. Sources citées (liste fichier + article)

Rappel : ce rapport est un document de travail syndical, pas un conseil juridique.
"""

SYSTEM_AUDIT_HTML = SYSTEM_AUDIT + """
FORMAT DE SORTIE : produis UNIQUEMENT le corps HTML du rapport (pas de <html>,
<head> ni <body> — juste le contenu). Utilise des balises sémantiques :
<h2> pour les titres de section, <table><thead><tr><th>…</th></tr></thead><tbody>…
pour les tableaux, <ul><li> pour les listes, <strong> pour l'emphase,
<span class="badge ok|moy|haut"> pour les niveaux de risque (vert/orange/rouge),
<span class="ref"> pour les références d'articles. Commence directement par <h2>.
"""


def extract_style():
    """Récupère le <style>…</style> du gabarit pour habiller le PDF."""
    html = read_file(STYLE_FILE)
    m = re.search(r"<style>.*?</style>", html, re.DOTALL)
    return m.group(0) if m else "<style>body{font-family:sans-serif;max-width:820px;margin:auto}</style>"


def wrap_html(body, title="Rapport d'audit — syndicat"):
    style = extract_style()
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{title}</title>
{style}
</head>
<body>
<div class="page">
<header>
  <div class="kicker">Document de travail syndical</div>
  <h1>{title}</h1>
  <div class="disclaimer">Document de travail à usage syndical interne. Ne constitue
  pas un conseil juridique. Vérifier toute référence sur Légifrance avant usage contentieux.</div>
</header>
{body}
<footer>Établi par l'assistant documentaire syndical · Corpus : CCN 3029 (IDCC 493) + Code du travail.</footer>
</div>
</body>
</html>
"""


def call_gemini(api_key, model, system, user, max_tokens):
    url = API_URL.format(model=model)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"Erreur HTTP {e.code} : {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Erreur réseau : {e.reason}")
    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        sys.exit(f"Réponse inattendue : {json.dumps(payload, ensure_ascii=False)[:800]}")


def main():
    load_env(os.path.join(BASE, ".env"))
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY absent. Mets-le dans .env (voir .env.example).")

    ap = argparse.ArgumentParser(description="Assistant documentaire syndical.")
    ap.add_argument("question", nargs="+", help="la question ou la consigne d'audit")
    ap.add_argument("--audit", action="store_true", help="mode audit (croisement + rapport structuré)")
    ap.add_argument("--doc", action="append", default=[], help="document à auditer (répétable)")
    ap.add_argument("--pdf", metavar="FICHIER.html", help="mode audit : écrit un rapport HTML (à imprimer en PDF)")
    args = ap.parse_args()
    question = " ".join(args.question).strip()

    index = read_file(INDEX_FILE)
    legal = load_legal()
    ccn = load_ccn_passages(question)

    audit = args.audit or args.pdf or args.doc
    if audit:
        docs = load_docs(args.doc) if args.doc else "(aucun document nommé — audit sur le corpus général)"
        context = f"""INDEX DU CORPUS :
{index}

DOCUMENT(S) À AUDITER :
{docs}

CODE DU TRAVAIL (extraits vérifiés) :
{legal}

{ccn}

CONSIGNE D'AUDIT :
{question}
"""
        if args.pdf:
            body = call_gemini(api_key, MODEL_AUDIT, SYSTEM_AUDIT_HTML, context, 8192)
            body = re.sub(r"^```html\s*|\s*```$", "", body.strip())
            html = wrap_html(body, title=f"Rapport d'audit — {question[:60]}")
            with open(args.pdf, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Rapport écrit : {args.pdf}\nOuvre-le puis Ctrl+P -> Enregistrer en PDF.")
        else:
            print(call_gemini(api_key, MODEL_AUDIT, SYSTEM_AUDIT, context, 8192))
    else:
        context = f"""INDEX DU CORPUS :
{index}

DOCUMENTS — CODE DU TRAVAIL (extraits vérifiés) :
{legal}

{ccn}

QUESTION DU SALARIÉ / DE L'ÉLU :
{question}
"""
        print(call_gemini(api_key, MODEL_QUESTION, SYSTEM_QUESTION, context, 2048))


if __name__ == "__main__":
    main()
