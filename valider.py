#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valider.py — rejoue le banc de test et dit, en clair, si l'assistant dérive.

    python3 valider.py                      # modèle courant (Réglages)
    python3 valider.py --modele gemini-flash-latest
    python3 valider.py --compare gemini-flash-lite-latest gemini-flash-latest
    python3 valider.py --ids 4 7 12         # seulement ces questions
    python3 valider.py --pause 4            # ménager un quota gratuit

L'évaluation est MÉCANIQUE : expressions régulières sur la réponse et
vérification des articles réellement cités. Aucun modèle ne juge un autre
modèle — sinon on ne mesurerait que la complaisance de l'arbitre.

Sorties : tests/rapport-<modele>.json (brut) et VALIDATION.md (lisible).
stdlib uniquement.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time

import demande as D
import recherche as R

BASE = os.path.dirname(os.path.abspath(__file__))
FICHIER_BANC = os.path.join(BASE, "tests", "banc.json")
FICHIER_VALIDATION = os.path.join(BASE, "VALIDATION.md")


def charger_banc():
    with open(FICHIER_BANC, encoding="utf-8") as f:
        return json.load(f)


def evaluer(cas, res):
    """
    Compare une réponse au cas attendu. -> (conforme, ecarts[])
    Aucune tolérance implicite : ce qui n'est pas retrouvé est un écart.
    """
    reponse = res["reponse"]
    norm = R.normalise(reponse)
    ecarts = []

    def present(motif):
        # La normalisation supprime accents ET symboles : « 10 % » y devient
        # « 10 ». On cherche donc dans les deux formes, sinon le banc échoue
        # sur des réponses justes.
        return re.search(motif, norm) or re.search(motif, reponse, re.I)

    if cas["comportement"] == "refus_individuel" and not res.get("bloque"):
        ecarts.append("la question individuelle n'a PAS été arrêtée avant "
                      "l'appel au modèle")

    for groupe in cas.get("motifs_obligatoires", []):
        if not any(present(m) for m in groupe):
            ecarts.append("attendu, absent de la réponse : " + " / ".join(groupe))

    cites = R.refs_code(reponse)
    for art in cas.get("articles_attendus", []):
        if art not in cites:
            ecarts.append(f"article {art} non cité"
                          + (f" (cités : {', '.join(sorted(cites))})"
                             if cites else " (aucun article cité)"))

    for interdit in cas.get("interdits", []):
        m = re.search(interdit, reponse, re.I)
        if m:
            ecarts.append(f"contient ce qui est interdit : « {m.group(0)} » "
                          f"(motif {interdit})")

    # Un garde-fou de citation ne peut se déclencher que si le modèle a
    # effectivement cité la référence : s'il a refusé de répondre, il n'y a rien
    # à signaler, et c'est le bon comportement.
    refs_alertees = {a["reference"] for a in res.get("alertes", [])}
    for attendue in cas.get("alertes_si_cite", []):
        if attendue in cites and not any(attendue in r for r in refs_alertees):
            ecarts.append(f"« {attendue} » est cité sans que le garde-fou "
                          f"le signale comme non vérifié")

    if cas["comportement"] == "non_couvert":
        graves = [a for a in res.get("alertes", []) if a["niveau"] == "alerte"]
        if graves and not cas.get("alertes_attendues"):
            ecarts.append("références non vérifiées produites alors que le "
                          "corpus ne couvre pas le sujet : "
                          + ", ".join(a["reference"] for a in graves))
    return (not ecarts), ecarts


