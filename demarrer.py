#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demarrer.py — un seul point d'entrée, Linux, Windows et macOS.

Ce fichier est le lanceur. Les deux petits fichiers à côté (`lancer.sh` et
`Assistant-Syndical.bat`) ne servent qu'à l'atteindre : sous Windows on ne peut
pas double-cliquer un .py de façon fiable, et si Python manque, un .py ne peut
rien expliquer. Toute la logique est ici, une seule fois, pour les trois
systèmes.

Au premier lancement, une icône est posée sur le bureau. Aux suivants, plus
rien : on lance, c'est tout. Rien n'est installé ailleurs, rien n'est envoyé
sur le réseau.

    python3 demarrer.py                 vérifie, pose l'icône si besoin, lance
    python3 demarrer.py --sans-icone    lance sans rien poser
    python3 demarrer.py --icone         pose l'icône et s'arrête
    python3 demarrer.py --diagnostic    dit ce qui va et ce qui manque

stdlib uniquement.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile

DOSSIER = os.path.dirname(os.path.abspath(__file__))
NOM = "Assistant Syndical"
DESCRIPTION = "Assistant documentaire syndical — CCN 3029 + Code du travail"
PYTHON_MINIMUM = (3, 8)

SYSTEME = platform.system()          # 'Linux' | 'Windows' | 'Darwin'
WINDOWS = SYSTEME == "Windows"
MACOS = SYSTEME == "Darwin"


# --- Affichage ---------------------------------------------------------------
# Sous Windows la console peut refuser certains caractères : on reste sobre.

def dire(texte=""):
    try:
        print(texte)
    except UnicodeEncodeError:
        print(texte.encode("ascii", "replace").decode("ascii"))


def titre(texte):
    dire()
    dire("  " + texte)
    dire("  " + "-" * len(texte))


# --- Vérifications -----------------------------------------------------------

def verifier():
    """
    -> (bloquants, avertissements). Un bloquant empêche le lancement ;
    un avertissement est une limite à connaître, pas une panne.
    """
    bloquants, avertissements = [], []

    if sys.version_info < PYTHON_MINIMUM:
        v = ".".join(str(n) for n in PYTHON_MINIMUM)
        bloquants.append(
            f"Python {platform.python_version()} est trop ancien : il faut au "
            f"moins {v}. Télécharger sur https://www.python.org/downloads/")

    for fichier in ("serveur.py", "demande.py", "corpus.py"):
        if not os.path.isfile(os.path.join(DOSSIER, fichier)):
            bloquants.append(
                f"Fichier manquant : {fichier}. Le dossier est incomplet — "
                f"le recopier en entier depuis la source.")

    if not os.access(DOSSIER, os.W_OK):
        bloquants.append(
            f"Le dossier n'est pas modifiable : {DOSSIER}. L'assistant a besoin "
            f"d'y écrire. Le déplacer dans le dossier personnel.")

    if not os.path.isfile(os.path.join(DOSSIER, ".env")):
        avertissements.append(
            "Aucune clé d'accès enregistrée pour l'instant. L'assistant démarre "
            "quand même : la coller dans Réglages > Clés d'accès.")

    if not shutil.which("pdftotext"):
        if WINDOWS:
            avertissements.append(
                "Lecture des PDF indisponible sur ce poste. Déposer les "
                "documents en .docx ou .txt : la lecture y est exacte.")
        else:
            avertissements.append(
                "Lecture des PDF indisponible : installer poppler "
                + ("(brew install poppler)" if MACOS
                   else "(sudo apt install poppler-utils)") + ".")
    return bloquants, avertissements


# --- Raccourci : bureau et menu ----------------------------------------------

