#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingestion.py — tout fichier déposé devient un .md, ou n'entre pas.

Règle unique : le corpus ne contient que du Markdown vérifié. Un document
déposé est converti, MESURÉ, puis écrit — ou refusé avec la raison exacte.

« 100 % sans faute » n'est pas une promesse, c'est une mesure. On ne peut pas
garantir qu'une extraction est parfaite ; on peut refuser tout ce qui ne l'est
pas démontrablement. D'où deux extractions indépendantes confrontées l'une à
l'autre, plus une batterie de contrôles de dégât d'encodage.

  .docx / .odt  -> exact. Le texte est dans le XML, il n'y a rien à deviner.
  .md / .txt    -> exact si l'encodage est propre, refusé sinon.
  .pdf natif    -> deux extracteurs confrontés. Accepté au-dessus du seuil.
  .pdf scanné   -> REFUSÉ. Sans couche texte il n'y a rien à extraire, et une
                   OCR non relue produit un corpus juridique faux.

L'original est toujours conservé dans _sources/, jamais lu par l'assistant.

stdlib uniquement ; pdftotext (poppler-utils) utilisé s'il est présent.
"""

import datetime
import collections
import difflib
import io
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import corpus

BASE = os.path.dirname(os.path.abspath(__file__))

# Deux mesures, deux seuils. Elles ne disent pas la même chose :
#   couverture = a-t-on TOUT le texte ?     Une perte est rédhibitoire.
#   ordre      = est-il dans le bon ordre ? Un désordre se voit à la lecture.
SEUIL_COUVERTURE = 0.999      # en dessous : du texte a disparu -> refus
SEUIL_ORDRE = 0.98            # en dessous : colonnes entremêlées -> signalement

# Un document plus court que ça n'est pas un document.
MINIMUM_UTILE = 200

FORMATS = (".md", ".txt", ".text", ".pdf", ".docx", ".odt", ".html", ".htm")


class Refus(Exception):
    """Le fichier n'entre pas dans le corpus. Le message dit quoi faire."""


# --- Extraction --------------------------------------------------------------

def _texte_brut(octets):
    """Décodage strict. Un encodage douteux est signalé, jamais rafistolé."""
    try:
        return octets.decode("utf-8"), []
    except UnicodeDecodeError:
        pass
    for codec in ("cp1252", "latin-1"):
        try:
            return octets.decode(codec), [
                f"Fichier encodé en {codec}, converti en UTF-8 : vérifier les "
                f"caractères accentués et les guillemets."]
        except UnicodeDecodeError:
            continue
    raise Refus("Encodage illisible : réenregistrer le fichier en UTF-8.")


def _docx(octets):
    """
    Texte d'un .docx. Exact : les paragraphes sont dans le XML, on les lit.
    Les tableaux sont rendus en Markdown, une ligne par ligne de tableau.
    """
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        z = zipfile.ZipFile(io.BytesIO(octets))
        racine = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise Refus(f"Fichier .docx illisible ({e}).")

    lignes = []
    corps = racine.find(f"{W}body")
    for bloc in (list(corps) if corps is not None else []):
        if bloc.tag == f"{W}p":
            lignes.append(_docx_paragraphe(bloc, W))
        elif bloc.tag == f"{W}tbl":
            for n, tr in enumerate(bloc.findall(f"{W}tr")):
                cellules = [" ".join(_docx_paragraphe(p, W)
                                     for p in tc.findall(f"{W}p")).strip()
                            for tc in tr.findall(f"{W}tc")]
                lignes.append("| " + " | ".join(cellules) + " |")
                if n == 0:          # ligne de séparation, sinon pas un tableau
                    lignes.append("|" + "|".join(["---"] * len(cellules)) + "|")
            lignes.append("")
    return "\n".join(lignes)


