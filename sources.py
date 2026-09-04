#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sources.py — combler les trous du corpus.

Quand une référence citée n'est pas dans le corpus, trois cas et trois
réponses. Le système ne fait jamais semblant d'avoir le texte.

  1. Article de code absent, source publique récupérable
        -> téléchargé sur Légifrance, écrit dans 04-legal/, journalisé.
  2. Article de code absent, pas de clé Légifrance configurée
        -> fiche « à récupérer » avec l'URL exacte. Rien n'est inventé.
  3. Document privé (contrat, avenant, bulletin, accord, PV)
        -> jamais récupérable par une machine. Demande de pièce nommée,
           adressée à l'utilisateur, avec la raison et ce qu'elle débloque.

Le cas 3 alimente directement l'encart « Pièces manquantes — portée des
conclusions » du préambule du rapport d'audit : dire ce qui manque fait
partie du rapport, ce n'est pas un message d'erreur.

stdlib uniquement.
"""

import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import corpus
import garde_fous
import recherche as R

BASE = os.path.dirname(os.path.abspath(__file__))

# --- Codes reconnus ----------------------------------------------------------
# Le fond Légifrance et le libellé cité dans les rapports.

CODES = {
    "travail": {
        "libelle": "Code du travail",
        "cite": "C. trav.",
        "legifrance": "LEGITEXT000006072050",
        "url": "https://www.legifrance.gouv.fr/codes/article_lc/",
        "miroir": "https://code.travail.gouv.fr/code-du-travail/",
    },
    "secu": {
        "libelle": "Code de la sécurité sociale",
        "cite": "C. séc. soc.",
        "legifrance": "LEGITEXT000006073189",
        "url": "https://www.legifrance.gouv.fr/codes/article_lc/",
        "miroir": "https://www.legifrance.gouv.fr/codes/article_lc/",
    },
}


def deviner_code(ref, contexte=""):
    """
    Code du travail ou sécurité sociale ? La forme de la référence tranche
    dans la plupart des cas ; la mention qui PRÉCÈDE l'article départage le
    reste (« C. séc. soc. L. 161-22-1-5 » : le code est écrit avant).
    """
    marqueur = _marqueur_amont(contexte, ref)
    if marqueur:
        return marqueur
    m = re.match(r"[LRD](\d+)-", ref)
    if m and len(m.group(1)) == 4 and m.group(1)[0] in "12345678":
        return "travail"
    return "secu"


RE_SECU = re.compile(r"s[ée]c\.?\s*soc|s[ée]curit[ée]\s+sociale", re.I)
RE_TRAV = re.compile(r"c\.?\s*trav|code\s+du\s+travail", re.I)


def _marqueur_amont(texte, ref, portee=60):
    """
    Le nom de code cité juste avant la référence, dans la même proposition.
    On s'arrête au premier séparateur fort : une citation voisine ne doit pas
    contaminer celle-ci.
    """
    for v in R.variantes_code(ref):
        i = texte.lower().find(v.lower())
        if i < 0:
            continue
        amont = texte[max(0, i - portee):i]
        amont = re.split(r"[;\n]|(?<=\S)\.\s", amont)[-1]
        if RE_SECU.search(amont):
            return "secu"
        if RE_TRAV.search(amont):
            return "travail"
    return None


# --- 1 · Détection des manques ----------------------------------------------

# Pièces qui ne peuvent venir que de l'utilisateur. Le motif sert à les
# reconnaître dans une consigne d'audit ; le libellé sert à les réclamer.
PIECES_PRIVEES = [
    (re.compile(r"\bcontrat\s+de\s+travail\b", re.I),
     "le contrat de travail",
     "sans lui, la convention individuelle de forfait et la rémunération "
     "réelle restent théoriques"),
    (re.compile(r"\bavenant\b", re.I),
     "l'avenant au contrat",
     "c'est lui qui porte la convention individuelle, pas l'accord collectif"),
    (re.compile(r"\bbulletin[s]?\s+de\s+(?:paie|salaire)\b", re.I),
     "un bulletin de paie récent",
     "seule pièce qui donne le salaire réel : sans lui, l'analyse économique "
     "reste une simulation"),
    (re.compile(r"\baccord\s+d['’]entreprise\b|\baccord\s+collectif\b", re.I),
     "l'accord d'entreprise signé et déposé",
     "un projet n'est pas du droit applicable : la version déposée seule fait foi"),
    (re.compile(r"\bproc[èe]s[- ]verb(?:al|aux)\b|\bPV\s+(?:du\s+)?CSE\b", re.I),
     "les procès-verbaux de CSE concernés",
     "ils établissent la consultation et sa date"),
    (re.compile(r"\br[èe]glement\s+int[ée]rieur\b", re.I),
     "le règlement intérieur en vigueur",
     "avec la date de dépôt à l'inspection du travail"),
    (re.compile(r"\bDUERP\b|document\s+unique", re.I),
     "le document unique d'évaluation des risques",
     "il conditionne l'appréciation de l'obligation de sécurité"),
    (re.compile(r"\bgrille\s+de\s+classification\b|\bcoefficient\b", re.I),
     "la grille de classification appliquée dans l'entreprise",
     "sans elle, impossible de confronter aux minima de branche"),
]


def articles_manquants(texte, contexte=""):
    """
    Références de code citées et absentes de 04-legal/ (le texte vérifié).
    -> [{'ref','code','libelle','cite','url_miroir'}] trié.
    """
    out = []
    for ref in sorted(R.refs_code(texte)):
        if garde_fous.fichier_legal_de(ref):
            continue
        code = deviner_code(ref, contexte or texte)
        c = CODES[code]
        out.append({
            "ref": ref, "code": code,
            "libelle": c["libelle"], "cite": c["cite"],
            "url_miroir": c["miroir"] + ref.lower(),
        })
    return out


def pieces_manquantes(consigne, contexte=""):
    """
    Documents privés évoqués par la consigne mais absents du contexte envoyé.
    -> [{'piece','pourquoi'}]
    """
    out = []
    ctx = R.normalise(contexte)
    for motif, libelle, pourquoi in PIECES_PRIVEES:
        if not motif.search(consigne):
            continue
        cle = R.normalise(libelle.split("(")[0])
        mots = [m for m in cle.split() if len(m) > 4]
        if mots and all(m in ctx for m in mots):
            continue                      # la pièce est déjà dans le contexte
        out.append({"piece": libelle, "pourquoi": pourquoi})
    return out


def manques(consigne, reponse="", contexte=""):
    """Tout ce qui manque pour que le rapport tienne. Rien n'est masqué."""
    return {
        "articles": articles_manquants((consigne + "\n" + reponse), contexte),
        "pieces": pieces_manquantes(consigne, contexte),
    }


