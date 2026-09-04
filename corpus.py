#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
corpus.py — état du corpus et opérations dessus (ajout, modification, archivage).

Trois principes :

  1. Les métadonnées vivent dans le fichier (front matter), pas dans un index
     tenu à la main. INDEX.md devient une SORTIE calculée : un index manuel
     dérive du corpus réel, c'est la première source d'erreur silencieuse.
  2. Rien n'est supprimé. Un document remplacé part dans _ABROGES/ sous le nom
     _REMPLACE-PAR-<fichier>, et reste lisible.
  3. Tout écrit est journalisé (append-only) avec l'état antérieur -> on peut
     restaurer sans git.

stdlib uniquement.
"""

import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import zlib

BASE = os.path.dirname(os.path.abspath(__file__))
DOSSIER_ABROGES = os.path.join(BASE, "_ABROGES")
DOSSIER_JOURNAL = os.path.join(BASE, "_journal")
DOSSIER_SNAPSHOTS = os.path.join(DOSSIER_JOURNAL, "etats")
FICHIER_JOURNAL = os.path.join(DOSSIER_JOURNAL, "journal.jsonl")
FICHIER_INDEX = os.path.join(BASE, "INDEX.md")

# Dossiers de corpus : découverte automatique des dossiers « NN-nom ».
# Ajouter un dossier ne demande aucune modification du code.
RE_DOSSIER_CORPUS = re.compile(r"^\d{2}-[a-z0-9-]+$")
DOSSIER_LEGAL = "04-legal"
DOSSIERS_NOMINATIFS = {"05-pv-cse"}          # jamais envoyés au modèle
DOSSIERS_HORS_CORPUS = {"_ABROGES", "_sources", "_templates", "_journal",
                        "_historique", "tests", "__pycache__"}

STATUTS = ("projet", "en_vigueur", "abroge")
LIBELLE_STATUT = {"projet": "projet", "en_vigueur": "en vigueur", "abroge": "abrogé"}
CHAMPS_OBLIGATOIRES = ("titre", "statut", "date_signature", "date_effet", "source")
# Un extrait du Code du travail n'a ni date de signature ni date d'effet propres
# (chaque article porte la sienne) : on exige à la place la date de vérification.
CHAMPS_LEGAL = ("statut", "source", "verifie_le")


def champs_requis(dossier):
    return CHAMPS_LEGAL if dossier == DOSSIER_LEGAL else CHAMPS_OBLIGATOIRES
FRAICHEUR_MOIS = 6                            # au-delà : « à re-vérifier »


# --- Front matter ------------------------------------------------------------

def lire_front_matter(texte):
    """'---\\nk: v\\n---\\ncorps' -> ({'k': 'v'}, 'corps'). Tolérant : pas de YAML."""
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", texte, re.DOTALL)
    if not m:
        return {}, texte
    meta = {}
    for ligne in m.group(1).split("\n"):
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or ":" not in ligne:
            continue
        cle, _, val = ligne.partition(":")
        val = val.strip().strip('"').strip("'")
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        meta[cle.strip()] = val
    return meta, m.group(2)


def ecrire_front_matter(meta, corps):
    lignes = ["---"]
    for cle, val in meta.items():
        if isinstance(val, list):
            val = "[" + ", ".join(str(v) for v in val) + "]"
        lignes.append(f"{cle}: {val}")
    lignes.append("---")
    return "\n".join(lignes) + "\n" + corps.lstrip("\n")


# --- Lecture du corpus -------------------------------------------------------

def dossiers_corpus():
    out = []
    for nom in sorted(os.listdir(BASE)):
        if os.path.isdir(os.path.join(BASE, nom)) and RE_DOSSIER_CORPUS.match(nom):
            out.append(nom)
    return out


def dossiers_interrogeables():
    """Dossiers dont le contenu peut partir chez le modèle."""
    return [d for d in dossiers_corpus() if d not in DOSSIERS_NOMINATIFS]


def _titre_depuis_corps(corps, chemin):
    for ligne in corps.split("\n"):
        if ligne.startswith("# "):
            return ligne[2:].strip()
    return os.path.splitext(os.path.basename(chemin))[0].replace("_", " ").strip()


def _mois_ecoules(date_iso):
    try:
        d = datetime.date.fromisoformat(str(date_iso)[:10])
    except (ValueError, TypeError):
        return None
    ecart = datetime.date.today() - d
    return ecart.days / 30.44


def lire_document(rel):
    """Un document du corpus, métadonnées normalisées. rel = chemin relatif."""
    chemin = os.path.join(BASE, rel)
    try:
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
    except OSError:
        return None
    meta, corps = lire_front_matter(texte)
    dossier = rel.split(os.sep)[0]
    statut = str(meta.get("statut", "")).strip().lower().replace("é", "e")
    statut = {"en vigueur": "en_vigueur", "abrogé": "abroge"}.get(statut, statut)
    if statut not in STATUTS:
        statut = "inconnu"
    verifie = meta.get("verifie_le", "")
    mois = _mois_ecoules(verifie) if verifie else None
    doc = {
        "chemin": rel,
        "dossier": dossier,
        "titre": meta.get("titre") or _titre_depuis_corps(corps, chemin),
        "statut": statut,
        "date_signature": meta.get("date_signature", ""),
        "date_effet": meta.get("date_effet", ""),
        "source": meta.get("source", ""),
        "verifie_le": verifie,
        "remplace_par": meta.get("remplace_par", ""),
        "articles": meta.get("articles", []),
        "octets": os.path.getsize(chemin),
        "modifie_le": datetime.date.fromtimestamp(
            os.path.getmtime(chemin)).isoformat(),
        "perime": bool(mois is not None and mois > FRAICHEUR_MOIS),
        "mois_depuis_verif": None if mois is None else round(mois, 1),
        "meta": meta,
        "corps": corps,
    }
    doc["champs_manquants"] = [c for c in champs_requis(dossier)
                               if not str(meta.get(c, "")).strip()]
    return doc


def documents(inclure_abroges=False, avec_corps=False):
    """Tous les documents du corpus, triés par dossier puis titre."""
    dossiers = dossiers_corpus() + (["_ABROGES"] if inclure_abroges else [])
    out = []
    for d in dossiers:
        for chemin in sorted(glob.glob(os.path.join(BASE, d, "**", "*.md"),
                                       recursive=True)):
            rel = os.path.relpath(chemin, BASE)
            if os.path.basename(rel).startswith("_INDEX"):
                continue
            doc = lire_document(rel)
            if doc:
                if not avec_corps:
                    doc.pop("corps", None)
                out.append(doc)
    return out


# --- Journal append-only -----------------------------------------------------

def _horodatage():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def journal_ajouter(action, cible, avant=None, apres=None, acteur="interface",
                    detail=""):
    """
    Écrit une ligne de journal. `avant` (contenu intégral) est conservé dans
    _journal/etats/ -> restauration possible sans git.
    """
    os.makedirs(DOSSIER_SNAPSHOTS, exist_ok=True)
    entree = {"id": hashlib.sha1(
                  f"{_horodatage()}{cible}{action}".encode()).hexdigest()[:12],
              "horodatage": _horodatage(), "acteur": acteur, "action": action,
              "cible": cible, "detail": detail}
    if avant is not None:
        nom = f"{entree['id']}-avant.txt"
        with open(os.path.join(DOSSIER_SNAPSHOTS, nom), "w", encoding="utf-8") as f:
            f.write(avant)
        entree["etat_avant"] = nom
        entree["taille_avant"] = len(avant)
    if apres is not None:
        entree["taille_apres"] = len(apres)
        entree["resume_diff"] = resume_diff(avant or "", apres)
    with open(FICHIER_JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    return entree


def journal_lire(limite=200):
    if not os.path.isfile(FICHIER_JOURNAL):
        return []
    out = []
    with open(FICHIER_JOURNAL, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne:
                try:
                    out.append(json.loads(ligne))
                except json.JSONDecodeError:
                    continue
    return out[-limite:][::-1]


def restaurer(id_entree, acteur="interface"):
    """Remet un document dans l'état conservé par une entrée de journal."""
    for e in journal_lire(10000):
        if e["id"] == id_entree and e.get("etat_avant"):
            chemin_etat = os.path.join(DOSSIER_SNAPSHOTS, e["etat_avant"])
            with open(chemin_etat, encoding="utf-8") as f:
                contenu = f.read()
            cible = os.path.join(BASE, e["cible"])
            avant = ""
            if os.path.isfile(cible):
                with open(cible, encoding="utf-8") as f:
                    avant = f.read()
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with open(cible, "w", encoding="utf-8") as f:
                f.write(contenu)
            journal_ajouter("restauration", e["cible"], avant, contenu, acteur,
                            f"depuis l'entrée {id_entree}")
            ecrire_index(acteur, "après restauration")
            return True, e["cible"]
    return False, "entrée de journal introuvable ou sans état conservé"