def _docx_paragraphe(p, W):
    """Un paragraphe, titres compris. <w:t> porte tout le texte."""
    texte = "".join(t.text or "" for t in p.iter(f"{W}t"))
    style = p.find(f"{W}pPr/{W}pStyle")
    if style is not None and texte.strip():
        val = (style.get(f"{W}val") or "").lower()
        m = re.search(r"(?:heading|titre)\s*(\d)", val)
        if m:
            return "#" * min(int(m.group(1)) + 1, 6) + " " + texte.strip()
    return texte


def _odt(octets):
    """Texte d'un .odt. Même principe que le .docx : le XML fait foi."""
    T = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    try:
        z = zipfile.ZipFile(io.BytesIO(octets))
        racine = ET.fromstring(z.read("content.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise Refus(f"Fichier .odt illisible ({e}).")
    lignes = []
    for el in racine.iter():
        if el.tag in (f"{T}p", f"{T}h"):
            texte = "".join(el.itertext())
            if el.tag == f"{T}h" and texte.strip():
                niveau = int(el.get(f"{T}outline-level") or 1)
                lignes.append("#" * min(niveau + 1, 6) + " " + texte.strip())
            else:
                lignes.append(texte)
    return "\n".join(lignes)


def _html(octets):
    texte, notes = _texte_brut(octets)
    texte = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", texte)
    texte = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", texte)
    texte = re.sub(r"<[^>]+>", "", texte)
    for ent, car in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                     ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"),
                     ("&eacute;", "é"), ("&egrave;", "è"), ("&agrave;", "à")):
        texte = texte.replace(ent, car)
    return texte, notes


def _pdftotext_dispo():
    return shutil.which("pdftotext") is not None


def _pdftotext(octets, layout=True):
    """Extraction par poppler. Renvoie None si l'outil est absent ou échoue."""
    if not _pdftotext_dispo():
        return None
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "e.pdf")
        with open(src, "wb") as f:
            f.write(octets)
        cmd = ["pdftotext", "-enc", "UTF-8"]
        if layout:
            cmd.append("-layout")
        cmd += [src, "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", "replace")


def _pages_pdf(octets):
    """Nombre de pages annoncé par le PDF, pour repérer les pages vides."""
    m = re.findall(rb"/Type\s*/Page\b[^s]", octets)
    return len(m) or len(re.findall(rb"/Count\s+(\d+)", octets)) and 0


# --- Contrôles de fidélité ---------------------------------------------------

RE_LIGATURE = re.compile("[ﬀ-ﬆ]")
RE_CESURE = re.compile(r"[a-zàâçéèêëîïôûùüÿœ]-\n[a-zàâçéèêëîïôûùüÿœ]")
RE_MOT_FR = re.compile(r"\b(?:le|la|les|des|dans|pour|qui|est|par|sur)\b", re.I)


def controler(texte, ext, octets=b""):
    """
    Anomalies mesurables. Deux niveaux :
      'bloquant'    -> le document n'entre pas
      'signalement' -> il entre, mais l'anomalie est écrite dans le document
    """
    anomalies = []
    net = texte.strip()

    if len(net) < MINIMUM_UTILE:
        anomalies.append(("bloquant",
                          f"Texte extrait trop court ({len(net)} caractères). "
                          f"Pour un PDF, c'est le symptôme d'un scan : il n'y a "
                          f"pas de couche texte à extraire."))
        return anomalies

    n = texte.count("�")
    if n:
        anomalies.append(("bloquant",
                          f"{n} caractère(s) de remplacement « � » : "
                          f"l'encodage source est perdu, le texte est corrompu."))

    lig = len(RE_LIGATURE.findall(texte))
    if lig:
        anomalies.append(("signalement",
                          f"{lig} ligature(s) typographique(s) (ﬁ, ﬂ…) : "
                          f"remplacées à l'ingestion."))

    ces = len(RE_CESURE.findall(texte))
    if ces > 5:
        anomalies.append(("signalement",
                          f"{ces} césure(s) de fin de ligne : recollées à "
                          f"l'ingestion. Vérifier les mots composés."))

    if len(net) > 1000 and len(RE_MOT_FR.findall(texte)) < len(net) / 400:
        anomalies.append(("bloquant",
                          "Aucun mot français courant dans un texte de "
                          f"{len(net)} caractères : l'extraction rend des codes "
                          f"de glyphes, pas du texte. Typique d'un PDF à "
                          f"polices sous-classées lu par un extracteur naïf."))
        return anomalies

    if RE_MOT_FR.search(texte) and not re.search(r"[àâçéèêëîïôûùüÿœ]", texte):
        anomalies.append(("bloquant",
                          "Texte français sans aucun accent : les caractères "
                          "accentués ont été perdus à l'extraction."))

    invisibles = len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", texte))
    if invisibles > len(texte) * 0.001:
        anomalies.append(("bloquant",
                          f"{invisibles} caractère(s) de contrôle : extraction "
                          f"binaire, pas du texte."))

    if ext == ".pdf" and octets:
        pages = _pages_pdf(octets)
        if pages and len(net) / pages < 80:
            anomalies.append(("bloquant",
                              f"{len(net)} caractères pour {pages} page(s) : "
                              f"la plupart des pages sont vides. PDF scanné ou "
                              f"protégé."))
    return anomalies


