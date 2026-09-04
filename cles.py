#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cles.py — les clés d'accès, réglables depuis l'interface.

Principes, dans l'ordre où ils comptent :

  1. Une clé enregistrée n'est JAMAIS renvoyée. L'interface reçoit l'état
     (présente / absente), l'origine, et les quatre derniers caractères. Rien
     d'autre. Un secret affiché est un secret perdu : capture d'écran, cache
     du navigateur, épaule voisine.
  2. Une clé n'apparaît jamais dans un message d'erreur ni dans un journal.
     Les appels de test ne renvoient que « ça marche » ou « refusée ».
  3. Le fichier .env est écrit en 0600 (lisible par son seul propriétaire) et
     remplacé atomiquement : jamais de fichier à moitié écrit.
  4. Les commentaires et les autres lignes de .env sont préservés.
  5. Une clé posée depuis l'interface prend effet immédiatement, sans
     redémarrage : os.environ est mis à jour dans la foulée.

stdlib uniquement.
"""

import json
import os
import platform
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
FICHIER_ENV = os.path.join(BASE, ".env")


# --- Emplacements connus -----------------------------------------------------
# Ajouter un service = ajouter une entrée ici. Rien d'autre à toucher.

EMPLACEMENTS = [
    {
        "id": "gemini",
        "variable": "GEMINI_API_KEY",
        "nom": "Google Gemini",
        "role": "Fait tourner l'assistant. Sans elle, aucune question ne part.",
        "obligatoire": True,
        "obtenir": "https://aistudio.google.com/apikey",
        "aide": "Gratuite, sans carte bancaire.",
        "forme": r"^[A-Za-z0-9_\-]{20,}$",
        "forme_dit": "une suite de lettres, chiffres, tirets et soulignés "
                     "(au moins 20 caractères)",
    },
    {
        "id": "legifrance_id",
        "variable": "LEGIFRANCE_CLIENT_ID",
        "nom": "Légifrance — identifiant client",
        "role": "Récupère automatiquement les articles de code absents du "
                "corpus. Sans elle, les manques sont signalés au lieu d'être "
                "comblés.",
        "obligatoire": False,
        "obtenir": "https://piste.gouv.fr",
        "aide": "Compte gratuit, puis abonnement à l'API « Légifrance ». "
                "Va avec le secret client.",
        "forme": r"^[A-Za-z0-9_\-]{8,}$",
        "forme_dit": "une suite de lettres, chiffres, tirets et soulignés",
    },
    {
        "id": "legifrance_secret",
        "variable": "LEGIFRANCE_CLIENT_SECRET",
        "nom": "Légifrance — secret client",
        "role": "Va avec l'identifiant client ci-dessus. Les deux sont "
                "nécessaires, l'un sans l'autre ne sert à rien.",
        "obligatoire": False,
        "obtenir": "https://piste.gouv.fr",
        "aide": "Délivré en même temps que l'identifiant.",
        "forme": r"^[A-Za-z0-9_\-]{8,}$",
        "forme_dit": "une suite de lettres, chiffres, tirets et soulignés",
    },
]

PAR_ID = {e["id"]: e for e in EMPLACEMENTS}
VARIABLES = {e["variable"] for e in EMPLACEMENTS}


# --- Lecture -----------------------------------------------------------------

def _lignes_env():
    if not os.path.isfile(FICHIER_ENV):
        return []
    with open(FICHIER_ENV, encoding="utf-8") as f:
        return f.read().splitlines()


def _valeurs_env():
    """Ce que contient .env, sans toucher à os.environ."""
    out = {}
    for ligne in _lignes_env():
        nu = ligne.strip()
        if not nu or nu.startswith("#") or "=" not in nu:
            continue
        k, _, v = nu.partition("=")
        out[k.strip()] = v.strip()
    return out


def _apercu(valeur):
    """Les quatre derniers caractères, et rien de plus."""
    if not valeur:
        return ""
    if len(valeur) <= 8:
        return "•" * len(valeur)
    return "•" * 6 + valeur[-4:]


def etat():
    """
    État de chaque emplacement, sans jamais renvoyer une valeur complète.
    -> [{'id','nom','role','obligatoire','obtenir','aide',
         'configuree','origine','apercu'}]
    origine : 'fichier .env' | 'variable d environnement' | ''
    """
    du_fichier = _valeurs_env()
    out = []
    for e in EMPLACEMENTS:
        v_fichier = du_fichier.get(e["variable"], "")
        v_env = os.environ.get(e["variable"], "")
        valeur = v_fichier or v_env
        if v_fichier:
            origine = "fichier .env"
        elif v_env:
            origine = "variable d'environnement"
        else:
            origine = ""
        out.append({
            "id": e["id"], "nom": e["nom"], "role": e["role"],
            "obligatoire": e["obligatoire"], "obtenir": e["obtenir"],
            "aide": e["aide"], "forme_dit": e["forme_dit"],
            "configuree": bool(valeur),
            "modifiable": origine != "variable d'environnement",
            "origine": origine,
            "apercu": _apercu(valeur),
        })
    return out


# --- Écriture ----------------------------------------------------------------

class CleRefusee(Exception):
    """Message lisible. Ne contient jamais la valeur soumise."""


def _verifier_forme(emplacement, valeur):
    if not valeur:
        raise CleRefusee("Valeur vide.")
    if valeur != valeur.strip():
        raise CleRefusee("La valeur commence ou finit par une espace — "
                         "elle a probablement été collée avec du texte autour.")
    if "\n" in valeur or "\r" in valeur:
        raise CleRefusee("La valeur contient un saut de ligne.")
    if len(valeur) > 400:
        raise CleRefusee("Valeur anormalement longue (plus de 400 caractères).")
    if not re.match(emplacement["forme"], valeur):
        raise CleRefusee(f"Format inattendu : cette clé est {emplacement['forme_dit']}. "
                         f"Vérifier qu'elle a été copiée en entier, sans "
                         f"guillemets ni préfixe.")


SOUS_WINDOWS = platform.system() == "Windows"


def _restreindre(chemin):
    """
    Réserve le fichier à son propriétaire.

    Sous Linux et macOS : mode 0600, la protection est réelle.
    Sous Windows : os.chmod ne pilote que l'attribut « lecture seule », il ne
    restreint personne. La protection y vient des droits du dossier de
    l'utilisateur, pas du mode du fichier. On n'applique donc rien plutôt que
    de rendre .env non modifiable et de faire croire à une protection.
    """
    if SOUS_WINDOWS:
        return
    os.chmod(chemin, stat.S_IRUSR | stat.S_IWUSR)


def protection_fichier():
    """Ce qu'on peut honnêtement dire à l'utilisateur sur la protection de .env."""
    if SOUS_WINDOWS:
        return ("dans votre dossier personnel Windows — accessible aux "
                "administrateurs de la machine")
    return "permissions 0600, lisible par vous seul"


def _ecrire_fichier(lignes):
    """
    Remplacement atomique. Le fichier temporaire est créé dans le même dossier
    pour que os.replace reste atomique.
    """
    contenu = "\n".join(lignes).rstrip("\n") + "\n"
    fd, temporaire = tempfile.mkstemp(dir=BASE, prefix=".env.", suffix=".tmp")
    try:
        _restreindre(temporaire)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenu)
        os.replace(temporaire, FICHIER_ENV)
    except BaseException:
        try:
            os.unlink(temporaire)
        except OSError:
            pass
        raise
    _restreindre(FICHIER_ENV)


def _poser(variable, valeur):
    """
    Écrit VARIABLE=valeur dans .env. Remplace la ligne existante, ou l'ajoute.
    Les commentaires et les autres variables sont conservés tels quels.
    valeur=None supprime la ligne.
    """
    lignes = _lignes_env()
    motif = re.compile(r"^\s*" + re.escape(variable) + r"\s*=")
    sorties, remplace = [], False
    for ligne in lignes:
        if motif.match(ligne):
            if valeur is not None and not remplace:
                sorties.append(f"{variable}={valeur}")
                remplace = True
            continue                      # supprime les doublons éventuels
        sorties.append(ligne)
    if valeur is not None and not remplace:
        if sorties and sorties[-1].strip():
            sorties.append("")
        sorties.append(f"{variable}={valeur}")
    _ecrire_fichier(sorties)


def enregistrer(id_emplacement, valeur):
    """Pose une clé et la rend active immédiatement. -> message pour l'humain."""
    e = PAR_ID.get(id_emplacement)
    if not e:
        raise CleRefusee("Emplacement inconnu.")
    valeur = (valeur or "").strip()
    _verifier_forme(e, valeur)
    _poser(e["variable"], valeur)
    os.environ[e["variable"]] = valeur        # effet immédiat, sans redémarrage
    return f"{e['nom']} : clé enregistrée dans .env ({protection_fichier()})."