def _dossier_bureau():
    """Le bureau de l'utilisateur, quel que soit le système et la langue."""
    if WINDOWS:
        for chemin in (os.path.join(os.path.expanduser("~"), "Desktop"),
                       os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
                       os.path.join(os.environ.get("OneDrive", ""), "Desktop")):
            if chemin and os.path.isdir(chemin):
                return chemin
        return None
    try:                                   # Linux : le nom dépend de la langue
        sortie = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                capture_output=True, timeout=5)
        chemin = sortie.stdout.decode("utf-8", "replace").strip()
        if chemin and os.path.isdir(chemin):
            return chemin
    except (OSError, subprocess.SubprocessError):
        pass
    for nom in ("Desktop", "Bureau", "Escritorio", "Schreibtisch"):
        chemin = os.path.join(os.path.expanduser("~"), nom)
        if os.path.isdir(chemin):
            return chemin
    return None


def raccourci_existant():
    """
    Un raccourci vers CE dossier est-il déjà posé ? On lit les fichiers plutôt
    que de se fier à un nom : l'icône peut avoir été renommée, ou venir d'une
    version antérieure. Sinon on en empile un à chaque lancement.
    """
    endroits = [_dossier_bureau()]
    if not WINDOWS and not MACOS:
        endroits.append(os.path.join(os.path.expanduser("~"),
                                     ".local", "share", "applications"))
    marque = DOSSIER.lower()
    for endroit in endroits:
        if not endroit or not os.path.isdir(endroit):
            continue
        for nom in os.listdir(endroit):
            if not nom.lower().endswith((".desktop", ".lnk", ".command")):
                continue
            chemin = os.path.join(endroit, nom)
            if nom.lower().endswith(".lnk"):
                # Un .lnk est binaire : le chemin y figure en clair, en UTF-16
                # comme en ASCII selon les champs. On cherche les deux.
                try:
                    brut = open(chemin, "rb").read()
                except OSError:
                    continue
                for encodage in ("utf-16-le", "latin-1"):
                    if marque in brut.decode(encodage, "ignore").lower():
                        return chemin
                continue
            try:
                if marque in open(chemin, encoding="utf-8",
                                  errors="ignore").read().lower():
                    return chemin
            except OSError:
                continue
    return None


def installer_raccourci():
    """-> (ok, message). Ne lève jamais : une icône ratée n'empêche pas de lancer."""
    deja = raccourci_existant()
    if deja:
        return True, f"Raccourci déjà en place : {deja}"
    try:
        if WINDOWS:
            return _raccourci_windows()
        if MACOS:
            return _raccourci_macos()
        return _raccourci_linux()
    except Exception as e:                                    # noqa: BLE001
        return False, (f"Icône non posée ({type(e).__name__}). Ce n'est pas "
                       f"grave : l'assistant se lance depuis ce fichier.")


def _raccourci_linux():
    contenu = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NOM}\n"
        f"Comment={DESCRIPTION}\n"
        f"Exec={os.path.join(DOSSIER, 'lancer.sh')}\n"
        f"Path={DOSSIER}\n"
        "Icon=text-x-generic\n"
        "Terminal=true\n"
        "Categories=Office;Utility;\n")
    poses = []

    menu = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
    os.makedirs(menu, exist_ok=True)
    fichier_menu = os.path.join(menu, "assistant-syndical.desktop")
    with open(fichier_menu, "w", encoding="utf-8") as f:
        f.write(contenu)
    os.chmod(fichier_menu, 0o755)
    poses.append("menu des applications")

    bureau = _dossier_bureau()
    if bureau:
        fichier_bureau = os.path.join(bureau, f"{NOM}.desktop")
        with open(fichier_bureau, "w", encoding="utf-8") as f:
            f.write(contenu)
        os.chmod(fichier_bureau, 0o755)
        # GNOME n'exécute un lanceur que s'il est marqué « de confiance ».
        subprocess.run(["gio", "set", fichier_bureau, "metadata::trusted", "true"],
                       capture_output=True, timeout=5, check=False)
        poses.append("bureau")

    lanceur = os.path.join(DOSSIER, "lancer.sh")
    if os.path.isfile(lanceur):
        os.chmod(lanceur, 0o755)
    return True, "Icône posée : " + " et ".join(poses) + "."


def _raccourci_macos():
    bureau = _dossier_bureau()
    if not bureau:
        return False, "Bureau introuvable."
    fichier = os.path.join(bureau, f"{NOM}.command")
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/bash\ncd "{DOSSIER}"\nexec python3 demarrer.py\n')
    os.chmod(fichier, 0o755)
    return True, f"Icône posée sur le bureau : {fichier}"