def executer(modele=None, ids=None, pause=0.0, progression=None):
    """Rejoue le banc. `progression(i, total, cas, resultat)` est optionnel."""
    banc = charger_banc()
    cas_list = [c for c in banc["questions"] if not ids or c["id"] in ids]
    modele = modele or D.lire_reglages()["modele_question"]
    resultats, debut = [], time.time()
    for i, cas in enumerate(cas_list, 1):
        entree = {"id": cas["id"], "question": cas["question"],
                  "categorie": cas["categorie"], "attendu": cas["attendu"],
                  "piege": cas["piege"]}
        try:
            res = D.repondre(cas["question"], modele=modele)
            conforme, ecarts = evaluer(cas, res)
            entree.update({
                "conforme": conforme, "ecarts": ecarts,
                "reponse": res["reponse"], "bloque": res.get("bloque", False),
                "articles_cites": sorted(R.refs_code(res["reponse"])),
                "alertes": res.get("alertes", []),
                "sources": [f"{p['fichier']} § {p['titre']}"
                            for p in res.get("passages", [])],
            })
        except D.ErreurAssistant as e:
            # Une panne du service n'est PAS un écart du modèle : la question
            # n'a pas été mesurée. Les confondre gonflerait ou masquerait le
            # taux d'erreur réel.
            entree.update({"conforme": False, "non_mesuree": True,
                           "ecarts": [f"non mesurée — {e}"],
                           "reponse": "", "erreur": str(e), "alertes": [],
                           "articles_cites": [], "sources": []})
        resultats.append(entree)
        if progression:
            progression(i, len(cas_list), cas, entree)
        if pause and i < len(cas_list):
            time.sleep(pause)
    reussites = sum(1 for r in resultats if r["conforme"])
    non_mesurees = sum(1 for r in resultats if r.get("non_mesuree"))
    return {"modele": modele, "horodatage": datetime.datetime.now()
                                            .replace(microsecond=0).isoformat(),
            "version_banc": banc["version"], "total": len(resultats),
            "reussites": reussites,
            "echecs": len(resultats) - reussites - non_mesurees,
            "non_mesurees": non_mesurees,
            "mesurees": len(resultats) - non_mesurees,
            "duree_s": round(time.time() - debut, 1), "resultats": resultats}


def ecrire_rapport_json(rapport, partiel=False):
    os.makedirs(os.path.join(BASE, "tests"), exist_ok=True)
    nom = ("rapport-" + re.sub(r"[^\w.-]", "-", rapport["modele"])
           + ("-partiel" if partiel else "") + ".json")
    chemin = os.path.join(BASE, "tests", nom)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2)
    return chemin


def resume_texte(rapport):
    """Résumé court, affichable tel quel dans l'interface."""
    nm = rapport.get("non_mesurees", 0)
    suffixe = (f" · {nm} question(s) NON MESURÉE(S) — le service n'a pas "
               f"répondu (quota ou panne) ; relancer pour les mesurer"
               if nm else "")
    if rapport["echecs"] == 0:
        return (f"{rapport['reussites']}/{rapport['mesurees']} conforme — "
                f"aucun écart détecté ({rapport['modele']}){suffixe}.")
    lignes = [f"{rapport['reussites']}/{rapport['mesurees']} conforme — "
              f"{rapport['echecs']} écart(s) ({rapport['modele']}){suffixe} :"]
    for r in rapport["resultats"]:
        if not r["conforme"]:
            lignes.append(f"  Q{r['id']} ({r['categorie']}) — "
                          + " ; ".join(r["ecarts"]))
    return "\n".join(lignes)


