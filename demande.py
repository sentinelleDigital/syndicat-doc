#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demande.py — assistant documentaire syndical (mode question).

Usage :
    python3 demande.py "quelle est la durée légale hebdomadaire ?"

Principe (mode question) :
    - Envoie au modèle : les règles + TOUT 04-legal + les passages pertinents
      de la CCN + la question.
    - Le modèle répond en citant fichier + article, refuse si non couvert.
    - Corpus figé + petit -> on envoie l'essentiel en entier => fiabilité maximale,
      pas de récupération hasardeuse. Seule la CCN (volumineuse) est filtrée par
      mots-clés bornés.

Aucune dépendance externe : stdlib uniquement (urllib, json).
Lit GEMINI_API_KEY depuis l'environnement ou depuis .env.
"""

import json
import os
import re
import sys
import glob
import urllib.request
import urllib.error

# --- Chemins ---
BASE = os.path.dirname(os.path.abspath(__file__))
LEGAL_DIR = os.path.join(BASE, "04-legal")
INDEX_FILE = os.path.join(BASE, "INDEX.md")
CCN_GLOB = os.path.join(BASE, "03-convention-collective", "*.md")
RULES_FILE = os.path.join(BASE, "AGENTS.md")

# --- Modèle ---
MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Budget de caractères pour les passages CCN (borne l'entrée).
CCN_MAX_CHARS = 14000

FR_STOP = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "à",
    "au", "aux", "en", "dans", "pour", "par", "sur", "que", "qui", "quoi",
    "est", "sont", "il", "elle", "je", "tu", "on", "mon", "ma", "mes", "ce",
    "cette", "ces", "se", "sa", "son", "ses", "avec", "pas", "ne", "plus",
    "quel", "quelle", "quels", "quelles", "combien", "comment", "peut", "peux",
    "puis", "dois", "droit", "y", "n", "l", "d", "s", "j", "c", "t",
}


def load_env(path):
    """Charge .env dans os.environ si présent (le script est autonome)."""
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
    """Tout 04-legal (petit, envoyé en entier => zéro risque de récupération)."""
    parts = []
    for path in sorted(glob.glob(os.path.join(LEGAL_DIR, "*.md"))):
        rel = os.path.relpath(path, BASE)
        parts.append(f"===== FICHIER: {rel} =====\n{read_file(path)}")
    return "\n\n".join(parts)


def keywords(question):
    words = re.findall(r"[a-zàâäéèêëïîôöùûüç0-9]{3,}", question.lower())
    return [w for w in words if w not in FR_STOP]


def load_ccn_passages(question):
    """
    CCN = volumineuse. On ne l'envoie PAS en entier : on extrait les paragraphes
    contenant les mots-clés de la question, borné à CCN_MAX_CHARS.
    """
    files = glob.glob(CCN_GLOB)
    if not files:
        return ""
    kws = keywords(question)
    if not kws:
        return ""
    text = read_file(files[0])
    rel = os.path.relpath(files[0], BASE)
    # découpe en paragraphes
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
        if total + len(p) > CCN_MAX_CHARS:
            break
        out.append(p)
        total += len(p)
    if not out:
        return ""
    return f"===== EXTRAITS CCN ({rel}) — passages contenant les mots-clés =====\n" + "\n\n".join(out)


SYSTEM = """Tu es l'assistant documentaire d'un syndicat (branche IDCC 493).
Tu réponds UNIQUEMENT à partir des documents fournis ci-dessous. Règles STRICTES :

- Cite TOUJOURS le fichier et l'article : ex. [C. trav., L.3121-27], [CCN 3029, art. X].
- Si l'information n'est PAS dans les documents fournis : dis-le clairement
  (« non couvert par le corpus, à vérifier sur Légifrance »). N'invente JAMAIS
  un article, un numéro ou un chiffre.
- Hiérarchie branche/entreprise depuis 2017 : blocs L.2253-1/2/3 (voir le fichier
  fourni). Ne dis pas « le plus favorable gagne » automatiquement.
- JAMAIS de qualification juridique d'un cas individuel (« ton licenciement est-il
  valable ? ») : renvoie vers un juriste de la fédération.
- Style : direct, dense, professionnel mais compréhensible par un salarié.
  Réponse d'abord, justification ensuite, source toujours. Pas de préambule.
"""


def call_gemini(api_key, system, user):
    url = API_URL.format(model=MODEL)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        sys.exit(f"Erreur HTTP {e.code} : {detail}")
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

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        sys.exit('Usage : python3 demande.py "ta question"')

    legal = load_legal()
    ccn = load_ccn_passages(question)
    index = read_file(INDEX_FILE)

    context = f"""INDEX DU CORPUS :
{index}

DOCUMENTS — CODE DU TRAVAIL (extraits vérifiés) :
{legal}

{ccn}

QUESTION DU SALARIÉ / DE L'ÉLU :
{question}
"""
    answer = call_gemini(api_key, SYSTEM, context)
    print(answer)


if __name__ == "__main__":
    main()
