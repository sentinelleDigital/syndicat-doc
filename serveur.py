#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serveur.py — interface web locale de l'assistant syndical.

http://127.0.0.1:8765 — localhost UNIQUEMENT, rien n'est exposé sur le réseau.
Aucune ligne de commande n'est nécessaire : question, audit, gestion du corpus,
historique, réglages et banc de test se pilotent depuis la page.

    python3 serveur.py

L'interface est dans _templates/interface.html. Ce fichier ne contient que les
routes ; la logique métier est dans demande.py / corpus.py / recherche.py /
garde_fous.py. stdlib pure.
"""

import base64
import datetime
import json
import os
import re
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cles
import corpus
import ingestion
import demande as D
import garde_fous
import valider

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT_ASSISTANT", "8765"))
PORTS_SECOURS = 10       # si le port est pris, on essaie les suivants
PAGE_HTML = os.path.join(BASE, "_templates", "interface.html")
DOSSIER_HISTORIQUE = os.path.join(BASE, "_historique")
FICHIER_HISTORIQUE = os.path.join(DOSSIER_HISTORIQUE, "historique.jsonl")
TAILLE_MAX_ENVOI = 25 * 1024 * 1024      # 25 Mo : un PDF de CCN passe, pas plus


# --- Historique local --------------------------------------------------------

def historique_ajouter(entree):
    os.makedirs(DOSSIER_HISTORIQUE, exist_ok=True)
    entree = dict(entree)
    entree["horodatage"] = datetime.datetime.now().replace(
        microsecond=0).isoformat()
    with open(FICHIER_HISTORIQUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")


def historique_lire(limite=300):
    if not os.path.isfile(FICHIER_HISTORIQUE):
        return []
    out = []
    with open(FICHIER_HISTORIQUE, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne:
                try:
                    out.append(json.loads(ligne))
                except json.JSONDecodeError:
                    continue
    return out[-limite:][::-1]


def historique_markdown():
    lignes = ["# Historique des questions — assistant syndical", ""]
    for e in reversed(historique_lire(10000)):
        lignes += [f"## {e['horodatage']} — {e.get('mode', 'question')}", "",
                   f"**Question :** {e.get('question', '')}", "",
                   e.get("reponse", ""), ""]
        if e.get("alertes"):
            lignes.append("**Contrôles automatiques :**")
            for a in e["alertes"]:
                lignes.append(f"- {a['reference']} : {a['message']}")
            lignes.append("")
        if e.get("sources"):
            lignes.append("**Sources consultées :**")
            for s in e["sources"]:
                lignes.append(f"- {s}")
            lignes.append("")
        lignes.append("---")
        lignes.append("")
    return "\n".join(lignes)


# --- Serveur -----------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AssistantSyndical"

    # -- envoi --
    def _envoyer(self, code, ctype, corps):
        if isinstance(corps, str):
            corps = corps.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(corps)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, donnees, code=200):
        self._envoyer(code, "application/json; charset=utf-8",
                      json.dumps(donnees, ensure_ascii=False))

    def _ouvrir_flux(self):
        self.close_connection = True      # flux sans Content-Length
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def _evenement(self, nom, donnees):
        bloc = (f"event: {nom}\n"
                f"data: {json.dumps(donnees, ensure_ascii=False)}\n\n")
        try:
            self.wfile.write(bloc.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ValueError):
            return False

    def _corps_json(self):
        longueur = int(self.headers.get("Content-Length", 0))
        if longueur > TAILLE_MAX_ENVOI:
            raise ValueError("fichier trop volumineux (25 Mo maximum)")
        brut = self.rfile.read(longueur) if longueur else b"{}"
        try:
            return json.loads(brut or b"{}")
        except json.JSONDecodeError:
            raise ValueError("requête invalide")

    # -- GET --
    # -- Garde d'origine ------------------------------------------------------
    # Le serveur n'écoute que sur 127.0.0.1, mais « local » ne veut pas dire
    # « protégé » : n'importe quelle page ouverte dans le navigateur peut
    # adresser une requête à localhost. Sans ce contrôle, un site malveillant
    # pourrait écrire dans le corpus ou poser une clé API à l'insu de
    # l'utilisateur. Trois verrous :
    #   1. Host      — parade au DNS rebinding (un nom qui résout vers 127.0.0.1)
    #   2. Origin    — refus de toute origine autre que l'interface elle-même
    #   3. En-tête maison sur les POST — un formulaire HTML d'un autre site ne
    #      peut pas en poser un, et un fetch qui le pose déclenche un préflight
    #      que l'on ne satisfait jamais.

    HOTES_AUTORISES = {"127.0.0.1", "localhost", "[::1]"}

    def _origine_sure(self, exige_entete=False):
        hote = (self.headers.get("Host") or "").split(":")[0]
        if hote not in self.HOTES_AUTORISES:
            return False, f"Hôte refusé : {hote or '(absent)'}."

        origine = self.headers.get("Origin") or ""
        if origine:
            from urllib.parse import urlparse
            u = urlparse(origine)
            if u.scheme != "http" or u.hostname not in self.HOTES_AUTORISES:
                return False, "Requête refusée : origine externe."

        if exige_entete and self.headers.get("X-Assistant") != "1":
            return False, ("Requête refusée : en-tête d'application absent. "
                           "Recharger la page de l'assistant.")
        return True, ""

    def _garde(self, chemin, exige_entete=False):
        """True si la requête peut continuer ; sinon elle est déjà refusée."""
        if not chemin.startswith("/api/"):
            return True
        ok, motif = self._origine_sure(exige_entete)
        if not ok:
            self._json({"erreur": motif}, 403)
        return ok

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if not self._garde(chemin):
            return
        parametres = {}
        if "?" in self.path:
            from urllib.parse import parse_qs, unquote
            parametres = {k: unquote(v[0]) for k, v in
                          parse_qs(self.path.split("?", 1)[1]).items()}
        try:
            if chemin in ("/", ""):
                with open(PAGE_HTML, encoding="utf-8") as f:
                    self._envoyer(200, "text/html; charset=utf-8", f.read())
            elif chemin == "/api/etat":
                self._json(self._etat())
            elif chemin == "/api/corpus":
                self._json({"documents": corpus.documents(inclure_abroges=True),
                            "dossiers": corpus.dossiers_corpus(),
                            "statuts": list(corpus.STATUTS)})
            elif chemin == "/api/document":
                doc = corpus.lire_document(parametres.get("chemin", ""))
                if not doc:
                    self._json({"erreur": "document introuvable"}, 404)
                else:
                    self._json(doc)
            elif chemin == "/api/cles":
                self._json({"emplacements": cles.etat()})
            elif chemin == "/api/journal":
                self._json({"entrees": corpus.journal_lire(200)})
            elif chemin == "/api/historique":
                self._json({"entrees": historique_lire()})
            elif chemin == "/api/historique/export":
                self.send_response(200)
                corps = historique_markdown().encode("utf-8")
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="historique-assistant.md"')
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)
            else:
                self._envoyer(404, "text/plain; charset=utf-8", "introuvable")
        except Exception as e:                       # jamais de trace au client
            self._erreur_interne(e)

    # -- POST --
    def do_POST(self):
        chemin = self.path.split("?")[0]
        if not self._garde(chemin, exige_entete=True):
            return
        try:
            if chemin == "/api/ask":
                self._flux_reponse()
            elif chemin == "/api/banc":
                self._flux_banc()
            else:
                donnees = self._corps_json()
                routes = {
                    "/api/pdf": self._pdf_audit,
                    "/api/pdf-reponse": self._pdf_reponse,
                    "/api/conversion": self._conversion,
                    "/api/masquage": self._masquage,
                    "/api/document/ajouter": self._doc_ajouter,
                    "/api/document/enregistrer": self._doc_enregistrer,
                    "/api/document/apercu": self._doc_apercu,
                    "/api/document/archiver": self._doc_archiver,
                    "/api/journal/restaurer": self._journal_restaurer,
                    "/api/reglages": self._reglages,
                    "/api/cles": self._cles,
                }
                if chemin not in routes:
                    self._json({"erreur": "route inconnue"}, 404)
                else:
                    routes[chemin](donnees)
        except ValueError as e:
            self._json({"erreur": str(e)}, 400)
        except D.ErreurAssistant as e:
            self._json({"erreur": str(e)}, 200)
        except Exception as e:
            self._erreur_interne(e)

    def _erreur_interne(self, e):
        traceback.print_exc()          # trace côté terminal, pour diagnostic
        try:
            self._json({"erreur": "Erreur interne de l'assistant : "
                                  f"{type(e).__name__}. Le détail technique est "
                                  "dans la fenêtre du terminal."}, 200)
        except Exception:
            pass

    # -- état --
    def _etat(self):
        reglages = D.lire_reglages()
        cle = D.cle_api()
        docs = corpus.documents()
        return {
            "cle_presente": bool(cle),
            "message_cle": "" if cle else
                "Clé API absente. Ouvrir le fichier .env à la racine du dossier "
                "et y écrire GEMINI_API_KEY=votre_clé (clé gratuite sur "
                "https://aistudio.google.com/apikey), puis relancer.",
            "modeles": D.MODELES, "reglages": reglages,
            "dossiers": corpus.dossiers_corpus(),
            "dossiers_nominatifs": sorted(corpus.DOSSIERS_NOMINATIFS),
            "statuts": list(corpus.STATUTS),
            "libelles_statut": corpus.LIBELLE_STATUT,
            "champs_obligatoires": list(corpus.CHAMPS_OBLIGATOIRES),
            "champs_legal": list(corpus.CHAMPS_LEGAL),
            "dossier_legal": corpus.DOSSIER_LEGAL,
            "nb_documents": len(docs),
            "nb_projets": len([d for d in docs if d["statut"] == "projet"]),
            "nb_perimes": len([d for d in docs if d["perime"]]),
            "nb_incomplets": len([d for d in docs if d["champs_manquants"]]),
        }

    # -- question / audit en flux --
    def _flux_reponse(self):
        donnees = self._corps_json()
        question = (donnees.get("question") or "").strip()
        mode = "audit" if donnees.get("mode") == "audit" else "question"
        doc_texte = donnees.get("docTexte") or None
        doc_nom = donnees.get("docNom") or None
        if not question:
            self._json({"erreur": "question vide"}, 400)
            return
        self._ouvrir_flux()

        bloque, _, motif = garde_fous.question_individuelle(question)
        if bloque:
            self._evenement("bloque", {
                "reponse": garde_fous.RENVOI_JURISTE,
                "alertes": [{"niveau": "alerte", "reference": "cas individuel",
                             "message": f"Question individuelle détectée "
                                        f"({motif}). Aucun appel au modèle "
                                        f"n'a été fait."}]})
            historique_ajouter({"mode": mode, "question": question,
                                "reponse": garde_fous.RENVOI_JURISTE,
                                "modele": None, "bloque": True,
                                "alertes": [], "sources": []})
            self._evenement("fin", {})
            return

        try:
            prep = D.preparer(question, mode, doc_texte, doc_nom)
        except Exception as e:
            self._evenement("erreur", {"message": f"Préparation impossible : {e}"})
            return
        modele = donnees.get("modele") or prep["modele"]
        self._evenement("sources", {
            "passages": [{"fichier": p["fichier"], "titre": p["titre"],
                          "motif": p["motif"], "tronque": p["tronque"],
                          "taille": len(p["texte"])} for p in prep["passages"]],
            "modele": modele,
            "octets_envoyes": len(prep["contexte"])})

        morceaux = []
        try:
            for bout in D.call_gemini_flux(D.cle_api(), modele, prep["systeme"],
                                           prep["contexte"], prep["max_tokens"],
                                           prep["temperature"]):
                morceaux.append(bout)
                if not self._evenement("texte", {"t": bout}):
                    return                      # le navigateur est parti
        except D.ErreurAssistant as e:
            self._evenement("erreur", {"message": str(e)})
            return
        except Exception as e:
            traceback.print_exc()
            self._evenement("erreur", {
                "message": "Erreur pendant la génération : "
                           f"{type(e).__name__}. Détail dans le terminal."})
            return

        reponse = "".join(morceaux)
        alertes = D.controler(reponse, prep["contexte"], prep["passages"], question)
        self._evenement("alertes", {"alertes": alertes})
        historique_ajouter({
            "mode": mode, "question": question, "reponse": reponse,
            "modele": modele, "bloque": False, "alertes": alertes,
            "sources": [f"{p['fichier']} § {p['titre']}"
                        for p in prep["passages"]]})
        self._evenement("fin", {})

    # -- banc de test en flux --
    def _flux_banc(self):
        donnees = self._corps_json()
        modele = donnees.get("modele") or D.lire_reglages()["modele_question"]
        pause = float(donnees.get("pause") or 0)
        self._ouvrir_flux()
        vivant = [True]

        def avance(i, total, cas, entree):
            if not self._evenement("question", {
                    "i": i, "total": total, "id": cas["id"],
                    "question": cas["question"], "conforme": entree["conforme"],
                    "ecarts": entree["ecarts"]}):
                vivant[0] = False

        try:
            rapport = valider.executer(modele, None, pause, avance)
        except Exception as e:
            traceback.print_exc()
            self._evenement("erreur", {"message": f"Banc interrompu : {e}"})
            return
        # Le rapport est écrit MÊME si le navigateur s'est déconnecté : le banc
        # consomme du quota, on ne jette pas une mesure déjà payée.
        valider.ecrire_rapport_json(rapport)
        valider.ecrire_validation_md(
            [rapport] + valider._rapports_existants(exclure=[rapport["modele"]]))
        if vivant[0]:
            self._evenement("fin", {"resume": valider.resume_texte(rapport),
                                    "rapport": rapport})

    # -- PDF --
    def _pdf_audit(self, donnees):
        question = (donnees.get("question") or "").strip()
        if not question:
            raise ValueError("consigne d'audit vide")
        comble = D.completer_corpus(question, donnees.get("docTexte") or "",
                                    "audit web")
        prep = D.preparer(question, "audit", donnees.get("docTexte"),
                          donnees.get("docNom"))
        corps = D.call_gemini(D.cle_api(), prep["modele"], D.SYSTEM_AUDIT_HTML,
                              prep["contexte"], prep["max_tokens"],
                              prep["temperature"])
        corps = re.sub(r"^```html\s*|\s*```$", "", corps.strip())
        alertes = D.controler(corps, prep["contexte"], prep["passages"], question)
        html = D.wrap_html(D.sources.bloc_manques_html(comble) + corps
                           + D.bloc_alertes_html(alertes)
                           + D.bloc_sources_html(prep["passages"]),
                           title=f"Rapport d'audit — {question[:60]}")
        self._envoyer(200, "text/html; charset=utf-8", html)

    def _pdf_reponse(self, donnees):
        """Export d'une réponse simple déjà obtenue — aucun nouvel appel."""
        question = (donnees.get("question") or "").strip()
        reponse = donnees.get("reponse") or ""
        if not reponse:
            raise ValueError("aucune réponse à exporter")
        corps = ("<h2>Question</h2><p>" + D._echapper(question) + "</p>"
                 "<h2>Réponse</h2>" + _markdown_html(reponse)
                 + D.bloc_alertes_html(donnees.get("alertes") or [])
                 + _sources_html(donnees.get("sources") or []))
        html = D.wrap_html(corps, title=f"Réponse — {question[:60]}",
                           style_file=D.STYLE_FILE, couverture=False)
        self._envoyer(200, "text/html; charset=utf-8", html)

    # -- corpus --
    def _conversion(self, donnees):
        """Fichier déposé -> markdown proposé, TOUJOURS soumis à validation."""
        nom = donnees.get("nom") or "document"
        try:
            octets = base64.b64decode(donnees.get("contenu") or "")
        except (ValueError, TypeError):
            raise ValueError("fichier illisible")
        try:
            res = ingestion.extraire(nom, octets)
        except ingestion.Refus as e:
            self._json({"texte": "", "refuse": True, "avertissement": str(e),
                        "original": "", "caracteres": 0})
            return

        bloquants = [m for n, m in res["anomalies"] if n == "bloquant"]
        signalements = [m for n, m in res["anomalies"] if n != "bloquant"]
        if res["couverture"] < ingestion.SEUIL_COUVERTURE:
            bloquants.append(
                f"Couverture {res['couverture'] * 100:.2f} % : les deux "
                f"extractions ne voient pas le même texte, du contenu est perdu.")
        if res["ordre"] < ingestion.SEUIL_ORDRE:
            signalements.append(
                f"Ordre de lecture incertain ({res['ordre'] * 100:.1f} %) : "
                f"colonnes ou encarts. Le texte est complet, son enchaînement "
                f"est à vérifier.")

        source = ""
        if octets and not nom.lower().endswith((".md", ".txt", ".text")):
            source = corpus.sauvegarder_source(nom, octets)
        self._json({
            "texte": "" if bloquants else res["texte"],
            "refuse": bool(bloquants),
            "avertissement": " ".join(bloquants + signalements + res["notes"]),
            "extraction": res["methode"],
            "couverture": round(res["couverture"] * 100, 2),
            "ordre": round(res["ordre"] * 100, 1),
            "original": source,
            "caracteres": 0 if bloquants else len(res["texte"])})

    def _masquage(self, donnees):
        texte = donnees.get("texte") or ""
        masque, trouvailles = garde_fous.masquer_donnees_personnelles(texte)
        self._json({"texte": masque, "trouvailles": trouvailles})

    def _doc_apercu(self, donnees):
        """Diff avant enregistrement : on voit ce qu'on change."""
        rel = donnees.get("chemin") or ""
        doc = corpus.lire_document(rel)
        if not doc:
            raise ValueError("document introuvable")
        avant = corpus.ecrire_front_matter(doc["meta"], doc["corps"])
        meta = dict(doc["meta"])
        meta.update(donnees.get("meta") or {})
        apres = corpus.ecrire_front_matter(meta, donnees.get("corps") or "")
        self._json({"diff": corpus.diff_texte(avant, apres, rel + " (actuel)",
                                              rel + " (proposé)"),
                    "resume": corpus.resume_diff(avant, apres)})

    def _doc_ajouter(self, donnees):
        ok, message = corpus.ajouter_document(
            donnees.get("dossier") or "", donnees.get("nom") or "",
            donnees.get("meta") or {}, donnees.get("corps") or "",
            "interface")
        self._json({"ok": ok, "message": message})

    def _doc_enregistrer(self, donnees):
        doc = corpus.lire_document(donnees.get("chemin") or "")
        if not doc:
            raise ValueError("document introuvable")
        meta = dict(doc["meta"])
        meta.update(donnees.get("meta") or {})
        ok, message = corpus.enregistrer_document(
            donnees["chemin"], meta, donnees.get("corps") or "", "interface")
        self._json({"ok": ok, "message": message})

    def _doc_archiver(self, donnees):
        if not donnees.get("confirmation"):
            raise ValueError("archivage non confirmé")
        ok, message = corpus.archiver_document(
            donnees.get("chemin") or "", donnees.get("remplacePar") or "",
            "interface")
        self._json({"ok": ok, "message": message})

    def _journal_restaurer(self, donnees):
        ok, message = corpus.restaurer(donnees.get("id") or "", "interface")
        self._json({"ok": ok, "message": message})

    def _cles(self, donnees):
        """
        Pose, retire ou teste une clé. Ne renvoie JAMAIS une valeur enregistrée.
        Les exceptions sont attrapées ici : une trace remontant au gestionnaire
        générique pourrait faire apparaître la valeur soumise dans le terminal.
        """
        action = (donnees.get("action") or "enregistrer").strip()
        identifiant = (donnees.get("cle") or "").strip()
        try:
            if action == "enregistrer":
                message = cles.enregistrer(identifiant, donnees.get("valeur"))
                self._json({"ok": True, "message": message,
                            "emplacements": cles.etat()})
            elif action == "supprimer":
                message = cles.supprimer(identifiant)
                self._json({"ok": True, "message": message,
                            "emplacements": cles.etat()})
            elif action == "tester":
                ok, message = cles.tester(identifiant)
                self._json({"ok": ok, "message": message,
                            "emplacements": cles.etat()})
            else:
                self._json({"ok": False, "message": "Action inconnue."}, 400)
        except cles.CleRefusee as e:
            self._json({"ok": False, "message": str(e)}, 200)
        except Exception as e:                       # jamais la valeur soumise
            self._json({"ok": False,
                        "message": f"Échec de l'enregistrement "
                                   f"({type(e).__name__}). Vérifier les droits "
                                   f"d'écriture sur le fichier .env."}, 200)

    def _reglages(self, donnees):
        self._json({"ok": True, "reglages": D.ecrire_reglages(donnees)})

    def log_message(self, fmt, *args):
        sys.stderr.write("· %s\n" % (fmt % args))


