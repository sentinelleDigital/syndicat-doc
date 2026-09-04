#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demande.py — moteur de l'assistant documentaire syndical.

Deux modes :

  QUESTION (défaut) — réponse courte, sourcée :
      python3 demande.py "quelle est la durée légale hebdomadaire ?"

  AUDIT — croise plusieurs documents, rapport structuré :
      python3 demande.py --audit "l'accord X est-il conforme au forfait jours ?"
      python3 demande.py --audit --doc 06-cet/cet.md "conforme ?"
      python3 demande.py --audit --pdf rapport.html --doc ... "conforme ?"

Enchaînement d'une demande :

  1. garde_fous : la question porte-t-elle sur un cas individuel ? -> on
     s'arrête AVANT l'appel au modèle ;
  2. recherche  : sélection des passages (sections titrées, synonymes, numéros
     d'article) — ce qui est envoyé est aussi ce qui sera montré à l'utilisateur ;
  3. appel du modèle, température 0 en mode question ;
  4. garde_fous : vérification des citations produites, fraîcheur, statuts.

Aucune alerte n'est masquée : une réponse fausse est pire qu'une absence de
réponse.

stdlib uniquement. Clé lue dans l'environnement ou .env.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import corpus
import garde_fous
import recherche as R
import sources

BASE = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE, "INDEX.md")
STYLE_FILE = os.path.join(BASE, "_templates", "rapport-style.html")
STYLE_AUDIT_FILE = os.path.join(BASE, "_templates", "audit-style.html")
FICHIER_REGLAGES = os.path.join(BASE, "reglages.json")

API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:{methode}")

# Modèles proposés dans l'interface. L'arbitrage est écrit, pas sous-entendu.
MODELES = [
    {"id": "gemini-flash-lite-latest", "nom": "Flash-Lite",
     "cout": "gratuit — quota le plus large",
     "note": "Le plus faible de la gamme. Suffit pour restituer un article "
             "présent dans le corpus ; se trompe plus souvent dès qu'il faut "
             "lire un tableau ou raisonner sur une hiérarchie de normes."},
    {"id": "gemini-flash-latest", "nom": "Flash",
     "cout": "gratuit — quota plus serré",
     "note": "Nettement plus fiable sur la lecture de tableaux (barème) et sur "
             "le refus de répondre hors corpus. À préférer si le quota tient."},
    {"id": "gemini-3.5-flash-lite", "nom": "Flash-Lite 3.5",
     "cout": "gratuit — quota distinct des autres Flash",
     "note": "Génération plus récente, quota séparé : utile quand le quota du "
             "modèle courant est épuisé. Mesuré sur le banc — voir VALIDATION.md."},
    {"id": "gemini-pro-latest", "nom": "Pro",
     "cout": "payant (facturé à l'usage)",
     "note": "Le plus fiable en raisonnement juridique. Nécessite un compte "
             "Google Cloud avec facturation activée."},
]

REGLAGES_DEFAUT = {
    "modele_question": os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
    "modele_audit": os.environ.get("GEMINI_MODEL_AUDIT", "gemini-flash-lite-latest"),
    "masquer_donnees_personnelles": True,
}

TEMPERATURE_QUESTION = 0.0   # restitution sourcée : aucune raison de varier
TEMPERATURE_AUDIT = 0.0


# --- Réglages ----------------------------------------------------------------

def lire_reglages():
    r = dict(REGLAGES_DEFAUT)
    try:
        with open(FICHIER_REGLAGES, encoding="utf-8") as f:
            r.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
    return r


