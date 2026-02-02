# -*- coding: utf-8 -*-
import os
import sqlite3
import secrets
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# =====================================================
# CONFIG (USE VARIAVEIS NO RAILWAY)
# =====================================================

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wb03122008!")
SALASFF_API_URL = os.getenv("SALASFF_API_URL", "https://salasff.com")

DB_NAME = os.getenv("DB_NAME", "licencas.db")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))

# =====================================================
# DB
# =====================================================

def db_conn():
    # check_same_thread False evita problema com threads do gunicorn
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    con = db_conn()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        tipo TEXT NOT NULL,
        dias INTEGER NOT NULL,
        ativada INTEGER DEFAULT 0,
        hwid TEXT,
        salasff_key TEXT,
        data_ativacao TEXT,
        data_expiracao TEXT,
        data_criacao TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hwid TEXT,
        acao TEXT,
        data TEXT,
        detalhes TEXT
    )
    """)

    con.commit()
    con.close()

def log(hwid, acao, detalhes=""):
    try:
        con = db_conn()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO logs (hwid, acao, data, detalhes) VALUES (?, ?, ?, ?)",
            (hwid, acao, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), detalhes),
        )
        con.commit()
        con.close()
    except Exception:
        pass

# =====================================================
# LICENCA
# =====================================================

def gerar_key_unica():
    return secrets.token_hex(16).upper()

def calcular_expiracao(dias):
    if dias == -1:
        return "PERMANENTE"
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")

def expirou(data_expiracao):
    if data_expiracao == "PERMANENTE":
        return False
    dt = datetime.strptime(data_expiracao, "%Y-%m-%d %H:%M:%S")
    return datetime.now() > dt

def buscar_licenca_por_hwid(hwid):
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT key, tipo, dias, ativada, hwid, salasff_key, data_ativacao, data_expiracao, data_criacao FROM keys WHERE hwid = ? AND ativada = 1", (hwid,))
    row = cur.fetchone()
    con.close()
    return row

def licenca_valida(hwid):
    row = buscar_licenca_por_hwid(hwid)
    if not row:
        return False, "Nenhuma licenca ativa para este HWID"
    data_exp = row[7]
    if expirou(data_exp):
        return False, "Licenca expirada"
    return True, "OK"

def salasff_key_do_cliente(hwid):
    row = buscar_licenca_por_hwid(hwid)
    if not row:
        return None
    return row[5]  # salasff_key

# =====================================================
# ROTAS PUBLICAS
# =====================================================

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "sistema": "API Licencas + Proxy SalasFF",
        "rotas": {
            "POST /gerar-key": "admin gera keys",
            "POST /ativar-key": "cliente ativa key no hwid",
            "POST /set-salasff-key": "cliente cadastra sua api key do SalasFF",
            "POST /validar-licenca": "checa licenca",
            "POST /proxy-criar-sala": "cria sala usando key do cliente",
            "POST /proxy-info-sala": "consulta sala",
            "POST /proxy-iniciar-partida": "inicia partida",
            "GET /admin": "painel admin",
            "POST /stats": "stats admin",
        }
    })

@app.route("/gerar-key", methods=["POST"])
def gerar_key():
    data = request.get_json(silent=True) or {}
    senha = data.get("senha")
    tipo = (data.get("tipo") or "1d").strip()
    quantidade = int(data.get("quantidade", 1))

    if senha != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Senha incorreta"}), 401

    tipos_dias = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "perm": -1}
    if tipo not in tipos_dias:
        return jsonify({"success": False, "error": "Tipo invalido"}), 400

    dias = tipos_dias[tipo]
    quantidade = max(1, min(quantidade, 100))

    con = db_conn()
    cur = con.cursor()

    keys = []
    for _ in range(quantidade):
        k = gerar_key_unica()
        cur.execute(
            "INSERT INTO keys (key, tipo, dias, data_criacao) VALUES (?, ?, ?, ?)",
            (k, tipo, dias, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        keys.append(k)

    con.commit()
    con.close()

    return jsonify({"success": True, "tipo": tipo, "quantidade": len(keys), "keys": keys})

@app.route("/ativar-key", methods=["POST"])
def ativar_key():
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").upper().strip()
    hwid = (data.get("hwid") or "").strip()

    if not key or not hwid:
        return jsonify({"success": False, "error": "Key e HWID sao obrigatorios"}), 400

    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT key, tipo, dias, ativada, hwid, salasff_key, data_ativacao, data_expiracao, data_criacao FROM keys WHERE key = ?", (key,))
    row = cur.fetchone()

    if not row:
        con.close()
        return jsonify({"success": False, "error": "Key nao encontrada"}), 404

    ativada = row[3]
    hwid_db = row[4]
    dias = row[2]
    tipo = row[1]

    if ativada == 1:
        con.close()
        return jsonify({"success": False, "error": "Key ja foi ativada"}), 403

    data_ativ = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_exp = calcular_expiracao(dias)

    cur.execute(
        "UPDATE keys SET ativada = 1, hwid = ?, data_ativacao = ?, data_expiracao = ? WHERE key = ?",
        (hwid, data_ativ, data_exp, key),
    )
    con.commit()
    con.close()

    log(hwid, "KEY_ATIVADA", f"tipo={tipo}")

    return jsonify({
        "success": True,
        "message": "Key ativada com sucesso",
        "tipo": tipo,
        "data_expiracao": data_exp
    })

@app.route("/set-salasff-key", methods=["POST"])
def set_salasff_key():
    """
    Cliente cadastra a API key dele do SalasFF
    Body: {"hwid":"...", "salasff_key":"..."}
    """
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    s_key = (data.get("salasff_key") or "").strip()

    if not hwid or not s_key:
        return jsonify({"success": False, "error": "hwid e salasff_key sao obrigatorios"}), 400

    ok, msg = licenca_valida(hwid)
    if not ok:
        return jsonify({"success": False, "error": msg}), 403

    # opcional: validar a key chamando uma rota leve do SalasFF
    # como nao temos doc, vamos só testar /criar com um modo fake? pior.
    # então aqui apenas salva, e erros aparecem no uso real.

    con = db_conn()
    cur = con.cursor()
    cur.execute("UPDATE keys SET salasff_key = ? WHERE hwid = ? AND ativada = 1", (s_key, hwid))
    con.commit()
    con.close()

    log(hwid, "SALASFF_KEY_SET", "cliente cadastrou api key")

    return jsonify({"success": True, "message": "API key do SalasFF cadastrada com sucesso"})

@app.route("/validar-licenca", methods=["POST"])
def validar_licenca():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    if not hwid:
        return jsonify({"success": False, "error": "HWID e obrigatorio"}), 400

    row = buscar_licenca_por_hwid(hwid)
    if not row:
        return jsonify({"success": False, "valida": False, "error": "Nenhuma licenca encontrada"}), 404

    tipo = row[1]
    data_exp = row[7]
    if expirou(data_exp):
        return jsonify({"success": True, "valida": False, "error": "Licenca expirada", "data_expiracao": data_exp})

    tem_key = True if (row[5] and row[5].strip()) else False

    return jsonify({
        "success": True,
        "valida": True,
        "tipo": tipo,
        "data_expiracao": data_exp,
        "salasff_key_cadastrada": tem_key
    })

# =====================================================
# PROXY (USA A KEY DO CLIENTE)
# =====================================================

@app.route("/proxy-criar-sala", methods=["POST"])
def proxy_criar_sala():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    modo_id = (data.get("modo_id") or "").strip()
    iniciar_em = int(data.get("iniciar_em", 4))

    if not hwid or not modo_id:
        return jsonify({"success": False, "error": "hwid e modo_id sao obrigatorios"}), 400

    ok, msg = licenca_valida(hwid)
    if not ok:
        log(hwid, "CRIAR_SALA_NEGADO", msg)
        return jsonify({"success": False, "error": msg}), 403

    s_key = salasff_key_do_cliente(hwid)
    if not s_key:
        return jsonify({"success": False, "error": "Cliente nao cadastrou a API key do SalasFF"}), 400

    url = f"{SALASFF_API_URL}/criar?key={s_key}&salaid={modo_id}&iniciar={iniciar_em}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        out = r.json()
        log(hwid, "CRIAR_SALA", f"modo={modo_id} success={out.get('success')}")
        return jsonify(out)
    except Exception as e:
        log(hwid, "CRIAR_SALA_ERRO", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/proxy-info-sala", methods=["POST"])
def proxy_info_sala():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    pedido_id = (data.get("pedido_id") or "").strip()

    if not hwid or not pedido_id:
        return jsonify({"success": False, "error": "hwid e pedido_id sao obrigatorios"}), 400

    ok, msg = licenca_valida(hwid)
    if not ok:
        return jsonify({"success": False, "error": msg}), 403

    url = f"{SALASFF_API_URL}/info?pedidoid={pedido_id}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/proxy-iniciar-partida", methods=["POST"])
def proxy_iniciar_partida():
    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    pedido_id = (data.get("pedido_id") or "").strip()

    if not hwid or not pedido_id:
        return jsonify({"success": False, "error": "hwid e pedido_id sao obrigatorios"}), 400

    ok, msg = licenca_valida(hwid)
    if not ok:
        return jsonify({"success": False, "error": msg}), 403

    s_key = salasff_key_do_cliente(hwid)
    if not s_key:
        return jsonify({"success": False, "error": "Cliente nao cadastrou a API key do SalasFF"}), 400

    url = f"{SALASFF_API_URL}/iniciar?pedidoid={pedido_id}&key={s_key}"
    # se a API /iniciar nao usa key, não tem problema: só vai ignorar.
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        out = r.json()
        log(hwid, "INICIAR_PARTIDA", f"pedido={pedido_id} success={out.get('success')}")
        return jsonify(out)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================================
# ADMIN (PAINEL)
# =====================================================

@app.route("/stats", methods=["POST"])
def stats():
    data = request.get_json(silent=True) or {}
    senha = data.get("senha")
    if senha != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Senha incorreta"}), 401

    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM keys")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM keys WHERE ativada = 1")
    ativas = cur.fetchone()[0]
    pendentes = total - ativas

    cur.execute("SELECT id, hwid, acao, data, detalhes FROM logs ORDER BY data DESC LIMIT 50")
    logs_raw = cur.fetchall()
    con.close()

    logs = []
    for (i, hw, ac, dt, det) in logs_raw:
        logs.append({
            "id": i,
            "hwid": (hw[:16] + "...") if hw else "N/A",
            "acao": ac,
            "data": dt,
            "detalhes": det
        })

    return jsonify({
        "success": True,
        "stats": {"total_keys": total, "keys_ativas": ativas, "keys_pendentes": pendentes},
        "logs": logs
    })

@app.route("/admin")
def admin():
    html = r"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Painel Admin</title>
  <style>
    body{font-family:Arial;background:#0b0b10;color:#fff;margin:0;padding:30px}
    .box{max-width:900px;margin:0 auto;background:#151525;border-radius:16px;padding:24px}
    input,select,button{width:100%;padding:12px;border-radius:10px;border:0;margin:8px 0}
    button{background:#6a5acd;color:#fff;font-weight:700;cursor:pointer}
    pre{background:#0a0a0f;padding:12px;border-radius:10px;white-space:pre-wrap}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  </style>
</head>
<body>
<div class="box">
  <h1>Painel Admin</h1>
  <p>Gera keys e ve stats.</p>

  <h2>Gerar Keys</h2>
  <input type="password" id="senha" placeholder="Senha admin">
  <select id="tipo">
    <option value="1d">1d (teste)</option>
    <option value="7d">7d</option>
    <option value="30d" selected>30d</option>
    <option value="90d">90d</option>
    <option value="perm">perm</option>
  </select>
  <input type="number" id="quantidade" value="1" min="1" max="100">
  <button onclick="gerar()">Gerar</button>

  <h3>Saida</h3>
  <pre id="out">{}</pre>

  <h2>Stats</h2>
  <button onclick="stats()">Atualizar stats</button>
  <pre id="stats">{}</pre>
</div>

<script>
async function gerar(){
  const senha=document.getElementById('senha').value;
  const tipo=document.getElementById('tipo').value;
  const quantidade=parseInt(document.getElementById('quantidade').value || "1");
  const out=document.getElementById('out');
  out.textContent="gerando...";
  const r=await fetch('/gerar-key',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({senha,tipo,quantidade})
  });
  const j=await r.json();
  out.textContent=JSON.stringify(j,null,2);
}
async function stats(){
  const senha=document.getElementById('senha').value;
  const box=document.getElementById('stats');
  box.textContent="carregando...";
  const r=await fetch('/stats',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({senha})
  });
  const j=await r.json();
  box.textContent=JSON.stringify(j,null,2);
}
</script>
</body>
</html>
"""
    return render_template_string(html)

# =====================================================
# STARTUP
# =====================================================

# garante que DB existe mesmo quando roda com gunicorn
init_db()

# gunicorn vai importar "app" direto, então não precisa app.run aqui.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