def resume_diff(avant, apres):
    a, b = avant.split("\n"), apres.split("\n")
    import difflib
    plus = moins = 0
    for ligne in difflib.unified_diff(a, b, n=0, lineterm=""):
        if ligne.startswith("+") and not ligne.startswith("+++"):
            plus += 1
        elif ligne.startswith("-") and not ligne.startswith("---"):
            moins += 1
    return f"+{plus} / -{moins} ligne(s)"


def diff_texte(avant, apres, avant_nom="avant", apres_nom="après"):
    import difflib
    return "\n".join(difflib.unified_diff(avant.split("\n"), apres.split("\n"),
                                          avant_nom, apres_nom, lineterm="", n=3))


# --- Écriture ----------------------------------------------------------------

def _nom_sur(nom):
    """Nom de fichier sûr : pas de séparateur, pas d'espace, extension .md."""
    nom = os.path.basename(nom).strip().replace(" ", "-")
    nom = re.sub(r"[^A-Za-z0-9._-]", "-", nom)
    nom = re.sub(r"-+", "-", nom).strip("-.")
    if not nom.lower().endswith(".md"):
        nom = os.path.splitext(nom)[0] + ".md"
    return nom or "document.md"


def ajouter_document(dossier, nom_fichier, meta, corps, acteur="interface"):
    """Ajoute un document. Refuse si une métadonnée obligatoire manque."""
    if dossier not in dossiers_corpus():
        return False, f"dossier inconnu : {dossier}"
    manquants = [c for c in champs_requis(dossier)
                 if not str(meta.get(c, "")).strip()]
    if manquants:
        return False, "métadonnées obligatoires manquantes : " + ", ".join(manquants)
    if meta.get("statut") not in STATUTS:
        return False, "statut invalide (projet / en_vigueur / abroge)"
    if not corps.strip():
        return False, "document vide"
    nom = _nom_sur(nom_fichier)
    rel = os.path.join(dossier, nom)
    chemin = os.path.join(BASE, rel)
    if os.path.exists(chemin):
        return False, f"{rel} existe déjà — modifier le document existant"
    meta = dict(meta)
    meta.setdefault("verifie_le", datetime.date.today().isoformat())
    texte = ecrire_front_matter(meta, corps)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte)
    journal_ajouter("ajout", rel, None, texte, acteur, meta.get("titre", ""))
    ecrire_index(acteur, f"ajout de {rel}")
    return True, rel


