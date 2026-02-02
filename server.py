# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request, render_template_string
import sqlite3
import secrets
from datetime import datetime, timedelta
import requests
import os

app = Flask(__name__)

# =========================
# CONFIG (use Railway Variables)
# =========================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wb03122008!")
SALASFF_API_URL = os.getenv("SALASFF_API_URL", "https://salasff.com")

DB_NAME = os.getenv("DB_NAME", "licencas.db")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))

# =========================
# DB helpers
# =========================
def db_conn():
    # timeout alto + check_same_thread False reduz travamentos no Railway
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn

def init_db():
    conn = db_conn()
    c = conn.cursor()

    # Keys do SEU sistema (licenças)
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

    # Logs
    c.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hwid TEXT,
        acao TEXT,
        data TEXT,
        detalhes TEXT
    )
    """)

    # DADOS DO CLIENTE (aqui fica a API key do SalasFF DELE)
    c.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        hwid TEXT PRIMARY KEY,
        salasff_key TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def gerar_key_unica():
    return secrets.token_hex(16).upper()

def calcular_expiracao(dias):
    if dias == -1:
        return "PERMANENTE"
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")

def verificar_expiracao(data_expiracao):
    if data_expiracao == "PERMANENTE":
        return False
    data_exp = datetime.strptime(data_expiracao, "%Y-%m-%d %H:%M:%S")
    return datetime.now() > data_exp

def registrar_log(hwid, acao, detalhes=""):
    try:
        conn = db_conn()
        conn.execute(
            "INSERT INTO logs (hwid, acao, data, detalhes) VALUES (?, ?, ?, ?)",
            (hwid or "N/A", acao, now_str(), detalhes or "")
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def validar_licenca_interna(hwid):
    try:
        conn = db_conn()
        row = conn.execute(
            "SELECT * FROM keys WHERE hwid = ? AND ativada = 1",
            (hwid,)
        ).fetchone()
        conn.close()

        if not row:
            return False

        data_exp = row["data_expiracao"]
        if verificar_expiracao(data_exp):
            return False

        return True
    except Exception as e:
        registrar_log(hwid, "VALIDAR_LICENCA_ERRO", str(e))
        return False

def get_salasff_key_do_cliente(hwid):
    conn = db_conn()
    row = conn.execute("SELECT salasff_key FROM clients WHERE hwid = ?", (hwid,)).fetchone()
    conn.close()
    return row["salasff_key"] if row and row["salasff_key"] else None

# =========================
# ROTAS
# =========================

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "sistema": "API de Licencas - Free Fire Bot",
        "versao": "3.0 - SalasFF Key por cliente",
        "rotas": {
            "POST /gerar-key": "Gera key (admin)",
            "POST /ativar-key": "Ativa key no HWID",
            "POST /validar-licenca": "Valida licenca",
            "POST /admin/set-salasff-key": "Define API key SalasFF do cliente (admin)",
            "POST /proxy-criar-sala": "Cria sala usando a key do cliente",
            "POST /proxy-info-sala": "Info sala",
            "POST /proxy-iniciar-partida": "Iniciar partida",
            "GET /admin": "Painel admin"
        }
    })

@app.route("/gerar-key", methods=["POST"])
def gerar_key():
    try:
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
        quantidade = max(1, min(quantidade, 200))

        conn = db_conn()
        keys_geradas = []
        for _ in range(quantidade):
            k = gerar_key_unica()
            conn.execute(
                "INSERT INTO keys (key, tipo, dias, data_criacao) VALUES (?, ?, ?, ?)",
                (k, tipo, dias, now_str())
            )
            keys_geradas.append(k)
        conn.commit()
        conn.close()

        return jsonify({"success": True, "keys": keys_geradas, "tipo": tipo, "quantidade": len(keys_geradas)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/ativar-key", methods=["POST"])
def ativar_key():
    try:
        data = request.get_json(silent=True) or {}
        key = (data.get("key") or "").upper().strip()
        hwid = (data.get("hwid") or "").strip()

        if not key or not hwid:
            return jsonify({"success": False, "error": "Key e HWID sao obrigatorios"}), 400

        conn = db_conn()
        row = conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "error": "Key nao encontrada"}), 404

        if row["ativada"] == 1:
            conn.close()
            return jsonify({"success": False, "error": "Key ja foi ativada em outro PC"}), 403

        data_exp = calcular_expiracao(row["dias"])
        conn.execute("""
            UPDATE keys
            SET ativada = 1, hwid = ?, data_ativacao = ?, data_expiracao = ?
            WHERE key = ?
        """, (hwid, now_str(), data_exp, key))

        conn.commit()
        conn.close()

        registrar_log(hwid, "KEY_ATIVADA", f"Key: {key[:8]}..., Tipo: {row['tipo']}")
        return jsonify({"success": True, "message": "Key ativada com sucesso!", "tipo": row["tipo"], "data_expiracao": data_exp})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/validar-licenca", methods=["POST"])
def validar_licenca():
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()
        if not hwid:
            return jsonify({"success": False, "error": "HWID e obrigatorio"}), 400

        conn = db_conn()
        row = conn.execute("SELECT * FROM keys WHERE hwid = ? AND ativada = 1", (hwid,)).fetchone()
        conn.close()

        if not row:
            return jsonify({"success": False, "valida": False, "error": "Nenhuma licenca encontrada para este PC"}), 404

        if verificar_expiracao(row["data_expiracao"]):
            return jsonify({"success": True, "valida": False, "error": "Licenca expirada", "data_expiracao": row["data_expiracao"]})

        return jsonify({"success": True, "valida": True, "tipo": row["tipo"], "data_expiracao": row["data_expiracao"]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ---- Admin: setar SalasFF API key do cliente ----
@app.route("/admin/set-salasff-key", methods=["POST"])
def admin_set_salasff_key():
    """
    Body: {"senha":"...","hwid":"...","salasff_key":"..."}
    """
    try:
        data = request.get_json(silent=True) or {}
        senha = data.get("senha")
        hwid = (data.get("hwid") or "").strip()
        salasff_key = (data.get("salasff_key") or "").strip()

        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401
        if not hwid or not salasff_key:
            return jsonify({"success": False, "error": "hwid e salasff_key sao obrigatorios"}), 400

        conn = db_conn()
        conn.execute("""
            INSERT INTO clients (hwid, salasff_key, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(hwid) DO UPDATE SET
                salasff_key=excluded.salasff_key,
                updated_at=excluded.updated_at
        """, (hwid, salasff_key, now_str()))
        conn.commit()
        conn.close()

        registrar_log(hwid, "SET_SALASFF_KEY", "SalasFF key definida/atualizada")
        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ---- Proxy: usa SalasFF key do cliente ----
@app.route("/proxy-criar-sala", methods=["POST"])
def proxy_criar_sala():
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()
        modo_id = data.get("modo_id")
        iniciar_em = int(data.get("iniciar_em", 4))

        if not hwid or not modo_id:
            return jsonify({"success": False, "error": "hwid e modo_id sao obrigatorios"}), 400
        if not validar_licenca_interna(hwid):
            registrar_log(hwid, "CRIAR_SALA_NEGADO", "Licenca invalida/expirada")
            return jsonify({"success": False, "error": "Licenca invalida ou expirada"}), 403

        salasff_key = get_salasff_key_do_cliente(hwid)
        if not salasff_key:
            return jsonify({"success": False, "error": "Cliente sem SalasFF API key cadastrada (admin precisa setar)"}), 403

        url = f"{SALASFF_API_URL}/criar?key={salasff_key}&salaid={modo_id}&iniciar={iniciar_em}"
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = r.json()

        registrar_log(hwid, "CRIAR_SALA", f"Modo: {modo_id}, Sucesso: {resultado.get('success')}")
        return jsonify(resultado)

    except Exception as e:
        registrar_log((locals().get("hwid") or "DESCONHECIDO"), "CRIAR_SALA_ERRO", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/proxy-info-sala", methods=["POST"])
def proxy_info_sala():
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()
        pedido_id = data.get("pedido_id")

        if not hwid or not pedido_id:
            return jsonify({"success": False, "error": "hwid e pedido_id sao obrigatorios"}), 400
        if not validar_licenca_interna(hwid):
            return jsonify({"success": False, "error": "Licenca invalida ou expirada"}), 403

        url = f"{SALASFF_API_URL}/info?pedidoid={pedido_id}"
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        return jsonify(r.json())

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/proxy-iniciar-partida", methods=["POST"])
def proxy_iniciar_partida():
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()
        pedido_id = data.get("pedido_id")

        if not hwid or not pedido_id:
            return jsonify({"success": False, "error": "hwid e pedido_id sao obrigatorios"}), 400
        if not validar_licenca_interna(hwid):
            return jsonify({"success": False, "error": "Licenca invalida ou expirada"}), 403

        url = f"{SALASFF_API_URL}/iniciar?pedidoid={pedido_id}"
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = r.json()

        registrar_log(hwid, "INICIAR_PARTIDA", f"Pedido: {pedido_id}")
        return jsonify(resultado)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ---- Admin panel simples + nova função de setar key do cliente ----
@app.route("/admin")
def admin_panel():
    html = r"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Painel Admin</title>
  <style>
    body{font-family:Arial;background:#111;color:#eee;padding:20px}
    .box{max-width:900px;margin:0 auto;background:#1b1b1b;padding:20px;border-radius:12px}
    input,select,button{width:100%;padding:10px;margin:6px 0;border-radius:8px;border:1px solid #333;background:#0f0f0f;color:#eee}
    button{background:#6c5ce7;border:none;font-weight:700;cursor:pointer}
    pre{background:#0b0b0b;padding:12px;border-radius:10px;overflow:auto}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    @media(max-width:700px){.row{grid-template-columns:1fr}}
  </style>
</head>
<body>
<div class="box">
  <h1>Painel Admin</h1>
  <p>Gera keys, vê stats e cadastra SalasFF API key do cliente.</p>

  <h2>Gerar Keys</h2>
  <input id="senha" type="password" placeholder="Senha admin">
  <select id="tipo">
    <option value="1d">1 dia</option>
    <option value="7d">7 dias</option>
    <option value="30d" selected>30 dias</option>
    <option value="90d">90 dias</option>
    <option value="perm">Permanente</option>
  </select>
  <input id="quantidade" type="number" value="1" min="1" max="200"/>
  <button onclick="gerar()">Gerar</button>

  <h3>Saída</h3>
  <pre id="out">{}</pre>

  <hr style="border:0;border-top:1px solid #333;margin:20px 0">

  <h2>Cadastrar SalasFF API key do cliente</h2>
  <div class="row">
    <input id="hwid" placeholder="HWID do cliente (ele te manda)">
    <input id="salasff" placeholder="SalasFF API key do cliente">
  </div>
  <button onclick="setKey()">Salvar SalasFF key no servidor</button>

  <hr style="border:0;border-top:1px solid #333;margin:20px 0">

  <h2>Stats</h2>
  <button onclick="stats()">Atualizar stats</button>
  <pre id="stats">{}</pre>
</div>

<script>
function show(id, obj){ document.getElementById(id).textContent = JSON.stringify(obj, null, 2); }

async function gerar(){
  const senha = document.getElementById('senha').value;
  const tipo = document.getElementById('tipo').value;
  const quantidade = parseInt(document.getElementById('quantidade').value || "1");

  const r = await fetch('/gerar-key', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({senha, tipo, quantidade})
  });
  show('out', await r.json());
}

async function stats(){
  const senha = document.getElementById('senha').value;
  const r = await fetch('/stats', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({senha})
  });
  show('stats', await r.json());
}

async function setKey(){
  const senha = document.getElementById('senha').value;
  const hwid = document.getElementById('hwid').value;
  const salasff_key = document.getElementById('salasff').value;

  const r = await fetch('/admin/set-salasff-key', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({senha, hwid, salasff_key})
  });
  show('out', await r.json());
}
</script>
</body>
</html>
"""
    return render_template_string(html)

@app.route("/stats", methods=["POST"])
def stats():
    try:
        data = request.get_json(silent=True) or {}
        senha = data.get("senha")
        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401

        conn = db_conn()
        total_keys = conn.execute("SELECT COUNT(*) AS n FROM keys").fetchone()["n"]
        keys_ativas = conn.execute("SELECT COUNT(*) AS n FROM keys WHERE ativada = 1").fetchone()["n"]
        keys_pendentes = total_keys - keys_ativas

        logs_raw = conn.execute("SELECT * FROM logs ORDER BY data DESC LIMIT 50").fetchall()
        conn.close()

        logs = []
        for row in logs_raw:
            logs.append({
                "id": row["id"],
                "hwid": (row["hwid"][:16] + "...") if row["hwid"] else "N/A",
                "acao": row["acao"],
                "data": row["data"],
                "detalhes": row["detalhes"],
            })

        return jsonify({
            "success": True,
            "stats": {"total_keys": total_keys, "keys_ativas": keys_ativas, "keys_pendentes": keys_pendentes},
            "logs": logs
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Inicializa DB SEM depender do __main__
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