def ecrire_reglages(nouveaux):
    r = lire_reglages()
    for cle in REGLAGES_DEFAUT:
        if cle in nouveaux:
            r[cle] = nouveaux[cle]
    with open(FICHIER_REGLAGES, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    return r


# --- Utilitaires -------------------------------------------------------------

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


def cle_api():
    load_env(os.path.join(BASE, ".env"))
    return os.environ.get("GEMINI_API_KEY", "").strip()


# --- Erreurs en français -----------------------------------------------------

class ErreurAssistant(Exception):
    """Erreur destinée à être lue par l'utilisateur, jamais une trace Python."""


def _erreur_http(code, corps):
    detail = ""
    try:
        detail = json.loads(corps).get("error", {}).get("message", "")
    except (ValueError, AttributeError):
        detail = corps[:200]
    if code == 429:
        return ErreurAssistant(
            "Quota Gemini épuisé pour ce modèle. Deux issues : attendre la "
            "remise à zéro (le lendemain, heure du Pacifique), ou changer de "
            "modèle dans Réglages.")
    if code in (401, 403):
        return ErreurAssistant(
            "Clé API refusée. Vérifier GEMINI_API_KEY dans le fichier .env "
            "(clé gratuite : https://aistudio.google.com/apikey).")
    if code == 404:
        return ErreurAssistant(
            "Modèle inconnu ou indisponible sur ce compte. En choisir un autre "
            "dans Réglages.")
    if code == 400 and "API key" in detail:
        return ErreurAssistant("Clé API invalide — la recopier depuis "
                               "https://aistudio.google.com/apikey dans .env.")
    if code >= 500:
        return ErreurTransitoire("Le service Gemini est momentanément "
                                 "indisponible. Réessayer dans quelques minutes.")
    return ErreurAssistant(f"Erreur du service Gemini (code {code}). {detail}"[:400])


def _erreur_reseau(raison):
    return ErreurAssistant(
        "Pas de connexion au service Gemini. Vérifier la connexion internet. "
        f"(détail : {raison})")


# --- Appel du modèle ---------------------------------------------------------

def _corps_requete(system, user, max_tokens, temperature):
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature,
                             "maxOutputTokens": max_tokens},
    }


class ErreurTransitoire(ErreurAssistant):
    """Panne passagère du service : il vaut la peine de réessayer."""


TENTATIVES = 3          # une 503 passagère ne doit pas compter comme une réponse


def call_gemini(api_key, model, system, user, max_tokens, temperature=0.0):
    """Appel avec reprise sur panne passagère (5xx). Le quota (429) ne se retente
    pas : réessayer ne ferait que consommer davantage."""
    derniere = None
    for essai in range(TENTATIVES):
        try:
            return _call_gemini_une_fois(api_key, model, system, user,
                                         max_tokens, temperature)
        except ErreurTransitoire as e:
            derniere = e
            if essai < TENTATIVES - 1:
                time.sleep(2 * (essai + 1))
    raise derniere