# --- Rendu markdown minimal pour l'export PDF d'une réponse ------------------

def _markdown_html(texte):
    lignes, html, i = texte.split("\n"), [], 0
    while i < len(lignes):
        ligne = lignes[i]
        if re.match(r"^\s*\|.*\|\s*$", ligne):
            rangs = []
            while i < len(lignes) and re.match(r"^\s*\|.*\|\s*$", lignes[i]):
                if not re.match(r"^\s*\|[\s:|-]+\|\s*$", lignes[i]):
                    rangs.append(lignes[i])
                i += 1
            html.append("<table>")
            for n, rang in enumerate(rangs):
                cellules = [c.strip() for c in
                            rang.strip().strip("|").split("|")]
                balise = "th" if n == 0 else "td"
                html.append("<tr>" + "".join(
                    f"<{balise}>{_inline(c)}</{balise}>" for c in cellules)
                    + "</tr>")
            html.append("</table>")
            continue
        if re.match(r"^\s*#{2,}\s+", ligne):
            html.append("<h3>" + _inline(re.sub(r"^\s*#+\s+", "", ligne))
                        + "</h3>")
        elif re.match(r"^\s*#\s+", ligne):
            html.append("<h2>" + _inline(re.sub(r"^\s*#\s+", "", ligne))
                        + "</h2>")
        elif re.match(r"^\s*[-*]\s+", ligne):
            html.append("<ul>")
            while i < len(lignes) and re.match(r"^\s*[-*]\s+", lignes[i]):
                html.append("<li>" + _inline(
                    re.sub(r"^\s*[-*]\s+", "", lignes[i])) + "</li>")
                i += 1
            html.append("</ul>")
            continue
        elif ligne.strip():
            html.append(f"<p>{_inline(ligne)}</p>")
        i += 1
    return "".join(html)