def enregistrer_document(rel, meta, corps, acteur="interface"):
    """Modifie un document existant (métadonnées + texte), avec journal."""
    chemin = os.path.join(BASE, rel)
    if not os.path.isfile(chemin):
        return False, f"document introuvable : {rel}"
    manquants = [c for c in champs_requis(rel.split(os.sep)[0])
                 if not str(meta.get(c, "")).strip()]
    if manquants:
        return False, "métadonnées obligatoires manquantes : " + ", ".join(manquants)
    with open(chemin, encoding="utf-8") as f:
        avant = f.read()
    texte = ecrire_front_matter(meta, corps)
    if texte == avant:
        return True, "aucun changement"
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte)
    journal_ajouter("modification", rel, avant, texte, acteur)
    ecrire_index(acteur, f"modification de {rel}")
    return True, rel


def archiver_document(rel, remplace_par="", acteur="interface"):
    """
    Sort un document du corpus actif. Jamais de suppression : déplacement dans
    _ABROGES/ sous le nom _REMPLACE-PAR-<fichier>, statut forcé à `abroge`.
    """
    chemin = os.path.join(BASE, rel)
    if not os.path.isfile(chemin):
        return False, f"document introuvable : {rel}"
    with open(chemin, encoding="utf-8") as f:
        avant = f.read()
    meta, corps = lire_front_matter(avant)
    meta["statut"] = "abroge"
    meta["abroge_le"] = datetime.date.today().isoformat()
    if remplace_par:
        meta["remplace_par"] = remplace_par
    base_nom = os.path.basename(rel)
    suffixe = _nom_sur(remplace_par) if remplace_par else "SANS-REMPLACANT.md"
    nouveau = f"_REMPLACE-PAR-{os.path.splitext(suffixe)[0]}__{base_nom}"
    os.makedirs(DOSSIER_ABROGES, exist_ok=True)
    cible = os.path.join(DOSSIER_ABROGES, nouveau)
    n = 1
    while os.path.exists(cible):
        cible = os.path.join(DOSSIER_ABROGES, f"{n}-{nouveau}")
        n += 1
    with open(cible, "w", encoding="utf-8") as f:
        f.write(ecrire_front_matter(meta, corps))
    os.remove(chemin)
    journal_ajouter("archivage", rel, avant, None, acteur,
                    f"déplacé vers {os.path.relpath(cible, BASE)}")
    ecrire_index(acteur, f"archivage de {rel}")
    return True, os.path.relpath(cible, BASE)