def supprimer(id_emplacement):
    e = PAR_ID.get(id_emplacement)
    if not e:
        raise CleRefusee("Emplacement inconnu.")
    _poser(e["variable"], None)
    os.environ.pop(e["variable"], None)
    return f"{e['nom']} : clé retirée de .env."


# --- Test ---------------------------------------------------------------------
# Chaque test fait un vrai appel. Il ne renvoie jamais la clé, et jamais le
# corps de la réponse du service : seulement un verdict.

def tester(id_emplacement):
    """-> (ok: bool, message: str)"""
    e = PAR_ID.get(id_emplacement)
    if not e:
        return False, "Emplacement inconnu."
    if id_emplacement == "gemini":
        return _tester_gemini()
    if id_emplacement.startswith("legifrance"):
        return _tester_legifrance()
    return False, "Aucun test disponible pour cet emplacement."


def _valeur_active(variable):
    return _valeurs_env().get(variable) or os.environ.get(variable, "")


def _tester_gemini():
    cle = _valeur_active("GEMINI_API_KEY")
    if not cle:
        return False, "Aucune clé Gemini enregistrée."
    url = ("https://generativelanguage.googleapis.com/v1beta/models?key="
           + urllib.parse.quote(cle))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            donnees = json.loads(r.read())
        n = len(donnees.get("models", []))
        return True, f"Clé acceptée — {n} modèle(s) accessible(s)."
    except urllib.error.HTTPError as ex:
        if ex.code in (401, 403):
            return False, "Clé refusée par Google. La recopier depuis " \
                          "https://aistudio.google.com/apikey."
        if ex.code == 429:
            return True, "Clé valide, mais quota épuisé pour l'instant."
        return False, f"Google a répondu {ex.code}."
    except OSError:
        return False, "Pas de connexion à Google."
    except ValueError:
        return False, "Réponse illisible de Google."