def _inline(s):
    s = D._echapper(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]", r'<span class="ref">[\1]</span>', s)
    return s


def _sources_html(sources):
    if not sources:
        return ""
    return ("<h2>Sources consultées</h2><ul>"
            + "".join(f"<li>{D._echapper(s)}</li>" for s in sources) + "</ul>")


def main():
    cle = D.cle_api()
    if not cle:
        print("⚠  Clé API absente : l'interface démarre quand même et affiche\n"
              "   la marche à suivre. Pour répondre aux questions, mettre\n"
              "   GEMINI_API_KEY=… dans le fichier .env (clé gratuite :\n"
              "   https://aistudio.google.com/apikey).\n", flush=True)
    if not os.path.isfile(PAGE_HTML):
        sys.exit(f"Interface introuvable : {PAGE_HTML}")
    srv, port = None, None
    for essai in range(PORTS_SECOURS):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PORT + essai), Handler)
            port = PORT + essai
            break
        except OSError:
            continue          # port occupé (souvent une autre application)
    if srv is None:
        sys.exit(f"Aucun port libre entre {PORT} et {PORT + PORTS_SECOURS - 1}.\n"
                 f"Une copie de l'assistant tourne peut-être déjà : fermer sa "
                 f"fenêtre, puis relancer.")
    if port != PORT:
        print(f"(le port {PORT} est occupé par une autre application — "
              f"l'assistant utilise le port {port})", flush=True)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Assistant Syndical ouvert sur {url}\n"
          f"(laisser cette fenêtre ouverte ; Ctrl+C pour arrêter)", flush=True)
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêté.")


if __name__ == "__main__":
    main()
