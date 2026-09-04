#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
garde_fous.py — contrôles EN CODE, pas seulement dans le prompt.

Une règle écrite dans un prompt est une intention ; un contrôle en code est une
garantie. Ce module vérifie mécaniquement ce que le modèle a produit :

  - chaque référence citée est-elle réellement dans ce qu'on lui a envoyé ?
  - un article du Code cité hors de 04-legal/ est signalé « à vérifier sur
    Légifrance » — jamais masqué ;
  - une question qui porte sur un cas individuel est arrêtée AVANT l'appel ;
  - un extrait légal vérifié il y a plus de 6 mois porte un bandeau ;
  - un document au statut « projet » n'est jamais présenté comme applicable.

Aucun de ces contrôles ne modifie la réponse : ils l'annotent. Masquer une
alerte reviendrait à recréer le problème qu'on cherche à éviter.

stdlib uniquement.
"""

import os
import re

import corpus
import recherche as R

BASE = os.path.dirname(os.path.abspath(__file__))


# --- 1. Question portant sur un cas individuel -------------------------------

# Deux niveaux, volontairement : bloquer sur le seul mot « je » rendrait l'outil
# inutilisable (« je cherche la durée légale »). On ne bloque que quand un
# marqueur personnel rencontre une situation juridique concrète.
MARQUEURS_PERSONNELS = re.compile(
    r"\b(mon|ma|mes|je|j ai|suis je|ai je|puis je|me|m a|mon employeur|"
    r"mon patron|mon cas|chez moi|dans mon cas)\b")

SITUATIONS = re.compile(
    r"\b(licenciement|licencie|licenciee|licencier|rupture|demission|"
    r"sanction|avertissement|mise a pied|contrat|contrats|salaire|paie|"
    r"prime|solde de tout compte|preavis|inaptitude|maladie|arret|"
    r"harcelement|discrimination|prud hommes|prudhommes|litige|conflit|"
    r"heures supplementaires|conges|mutation|essai|indemnite|droit|"
    r"valable|legal|abusif|abusive|attaquer|contester|recours)\b")

QUESTIONS_QUALIFICATION = re.compile(
    r"\b(est il valable|est elle valable|est ce legal|est ce abusif|"
    r"ai je droit|puis je|dois je|que dois je faire|que faire|"
    r"est ce que je peux|suis je)\b")

RENVOI_JURISTE = (
    "Question portant sur une situation individuelle. Cet outil ne qualifie "
    "jamais un cas particulier : la réponse dépend de pièces (contrat, "
    "courriers, dates, ancienneté) qu'il ne voit pas, et une erreur ici coûte "
    "cher.\n\n**À faire : saisir le juriste de la fédération**, avec le dossier "
    "complet.\n\nCet outil peut en revanche répondre à la question générale "
    "correspondante — la reformuler sans « je / mon / ma ». Exemple : au lieu de "
    "« mon licenciement est-il valable ? », demander « quelle procédure le Code "
    "du travail impose-t-il pour un licenciement pour motif personnel ? »."
)


def question_individuelle(question):
    """
    (bloquant, avertissement, motif).
      bloquant     -> on ne va pas voir le modèle du tout
      avertissement-> on répond, avec un rappel affiché
    """
    q = R.normalise(question)
    perso = MARQUEURS_PERSONNELS.search(q)
    situation = SITUATIONS.search(q)
    qualif = QUESTIONS_QUALIFICATION.search(q)
    if perso and (situation or qualif):
        motif = "« {} » + « {} »".format(
            perso.group(0), (situation or qualif).group(0))
        return True, False, motif
    if perso:
        return False, True, f"« {perso.group(0)} »"
    return False, False, ""


# --- 2. Vérification des citations après génération --------------------------

RE_FICHIER = re.compile(r"\b[\w./-]+\.md\b")


def _textes_legal():
    """Concaténation des extraits 04-legal, avec la provenance de chacun."""
    out = []
    dossier = os.path.join(BASE, corpus.DOSSIER_LEGAL)
    for nom in sorted(os.listdir(dossier)) if os.path.isdir(dossier) else []:
        if not nom.endswith(".md") or nom.startswith("_INDEX"):
            continue
        chemin = os.path.join(dossier, nom)
        try:
            with open(chemin, encoding="utf-8") as f:
                out.append((os.path.join(corpus.DOSSIER_LEGAL, nom), f.read()))
        except OSError:
            continue
    return out


def fichier_legal_de(ref):
    """Le fichier 04-legal qui contient littéralement cet article, ou None."""
    for rel, texte in _textes_legal():
        bas = texte.lower()
        for v in R.variantes_code(ref):
            if v.lower() in bas:
                return rel
    return None


def verifier_citations(reponse, contexte):
    """
    Chaque référence produite par le modèle est cherchée LITTÉRALEMENT dans ce
    qui lui a été envoyé. Renvoie une liste d'alertes (jamais une réécriture).
    """
    alertes = []
    contexte_bas = contexte.lower()
    contexte_norm = R.normalise(contexte)

    for ref in sorted(R.refs_code(reponse)):
        fichier = fichier_legal_de(ref)
        if fichier:
            continue
        present = any(v.lower() in contexte_bas for v in R.variantes_code(ref))
        if present:
            alertes.append({
                "niveau": "avertissement", "reference": ref,
                "message": f"{ref} est cité d'après un document du corpus mais "
                           f"n'est pas dans 04-legal/ (texte vérifié) — "
                           f"à vérifier sur Légifrance."})
        else:
            alertes.append({
                "niveau": "alerte", "reference": ref,
                "message": f"{ref} n'apparaît dans aucun document envoyé au "
                           f"modèle : référence non vérifiée dans le corpus — "
                           f"à vérifier sur Légifrance avant tout usage."})

    for num in sorted(R.refs_ccn(reponse)):
        motif = r"\barticle\s+" + re.escape(R.normalise(num)) + r"\b"
        if not re.search(motif, contexte_norm):
            alertes.append({
                "niveau": "alerte", "reference": f"art. {num}",
                "message": f"L'article {num} n'a pas été retrouvé dans les "
                           f"passages envoyés au modèle : référence non "
                           f"vérifiée dans le corpus."})

    for nom in sorted(set(RE_FICHIER.findall(reponse))):
        rel = nom.lstrip("./")
        if os.path.isfile(os.path.join(BASE, rel)):
            continue
        if os.path.basename(rel) in {os.path.basename(c)
                                     for c in _fichiers_corpus()}:
            continue
        alertes.append({
            "niveau": "alerte", "reference": nom,
            "message": f"Le fichier « {nom} » n'existe pas dans le corpus."})
    return alertes


def _fichiers_corpus():
    return [d["chemin"] for d in corpus.documents(inclure_abroges=True)]


# --- 3. Fraîcheur et statut des documents réellement utilisés ----------------

def alertes_documents(passages, reponse=""):
    """
    Bandeaux liés aux documents mobilisés : extrait légal périmé, document au
    statut « projet », dossier nominatif.
    """
    alertes, vus = [], set()
    fichiers = {p["fichier"] for p in passages}
    # 04-legal part en entier : on ne signale que les fichiers réellement cités.
    for ref in R.refs_code(reponse):
        rel = fichier_legal_de(ref)
        if rel:
            fichiers.add(rel)
    for rel in sorted(fichiers):
        if rel in vus:
            continue
        vus.add(rel)
        doc = corpus.lire_document(rel)
        if not doc:
            continue
        if doc["perime"]:
            alertes.append({
                "niveau": "avertissement", "reference": rel,
                "message": f"{os.path.basename(rel)} : vérifié le "
                           f"{doc['verifie_le']} (il y a "
                           f"{doc['mois_depuis_verif']} mois) — à re-vérifier, "
                           f"le droit du travail bouge."})
        if doc["statut"] == "projet":
            alertes.append({
                "niveau": "alerte", "reference": rel,
                "message": f"{os.path.basename(rel)} est au statut PROJET : ce "
                           f"n'est pas du droit applicable."})
        if doc["statut"] == "abroge":
            alertes.append({
                "niveau": "alerte", "reference": rel,
                "message": f"{os.path.basename(rel)} est ABROGÉ — ne pas citer."})
    return alertes


# --- 4. Confidentialité : masquage avant envoi -------------------------------
#
# Détection heuristique, en stdlib. Elle n'est PAS exhaustive et l'interface le
# dit : une garantie de confidentialité fausse serait pire qu'aucune garantie.
# Ce que le masquage a trouvé est toujours montré à l'utilisateur, qui relit.

MOTIFS_PERSO = [
    ("courriel", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("téléphone", re.compile(r"\b0[1-9](?:[ .-]?\d{2}){4}\b")),
    ("n° sécurité sociale", re.compile(r"\b[12]\s?\d{2}\s?\d{2}\s?\d{2,3}\s?"
                                       r"\d{3}\s?\d{3}(?:\s?\d{2})?\b")),
    ("matricule", re.compile(r"\bmatricule\s*(?:n°)?\s*[:=]?\s*([\w-]{3,})",
                             re.I)),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\b")),
    ("adresse", re.compile(r"\b\d{1,4}\s?(?:bis|ter)?\s+(?:rue|avenue|av\.|"
                           r"boulevard|bd|impasse|allée|allee|chemin|place|"
                           r"route)\s+[^\n,;.]{3,40}", re.I)),
    ("date de naissance", re.compile(r"\bné(?:e)?\s+le\s+\d{1,2}[/ .-]\w+"
                                     r"[/ .-]\d{2,4}", re.I)),
    ("nom (civilité)", re.compile(r"\b(?:M\.|MM\.|Mme|Mmes|Mlle|Monsieur|"
                                  r"Madame|Mademoiselle)\s+"
                                  r"([A-ZÀ-Ý][\w'’-]+(?:\s+[A-ZÀ-Ý][\w'’-]+)?)")),
    # Même ligne obligatoire : « …COMPTE EPARGNE TEMPS \n Direction… » n'est
    # pas un nom, et masquer un titre de section abîmerait le document envoyé.
    ("nom (majuscules)", re.compile(r"\b(?<![A-ZÀ-Ý])[A-ZÀ-Ý]{3,}"
                                    r"[ \t]+[A-ZÀ-Ý][a-zà-ÿ]+\b")),
]

MOTS_MAJ_COURANTS = {"CSE", "CCN", "IDCC", "CDI", "CDD", "CET", "RTT", "SMIC",
                     "DRH", "CGT", "CFDT", "FO", "CFTC", "CFE", "CGC", "UNSA",
                     "SAS", "SARL", "SA", "PDG", "DUP", "CHSCT", "NAO", "PSE",
                     "TITRE", "ARTICLE", "ANNEXE", "PREAMBULE", "PRÉAMBULE",
                     "NOTE", "SERVICE", "ACCORD", "AVENANT", "DIRECTION",
                     "TEMPS", "COMPTE", "EPARGNE", "ÉPARGNE", "OBJET",
                     "CHAPITRE", "SECTION", "CONVENTION", "COLLECTIVE"}


def masquer_donnees_personnelles(texte):
    """
    (texte_masqué, trouvailles). Heuristique — non exhaustive.
    Chaque remplacement est rendu à l'appelant pour affichage.
    """
    trouvailles, masque = [], texte
    for etiquette, motif in MOTIFS_PERSO:
        def _remplace(m, etiquette=etiquette):
            brut = m.group(0)
            if etiquette == "nom (majuscules)":
                tete = brut.split()[0]
                if tete in MOTS_MAJ_COURANTS:
                    return brut
            trouvailles.append({"type": etiquette, "extrait": brut.strip()})
            if etiquette in ("matricule",):
                return re.sub(r"[\w-]{3,}$", "[MASQUÉ]", brut)
            if etiquette.startswith("nom (civilité)"):
                return brut[:brut.index(m.group(1))] + "[NOM MASQUÉ]"
            return f"[{etiquette.upper()} MASQUÉ]"
        masque = motif.sub(_remplace, masque)
    return masque, trouvailles