def couverture(a, b):
    """
    Part du vocabulaire commun aux deux extractions. Mesure la PERTE : un mot
    présent d'un côté et absent de l'autre est du texte que l'une des deux n'a
    pas vu. Insensible à l'ordre, c'est voulu.
    """
    ma, mb = _mots(a), _mots(b)
    if not ma or not mb:
        return 0.0
    commun = sum((ma & mb).values())
    total = max(sum(ma.values()), sum(mb.values()))
    return commun / total if total else 0.0


def ordre(a, b):
    """Accord de séquence : mesure le DÉSORDRE de lecture (colonnes, encarts)."""
    na, nb = _normal(a), _normal(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


def _mots(s):
    return collections.Counter(re.findall(r"[\w'’-]+", _normal(s).lower()))


def mots_perdus(a, b, maximum=12):
    """Les mots vus par une extraction et pas par l'autre."""
    ma, mb = _mots(a), _mots(b)
    perdus = list((ma - mb).elements()) + list((mb - ma).elements())
    return sorted(set(perdus))[:maximum]


def _normal(s):
    """Espaces et sauts de ligne écrasés : on compare les mots, pas la mise en page."""
    return " ".join(s.split())


def divergences(a, b, maximum=5):
    """Les zones où les deux extractions ne disent pas la même chose."""
    na, nb = _normal(a), _normal(b)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, na, nb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append({"type": tag,
                    "extracteur_1": na[i1:i2][:90],
                    "extracteur_2": nb[j1:j2][:90]})
        if len(out) >= maximum:
            break
    return out


# --- Nettoyage sûr -----------------------------------------------------------
# Uniquement des transformations réversibles et sans perte de sens.

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
             "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def normaliser(texte):
    for a, b in LIGATURES.items():
        texte = texte.replace(a, b)
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    texte = texte.replace(" ", " ").replace(" ", " ")
    texte = RE_CESURE.sub(lambda m: m.group(0).replace("-\n", ""), texte)
    texte = re.sub(r"[ \t]+\n", "\n", texte)
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    return texte.strip() + "\n"


# --- Extraction pilotée ------------------------------------------------------

def extraire(nom, octets):
    """
    -> {'texte','methode','accord','anomalies','notes'}
    Lève Refus si le format n'est pas pris en charge.
    """
    ext = os.path.splitext(nom)[1].lower()
    if ext not in FORMATS:
        raise Refus(f"Format non pris en charge : {ext or 'inconnu'}. "
                    f"Formats acceptés : {', '.join(FORMATS)}.")
    notes = []

    tx_couv = tx_ordre = 1.0
    if ext in (".md", ".txt", ".text"):
        texte, notes = _texte_brut(octets)
        methode = "lecture directe"
    elif ext == ".docx":
        texte, methode = _docx(octets), "XML WordprocessingML"
    elif ext == ".odt":
        texte, methode = _odt(octets), "XML OpenDocument"
    elif ext in (".html", ".htm"):
        texte, notes = _html(octets)
        methode = "balises retirées"
    else:
        texte, methode, tx_couv, tx_ordre, notes = _extraire_pdf(octets)

    texte = normaliser(texte)
    return {"texte": texte, "methode": methode,
            "couverture": tx_couv, "ordre": tx_ordre,
            "anomalies": controler(texte, ext, octets), "notes": notes}


def _extraire_pdf(octets):
    """
    Deux lectures indépendantes du MÊME décodeur de caractères, avec deux
    algorithmes d'ordre de lecture différents : « -layout » respecte la mise en
    page, « -raw » suit l'ordre d'écriture dans le fichier. Ce qu'elles ont en
    commun est du texte réellement présent ; ce sur quoi elles divergent est un
    problème d'ordre de lecture, pas de contenu.

    L'extracteur interne n'est PAS un témoin valable : sur un PDF à polices
    sous-classées (tout PDF produit par un navigateur) il rend des codes de
    glyphes décalés — « $XGLW » pour « Audit ». Il ne sert qu'en dernier
    recours, et alors la fidélité est déclarée non vérifiée.
    """
    mise_en_page = _pdftotext(octets, layout=True)
    brut = _pdftotext(octets, layout=False)

    if mise_en_page is None or brut is None:
        maison = corpus.pdf_vers_texte(octets)
        return (maison, "extracteur interne — fidélité NON VÉRIFIÉE", 0.0, 0.0,
                ["pdftotext (paquet poppler-utils) est absent : une seule "
                 "extraction, aucune confrontation possible, et l'extracteur "
                 "interne échoue sur les PDF à polices sous-classées. "
                 "Installer : sudo apt install poppler-utils"])

    return (mise_en_page, "pdftotext -layout, confronté à pdftotext -raw",
            couverture(mise_en_page, brut), ordre(mise_en_page, brut), [])


# --- Ingestion ---------------------------------------------------------------

def ingerer(nom, octets, dossier, meta, acteur="interface", forcer=False):
    """
    Convertit, contrôle, écrit un .md dans le corpus. Conserve l'original.
    -> (True, {'fichier','rapport'}) ou (False, rapport lisible)

    Trois portes, dans cet ordre :
      1. anomalie bloquante        -> refus, jamais contournable
      2. couverture insuffisante   -> refus (du texte a disparu), levable par
                                      --forcer une fois les mots perdus lus
      3. ordre douteux             -> accepté, écrit dans le document

    forcer=True ne lève JAMAIS la porte 1 : un texte corrompu n'entre pas,
    même sur demande explicite.
    """
    res = extraire(nom, octets)
    bloquants = [m for niveau, m in res["anomalies"] if niveau == "bloquant"]
    signalements = [m for niveau, m in res["anomalies"] if niveau != "bloquant"]

    if bloquants:
        return False, _rapport(nom, res, bloquants, signalements, refuse=True)

    if res["couverture"] < SEUIL_COUVERTURE and not forcer:
        detail = [f"Couverture {res['couverture'] * 100:.2f} % (seuil "
                  f"{SEUIL_COUVERTURE * 100:.1f} %) : les deux extractions ne "
                  f"voient pas le même texte, du contenu est perdu."]
        if nom.lower().endswith(".pdf"):
            a, b = _pdftotext(octets, True), _pdftotext(octets, False)
            if a and b:
                perdus = mots_perdus(a, b)
                if perdus:
                    detail.append("Mots vus par une seule extraction : "
                                  + ", ".join(perdus))
        detail.append("Relire ces zones dans l'original, puis relancer avec "
                      "--forcer si le texte retenu est bon.")
        return False, _rapport(nom, res, detail, signalements, refuse=True)

    if res["ordre"] < SEUIL_ORDRE:
        signalements.append(
            f"Ordre de lecture incertain (accord {res['ordre'] * 100:.1f} %) : "
            f"le document contient des colonnes, des encarts ou des tableaux. "
            f"Le texte est complet, mais son enchaînement est à vérifier.")

    original = corpus.sauvegarder_source(nom, octets)
    meta = dict(meta)
    meta.setdefault("verifie_le", datetime.date.today().isoformat())
    meta["source_fichier"] = original
    meta["extraction"] = res["methode"]
    meta["couverture"] = ("exacte" if res["couverture"] >= 1.0
                          else f"{res['couverture'] * 100:.2f} %")
    meta["ordre_de_lecture"] = ("exact" if res["ordre"] >= 1.0
                                else f"{res['ordre'] * 100:.1f} %")

    entete = ""
    if signalements or res["notes"]:
        lignes = "".join(f"> - {m}\n" for m in signalements + res["notes"])
        entete = ("> **Contrôle d'ingestion**\n"
                  f"{lignes}"
                  f"> - Original conservé : `{original}`\n\n")

    nom_md = os.path.splitext(os.path.basename(nom))[0] + ".md"
    ok, info = corpus.ajouter_document(dossier, nom_md, meta,
                                       entete + res["texte"], acteur)
    if not ok:
        return False, f"Écriture refusée : {info}"
    return True, {"fichier": info,
                  "rapport": _rapport(nom, res, [], signalements, refuse=False)}


def _rapport(nom, res, bloquants, signalements, refuse):
    lignes = [f"{'REFUSÉ' if refuse else 'INGÉRÉ'} — {nom}",
              f"  extraction : {res['methode']}",
              f"  couverture : " + ("exacte (aucune perte possible)"
                                    if res["couverture"] >= 1.0
                                    else f"{res['couverture'] * 100:.2f} %"),
              f"  ordre      : " + ("exact" if res["ordre"] >= 1.0
                                    else f"{res['ordre'] * 100:.1f} %"),
              f"  longueur   : {len(res['texte'])} caractères"]
    for m in bloquants:
        lignes.append(f"  ⛔ {m}")
    for m in signalements + res["notes"]:
        lignes.append(f"  · {m}")
    if refuse:
        lignes.append("  → Le document n'est PAS entré dans le corpus.")
    return "\n".join(lignes)


# --- CLI ---------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Convertit un fichier en .md vérifié et l'ajoute au corpus.")
    ap.add_argument("fichier")
    ap.add_argument("--dossier", help="dossier du corpus (ex. 01-accords)")
    ap.add_argument("--titre", default="")
    ap.add_argument("--statut", default="en_vigueur",
                    choices=["projet", "en_vigueur", "abroge"])
    ap.add_argument("--signature", default="", help="date de signature (AAAA-MM-JJ)")
    ap.add_argument("--effet", default="", help="date d'effet (AAAA-MM-JJ)")
    ap.add_argument("--controle", action="store_true",
                    help="contrôler seulement, sans rien écrire")
    ap.add_argument("--forcer", action="store_true",
                    help="passer outre un accord insuffisant (jamais une "
                         "anomalie bloquante)")
    args = ap.parse_args()

    with open(args.fichier, "rb") as f:
        octets = f.read()
    nom = os.path.basename(args.fichier)

    try:
        if args.controle or not args.dossier:
            res = extraire(nom, octets)
            bloq = [m for n, m in res["anomalies"] if n == "bloquant"]
            sign = [m for n, m in res["anomalies"] if n != "bloquant"]
            print(_rapport(nom, res, bloq, sign, refuse=bool(bloq)))
            if not args.dossier:
                print("\n  (aucun --dossier : contrôle seul, rien n'a été écrit)")
            return
        meta = {"titre": args.titre or os.path.splitext(nom)[0],
                "statut": args.statut, "date_signature": args.signature,
                "date_effet": args.effet, "source": nom}
        ok, res = ingerer(nom, octets, args.dossier, meta,
                          acteur="ingestion CLI", forcer=args.forcer)
        print(res["rapport"] if ok else res)
        if ok:
            print(f"  → écrit : {res['fichier']}")
    except Refus as e:
        raise SystemExit(f"REFUSÉ — {nom}\n  ⛔ {e}")


if __name__ == "__main__":
    main()