# --- INDEX.md généré ---------------------------------------------------------

BANDEAU_INDEX = (
    "<!-- FICHIER GÉNÉRÉ PAR corpus.py — NE PAS ÉDITER À LA MAIN.\n"
    "     Il est recalculé à partir des métadonnées de chaque document\n"
    "     (front matter). Pour corriger une ligne, corriger le document. -->\n")


def generer_index():
    docs = documents(inclure_abroges=True)
    aujourdhui = datetime.date.today().isoformat()
    lignes = [BANDEAU_INDEX,
              f"# État du corpus — généré le {aujourdhui}", "",
              "> Sortie calculée à partir des métadonnées des documents. "
              "Toute correction se fait dans le document, pas ici.",
              "> Entreprise : SAS FRERES — Branche : vins, cidres, jus de fruits, "
              "sirops, spiritueux et liqueurs de France (IDCC 493 / brochure 3029).",
              ""]
    actifs = [d for d in docs if d["dossier"] != "_ABROGES"]
    lignes += [f"**{len(actifs)} document(s) actif(s)**, "
               f"{len([d for d in docs if d['dossier'] == '_ABROGES'])} archivé(s). "
               f"{len([d for d in actifs if d['statut'] == 'projet'])} au statut "
               f"projet, {len([d for d in actifs if d['perime']])} à re-vérifier "
               f"(plus de {FRAICHEUR_MOIS} mois).", ""]
    par_dossier = {}
    for d in docs:
        par_dossier.setdefault(d["dossier"], []).append(d)
    for dossier in sorted(par_dossier):
        titre = dossier
        if dossier in DOSSIERS_NOMINATIFS:
            titre += " — nominatif, jamais envoyé au modèle"
        if dossier == "_ABROGES":
            titre += " — NE JAMAIS CITER"
        lignes += [f"## {titre}", "",
                   "| Fichier | Titre | Statut | Effet | Vérifié le | Alerte |",
                   "|---|---|---|---|---|---|"]
        for d in sorted(par_dossier[dossier], key=lambda x: x["chemin"]):
            alertes = []
            if d["champs_manquants"]:
                alertes.append("métadonnées incomplètes : "
                               + ", ".join(d["champs_manquants"]))
            if d["perime"]:
                alertes.append(f"vérifié il y a {d['mois_depuis_verif']} mois")
            if d["statut"] == "projet":
                alertes.append("projet — pas du droit applicable")
            if d["remplace_par"]:
                alertes.append("remplacé par " + d["remplace_par"])
            lignes.append("| `{}` | {} | {} | {} | {} | {} |".format(
                os.path.basename(d["chemin"]), d["titre"].replace("|", "/"),
                LIBELLE_STATUT.get(d["statut"], d["statut"]),
                d["date_effet"] or "—", d["verifie_le"] or "—",
                " ; ".join(alertes) or "—"))
        lignes.append("")
    for dossier in dossiers_corpus():
        if dossier not in par_dossier:
            lignes += [f"## {dossier}", "", "_Vide._", ""]
    return "\n".join(lignes) + "\n"


def ecrire_index(acteur="interface", motif=""):
    """Réécrit INDEX.md. L'état précédent est toujours conservé au journal."""
    nouveau = generer_index()
    avant = ""
    if os.path.isfile(FICHIER_INDEX):
        with open(FICHIER_INDEX, encoding="utf-8") as f:
            avant = f.read()
    if avant == nouveau:
        return False
    with open(FICHIER_INDEX, "w", encoding="utf-8") as f:
        f.write(nouveau)
    journal_ajouter("index", "INDEX.md", avant, nouveau, acteur, motif)
    return True


# --- Conversion PDF ----------------------------------------------------------