def _call_gemini_une_fois(api_key, model, system, user, max_tokens, temperature=0.0):
    if not api_key:
        raise ErreurAssistant(
            "Clé API absente. Ouvrir le fichier .env et y mettre "
            "GEMINI_API_KEY=… (clé gratuite : https://aistudio.google.com/apikey).")
    url = API_URL.format(model=model, methode="generateContent")
    req = urllib.request.Request(
        url, data=json.dumps(_corps_requete(system, user, max_tokens,
                                            temperature)).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _erreur_http(e.code, e.read().decode("utf-8", "replace")) from None
    except urllib.error.URLError as e:
        raise _erreur_reseau(e.reason) from None
    return _texte_reponse(payload)


def _texte_reponse(payload):
    try:
        cand = payload["candidates"][0]
        parts = cand.get("content", {}).get("parts", [])
        texte = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        raise ErreurAssistant(
            "Réponse inattendue du service Gemini. Réessayer ; si cela persiste, "
            "changer de modèle dans Réglages.") from None
    if not texte:
        motif = payload.get("candidates", [{}])[0].get("finishReason", "")
        if motif == "MAX_TOKENS":
            raise ErreurAssistant("Réponse coupée par la limite de longueur. "
                                  "Reformuler la question plus précisément.")
        raise ErreurAssistant(
            f"Le modèle n'a rien renvoyé (motif : {motif or 'inconnu'}).")
    return texte


def call_gemini_flux(api_key, model, system, user, max_tokens, temperature=0.0):
    """Générateur de morceaux de texte (SSE). Même erreurs que call_gemini."""
    if not api_key:
        raise ErreurAssistant(
            "Clé API absente. Ouvrir le fichier .env et y mettre "
            "GEMINI_API_KEY=… (clé gratuite : https://aistudio.google.com/apikey).")
    url = API_URL.format(model=model,
                         methode="streamGenerateContent") + "?alt=sse"
    req = urllib.request.Request(
        url, data=json.dumps(_corps_requete(system, user, max_tokens,
                                            temperature)).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as e:
        raise _erreur_http(e.code, e.read().decode("utf-8", "replace")) from None
    except urllib.error.URLError as e:
        raise _erreur_reseau(e.reason) from None
    recu = False
    with resp:
        for ligne in resp:
            ligne = ligne.decode("utf-8", "replace").strip()
            if not ligne.startswith("data:"):
                continue
            charge = ligne[5:].strip()
            if not charge or charge == "[DONE]":
                continue
            try:
                bloc = json.loads(charge)
            except json.JSONDecodeError:
                continue
            for cand in bloc.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    txt = part.get("text", "")
                    if txt:
                        recu = True
                        yield txt
    if not recu:
        raise ErreurAssistant("Le modèle n'a rien renvoyé. Réessayer ou changer "
                              "de modèle dans Réglages.")


# --- Consignes système -------------------------------------------------------

SYSTEM_QUESTION = """Tu es l'assistant documentaire d'un syndicat (branche IDCC 493).
Tu réponds UNIQUEMENT à partir des documents fournis. Règles STRICTES :

- Cite TOUJOURS le fichier et l'article : ex. [C. trav., L.3121-27], [CCN 3029, art. 24].
- N'utilise QUE les numéros d'article présents dans les documents fournis. Un
  article que tu ne vois pas dans le contexte n'existe pas pour toi : dis
  « non couvert par le corpus, à vérifier sur Légifrance ». N'invente JAMAIS un
  article, un numéro, une date ou un chiffre.
- Une donnée qui varie dans le temps (SMIC, plafond sécu, taux) et qui n'est pas
  dans les documents : ne la donne pas de mémoire, renvoie à la source officielle.
- Hiérarchie branche/entreprise depuis 2017 : blocs L.2253-1/2/3. Pas de
  « le plus favorable gagne » automatique.
- JAMAIS de qualification juridique d'un cas individuel : renvoie vers un
  juriste de la fédération.
- Signale tout document au statut « projet » : ce n'est pas du droit applicable.
- Style : direct, dense, professionnel mais compréhensible par un salarié.
  Réponse d'abord, justification ensuite, source toujours. Pas de préambule.
"""

SYSTEM_AUDIT = """Tu es l'assistant documentaire d'un syndicat (branche IDCC 493).
Tu produis un RAPPORT D'AUDIT structuré à partir des documents fournis, en
croisant le(s) document(s) audité(s) avec le Code du travail et la convention
collective. Règles STRICTES :

- Cite TOUJOURS fichier + article pour chaque affirmation.
- N'utilise QUE les numéros d'article présents dans les documents fournis.
  N'invente RIEN. Si un point n'est pas couvert : « non couvert, à vérifier ».
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
================================================================================
FORMAT DE SORTIE — RAPPORT ÉDITORIAL
================================================================================
Produis UNIQUEMENT le corps HTML (pas de <html>, <head>, <body>, <style>).
Commence directement par <section class="cover">. N'invente aucune classe CSS :
utilise exclusivement le vocabulaire ci-dessous. Aucun attribut style=.

PLAN OBLIGATOIRE — une <section class="section"> par point, dans cet ordre.
Chaque section = une page. Ne saute aucune section ; si un point est hors sujet,
écris la section et dis en une phrase pourquoi elle est sans objet.

  Couverture     <section class="cover">
  Préambule      périmètre, pièces manquantes, sommaire
  Cadre préalable  hiérarchie branche/entreprise applicable au sujet (blocs
                   L.2253-1/2/3) — détermine la lecture de tout le rapport
  Section 1      conformité légale, article par article (tableau)
  Section 2      comparaison avec la convention collective (tableau)
  Section 3      audit spécial du dispositif : conditions, garanties, note /10
  Sections 4 & 5 clauses favorables à l'employeur / au salarié (deux tableaux)
  Section 6      analyse économique — plusieurs scénarios chiffrés + méthodologie
  Section 7      projection dans le temps (immédiat / 1-12 mois / 1-5 ans / 5-15 ans)
  Section 8      points attaquables : fondement, probabilité, conséquences
  Section 9      notes de synthèse, bilan réel, résumé exécutif
  Section B      contre-propositions de rédaction, prêtes à déposer

COMPOSANTS — le seul vocabulaire autorisé
-----------------------------------------
Couverture :
<section class="cover"><div class="kicker">Audit juridique · Droit du travail</div>
<h1>Titre court<br>en deux lignes.</h1><p class="deck">Une phrase de cadrage.</p>
<div class="score"><span class="val">6,5</span><span class="sur">/10</span>
<span class="lib">Note globale<br>de l'accord</span></div>
<div class="meta-grid"><div><div class="lab">Libellé</div><div class="val">Valeur</div></div>
…4 cases…</div></section>

Ouverture de section :
<section class="section"><div class="kicker">Section N</div>
<h1>Titre court<br>en deux lignes.</h1><p class="deck">Ce que fait la section.</p>
<hr class="rule"> … </section>

Tableau (jamais de <th> dans le corps, jamais de colonne vide) :
<h2>Titre du tableau</h2><table><thead><tr><th>…</th></tr></thead><tbody>
<tr><td>…</td><td>…</td><td><span class="pill moyen">Moyen</span></td></tr></tbody></table>
<p class="micro">Méthodologie / hypothèses.</p>

Pastilles de risque — échelle fermée, rien d'autre :
<span class="pill aucun">Aucun</span> · <span class="pill faible">Faible</span> ·
<span class="pill moyen">Moyen</span> · <span class="pill eleve">Élevé</span> ·
<span class="pill tres-eleve">Très élevé</span>
Pour une probabilité contentieuse : mêmes classes, libellés Faible / Moyenne /
Élevée.

Encart de conclusion (ferme CHAQUE section, une seule par section) :
<div class="note rouge|bleu|vert|gris"><span class="t">Titre de l'encart</span>
<p>Ce qu'il faut retenir.</p></div>
  rouge = limite, danger, ce que le document dissimule
  bleu  = clé de lecture, synthèse d'analyse
  vert  = acquis à préserver
  gris  = consigne d'action

Rangée de cartes (2 ou 3, jamais 4) :
<div class="cartes"><div class="carte"><div class="lab">LABEL COURT</div>
<div class="aff">Affirmation en gras</div><div class="exp">Explication.</div></div>…</div>
Variantes de fond : carte vert / carte rouge / carte ambre / carte large.

Notes de synthèse (section 9, exactement 5 tuiles, la dernière globale) :
<div class="notes"><div class="tuile"><div class="n">7,5<span>/10</span></div>
<div class="lib">Conformité juridique</div></div>… 
<div class="tuile globale"><div class="n">6,5<span>/10</span></div>
<div class="lib">Note globale</div></div></div>

Note isolée (fin de section 3) :
<div class="note-bloc"><div class="lab">NOTE DU DISPOSITIF</div>
<div class="n">7 / 10</div><div class="exp">Ce qui la fait monter, ce qui la fait baisser.</div></div>

Contre-proposition (section B, une par point de fragilité) :
<div class="clause"><div class="tete"><span class="titre">1 · Intitulé</span>
<span class="prio absolue|haute|moyenne|secu">Priorité absolue</span></div>
<div class="corps">
<div class="lab">Problème (art. X actuel)</div><div class="txt">…</div>
<div class="lab">Clause proposée — à insérer à l'article X</div>
<div class="redaction">« Texte de la clause, déposable tel quel. »</div>
<div class="lab">Fondement</div><div class="txt">Articles et accords.</div></div></div>

Sommaire : <ul class="sommaire"><li><span>Libellé</span><span class="num">II</span></li></ul>

RÈGLES ÉDITORIALES — elles comptent autant que la mise en forme
--------------------------------------------------------------
1. Les <h1> de section sont des groupes nominaux courts terminés par un POINT :
   « Conformité légale. », « Devant le juge. », « Rapport final. ». Jamais de
   verbe conjugué, jamais plus de quatre mots. Coupe sur deux lignes avec <br>.
2. Tout tableau de conformité comporte une colonne « Pourquoi » : le motif, pas
   seulement le verdict. Une ligne sans motif est une ligne à supprimer.
3. Chaque section se termine par un encart .note qui énonce la conclusion. Pas
   de section qui s'arrête sur un tableau.
4. Chiffres : uniquement ceux présents dans les documents, ou calculés devant le
   lecteur à partir d'hypothèses écrites. Tout tableau chiffré est suivi d'un
   <p class="micro"> qui donne la méthode et dit que c'est un repère de
   négociation, pas un calcul de paie.
5. Les limites du rapport vont en tête (préambule), pas en note de bas de page.
   Pièce non communiquée = dire explicitement ce qui reste théorique.
6. La section B ne contient pas de recommandations vagues : du texte de clause
   rédigé, insérable tel quel, avec son fondement.
7. Ton : affirmatif, dense, sans adverbe d'atténuation. Le lecteur est un
   négociateur, pas un étudiant.

BARÈME DES NOTES — appliquer ces critères, ne pas improviser
------------------------------------------------------------
Cinq notes sur 10, arrondies au demi-point.
  Conformité juridique   : part des articles sans risque ; chaque risque
                           « Élevé » retire 1 pt, « Très élevé » 2 pts.
  Équilibre salarié/employeur : clauses favorables au salarié moins clauses
                           favorables à l'employeur, pondérées par l'enjeu financier.
  Protection de la santé : garanties L.3121-64 II présentes et opérantes
                           (suivi, amplitude, entretiens, alerte, déconnexion).
  Sécurité juridique     : résistance à une contestation prud'homale — nombre et
                           probabilité des points attaquables de la section 8.
  Note globale           : moyenne des quatre, arrondie au demi-point.
Chaque note est justifiée en une ligne dans son <div class="lib"> ou l'encart de
la section. Une note sans justification est interdite.
"""


# --- Construction du contexte ------------------------------------------------

def charger_legal():
    """04-legal en entier : petit, stable, c'est la référence citable."""
    parts = []
    for chemin in R.fichiers_de([corpus.DOSSIER_LEGAL]):
        rel = os.path.relpath(chemin, BASE)
        if os.path.basename(rel).startswith("_INDEX"):
            continue
        parts.append(f"===== FICHIER: {rel} =====\n{read_file(chemin)}")
    return "\n\n".join(parts)


def dossiers_recherche():
    """Dossiers fouillés par mots-clés : tout sauf 04-legal et le nominatif."""
    return [d for d in corpus.dossiers_interrogeables()
            if d != corpus.DOSSIER_LEGAL]


def completer_corpus(question, doc_texte="", acteur="assistant"):
    """
    Avant l'audit : récupérer les textes publics manquants, réclamer le reste.
    Ne lève jamais — un échec devient un signalement dans le rapport.
    """
    try:
        return sources.combler(question, "", doc_texte or "", acteur)
    except Exception as e:                      # noqa: BLE001 — jamais bloquant
        return {"recuperes": [], "a_recuperer": [], "pieces": [],
                "erreurs": [f"Complétion du corpus impossible : {e}"]}


def preparer(question, mode="question", doc_texte=None, doc_nom=None):
    """
    Prépare une demande sans appeler le modèle.
    -> {passages, contexte, systeme, modele, max_tokens, temperature}
    """
    reglages = lire_reglages()
    passages = R.chercher(question, R.fichiers_de(dossiers_recherche()))
    legal = charger_legal()
    index = read_file(INDEX_FILE)
    bloc = R.bloc_contexte(passages, "PASSAGES RETENUS DU CORPUS "
                                     "(accords / règlement intérieur / CCN)")
    if mode == "audit":
        docs = (f"===== DOCUMENT AUDITÉ: {doc_nom or 'document joint'} =====\n"
                f"{doc_texte}") if doc_texte else \
               "(aucun document joint — audit sur le corpus général)"
        contexte = (f"INDEX DU CORPUS :\n{index}\n\nDOCUMENT(S) À AUDITER :\n{docs}"
                    f"\n\nCODE DU TRAVAIL (extraits vérifiés) :\n{legal}\n\n{bloc}"
                    f"\n\nCONSIGNE D'AUDIT :\n{question}\n")
        return {"passages": passages, "contexte": contexte,
                "systeme": SYSTEM_AUDIT, "modele": reglages["modele_audit"],
                "max_tokens": 32768, "temperature": TEMPERATURE_AUDIT}
    contexte = (f"INDEX DU CORPUS :\n{index}\n\nCODE DU TRAVAIL "
                f"(extraits vérifiés) :\n{legal}\n\n{bloc}\n\n"
                f"QUESTION DU SALARIÉ / DE L'ÉLU :\n{question}\n")
    return {"passages": passages, "contexte": contexte,
            "systeme": SYSTEM_QUESTION, "modele": reglages["modele_question"],
            "max_tokens": 2048, "temperature": TEMPERATURE_QUESTION}


def controler(reponse, contexte, passages, question):
    """Tous les garde-fous d'après-génération, regroupés."""
    alertes = garde_fous.verifier_citations(reponse, contexte)
    alertes += garde_fous.alertes_documents(passages, reponse)
    _, avertir, motif = garde_fous.question_individuelle(question)
    if avertir:
        alertes.append({
            "niveau": "avertissement", "reference": "formulation",
            "message": f"Question formulée à la première personne ({motif}). "
                       f"La réponse ci-dessus est générale : elle ne qualifie "
                       f"aucune situation individuelle."})
    return alertes


def repondre(question, mode="question", doc_texte=None, doc_nom=None,
             modele=None):
    """
    Réponse complète, non streamée.
    -> {bloque, reponse, passages, alertes, modele, contexte}
    """
    bloque, _, motif = garde_fous.question_individuelle(question)
    if bloque:
        return {"bloque": True, "reponse": garde_fous.RENVOI_JURISTE,
                "passages": [], "modele": None, "contexte": "",
                "alertes": [{"niveau": "alerte", "reference": "cas individuel",
                             "message": f"Question individuelle détectée "
                                        f"({motif}) — aucun appel au modèle."}]}
    prep = preparer(question, mode, doc_texte, doc_nom)
    modele = modele or prep["modele"]
    reponse = call_gemini(cle_api(), modele, prep["systeme"], prep["contexte"],
                          prep["max_tokens"], prep["temperature"])
    return {"bloque": False, "reponse": reponse, "passages": prep["passages"],
            "alertes": controler(reponse, prep["contexte"], prep["passages"],
                                 question),
            "modele": modele, "contexte": prep["contexte"]}


# --- Rapport HTML ------------------------------------------------------------

def extract_style(fichier=STYLE_FILE):
    html = read_file(fichier)
    m = re.search(r"<style>.*?</style>", html, re.DOTALL)
    return m.group(0) if m else ("<style>body{font-family:sans-serif;"
                                 "max-width:820px;margin:auto}</style>")


def _echapper(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def bloc_alertes_html(alertes):
    if not alertes:
        return ""
    lignes = "".join(
        f"<li><strong>{_echapper(a['reference'])}</strong> — "
        f"{_echapper(a['message'])}</li>" for a in alertes)
    return ("<h2>Contrôles automatiques</h2><ul class=\"alertes\">"
            f"{lignes}</ul>")


def bloc_sources_html(passages):
    if not passages:
        return ""
    lignes = "".join(
        f"<li><code>{_echapper(p['fichier'])}</code> § "
        f"{_echapper(p['titre'])}</li>" for p in passages)
    return f"<h2>Sources consultées</h2><ul>{lignes}</ul>"


def wrap_html(body, title="Rapport d'audit — syndicat",
              style_file=STYLE_AUDIT_FILE, couverture=True):
    """
    Enveloppe le corps produit par le modèle.
    couverture=True : le modèle a produit sa propre <section class="cover">.
    couverture=False : on fabrique un en-tête minimal (export d'une réponse).
    """
    style = extract_style(style_file)
    entete = "" if couverture else (
        '<header><div class="kicker">Document de travail syndical</div>'
        f'<h1>{_echapper(title)}</h1></header>')
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{_echapper(title)}</title>
{style}
</head>
<body>
<div class="page">
{entete}
{body}
<footer>Établi par l'assistant documentaire syndical · Corpus : CCN 3029 (IDCC 493)
+ Code du travail. Document de travail à usage syndical interne : ne constitue pas
un conseil juridique et ne qualifie aucune situation individuelle. Vérifier toute
référence sur Légifrance avant usage contentieux.</footer>
</div>
</body>
</html>
"""


# --- CLI ---------------------------------------------------------------------

def _afficher(res, montrer_sources=True):
    print(res["reponse"])
    if montrer_sources and res["passages"]:
        print("\n--- Sources consultées (passages envoyés au modèle) ---")
        for p in res["passages"]:
            print(f"  · {p['fichier']} § {p['titre']}")
    if res["alertes"]:
        print("\n--- Contrôles automatiques ---")
        for a in res["alertes"]:
            marque = "⚠" if a["niveau"] == "alerte" else "·"
            print(f"  {marque} {a['reference']} : {a['message']}")


def main():
    ap = argparse.ArgumentParser(description="Assistant documentaire syndical.")
    ap.add_argument("question", nargs="+", help="la question ou la consigne d'audit")
    ap.add_argument("--audit", action="store_true", help="mode audit")
    ap.add_argument("--doc", action="append", default=[],
                    help="document à auditer (répétable)")
    ap.add_argument("--pdf", metavar="FICHIER.html",
                    help="mode audit : écrit un rapport HTML (à imprimer en PDF)")
    ap.add_argument("--modele", help="forcer un modèle pour cet appel")
    ap.add_argument("--sans-sources", action="store_true",
                    help="ne pas lister les passages consultés")
    ap.add_argument("--sans-completion", action="store_true",
                    help="ne pas compléter le corpus : signaler les manques "
                         "sans rien télécharger")
    args = ap.parse_args()
    question = " ".join(args.question).strip()

    doc_texte = doc_nom = None
    if args.doc:
        morceaux = []
        for p in args.doc:
            plein = p if os.path.isabs(p) else os.path.join(BASE, p)
            if not os.path.isfile(plein):
                sys.exit(f"Document introuvable : {p}")
            morceaux.append(f"----- {os.path.relpath(plein, BASE)} -----\n"
                            f"{read_file(plein)}")
        doc_texte = "\n\n".join(morceaux)
        doc_nom = ", ".join(args.doc)

    mode = "audit" if (args.audit or args.pdf or args.doc) else "question"
    try:
        if args.pdf:
            if args.sans_completion:
                trous = sources.manques(question, "", doc_texte or "")
                comble = {"recuperes": [], "a_recuperer": trous["articles"],
                          "pieces": trous["pieces"], "erreurs": []}
            else:
                comble = completer_corpus(question, doc_texte or "", "audit CLI")
            prep = preparer(question, "audit", doc_texte, doc_nom)
            corps = call_gemini(cle_api(), args.modele or prep["modele"],
                                SYSTEM_AUDIT_HTML, prep["contexte"],
                                prep["max_tokens"], prep["temperature"])
            corps = re.sub(r"^```html\s*|\s*```$", "", corps.strip())
            alertes = controler(corps, prep["contexte"], prep["passages"], question)
            html = wrap_html(sources.bloc_manques_html(comble) + corps
                             + bloc_alertes_html(alertes)
                             + bloc_sources_html(prep["passages"]),
                             title=f"Rapport d'audit — {question[:60]}")
            with open(args.pdf, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Rapport écrit : {args.pdf}\n"
                  f"Ouvre-le puis Ctrl+P -> Enregistrer en PDF.")
            print(sources.texte_manques(comble))
            return
        comble = None
        if mode == "audit":
            comble = (sources.manques(question, "", doc_texte or "")
                      if args.sans_completion
                      else completer_corpus(question, doc_texte or "", "audit CLI"))
            if args.sans_completion:
                comble = {"recuperes": [], "a_recuperer": comble["articles"],
                          "pieces": comble["pieces"], "erreurs": []}
        res = repondre(question, mode, doc_texte, doc_nom, args.modele)
        _afficher(res, not args.sans_sources)
        if comble:
            print(sources.texte_manques(comble))
    except ErreurAssistant as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
