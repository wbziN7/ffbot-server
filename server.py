# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request, render_template_string
import sqlite3
import secrets
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# =====================================================
# CONFIG
# =====================================================
DB_NAME = "licencas.db"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wb03122008!")
REQUEST_TIMEOUT = 10  # reservado caso você use requests no futuro

# =====================================================
# DB
# =====================================================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        tipo TEXT NOT NULL,
        dias INTEGER NOT NULL,
        ativada INTEGER DEFAULT 0,
        hwid TEXT,
        data_ativacao TEXT,
        data_expiracao TEXT,
        data_criacao TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hwid TEXT,
        acao TEXT,
        data TEXT,
        detalhes TEXT
    )
    """)

    conn.commit()
    conn.close()


def gerar_key_unica():
    return secrets.token_hex(16).upper()


def calcular_expiracao(dias: int):
    if dias == -1:
        return "PERMANENTE"
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")


def verificar_expiracao(data_expiracao: str):
    if data_expiracao == "PERMANENTE":
        return False
    data_exp = datetime.strptime(data_expiracao, "%Y-%m-%d %H:%M:%S")
    return datetime.now() > data_exp


def registrar_log(hwid, acao, detalhes=""):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO logs (hwid, acao, data, detalhes) VALUES (?, ?, ?, ?)",
            (hwid, acao, data, detalhes),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# =====================================================
# ROTAS
# =====================================================

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "sistema": "Licencas - Free Fire Bot",
        "rotas": {
            "POST /gerar-key": "Gera key (admin)",
            "POST /ativar-key": "Ativa key no HWID",
            "POST /validar-licenca": "Valida licenca por HWID",
            "GET  /admin": "Painel admin",
            "POST /stats": "Stats (admin)"
        }
    })


@app.route("/gerar-key", methods=["POST"])
def gerar_key():
    data = request.get_json(silent=True) or {}
    senha = data.get("senha")
    tipo = data.get("tipo", "1d")
    quantidade = int(data.get("quantidade", 1))

    if senha != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Senha incorreta"}), 401

    tipos_dias = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "perm": -1}
    if tipo not in tipos_dias:
        return jsonify({"success": False, "error": "Tipo invalido"}), 400

    dias = tipos_dias[tipo]
    quantidade = max(1, min(quantidade, 100))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    keys_geradas = []
    for _ in range(quantidade):
        k = gerar_key_unica()
        data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO keys (key, tipo, dias, data_criacao) VALUES (?, ?, ?, ?)",
            (k, tipo, dias, data_criacao),
        )
        keys_geradas.append(k)

    conn.commit()
    conn.close()

    return jsonify({"success": True, "tipo": tipo, "quantidade": len(keys_geradas), "keys": keys_geradas})


@app.route("/ativar-key", methods=["POST"])
def ativar_key():
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").upper().strip()
    hwid = (data.get("hwid") or "").strip()

    if not key or not hwid:
        return jsonify({"success": False, "error": "Key e HWID sao obrigatorios"}), 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT * FROM keys WHERE key = ?", (key,))
    row = c.fetchone()

    if not row:
        conn.close()
        return jsonify({"success": False, "error": "Key nao encontrada"}), 404

    key_db, tipo, dias, ativada, hwid_db, data_ativ, data_exp, data_cria = row

    if ativada == 1:
        conn.close()
        return jsonify({"success": False, "error": "Key ja foi ativada em outro PC"}), 403

    data_ativacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_expiracao = calcular_expiracao(dias)

    c.execute(
        "UPDATE keys SET ativada = 1, hwid = ?, data_ativacao = ?, data_expiracao = ? WHERE key = ?",
        (hwid, data_ativacao, data_expiracao, key),
    )

    conn.commit()
    conn.close()

    registrar_log(hwid, "KEY_ATIVADA", f"Tipo: {tipo}")

    return jsonify({
        "success": True,
        "message": "Key ativada com sucesso!",
        "tipo": tipo,
        "data_expiracao": data_expiracao
    })


@app.route("/validar-licenca", methods=["POST"])
def validar_licenca():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()

    if not hwid:
        return jsonify({"success": False, "error": "HWID e obrigatorio"}), 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE hwid = ? AND ativada = 1", (hwid,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "valida": False, "error": "Nenhuma licenca encontrada"}), 404

    _key_db, tipo, _dias, _ativada, _hwid_db, _data_ativ, data_exp, _data_cria = row

    if verificar_expiracao(data_exp):
        return jsonify({"success": True, "valida": False, "error": "Licenca expirada", "data_expiracao": data_exp})

    return jsonify({"success": True, "valida": True, "tipo": tipo, "data_expiracao": data_exp})


@app.route("/stats", methods=["POST"])
def stats():
    data = request.get_json(silent=True) or {}
    senha = data.get("senha")

    if senha != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Senha incorreta"}), 401

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM keys")
    total_keys = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM keys WHERE ativada = 1")
    keys_ativas = c.fetchone()[0]

    c.execute("SELECT * FROM logs ORDER BY data DESC LIMIT 50")
    logs_raw = c.fetchall()

    conn.close()

    logs = [{
        "id": r[0],
        "hwid": (r[1][:16] + "...") if r[1] else "N/A",
        "acao": r[2],
        "data": r[3],
        "detalhes": r[4]
    } for r in logs_raw]

    return jsonify({
        "success": True,
        "stats": {
            "total_keys": total_keys,
            "keys_ativas": keys_ativas,
            "keys_pendentes": total_keys - keys_ativas
        },
        "logs": logs
    })


@app.route("/admin")
def admin_panel():
    # Painel simples, funcional. Sem frescura.
    html = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Painel Admin</title>
  <style>
    body{font-family:Arial;background:#111;color:#eee;padding:20px}
    .box{max-width:900px;margin:auto;background:#1c1c1c;padding:20px;border-radius:12px}
    input,select,button{width:100%;padding:12px;margin:8px 0;border-radius:8px;border:1px solid #333;background:#0f0f0f;color:#eee}
    button{background:#6b5cff;border:0;font-weight:bold;cursor:pointer}
    pre{background:#0a0a0a;padding:12px;border-radius:8px;overflow:auto}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    @media(max-width:800px){.row{grid-template-columns:1fr}}
  </style>
</head>
<body>
<div class="box">
  <h2>Painel Admin</h2>
  <p>Gera keys e ve stats.</p>

  <h3>Gerar Keys</h3>
  <input id="senha" type="password" placeholder="Senha admin"/>
  <div class="row">
    <select id="tipo">
      <option value="1d">1d (teste)</option>
      <option value="7d">7d</option>
      <option value="30d" selected>30d</option>
      <option value="90d">90d</option>
      <option value="perm">perm</option>
    </select>
    <input id="qtd" type="number" value="1" min="1" max="100"/>
  </div>
  <button onclick="gerar()">Gerar</button>
  <h4>Saida</h4>
  <pre id="out">{}</pre>

  <h3>Stats</h3>
  <button onclick="stats()">Atualizar stats</button>
  <pre id="stats">{}</pre>
</div>

<script>
async function gerar(){
  const senha = document.getElementById('senha').value;
  const tipo = document.getElementById('tipo').value;
  const quantidade = parseInt(document.getElementById('qtd').value||'1');
  const out = document.getElementById('out');
  out.textContent = 'gerando...';
  const r = await fetch('/gerar-key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({senha,tipo,quantidade})});
  out.textContent = JSON.stringify(await r.json(), null, 2);
}
async function stats(){
  const senha = document.getElementById('senha').value;
  const box = document.getElementById('stats');
  box.textContent = 'carregando...';
  const r = await fetch('/stats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({senha})});
  box.textContent = JSON.stringify(await r.json(), null, 2);
}
</script>
</body>
</html>
"""
    return render_template_string(html)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