RE_TEXTE_PDF = re.compile(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>")


def _decoder_chaine_pdf(brut):
    if brut.startswith(b"<"):
        hexa = re.sub(rb"[^0-9A-Fa-f]", b"", brut[1:-1])
        if len(hexa) % 2:
            hexa += b"0"
        try:
            octets = bytes.fromhex(hexa.decode("ascii"))
        except ValueError:
            return ""
        if len(octets) >= 2 and all(octets[i] == 0 for i in range(0, len(octets), 2)):
            return octets.decode("utf-16-be", "replace")   # texte UTF-16BE
        return octets.decode("latin-1", "replace")
    corps = brut[1:-1]
    out, i = bytearray(), 0
    while i < len(corps):
        c = corps[i]
        if c == 0x5C and i + 1 < len(corps):                # antislash
            suiv = corps[i + 1]
            table = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if suiv in table:
                out.append(table[suiv]); i += 2; continue
            if 0x30 <= suiv <= 0x37:
                oct_ = corps[i + 1:i + 4]
                oct_ = oct_[:len(re.match(rb"[0-7]{1,3}", oct_).group(0))]
                out.append(int(oct_, 8) & 0xFF); i += 1 + len(oct_); continue
            out.append(suiv); i += 2; continue
        out.append(c); i += 1
    return bytes(out).decode("latin-1", "replace")


def pdf_vers_texte(donnees):
    """
    Extraction de texte d'un PDF, sans dépendance externe (zlib est stdlib).

    Couvre le cas courant : PDF « texte » compressé en Flate. Ne couvre PAS un
    PDF scanné (image) — il n'y a alors rien à extraire, et c'est dit
    explicitement plutôt que de rendre un document vide qui ferait un faux
    corpus. Le résultat est de toute façon soumis à validation humaine.
    """
    morceaux = []
    for m in re.finditer(rb"stream\r?\n", donnees):
        debut = m.end()
        fin = donnees.find(b"endstream", debut)
        if fin == -1:
            continue
        flux = donnees[debut:fin]
        try:
            flux = zlib.decompress(flux)
        except zlib.error:
            try:
                flux = zlib.decompressobj().decompress(flux)
            except zlib.error:
                pass          # flux non compressé : beaucoup de PDF simples
        if b"Tj" not in flux and b"TJ" not in flux:
            continue
        # On balaie le flux entier plutôt que des blocs BT…ET : « ET » apparaît
        # aussi à l'intérieur des mots (TELETRAVAIL), ce qui couperait le texte.
        page = []
        for op in re.finditer(rb"(\[(?:[^\[\]\\]|\\.)*\]|\((?:\\.|[^\\()])*\)"
                              rb"|<[0-9A-Fa-f\s]+>)\s*(TJ|Tj|'|\")"
                              rb"|\b(T\*|Td|TD|TL)\b", flux, re.DOTALL):
            if op.group(3):
                page.append("\n")
                continue
            arg = op.group(1)
            if arg.startswith(b"["):
                page.append("".join(_decoder_chaine_pdf(m.group(0))
                                    for m in RE_TEXTE_PDF.finditer(arg)))
            else:
                page.append(_decoder_chaine_pdf(arg))
            if op.group(2) in (b"'", b'"'):
                page.append("\n")
        if page:
            morceaux.append("".join(page))
    texte = "\n\n".join(morceaux)
    texte = re.sub(r"[ \t]+\n", "\n", texte)
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    texte = "".join(c for c in texte if c == "\n" or c == "\t" or ord(c) >= 32)
    return texte.strip()


def fichier_vers_markdown(nom, donnees):
    """
    (texte, avertissement). Le texte DOIT être relu par l'utilisateur avant
    ingestion : une extraction ratée produit un corpus faux que personne ne voit.
    """
    ext = os.path.splitext(nom)[1].lower()
    if ext in (".md", ".txt", ".text"):
        return donnees.decode("utf-8", "replace"), ""
    if ext == ".pdf":
        texte = pdf_vers_texte(donnees)
        if len(texte) < 200:
            return texte, ("Extraction quasi vide : ce PDF est probablement un "
                           "scan (image). Le convertir en texte avec un autre "
                           "outil, puis déposer le .txt.")
        return texte, ("Texte extrait automatiquement d'un PDF : relire "
                       "intégralement avant d'enregistrer. Les tableaux et les "
                       "colonnes sont souvent désordonnés.")
    return "", f"Format non pris en charge : {ext or 'inconnu'} (.md, .txt, .pdf)"


def sauvegarder_source(nom, donnees):
    """Conserve l'original déposé dans _sources/ (jamais lu par l'assistant)."""
    dossier = os.path.join(BASE, "_sources")
    os.makedirs(dossier, exist_ok=True)
    horodate = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    chemin = os.path.join(dossier, f"{horodate}-{_nom_sur(nom)[:-3]}"
                                   f"{os.path.splitext(nom)[1]}")
    with open(chemin, "wb") as f:
        f.write(donnees)
    return os.path.relpath(chemin, BASE)