# --- 2 · Récupération sur Légifrance -----------------------------------------

OAUTH = "https://oauth.piste.gouv.fr/api/oauth/token"
API = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"


class SourceIndisponible(Exception):
    """Aucune récupération automatique possible. Message lisible en français."""


def _identifiants():
    demande_env()
    cid = os.environ.get("LEGIFRANCE_CLIENT_ID", "").strip()
    secret = os.environ.get("LEGIFRANCE_CLIENT_SECRET", "").strip()
    return (cid, secret) if cid and secret else (None, None)


def demande_env():
    """Charge .env sans écraser l'environnement (même contrat que demande.py)."""
    chemin = os.path.join(BASE, ".env")
    if not os.path.isfile(chemin):
        return
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            k, _, v = ligne.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def recuperation_possible():
    return all(_identifiants())


def _jeton():
    cid, secret = _identifiants()
    if not cid:
        raise SourceIndisponible(
            "Récupération automatique non configurée. Créer un compte gratuit "
            "sur https://piste.gouv.fr, s'abonner à l'API « Légifrance », puis "
            "ajouter LEGIFRANCE_CLIENT_ID et LEGIFRANCE_CLIENT_SECRET dans .env.")
    donnees = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid,
        "client_secret": secret, "scope": "openid"}).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(OAUTH, data=donnees), timeout=20) as r:
            return json.loads(r.read()).get("access_token")
    except urllib.error.HTTPError as e:
        raise SourceIndisponible(
            f"Légifrance refuse les identifiants (code {e.code}). Vérifier "
            f"LEGIFRANCE_CLIENT_ID / LEGIFRANCE_CLIENT_SECRET dans .env.")
    except OSError as e:
        raise SourceIndisponible(f"Pas de connexion à Légifrance ({e}).")


