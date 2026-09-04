#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recherche.py — sélection des passages envoyés au modèle.

C'est le maillon critique : si la recherche rate le bon article, le modèle
répond faux avec assurance. D'où :

  - normalisation (minuscules, accents repliés, élisions, pluriels) ;
  - reconnaissance directe des numéros d'article dans la question, qui
    court-circuite le score de mots-clés (L.3121-64 -> on récupère L.3121-64) ;
  - découpage par SECTION TITRÉE (« Article 24 », « ## Article L3121-18 »)
    et non par paragraphe : un article n'est plus coupé en deux ;
  - synonymes métier (RTT, CET, forfait jours…) ;
  - chaque passage sait POURQUOI il a été retenu -> affichable à l'utilisateur.

stdlib uniquement.
"""

import glob
import os
import re
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))

BUDGET = 18000          # caractères max envoyés au modèle (hors 04-legal)
FICHIER_PETIT = 6000    # <= : le fichier pertinent part ENTIER (accord, RI)
SECTION_MAX = 5000      # une section plus longue est tronquée (marquée)

# --- Normalisation -----------------------------------------------------------

MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "au", "aux",
    "en", "dans", "pour", "par", "sur", "que", "qui", "quoi", "est", "sont",
    "il", "elle", "je", "tu", "on", "nous", "vous", "ils", "mon", "ma", "mes",
    "ce", "cette", "ces", "se", "sa", "son", "ses", "avec", "pas", "ne", "plus",
    "quel", "quelle", "quels", "quelles", "combien", "comment", "peut", "peux",
    "puis", "dois", "doit", "y", "n", "l", "d", "s", "j", "c", "t", "m",
    "faire", "etre", "avoir", "cas", "dit", "dire", "sous", "entre", "leur",
    "notre", "votre", "tout", "tous", "toute", "toutes", "quand", "donc", "si",
    "aussi", "meme", "selon", "apres", "avant", "lors", "chez", "vers", "sans",
}


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normalise(s):
    """minuscules + accents repliés + élisions coupées + ponctuation -> espace."""
    s = sans_accents(s.lower()).replace("’", "'").replace("ʼ", "'")
    s = re.sub(r"\b[ldjcmnstqu]{1,2}'", " ", s)          # l'accord, d'un, qu'il
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def racine(mot):
    """Radical grossier : replie pluriels et quelques suffixes courants."""
    for suf, rem in (("aux", "al"), ("ements", "ement"), ("ations", "ation"),
                     ("eaux", "eau"), ("ies", "ie")):
        if mot.endswith(suf) and len(mot) > len(suf) + 2:
            return mot[: -len(suf)] + rem
    if len(mot) > 4 and mot.endswith(("s", "x")):
        return mot[:-1]
    return mot


# --- Synonymes métier --------------------------------------------------------
# clé : expression normalisée cherchée dans la question
# valeur : termes ajoutés à la recherche (poids réduit)
SYNONYMES = {
    "rtt": "reduction du temps de travail jours de repos",
    "reduction du temps de travail": "rtt",
    "cet": "compte epargne temps",
    "compte epargne temps": "cet epargne",
    "forfait jours": "forfait annuel en jours convention de forfait 218",
    "forfait annuel en jours": "forfait jours",
    "ccn": "convention collective nationale branche",
    "convention collective": "ccn branche nationale",
    "cse": "comite social et economique comite entreprise delegues du personnel",
    "comite social et economique": "cse comite entreprise",
    "ds": "delegue syndical",
    "delegue syndical": "section syndicale designation",
    "essai": "periode essai embauchage",
    "periode essai": "embauchage essai renouvelable prevenance",
    "preavis": "delai conge rupture",
    "prime": "gratification prime annuelle",
    "gratification": "prime",
    "mutuelle": "prevoyance frais de sante complementaire",
    "prevoyance": "mutuelle garantie",
    "heures sup": "heures supplementaires contingent majoration",
    "heures supplementaires": "contingent majoration repos compensateur",
    "nuit": "travail de nuit poste",
    "ferie": "jours feries chomes",
    "maladie": "arret de travail garantie de salaire absence",
    "licenciement": "rupture du contrat indemnite",
    "retraite": "depart en retraite allocation de depart",
    "conges payes": "conge annuel jours ouvrables acquisition",
    "conge": "conges payes absence",
    "anciennete": "presence continue anciennete",
    "salaire": "remuneration appointements minima",
    "remuneration": "salaire minima",
    "smic": "salaire minimum de croissance minima",
    "temps partiel": "travail a temps partiel duree minimale",
    "astreinte": "astreintes intervention",
    "teletravail": "travail a distance",
    "harcelement": "harcelement moral sexuel",
    "discrimination": "egalite de traitement",
    "greve": "droit de greve",
    "formation": "formation professionnelle plan de developpement",
    "classification": "classifications coefficient niveau echelon",
    "maternite": "maternite adoption conge parental",
    "dimanche": "travail du dimanche repos hebdomadaire",
    "repos": "repos quotidien repos hebdomadaire",
    "duree du travail": "temps de travail effectif horaire",
    "audience": "representativite suffrages exprimes premier tour",
    "representativite": "audience suffrages exprimes",
    "negociation obligatoire": "negociation annuelle periodicite",
}


# --- Références d'article ----------------------------------------------------

RE_CODE = re.compile(r"\b([LRD])\.?\s*(\d{1,4})\s*[-‐-―]\s*(\d{1,3})"
                     r"(?:\s*[-‐-―]\s*(\d{1,3}))?", re.I)
# La CCN 3029 numérote ses articles de deux façons : « Article 24 » dans les
# clauses communes, « Article IV.5.1 » dans les annexes. Ne reconnaître que la
# première laissait passer sans contrôle toute citation en chiffres romains.
RE_ART_CCN = re.compile(
    r"\b[Aa]rt(?:icle)?s?\.?\s*"
    r"((?:[IVX]{1,5}|\d{1,3})(?:\s*[.\-]\s*\d{1,3}){0,3})"
    r"(?:[\s-]*(bis|ter|Bis|Ter))?\b")


def refs_code(texte):
    """Références Code du travail / sécu trouvées dans un texte -> {'L3121-64'}."""
    out = set()
    for m in RE_CODE.finditer(texte):
        lettre, a, b, c = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
        out.add(f"{lettre}{a}-{b}" + (f"-{c}" if c else ""))
    return out


def refs_ccn(texte):
    """Numéros d'article de convention/accord (« art. 24 », « article 14.2 »)."""
    out = set()
    for m in RE_ART_CCN.finditer(texte):
        num = re.sub(r"\s+", "", m.group(1))
        if RE_CODE.match("L" + num):          # évite de capter « L.3121-64 » ici
            continue
        suffixe = ("-" + m.group(2).lower()) if m.group(2) else ""
        out.add(num + suffixe)
    return out


def variantes_code(ref):
    """'L3121-64' -> formes littérales possibles dans les textes."""
    m = re.match(r"([LRD])(\d+)-(\d+)(?:-(\d+))?$", ref)
    if not m:
        return [ref]
    lettre, a, b, c = m.groups()
    fin = f"{b}" + (f"-{c}" if c else "")
    return [f"{lettre}{a}-{fin}", f"{lettre}. {a}-{fin}", f"{lettre}.{a}-{fin}",
            f"{lettre} {a}-{fin}", f"{lettre}.{a}-{fin}".lower()]


# --- Découpage en sections titrées -------------------------------------------

RE_BRUIT = re.compile(
    r"^\s*(?:©\s*Editions\s+Legimedia"
    r"|Page\s+\d+\s+de\s+\d+"
    r"|brochure\s+n°\s*\d+"
    r"|\s*)\s*$", re.I)

RE_SOMMAIRE = re.compile(r"\.{4,}")

RE_TITRE = re.compile(
    r"^\s*(?:#{1,6}\s+.{1,90}"                       # titre markdown
    r"|ARTICLE\s+[0-9IVX].{0,80}"                    # ARTICLE 3 : OBJET (accords)
    r"|Article\s+(?:unique|[0-9IVX]).{0,80}"         # Article 24, Article VIII. 4.2
    r"|Annexe\s+[IVX0-9].{0,60}"
    r"|Avenant\s+n°\s*\d+.{0,90})\s*$")


def _lignes_utiles(texte):
    """Retire l'en-tête de page, les sauts de page et le sommaire à points."""
    out = []
    for ligne in texte.split("\n"):
        ligne = ligne.replace("\x0c", "")
        if RE_SOMMAIRE.search(ligne):
            continue
        if RE_BRUIT.match(ligne):
            out.append("")
            continue
        out.append(ligne.rstrip())
    return out


def _titre_de(ligne):
    t = re.sub(r"^\s*#{1,6}\s+", "", ligne).strip()
    return re.sub(r"\s+", " ", t)[:120]


def decouper_sections(texte, fichier):
    """
    Découpe un document en sections titrées.

    Dans la CCN (texte extrait d'un PDF), l'intitulé du sujet précède la ligne
    « Article N » : « Embauchage - Période d'essai » / « Article 24 ». On
    rattache donc la ligne précédente au titre, sinon la section est
    introuvable par mot-clé.
    """
    lignes = _lignes_utiles(texte)
    debuts = [i for i, l in enumerate(lignes) if l.strip() and RE_TITRE.match(l)]
    if not debuts:
        return [{"fichier": fichier, "titre": "(document)", "texte": texte.strip()}]
    sections = []
    if debuts[0] > 0:
        tete = "\n".join(lignes[: debuts[0]]).strip()
        if tete:
            sections.append({"fichier": fichier, "titre": "(en-tête)", "texte": tete})
    for n, i in enumerate(debuts):
        fin = debuts[n + 1] if n + 1 < len(debuts) else len(lignes)
        titre = _titre_de(lignes[i])
        # chapeau : ligne non vide juste avant, si ce n'est pas déjà un titre
        j = i - 1
        while j >= 0 and not lignes[j].strip():
            j -= 1
        if j >= 0 and j not in debuts and 0 < len(lignes[j].strip()) <= 90 \
                and not lignes[j].strip().endswith((".", ";", ",", ":")):
            titre = f"{lignes[j].strip()} — {titre}"
        corps = "\n".join(lignes[i:fin]).strip()
        if corps:
            sections.append({"fichier": fichier, "titre": titre, "texte": corps})
    return sections


_CACHE = {}


def sections_fichier(chemin):
    """Sections d'un fichier, mises en cache tant que le fichier ne change pas."""
    try:
        mtime = os.path.getmtime(chemin)
    except OSError:
        return []
    if _CACHE.get(chemin, (None,))[0] == mtime:
        return _CACHE[chemin][1]
    try:
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
    except OSError:
        return []
    texte = re.sub(r"\A---\n.*?\n---\n", "", texte, flags=re.DOTALL)   # front matter
    rel = os.path.relpath(chemin, BASE)
    secs = decouper_sections(texte, rel)
    for s in secs:
        s["norm"] = normalise(s["texte"])
        s["norm_titre"] = normalise(s["titre"])
    _CACHE[chemin] = (mtime, secs)
    return secs


# --- Recherche ---------------------------------------------------------------

def termes(question):
    """
    (termes_forts, termes_faibles) : mots de la question, puis synonymes.
    Renvoie des radicaux, dédupliqués.
    """
    q = normalise(question)
    forts, faibles = [], []
    for mot in q.split():
        if len(mot) >= 3 and mot not in MOTS_VIDES:
            forts.append(racine(mot))
    for cle, ajout in SYNONYMES.items():
        if cle in q:
            for mot in normalise(ajout).split():
                if len(mot) >= 3 and mot not in MOTS_VIDES:
                    faibles.append(racine(mot))
    forts = list(dict.fromkeys(forts))
    faibles = [m for m in dict.fromkeys(faibles) if m not in forts]
    return forts, faibles


def _compte(norm, terme):
    """Occurrences d'un radical (préfixe de mot) dans un texte normalisé."""
    return len(re.findall(r"\b" + re.escape(terme) + r"[a-z]{0,3}\b", norm))


def score_section(sec, forts, faibles, arts_code, arts_ccn):
    score, motifs = 0.0, []
    touches = 0
    for t in forts:
        n = _compte(sec["norm"], t)
        if n:
            touches += 1
            score += min(n, 6) * 1.0
            if _compte(sec["norm_titre"], t):
                score += 4.0
    for t in faibles:
        n = _compte(sec["norm"], t)
        if n:
            score += min(n, 4) * 0.5
            if _compte(sec["norm_titre"], t):
                score += 2.0
    if touches >= 2:
        score *= 1.4                      # plusieurs mots de la question ensemble
    for ref in arts_code:
        for v in variantes_code(ref):
            if v.lower() in sec["texte"].lower():
                score += 60.0
                motifs.append(f"contient {ref}")
                break
    for num in arts_ccn:
        titre_norm = normalise(sec["titre"])
        if re.search(r"\barticle\s+" + re.escape(normalise(num)) + r"\b", titre_norm):
            score += 60.0
            motifs.append(f"article {num}")
    if touches:
        motifs.append(f"{touches} mot(s)-clé(s)")
    return score, ", ".join(motifs)


def chercher(question, fichiers, budget=BUDGET):
    """
    Renvoie la liste des passages retenus, meilleurs d'abord, sous budget.
    Chaque passage : {fichier, titre, texte, score, motif, tronque}
    """
    forts, faibles = termes(question)
    arts_code = refs_code(question)
    arts_ccn = refs_ccn(question)
    if not forts and not arts_code and not arts_ccn:
        return []

    petits, candidats = [], []
    for chemin in fichiers:
        try:
            taille = os.path.getsize(chemin)
        except OSError:
            continue
        rel = os.path.relpath(chemin, BASE)
        if taille <= FICHIER_PETIT:
            # petit document (accord, RI) : entier ou rien — jamais tronqué en
            # deux par la recherche, sinon on perd la moitié d'un accord.
            secs = sections_fichier(chemin)
            total = sum(score_section(s, forts, faibles, arts_code, arts_ccn)[0]
                        for s in secs)
            if total > 0:
                with open(chemin, encoding="utf-8") as f:
                    texte = re.sub(r"\A---\n.*?\n---\n", "", f.read(), flags=re.DOTALL)
                petits.append({"fichier": rel, "titre": "document entier",
                               "texte": texte.strip(), "score": total + 100,
                               "motif": "document court et pertinent", "tronque": False})
            continue
        for sec in sections_fichier(chemin):
            sc, motif = score_section(sec, forts, faibles, arts_code, arts_ccn)
            if sc > 0:
                candidats.append({"fichier": sec["fichier"], "titre": sec["titre"],
                                  "texte": sec["texte"], "score": sc,
                                  "motif": motif, "tronque": False})

    candidats.sort(key=lambda p: p["score"], reverse=True)
    retenus, total, vus = [], 0, set()
    for p in petits + candidats:
        # la CCN republie le même article en clauses communes, en annexe et en
        # avenant : sans ce filtre, trois copies mangent tout le budget.
        empreinte = normalise(p["texte"])[:400]
        if empreinte in vus:
            continue
        vus.add(empreinte)
        texte = p["texte"]
        if len(texte) > SECTION_MAX:
            texte = texte[:SECTION_MAX] + "\n[…section tronquée…]"
            p = dict(p, texte=texte, tronque=True)
        if total + len(texte) > budget:
            if total > 0:
                continue
            p = dict(p, texte=texte[:budget], tronque=True)
        retenus.append(p)
        total += len(p["texte"])
        if total >= budget:
            break
    return retenus


def bloc_contexte(passages, entete):
    """Passages -> bloc de texte étiqueté, citable par le modèle."""
    if not passages:
        return ""
    morceaux = [f"[{p['fichier']} § {p['titre']}]\n{p['texte']}" for p in passages]
    return f"===== {entete} =====\n" + "\n\n".join(morceaux)


def fichiers_de(dossiers, base=BASE):
    out = []
    for d in dossiers:
        out += glob.glob(os.path.join(base, d, "**", "*.md"), recursive=True)
    return sorted(out)
