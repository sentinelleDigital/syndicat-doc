#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serveur.py — interface web locale de l'assistant syndical.

Lance un petit serveur sur http://127.0.0.1:8765 (localhost UNIQUEMENT — rien
n'est exposé sur le réseau) et ouvre le navigateur. L'élu tape sa question dans
une page épurée : aucune ligne de commande.

Réutilise le moteur demande.py (mêmes 2 modes + rapport PDF). stdlib pure.

    python3 serveur.py
"""

import importlib.util
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765

# Import du moteur demande.py comme module (pas de duplication de logique)
_spec = importlib.util.spec_from_file_location("demande", os.path.join(BASE, "demande.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

D.load_env(os.path.join(BASE, ".env"))
API_KEY = os.environ.get("GEMINI_API_KEY")


def build_context(question, doc_text=None, doc_name=None, audit=False):
    index = D.read_file(D.INDEX_FILE)
    whole = D.load_whole()
    filtered = D.load_filtered(question)
    if audit:
        docs = f"===== DOCUMENT AUDITÉ: {doc_name} =====\n{doc_text}" if doc_text \
            else "(aucun document joint — audit sur le corpus général)"
        return (f"INDEX DU CORPUS :\n{index}\n\nDOCUMENT(S) À AUDITER :\n{docs}\n\n"
                f"CODE DU TRAVAIL (extraits vérifiés) :\n{whole}\n\n{filtered}\n\n"
                f"CONSIGNE D'AUDIT :\n{question}\n")
    return (f"INDEX DU CORPUS :\n{index}\n\nDOCUMENTS — CODE DU TRAVAIL (extraits vérifiés) :\n"
            f"{whole}\n\n{filtered}\n\nQUESTION DU SALARIÉ / DE L'ÉLU :\n{question}\n")


PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assistant Syndical</title>
<style>
  :root{
    --bg:#f5f5f7; --panel:#ffffff; --ink:#1d1d1f; --muted:#6e6e73;
    --line:#d2d2d7; --accent:#0071e3; --accent-ink:#fff;
    --ref-bg:#eef4ff; --ref-ink:#0058b0; --shadow:0 4px 24px rgba(0,0,0,.06);
  }
  @media (prefers-color-scheme: dark){
    :root{--bg:#000; --panel:#1c1c1e; --ink:#f5f5f7; --muted:#98989d;
      --line:#38383a; --accent:#0a84ff; --ref-bg:#0a2540; --ref-ink:#7fb4ff;
      --shadow:0 4px 24px rgba(0,0,0,.5);}
  }
  *{box-sizing:border-box}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased; line-height:1.5;
  }
  .wrap{max-width:760px; margin:0 auto; padding:48px 24px 80px}
  header{text-align:center; margin-bottom:32px}
  header h1{font-size:2rem; font-weight:600; letter-spacing:-.02em; margin:0}
  header p{color:var(--muted); margin:.4rem 0 0; font-size:.95rem}

  .seg{display:inline-flex; background:var(--line); border-radius:10px; padding:3px; margin:0 auto 18px; gap:2px}
  .seg button{border:0; background:transparent; color:var(--ink); font:inherit; font-size:.9rem;
    padding:7px 20px; border-radius:8px; cursor:pointer; transition:.15s}
  .seg button.on{background:var(--panel); box-shadow:0 1px 3px rgba(0,0,0,.12); font-weight:600}
  .segwrap{text-align:center}

  .card{background:var(--panel); border-radius:18px; box-shadow:var(--shadow); padding:22px; border:1px solid var(--line)}
  textarea{width:100%; border:0; outline:0; resize:vertical; min-height:84px; background:transparent;
    color:var(--ink); font:inherit; font-size:1.05rem}
  textarea::placeholder{color:var(--muted)}
  .row{display:flex; align-items:center; gap:12px; margin-top:14px; flex-wrap:wrap}
  .file{flex:1; min-width:180px; font-size:.85rem; color:var(--muted)}
  .file input{font:inherit; font-size:.8rem}
  button.go{margin-left:auto; background:var(--accent); color:var(--accent-ink); border:0; font:inherit;
    font-weight:600; font-size:.95rem; padding:11px 24px; border-radius:980px; cursor:pointer; transition:.15s}
  button.go:hover{filter:brightness(1.05)}
  button.go:disabled{opacity:.5; cursor:default}

  .hidden{display:none}
  .answer{margin-top:26px}
  .answer .box{background:var(--panel); border:1px solid var(--line); border-radius:18px;
    box-shadow:var(--shadow); padding:24px 26px}
  .answer h2{font-size:1.05rem; margin:1.2em 0 .5em; color:var(--ink)}
  .answer h3{font-size:.98rem; margin:1em 0 .4em}
  .answer p{margin:.5em 0}
  .answer ul{padding-left:1.2em; margin:.5em 0}
  .answer li{margin:.25em 0}
  .answer table{width:100%; border-collapse:collapse; font-size:.85rem; margin:.6em 0; overflow-x:auto; display:block}
  .answer th,.answer td{border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top}
  .answer th{background:var(--ref-bg)}
  .ref{background:var(--ref-bg); color:var(--ref-ink); border-radius:6px; padding:1px 7px;
    font-size:.82em; font-weight:600; white-space:nowrap}
  .pdfbtn{margin-top:16px; background:transparent; color:var(--accent); border:1px solid var(--accent);
    font:inherit; font-weight:600; padding:9px 18px; border-radius:980px; cursor:pointer}
  .muted{color:var(--muted); font-size:.85rem; text-align:center; margin-top:28px}
  .spinner{width:22px;height:22px;border:3px solid var(--line);border-top-color:var(--accent);
    border-radius:50%;animation:spin .8s linear infinite;margin:8px auto}
  @keyframes spin{to{transform:rotate(360deg)}}
  .err{color:#c62828}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Assistant Syndical</h1>
    <p>CCN 3029 · Code du travail — réponses citées, jamais inventées</p>
  </header>

  <div class="segwrap">
    <div class="seg">
      <button id="m-question" class="on" onclick="setMode('question')">Question</button>
      <button id="m-audit" onclick="setMode('audit')">Audit</button>
    </div>
  </div>

  <div class="card">
    <textarea id="q" placeholder="Posez votre question… (ex : combien de repos entre deux journées de travail ?)"></textarea>
    <div class="row">
      <label id="filewrap" class="file hidden">Document à auditer (optionnel) :
        <input type="file" id="doc" accept=".md,.txt,.text">
      </label>
      <button class="go" id="go" onclick="ask()">Demander</button>
    </div>
  </div>

  <div id="answer" class="answer hidden">
    <div class="box" id="answerBox"></div>
    <button class="pdfbtn hidden" id="pdfbtn" onclick="makePdf()">Générer le rapport PDF</button>
  </div>

  <p class="muted">Local et privé · le corpus reste sur cette machine.<br>
  Ne remplace pas un juriste — ne qualifie jamais un cas individuel.</p>
</div>

<script>
let MODE = "question";
let lastQuestion = "", lastDoc = null;

function setMode(m){
  MODE = m;
  document.getElementById("m-question").classList.toggle("on", m==="question");
  document.getElementById("m-audit").classList.toggle("on", m==="audit");
  document.getElementById("filewrap").classList.toggle("hidden", m!=="audit");
  document.getElementById("go").textContent = m==="audit" ? "Lancer l'audit" : "Demander";
  document.getElementById("q").placeholder = m==="audit"
    ? "Consigne d'audit… (ex : cet accord respecte-t-il le forfait jours ?)"
    : "Posez votre question…";
}

function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}

// petit rendu markdown -> HTML (titres, gras, listes, tableaux, citations)
function md(t){
  t = esc(t);
  t = t.replace(/\[([^\]]*?(?:L\.?\s?\d|art\.|CCN|C\. trav\.|\.md)[^\]]*?)\]/g,
      '<span class="ref">[$1]</span>');
  const lines = t.split(/\r?\n/);
  let html="", i=0;
  while(i<lines.length){
    let ln = lines[i];
    if(/^\s*\|.*\|\s*$/.test(ln)){                 // table
      let rows=[];
      while(i<lines.length && /^\s*\|.*\|\s*$/.test(lines[i])){ rows.push(lines[i]); i++; }
      rows = rows.filter(r=>!/^\s*\|[\s:|-]+\|\s*$/.test(r));
      html+="<table>";
      rows.forEach((r,ri)=>{
        const cells=r.trim().replace(/^\||\|$/g,"").split("|").map(c=>c.trim());
        const tag = ri===0?"th":"td";
        html+="<tr>"+cells.map(c=>`<${tag}>${inline(c)}</${tag}>`).join("")+"</tr>";
      });
      html+="</table>"; continue;
    }
    if(/^\s*#{2,3}\s+/.test(ln)){ html+=`<h3>${inline(ln.replace(/^\s*#+\s+/,""))}</h3>`; i++; continue; }
    if(/^\s*#\s+/.test(ln)){ html+=`<h2>${inline(ln.replace(/^\s*#\s+/,""))}</h2>`; i++; continue; }
    if(/^\s*[-*]\s+/.test(ln)){
      html+="<ul>";
      while(i<lines.length && /^\s*[-*]\s+/.test(lines[i])){ html+=`<li>${inline(lines[i].replace(/^\s*[-*]\s+/,""))}</li>`; i++; }
      html+="</ul>"; continue;
    }
    if(ln.trim()===""){ i++; continue; }
    html+=`<p>${inline(ln)}</p>`; i++;
  }
  return html;
}
function inline(s){
  return s.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>")
          .replace(/\*([^*]+)\*/g,"<em>$1</em>");
}

async function readDoc(){
  const f = document.getElementById("doc").files[0];
  if(!f) return null;
  const text = await f.text();
  return {name:f.name, text};
}

async function ask(){
  const q = document.getElementById("q").value.trim();
  if(!q) return;
  const go = document.getElementById("go"); go.disabled=true;
  const ans = document.getElementById("answer"); ans.classList.remove("hidden");
  const box = document.getElementById("answerBox");
  document.getElementById("pdfbtn").classList.add("hidden");
  box.innerHTML = '<div class="spinner"></div>';
  lastQuestion=q; lastDoc = MODE==="audit" ? await readDoc() : null;
  try{
    const r = await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question:q, mode:MODE,
        docText:lastDoc?lastDoc.text:null, docName:lastDoc?lastDoc.name:null})});
    const j = await r.json();
    if(j.error){ box.innerHTML = '<p class="err">'+esc(j.error)+'</p>'; }
    else{
      box.innerHTML = md(j.answer);
      if(MODE==="audit") document.getElementById("pdfbtn").classList.remove("hidden");
    }
  }catch(e){ box.innerHTML='<p class="err">Erreur : '+esc(""+e)+'</p>'; }
  go.disabled=false;
}

async function makePdf(){
  const btn=document.getElementById("pdfbtn"); btn.disabled=true; btn.textContent="Génération…";
  try{
    const r = await fetch("/api/pdf",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question:lastQuestion,
        docText:lastDoc?lastDoc.text:null, docName:lastDoc?lastDoc.name:null})});
    const html = await r.text();
    const w = window.open("","_blank");
    w.document.write(html); w.document.close();
    setTimeout(()=>w.print(), 600);
  }catch(e){ alert("Erreur PDF : "+e); }
  btn.disabled=false; btn.textContent="Générer le rapport PDF";
}

document.getElementById("q").addEventListener("keydown",e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==="Enter") ask();
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "") or self.path.startswith("/?"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"introuvable")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, "application/json", b'{"error":"requete invalide"}')
            return
        q = (data.get("question") or "").strip()
        if not q:
            self._send(400, "application/json", json.dumps({"error": "question vide"}).encode())
            return
        doc_text = data.get("docText")
        doc_name = data.get("docName")
        try:
            if self.path == "/api/ask":
                if data.get("mode") == "audit":
                    ctx = build_context(q, doc_text, doc_name, audit=True)
                    ans = D.call_gemini(API_KEY, D.MODEL_AUDIT, D.SYSTEM_AUDIT, ctx, 8192)
                else:
                    ctx = build_context(q, audit=False)
                    ans = D.call_gemini(API_KEY, D.MODEL_QUESTION, D.SYSTEM_QUESTION, ctx, 2048)
                self._send(200, "application/json", json.dumps({"answer": ans}).encode("utf-8"))
            elif self.path == "/api/pdf":
                ctx = build_context(q, doc_text, doc_name, audit=True)
                body = D.call_gemini(API_KEY, D.MODEL_AUDIT, D.SYSTEM_AUDIT_HTML, ctx, 8192)
                body = re.sub(r"^```html\s*|\s*```$", "", body.strip())
                html = D.wrap_html(body, title=f"Rapport d'audit — {q[:60]}")
                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
            else:
                self._send(404, "application/json", b'{"error":"route inconnue"}')
        except (SystemExit, Exception) as e:  # ne JAMAIS laisser le thread planter
            import traceback
            traceback.print_exc()  # visible dans le terminal pour diagnostic
            msg = str(e) or f"{type(e).__name__}"
            try:
                self._send(200, "application/json", json.dumps({"error": msg}).encode("utf-8"))
            except Exception:
                pass  # client déjà parti

    def log_message(self, fmt, *args):  # une ligne discrète par requête
        sys.stderr.write("· %s\n" % (fmt % args))


def main():
    if not API_KEY:
        sys.exit("GEMINI_API_KEY absent. Mets-le dans .env (voir .env.example).")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Assistant Syndical ouvert sur {url}\n(laisse cette fenêtre ouverte ; Ctrl+C pour arrêter)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêté.")


if __name__ == "__main__":
    main()