def _tester_legifrance():
    cid = _valeur_active("LEGIFRANCE_CLIENT_ID")
    secret = _valeur_active("LEGIFRANCE_CLIENT_SECRET")
    if not cid or not secret:
        return False, ("Les deux clés Légifrance sont nécessaires : "
                       "identifiant ET secret client.")
    donnees = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid,
        "client_secret": secret, "scope": "openid"}).encode()
    try:
        requete = urllib.request.Request(
            "https://oauth.piste.gouv.fr/api/oauth/token", data=donnees)
        with urllib.request.urlopen(requete, timeout=20) as r:
            jeton = json.loads(r.read()).get("access_token")
        return (True, "Identifiants acceptés — la récupération automatique "
                      "des articles est active.") if jeton else \
               (False, "Légifrance n'a pas délivré de jeton.")
    except urllib.error.HTTPError as ex:
        if ex.code in (400, 401, 403):
            return False, ("Identifiants refusés par Légifrance. Vérifier "
                           "l'abonnement à l'API sur piste.gouv.fr.")
        return False, f"Légifrance a répondu {ex.code}."
    except OSError:
        return False, "Pas de connexion à Légifrance."
    except ValueError:
        return False, "Réponse illisible de Légifrance."


# --- CLI ---------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Clés d'accès de l'assistant.")
    ap.add_argument("action", choices=["etat", "tester"], nargs="?",
                    default="etat")
    ap.add_argument("--cle", help="identifiant d'emplacement (ex. gemini)")
    args = ap.parse_args()

    if args.action == "tester":
        for e in EMPLACEMENTS:
            if args.cle and e["id"] != args.cle:
                continue
            ok, msg = tester(e["id"])
            print(f"  {'ok ' if ok else '⛔ '}{e['nom']} — {msg}")
        return
    for e in etat():
        marque = "✔" if e["configuree"] else ("⛔" if e["obligatoire"] else "·")
        detail = f"{e['apercu']} ({e['origine']})" if e["configuree"] else "absente"
        print(f"  {marque} {e['nom']:38} {detail}")


if __name__ == "__main__":
    main()