def _appel(chemin, charge, jeton):
    requete = urllib.request.Request(
        f"{API}/{chemin}", data=json.dumps(charge).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {jeton}"})
    try:
        with urllib.request.urlopen(requete, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SourceIndisponible(
            f"Légifrance a répondu {e.code} sur {chemin}. "
            f"Récupérer l'article à la main.")
    except OSError as e:
        raise SourceIndisponible(f"Pas de connexion à Légifrance ({e}).")


def recuperer_article(ref, code="travail", jeton=None):
    """
    Un article, verbatim, depuis Légifrance.
    -> {'ref','texte','date_debut','etat','id'}   ou lève SourceIndisponible.
    """
    jeton = jeton or _jeton()
    trouve = _appel("search", {
        "fond": "CODE_DATE",
        "recherche": {
            "filtres": [{"facette": "NOM_CODE",
                         "valeurs": [CODES[code]["libelle"]]}],
            "champs": [{"typeChamp": "NUM_ARTICLE", "operateur": "ET",
                        "criteres": [{"typeRecherche": "EXACTE",
                                      "valeur": ref, "operateur": "ET"}]}],
            "pageNumber": 1, "pageSize": 5,
            "operateur": "ET", "sort": "PERTINENCE",
            "typePagination": "ARTICLE"},
    }, jeton)

    ident = None
    for res in trouve.get("results", []):
        for section in res.get("sections", []):
            for art in section.get("extracts", []):
                ident = art.get("id") or ident
        ident = ident or res.get("id")
        if ident:
            break
    if not ident:
        raise SourceIndisponible(
            f"{ref} introuvable dans le {CODES[code]['libelle']} sur Légifrance. "
            f"Vérifier le numéro — il est peut-être abrogé ou mal cité.")

    detail = _appel("consult/getArticle", {"id": ident}, jeton)
    art = detail.get("article") or {}
    texte = re.sub(r"<[^>]+>", "", art.get("texte") or "").strip()
    if not texte:
        raise SourceIndisponible(f"{ref} : Légifrance renvoie un texte vide.")
    return {
        "ref": ref, "texte": texte, "id": ident,
        "etat": (art.get("etat") or "VIGUEUR").lower(),
        "date_debut": _date(art.get("dateDebut")),
    }


def _date(horodatage):
    """Légifrance renvoie des millisecondes epoch ; on veut AAAA-MM-JJ."""
    try:
        return datetime.date.fromtimestamp(int(horodatage) / 1000).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


# --- 3 · Classement dans 04-legal -------------------------------------------

def serie(ref):
    """'L3121-58' -> 'L3121'. Une série = un fichier."""
    m = re.match(r"([LRD]\d+)-", ref)
    return m.group(1) if m else ref


def fichier_de_serie(s):
    """Le fichier 04-legal/ qui porte cette série, ou None."""
    dossier = os.path.join(BASE, corpus.DOSSIER_LEGAL)
    if not os.path.isdir(dossier):
        return None
    for nom in sorted(os.listdir(dossier)):
        if nom.endswith(".md") and not nom.startswith("_INDEX") \
                and nom.split("_")[0].upper().startswith(s.upper()):
            return os.path.join(corpus.DOSSIER_LEGAL, nom)
    return None


def _slug(s):
    s = R.normalise(s).replace(" ", "-")
    return re.sub(r"-+", "-", s).strip("-")[:48] or "articles"


def enregistrer_articles(articles, theme=None, acteur="assistant"):
    """
    Écrit les articles récupérés dans 04-legal/, une série par fichier.
    Complète un fichier existant, en crée un sinon. Journal + INDEX par corpus.
    -> [{'ref','fichier','action'}]  action = 'ajout' | 'complement' | 'deja'
    """
    faits = []
    par_serie = {}
    for a in articles:
        par_serie.setdefault(serie(a["ref"]), []).append(a)

    for s, lot in sorted(par_serie.items()):
        lot.sort(key=lambda a: a["ref"])
        code = lot[0].get("code", "travail")
        titre_theme = theme or lot[0].get("theme") or _titre_defaut(s, lot)
        existant = fichier_de_serie(s)
        blocs = "\n\n".join(_bloc_article(a) for a in lot)

        if existant:
            chemin = os.path.join(BASE, existant)
            with open(chemin, encoding="utf-8") as f:
                avant = f.read()
            meta, corps = corpus.lire_front_matter(avant)
            nouveaux = [a for a in lot
                        if not any(v.lower() in corps.lower()
                                   for v in R.variantes_code(a["ref"]))]
            if not nouveaux:
                faits += [{"ref": a["ref"], "fichier": existant,
                           "action": "deja"} for a in lot]
                continue
            corps = corps.rstrip() + "\n\n" + "\n\n".join(
                _bloc_article(a) for a in nouveaux) + "\n"
            refs = list(meta.get("articles") or [])
            refs += [a["ref"] for a in nouveaux if a["ref"] not in refs]
            meta["articles"] = sorted(refs)
            meta["verifie_le"] = datetime.date.today().isoformat()
            ok, info = corpus.enregistrer_document(existant, meta, corps, acteur)
            faits += [{"ref": a["ref"], "fichier": existant,
                       "action": "complement" if ok else f"échec : {info}"}
                      for a in nouveaux]
            continue

        meta = {
            "titre": f"{titre_theme} — {CODES[code]['cite']} {s}-*",
            "theme": _slug(titre_theme),
            "articles": [a["ref"] for a in lot],
            "statut": "en_vigueur" if all(
                a.get("etat", "vigueur").startswith("vigueur") for a in lot)
                else "abroge",
            "source": "Légifrance (API PISTE)",
            "url_base": CODES[code]["url"],
            "verifie_le": datetime.date.today().isoformat(),
        }
        corps = (f"# {meta['titre']}\n\n"
                 f"> Texte verbatim récupéré sur Légifrance le "
                 f"{meta['verifie_le']}. Vérifier avant usage contentieux.\n\n"
                 f"{blocs}\n")
        nom = f"{s}_{_slug(titre_theme)}.md"
        ok, info = corpus.ajouter_document(corpus.DOSSIER_LEGAL, nom,
                                           meta, corps, acteur)
        faits += [{"ref": a["ref"],
                   "fichier": info if ok else "—",
                   "action": "ajout" if ok else f"échec : {info}"} for a in lot]
    return faits


def _titre_defaut(s, lot):
    return f"Articles {s}"


def _bloc_article(a):
    etat = a.get("etat", "vigueur")
    entete = f"## Article {a['ref']}"
    if a.get("date_debut"):
        entete += f" (en vigueur {a['date_debut']})"
    if etat and not etat.startswith("vigueur"):
        entete += f" — {etat.upper()}"
    return f"{entete}\n{a['texte'].strip()}"


# --- 4 · Boucle complète -----------------------------------------------------

def combler(consigne, reponse="", contexte="", acteur="assistant"):
    """
    Détecte, récupère ce qui est récupérable, signale le reste.
    -> {'recuperes', 'a_recuperer', 'pieces', 'erreurs'}
    Ne lève jamais : un échec de récupération devient un signalement.
    """
    trous = manques(consigne, reponse, contexte)
    res = {"recuperes": [], "a_recuperer": [], "pieces": trous["pieces"],
           "erreurs": []}
    if not trous["articles"]:
        return res

    if not recuperation_possible():
        res["a_recuperer"] = trous["articles"]
        res["erreurs"].append(
            "Récupération automatique non configurée (LEGIFRANCE_CLIENT_ID / "
            "LEGIFRANCE_CLIENT_SECRET absents de .env) — les articles ci-dessus "
            "sont à ajouter à la main.")
        return res

    try:
        jeton = _jeton()
    except SourceIndisponible as e:
        res["a_recuperer"] = trous["articles"]
        res["erreurs"].append(str(e))
        return res

    recoltes = []
    for a in trous["articles"]:
        try:
            art = recuperer_article(a["ref"], a["code"], jeton)
            art["code"] = a["code"]
            recoltes.append(art)
        except SourceIndisponible as e:
            res["a_recuperer"].append(a)
            res["erreurs"].append(str(e))
    if recoltes:
        res["recuperes"] = enregistrer_articles(recoltes, acteur=acteur)
    return res


# --- 5 · Restitution ---------------------------------------------------------

def texte_manques(res):
    """Version terminal."""
    lignes = []
    for f in res.get("recuperes", []):
        verbe = {"ajout": "ajouté à", "complement": "complété dans",
                 "deja": "déjà présent dans"}.get(f["action"], f["action"])
        lignes.append(f"  · {f['ref']} — {verbe} {f['fichier']}")
    for a in res.get("a_recuperer", []):
        lignes.append(f"  ⚠ {a['ref']} ({a['libelle']}) — absent du corpus : "
                      f"{a['url_miroir']}")
    for p in res.get("pieces", []):
        lignes.append(f"  ⚠ à fournir : {p['piece']} — {p['pourquoi']}")
    for e in res.get("erreurs", []):
        lignes.append(f"  ⚠ {e}")
    if not lignes:
        return ""
    return "\n--- Corpus : ce qui manquait ---\n" + "\n".join(lignes)


def _ech(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def bloc_manques_html(res):
    """
    Encart destiné au préambule du rapport d'audit — même classe .note que le
    reste de la maquette. Dire ce qui manque fait partie du rapport.
    """
    parties = []
    if res.get("a_recuperer") or res.get("pieces"):
        items = []
        for a in res.get("a_recuperer", []):
            items.append(f"<li><strong>{_ech(a['ref'])}</strong> "
                         f"({_ech(a['libelle'])}) — texte absent du corpus "
                         f"vérifié : toute affirmation le citant est à "
                         f"contrôler sur Légifrance.</li>")
        for p in res.get("pieces", []):
            items.append(f"<li><strong>{_ech(p['piece'])}</strong> — "
                         f"{_ech(p['pourquoi'])}.</li>")
        parties.append(
            '<div class="note rouge"><span class="t">Pièces manquantes — '
            'portée des conclusions</span><ul>' + "".join(items) + "</ul></div>")
    if res.get("recuperes"):
        faits = ", ".join(f"{_ech(f['ref'])} → <strong>{_ech(f['fichier'])}"
                          f"</strong>" for f in res["recuperes"]
                          if f["action"] in ("ajout", "complement"))
        if faits:
            parties.append('<div class="note bleu"><span class="t">Corpus '
                           'complété avant analyse</span><p>Textes récupérés '
                           'sur Légifrance et versés au corpus : '
                           + faits + ".</p></div>")
    return "".join(parties)


# --- CLI ---------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Complète le corpus à partir d'une consigne ou d'un texte.")
    ap.add_argument("texte", nargs="+", help="consigne d'audit ou texte à analyser")
    ap.add_argument("--sec", action="store_true",
                    help="ne rien télécharger : lister seulement les manques")
    args = ap.parse_args()
    consigne = " ".join(args.texte)

    if args.sec:
        trous = manques(consigne)
        res = {"recuperes": [], "a_recuperer": trous["articles"],
               "pieces": trous["pieces"], "erreurs": []}
    else:
        res = combler(consigne)
    sortie = texte_manques(res)
    print(sortie.lstrip() if sortie else "Rien ne manque : tout est dans le corpus.")


if __name__ == "__main__":
    main()