def ecrire_validation_md(rapports):
    """VALIDATION.md : ce qui a été mesuré, sur quels modèles, avec les écarts."""
    lignes = ["# Validation de l'assistant", "",
              "Sortie de `python3 valider.py` — banc de "
              f"{rapports[0]['total']} questions (`tests/banc.json`).",
              "Évaluation mécanique : expressions régulières sur la réponse + "
              "vérification des articles cités. Aucun modèle ne juge un autre "
              "modèle.", "",
              "## Résultats par modèle", "",
              "| Modèle | Conforme | Écarts | Non mesurées | Durée | Mesuré le |",
              "|---|---|---|---|---|---|"]
    for r in sorted(rapports, key=lambda x: -x["reussites"]):
        lignes.append(f"| `{r['modele']}` | "
                      f"{r['reussites']}/{r.get('mesurees', r['total'])} | "
                      f"{r['echecs']} | {r.get('non_mesurees', 0)} | "
                      f"{r['duree_s']} s | {r['horodatage']} |")
    lignes += ["", "## Détail des écarts", ""]
    for r in sorted(rapports, key=lambda x: -x["reussites"]):
        lignes.append(f"### `{r['modele']}` — {r['reussites']}/"
                      f"{r.get('mesurees', r['total'])}")
        lignes.append("")
        rates = [x for x in r["resultats"] if not x["conforme"]]
        if not rates:
            lignes += ["Aucun écart.", ""]
            continue
        for x in rates:
            lignes.append(f"**Q{x['id']} — {x['question']}**")
            lignes.append("")
            lignes.append(f"- Attendu : {x['attendu']}")
            lignes.append(f"- Piège testé : {x['piege']}")
            for e in x["ecarts"]:
                lignes.append(f"- Écart : {e}")
            extrait = " ".join(x["reponse"].split())[:300]
            if extrait:
                lignes.append(f"- Réponse obtenue : « {extrait}… »")
            lignes.append("")
    lignes += ["## Comment rejouer", "",
               "```bash",
               "python3 valider.py                       # modèle courant",
               "python3 valider.py --modele gemini-flash-latest",
               "python3 valider.py --compare gemini-flash-lite-latest "
               "gemini-flash-latest",
               "```", "",
               "Ou, sans terminal : bouton **Vérifier l'assistant** dans "
               "l'interface (page Réglages)."]
    with open(FICHIER_VALIDATION, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    return FICHIER_VALIDATION


def main():
    ap = argparse.ArgumentParser(description="Rejoue le banc de test.")
    ap.add_argument("--modele", help="modèle à mesurer")
    ap.add_argument("--compare", nargs="+", metavar="MODELE",
                    help="mesurer plusieurs modèles et écrire VALIDATION.md")
    ap.add_argument("--ids", nargs="+", type=int, help="ne jouer que ces questions")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="secondes entre deux appels (quota gratuit)")
    ap.add_argument("--sans-validation-md", action="store_true",
                    help="ne pas réécrire VALIDATION.md")
    args = ap.parse_args()

    modeles = args.compare or [args.modele or D.lire_reglages()["modele_question"]]
    rapports = []
    for modele in modeles:
        print(f"\n=== {modele} ===", flush=True)

        def avance(i, total, cas, entree):
            marque = "ok  " if entree["conforme"] else "ÉCART"
            print(f"  [{i:2}/{total}] Q{cas['id']:<2} {marque}  "
                  f"{cas['question'][:60]}", flush=True)
            for e in entree["ecarts"]:
                print(f"          → {e}", flush=True)

        rapport = executer(modele, args.ids, args.pause, avance)
        chemin = ecrire_rapport_json(rapport, partiel=bool(args.ids))
        print(f"\n{resume_texte(rapport)}")
        print(f"Rapport détaillé : {os.path.relpath(chemin, BASE)}")
        rapports.append(rapport)

    if not args.sans_validation_md and not args.ids:
        anciens = _rapports_existants(exclure=[r["modele"] for r in rapports])
        print("\nVALIDATION.md écrit : "
              + os.path.relpath(ecrire_validation_md(rapports + anciens), BASE))
    sys.exit(0 if all(r["echecs"] == 0 for r in rapports) else 1)


def _rapports_existants(exclure=()):
    """Reprend les mesures déjà faites sur d'autres modèles (banc identique)."""
    out = []
    dossier = os.path.join(BASE, "tests")
    for nom in sorted(os.listdir(dossier)) if os.path.isdir(dossier) else []:
        if not (nom.startswith("rapport-") and nom.endswith(".json")) \
                or nom.endswith("-partiel.json"):
            continue
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if r.get("modele") not in exclure and r.get("total"):
            out.append(r)
    return out


if __name__ == "__main__":
    main()