def _raccourci_windows():
    """
    Crée un .lnk. Deux voies, parce que l'une ou l'autre peut être bloquée par
    une stratégie de sécurité : PowerShell d'abord, VBScript en secours.
    """
    bureau = _dossier_bureau()
    if not bureau:
        return False, "Bureau introuvable."
    lien = os.path.join(bureau, f"{NOM}.lnk")
    cible = os.path.join(DOSSIER, "Assistant-Syndical.bat")

    script_ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lien}');"
        "$s.TargetPath='{cible}';"
        "$s.WorkingDirectory='{dossier}';"
        "$s.Description='{desc}';"
        "$s.IconLocation='shell32.dll,13';"
        "$s.Save()").format(lien=lien, cible=cible, dossier=DOSSIER,
                            desc=DESCRIPTION)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script_ps], capture_output=True, timeout=30)
        if r.returncode == 0 and os.path.isfile(lien):
            return True, f"Icône posée sur le bureau : {lien}"
    except (OSError, subprocess.SubprocessError):
        pass

    script_vbs = (
        'Set s = CreateObject("WScript.Shell").CreateShortcut("{lien}")\r\n'
        's.TargetPath = "{cible}"\r\n'
        's.WorkingDirectory = "{dossier}"\r\n'
        's.Description = "{desc}"\r\n'
        's.IconLocation = "shell32.dll,13"\r\n'
        's.Save\r\n').format(lien=lien, cible=cible, dossier=DOSSIER,
                             desc=DESCRIPTION)
    chemin_vbs = os.path.join(tempfile.gettempdir(), "raccourci-assistant.vbs")
    try:
        with open(chemin_vbs, "w", encoding="utf-8") as f:
            f.write(script_vbs)
        subprocess.run(["cscript", "//nologo", chemin_vbs],
                       capture_output=True, timeout=30)
    finally:
        try:
            os.unlink(chemin_vbs)
        except OSError:
            pass
    if os.path.isfile(lien):
        return True, f"Icône posée sur le bureau : {lien}"
    return False, ("Icône non posée : la création de raccourcis est bloquée sur "
                   "ce poste. Lancer l'assistant par un double-clic sur "
                   "Assistant-Syndical.bat.")


# --- Lancement ---------------------------------------------------------------

def lancer():
    """Passe la main à serveur.py, dans ce processus : Ctrl+C arrête bien tout."""
    os.chdir(DOSSIER)
    sys.path.insert(0, DOSSIER)
    import serveur
    serveur.main()


def main():
    args = set(sys.argv[1:])

    if "--diagnostic" in args:
        titre(f"{NOM} — diagnostic")
        dire(f"  Système   : {SYSTEME} {platform.release()}")
        dire(f"  Python    : {platform.python_version()} ({sys.executable})")
        dire(f"  Dossier   : {DOSSIER}")
        dire(f"  Bureau    : {_dossier_bureau() or 'introuvable'}")
        dire(f"  Raccourci : {raccourci_existant() or 'aucun'}")
        dire(f"  pdftotext : {shutil.which('pdftotext') or 'absent'}")
        bloquants, avertissements = verifier()
        for m in bloquants:
            dire(f"  BLOQUANT  : {m}")
        for m in avertissements:
            dire(f"  a savoir  : {m}")
        if not bloquants:
            dire("  Tout est en place.")
        return 0 if not bloquants else 1

    bloquants, avertissements = verifier()
    if bloquants:
        titre(f"{NOM} — impossible de démarrer")
        for m in bloquants:
            dire(f"  - {m}")
        dire()
        if WINDOWS:
            input("  Appuyer sur Entrée pour fermer. ")
        return 1

    if "--icone" in args or "--sans-icone" not in args:
        ok, message = installer_raccourci()
        if "--icone" in args or not message.startswith("Raccourci déjà"):
            dire(f"  {message}")
        if "--icone" in args:
            return 0 if ok else 1

    for m in avertissements:
        dire(f"  A savoir : {m}")

    lancer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
