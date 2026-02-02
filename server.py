# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request, render_template_string
import sqlite3
import secrets
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
import requests
import os

app = Flask(__name__)

# =====================================================
# CONFIG (Railway Variables recomendado)
# =====================================================
ADMIN_PASSWORD = os.getenv("Wb03122008!", "Wb03122008!")
DB_NAME = os.getenv("DB_NAME", "licencas.db")
SALASFF_API_URL = os.getenv("SALASFF_API_URL", "https://salasff.com")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))

# Chave para "proteger" a API key do cliente no banco (melhor que nada)
# Coloque uma string grande no Railway Variables: MASTER_KEY
MASTER_KEY = os.getenv("MASTER_KEY", "TROQUE_ESSA_MASTER_KEY_GIGANTE_AQUI")

# Limite de dispositivos por licença (anti-compartilhamento)
MAX_DEVICES = int(os.getenv("MAX_DEVICES", "1"))


# =====================================================
# DB helpers
# =====================================================

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def utcnow_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def hmac_sha256_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

def _xor_encrypt_to_b64(plaintext: str, key: str) -> str:
    # Não é criptografia “de banco”, mas impede vazamento bobo.
    # Se quiser ficar sério: migra p/ Postgres + cryptography.
    if plaintext is None:
        return ""
    kb = hashlib.sha256(key.encode("utf-8")).digest()
    pb = plaintext.encode("utf-8")
    out = bytes([pb[i] ^ kb[i % len(kb)] for i in range(len(pb))])
    return base64.urlsafe_b64encode(out).decode("ascii")

def _xor_decrypt_from_b64(cipher_b64: str, key: str) -> str:
    if not cipher_b64:
        return ""
    kb = hashlib.sha256(key.encode("utf-8")).digest()
    cb = base64.urlsafe_b64decode(cipher_b64.encode("ascii"))
    out = bytes([cb[i] ^ kb[i % len(kb)] for i in range(len(cb))])
    return out.decode("utf-8", errors="replace")


def init_db():
    con = db()
    cur = con.cursor()

    # licencas
    cur.execute("""
    CREATE TABLE IF NOT EXISTS licenses (
        license_key TEXT PRIMARY KEY,
        tipo TEXT NOT NULL,
        dias INTEGER NOT NULL,
        ativada INTEGER DEFAULT 0,
        customer_id TEXT,
        hwid_primeiro TEXT,
        data_criacao TEXT NOT NULL,
        data_ativacao TEXT,
        data_expiracao TEXT
    )
    """)

    # clientes
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        salasff_key_enc TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT
    )
    """)

    # devices
    cur.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id TEXT NOT NULL,
        hwid TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        UNIQUE(customer_id, hwid)
    )
    """)

    # nonces (anti replay simples)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS nonces (
        nonce TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # logs
    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id TEXT,
        hwid TEXT,
        acao TEXT NOT NULL,
        data TEXT NOT NULL,
        detalhes TEXT
    )
    """)

    con.commit()
    con.close()
    print("DB OK")


def registrar_log(customer_id, hwid, acao, detalhes=""):
    try:
        con = db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO logs (customer_id, hwid, acao, data, detalhes) VALUES (?, ?, ?, ?, ?)",
            (customer_id, hwid, acao, utcnow_str(), detalhes),
        )
        con.commit()
        con.close()
    except Exception as e:
        print("LOG FAIL:", e)


# =====================================================
# Licenca
# =====================================================

def calcular_expiracao(dias: int):
    if dias == -1:
        return "PERMANENTE"
    return (datetime.utcnow() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")

def expirou(data_expiracao: str) -> bool:
    if data_expiracao == "PERMANENTE":
        return False
    dt = datetime.strptime(data_expiracao, "%Y-%m-%d %H:%M:%S")
    return datetime.utcnow() > dt

def gerar_key_unica() -> str:
    return secrets.token_hex(16).upper()

def gerar_customer_id() -> str:
    return "CUST_" + secrets.token_hex(8).upper()

def gerar_token() -> str:
    # token “grande”
    return secrets.token_urlsafe(48)


# =====================================================
# Auth do cliente (TOKEN + assinatura HMAC)
# =====================================================

def autenticar_cliente_requisicao():
    """
    Espera:
      Headers:
        X-Client-Token: token
        X-Timestamp: unix int (segundos)
        X-Nonce: string
        X-Signature: hex hmac_sha256(token, f"{ts}\n{nonce}\n{path}\n{raw_body}")
      Body: JSON normal
    """
    token = request.headers.get("X-Client-Token", "").strip()
    ts = request.headers.get("X-Timestamp", "").strip()
    nonce = request.headers.get("X-Nonce", "").strip()
    sig = request.headers.get("X-Signature", "").strip()

    if not token or not ts or not nonce or not sig:
        return (False, None, "Cabecalhos de autenticacao faltando")

    # janela de tempo (2 min)
    try:
        ts_int = int(ts)
    except ValueError:
        return (False, None, "Timestamp invalido")

    now_int = int(datetime.utcnow().timestamp())
    if abs(now_int - ts_int) > 120:
        return (False, None, "Timestamp fora da janela")

    # buscar cliente pelo hash do token
    token_hash = sha256_hex(token)

    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM customers WHERE token_hash = ? AND status = 'active'", (token_hash,))
    cust = cur.fetchone()

    if not cust:
        con.close()
        return (False, None, "Token invalido")

    customer_id = cust["customer_id"]

    # nonce replay check
    cur.execute("SELECT nonce FROM nonces WHERE nonce = ?", (nonce,))
    if cur.fetchone():
        con.close()
        return (False, None, "Nonce repetido")

    # validar assinatura
    raw_body = request.get_data(as_text=True) or ""
    msg = f"{ts}\n{nonce}\n{request.path}\n{raw_body}"
    expected = hmac_sha256_hex(token, msg)
    if not hmac.compare_digest(expected, sig):
        con.close()
        return (False, None, "Assinatura invalida")

    # salvar nonce
    cur.execute(
        "INSERT INTO nonces (nonce, customer_id, created_at) VALUES (?, ?, ?)",
        (nonce, customer_id, utcnow_str()),
    )
    con.commit()
    con.close()

    return (True, customer_id, "")


def validar_hwid_do_cliente(customer_id: str, hwid: str):
    """
    Enforce MAX_DEVICES por cliente.
    """
    hwid = (hwid or "").strip()
    if not hwid:
        return (False, "HWID obrigatorio")

    con = db()
    cur = con.cursor()

    # contar devices
    cur.execute("SELECT COUNT(*) AS c FROM devices WHERE customer_id = ?", (customer_id,))
    total = int(cur.fetchone()["c"])

    # se ja existe, atualiza last_seen
    cur.execute("SELECT id FROM devices WHERE customer_id = ? AND hwid = ?", (customer_id, hwid))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE devices SET last_seen = ? WHERE customer_id = ? AND hwid = ?",
            (utcnow_str(), customer_id, hwid),
        )
        con.commit()
        con.close()
        return (True, "")

    # novo device
    if total >= MAX_DEVICES:
        con.close()
        return (False, f"Limite de dispositivos atingido ({MAX_DEVICES}).")

    cur.execute(
        "INSERT INTO devices (customer_id, hwid, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        (customer_id, hwid, utcnow_str(), utcnow_str()),
    )
    con.commit()
    con.close()
    return (True, "")


def cliente_tem_key(customer_id: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT salasff_key_enc FROM customers WHERE customer_id = ?", (customer_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return (False, "")
    enc = row["salasff_key_enc"]
    if not enc:
        return (False, "")
    return (True, _xor_decrypt_from_b64(enc, MASTER_KEY))


def checar_licenca_customer(customer_id: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM licenses WHERE customer_id = ? AND ativada = 1", (customer_id,))
    lic = cur.fetchone()
    con.close()

    if not lic:
        return (False, "Licenca nao encontrada para este cliente")

    data_exp = lic["data_expiracao"]
    if data_exp and expirou(data_exp):
        return (False, "Licenca expirada")

    return (True, "")


# =====================================================
# ROTAS
# =====================================================

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "sistema": "API Licencas + Proxy (API Key por cliente)",
        "rotas": {
            "GET /admin": "Painel admin",
            "POST /gerar-key": "Admin gera keys",
            "POST /ativar-key": "Cliente ativa key e recebe token",
            "POST /cliente/set-salasff-key": "Cliente cadastra a API key dele",
            "POST /validar-licenca": "Cliente valida token + licenca",
            "POST /proxy-criar-sala": "Cria sala usando API key do cliente",
            "POST /proxy-info-sala": "Info sala",
            "POST /proxy-iniciar-partida": "Inicia partida",
            "POST /stats": "Admin stats",
        }
    })


# ---------------- ADMIN ----------------

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
    keys = []

    con = db()
    cur = con.cursor()

    for _ in range(max(1, quantidade)):
        k = gerar_key_unica()
        cur.execute(
            "INSERT INTO licenses (license_key, tipo, dias, ativada, data_criacao) VALUES (?, ?, ?, 0, ?)",
            (k, tipo, dias, utcnow_str()),
        )
        keys.append(k)

    con.commit()
    con.close()

    return jsonify({"success": True, "tipo": tipo, "quantidade": len(keys), "keys": keys})


@app.route("/stats", methods=["POST"])
def stats():
    data = request.get_json(silent=True) or {}
    senha = data.get("senha")
    if senha != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Senha incorreta"}), 401

    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM licenses")
    total_keys = int(cur.fetchone()["c"])
    cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE ativada = 1")
    keys_ativas = int(cur.fetchone()["c"])
    cur.execute("SELECT COUNT(*) AS c FROM customers")
    total_clientes = int(cur.fetchone()["c"])

    cur.execute("SELECT * FROM logs ORDER BY data DESC LIMIT 50")
    logs_raw = cur.fetchall()
    con.close()

    logs = []
    for r in logs_raw:
        logs.append({
            "id": r["id"],
            "customer_id": r["customer_id"] or "N/A",
            "hwid": (r["hwid"][:16] + "...") if r["hwid"] else "N/A",
            "acao": r["acao"],
            "data": r["data"],
            "detalhes": r["detalhes"] or "",
        })

    return jsonify({
        "success": True,
        "stats": {
            "total_keys": total_keys,
            "keys_ativas": keys_ativas,
            "keys_pendentes": total_keys - keys_ativas,
            "total_clientes": total_clientes,
            "max_devices": MAX_DEVICES,
        },
        "logs": logs,
    })


# ---------------- CLIENTE ----------------

@app.route("/ativar-key", methods=["POST"])
def ativar_key():
    """
    Cliente envia: {"key":"...", "hwid":"..."}
    Servidor responde: token + tipo + expiracao
    """
    data = request.get_json(silent=True) or {}
    license_key = (data.get("key") or "").upper().strip()
    hwid = (data.get("hwid") or "").strip()

    if not license_key or not hwid:
        return jsonify({"success": False, "error": "Key e HWID sao obrigatorios"}), 400

    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM licenses WHERE license_key = ?", (license_key,))
    lic = cur.fetchone()

    if not lic:
        con.close()
        return jsonify({"success": False, "error": "Key nao encontrada"}), 404

    if int(lic["ativada"]) == 1:
        con.close()
        return jsonify({"success": False, "error": "Key ja foi ativada"}), 403

    tipo = lic["tipo"]
    dias = int(lic["dias"])
    customer_id = gerar_customer_id()
    token = gerar_token()

    data_ativ = utcnow_str()
    data_exp = calcular_expiracao(dias)

    # cria customer
    cur.execute(
        "INSERT INTO customers (customer_id, token_hash, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (customer_id, sha256_hex(token), data_ativ, data_ativ),
    )

    # ativa license
    cur.execute(
        """UPDATE licenses
           SET ativada = 1, customer_id = ?, hwid_primeiro = ?, data_ativacao = ?, data_expiracao = ?
           WHERE license_key = ?""",
        (customer_id, hwid, data_ativ, data_exp, license_key),
    )

    # registra device
    cur.execute(
        "INSERT INTO devices (customer_id, hwid, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        (customer_id, hwid, data_ativ, data_ativ),
    )

    con.commit()
    con.close()

    registrar_log(customer_id, hwid, "KEY_ATIVADA", f"Tipo={tipo}, exp={data_exp}")

    return jsonify({
        "success": True,
        "message": "Key ativada com sucesso!",
        "tipo": tipo,
        "data_expiracao": data_exp,
        "client_token": token,
        "max_devices": MAX_DEVICES,
    })


@app.route("/cliente/set-salasff-key", methods=["POST"])
def set_salasff_key():
    """
    Cliente cadastra a API key DELE.
    Requer headers auth (token + assinatura).
    Body: {"hwid":"...", "salasff_key":"..."}
    """
    ok, customer_id, err = autenticar_cliente_requisicao()
    if not ok:
        return jsonify({"success": False, "error": err}), 401

    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    salasff_key = (data.get("salasff_key") or "").strip()

    if not salasff_key:
        return jsonify({"success": False, "error": "salasff_key obrigatoria"}), 400

    ok_hwid, msg = validar_hwid_do_cliente(customer_id, hwid)
    if not ok_hwid:
        registrar_log(customer_id, hwid, "SET_KEY_NEGADO", msg)
        return jsonify({"success": False, "error": msg}), 403

    enc = _xor_encrypt_to_b64(salasff_key, MASTER_KEY)

    con = db()
    cur = con.cursor()
    cur.execute(
        "UPDATE customers SET salasff_key_enc = ?, updated_at = ? WHERE customer_id = ?",
        (enc, utcnow_str(), customer_id),
    )
    con.commit()
    con.close()

    registrar_log(customer_id, hwid, "SET_SALASFF_KEY", "OK")
    return jsonify({"success": True, "message": "API key cadastrada com sucesso!"})


@app.route("/validar-licenca", methods=["POST"])
def validar_licenca():
    """
    Valida token + licenca.
    Requer headers auth.
    Body: {"hwid":"..."}
    """
    ok, customer_id, err = autenticar_cliente_requisicao()
    if not ok:
        return jsonify({"success": False, "error": err}), 401

    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()

    ok_hwid, msg = validar_hwid_do_cliente(customer_id, hwid)
    if not ok_hwid:
        return jsonify({"success": True, "valida": False, "error": msg}), 403

    ok_lic, msg_lic = checar_licenca_customer(customer_id)
    if not ok_lic:
        return jsonify({"success": True, "valida": False, "error": msg_lic}), 200

    has_key, _ = cliente_tem_key(customer_id)
    return jsonify({"success": True, "valida": True, "tem_api_key": has_key})


# ---------------- PROXY (usa API key do CLIENTE) ----------------

@app.route("/proxy-criar-sala", methods=["POST"])
def proxy_criar_sala():
    ok, customer_id, err = autenticar_cliente_requisicao()
    if not ok:
        return jsonify({"success": False, "error": err}), 401

    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    modo_id = data.get("modo_id")
    iniciar_em = int(data.get("iniciar_em", 4))

    ok_hwid, msg = validar_hwid_do_cliente(customer_id, hwid)
    if not ok_hwid:
        registrar_log(customer_id, hwid, "CRIAR_SALA_NEGADO", msg)
        return jsonify({"success": False, "error": msg}), 403

    ok_lic, msg_lic = checar_licenca_customer(customer_id)
    if not ok_lic:
        registrar_log(customer_id, hwid, "CRIAR_SALA_NEGADO", msg_lic)
        return jsonify({"success": False, "error": msg_lic}), 403

    has_key, salasff_key = cliente_tem_key(customer_id)
    if not has_key:
        return jsonify({"success": False, "error": "Cliente sem API key cadastrada. Use /cliente/set-salasff-key"}), 400

    if not modo_id:
        return jsonify({"success": False, "error": "modo_id obrigatorio"}), 400

    url = f"{SALASFF_API_URL}/criar?key={salasff_key}&salaid={modo_id}&iniciar={iniciar_em}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = resp.json()
        registrar_log(customer_id, hwid, "CRIAR_SALA", f"modo={modo_id}, ok={resultado.get('success')}")
        return jsonify(resultado)
    except Exception as e:
        registrar_log(customer_id, hwid, "CRIAR_SALA_ERRO", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/proxy-info-sala", methods=["POST"])
def proxy_info_sala():
    ok, customer_id, err = autenticar_cliente_requisicao()
    if not ok:
        return jsonify({"success": False, "error": err}), 401

    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    pedido_id = data.get("pedido_id")

    ok_hwid, msg = validar_hwid_do_cliente(customer_id, hwid)
    if not ok_hwid:
        return jsonify({"success": False, "error": msg}), 403

    ok_lic, msg_lic = checar_licenca_customer(customer_id)
    if not ok_lic:
        return jsonify({"success": False, "error": msg_lic}), 403

    if not pedido_id:
        return jsonify({"success": False, "error": "pedido_id obrigatorio"}), 400

    url = f"{SALASFF_API_URL}/info?pedidoid={pedido_id}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/proxy-iniciar-partida", methods=["POST"])
def proxy_iniciar_partida():
    ok, customer_id, err = autenticar_cliente_requisicao()
    if not ok:
        return jsonify({"success": False, "error": err}), 401

    data = request.get_json(silent=True) or {}
    hwid = (data.get("hwid") or "").strip()
    pedido_id = data.get("pedido_id")

    ok_hwid, msg = validar_hwid_do_cliente(customer_id, hwid)
    if not ok_hwid:
        return jsonify({"success": False, "error": msg}), 403

    ok_lic, msg_lic = checar_licenca_customer(customer_id)
    if not ok_lic:
        return jsonify({"success": False, "error": msg_lic}), 403

    if not pedido_id:
        return jsonify({"success": False, "error": "pedido_id obrigatorio"}), 400

    url = f"{SALASFF_API_URL}/iniciar?pedidoid={pedido_id}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = resp.json()
        registrar_log(customer_id, hwid, "INICIAR_PARTIDA", f"pedido={pedido_id}")
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------- ADMIN PANEL (mesmo estilo, só com keys) ----------------

@app.route("/admin")
def admin_panel():
    html = r"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Painel Admin</title>
  <style>
    body{font-family:Arial;background:#111;color:#eee;padding:20px}
    .box{max-width:900px;margin:0 auto;background:#1b1b1b;padding:20px;border-radius:12px}
    input,select,button{padding:10px;border-radius:8px;border:1px solid #333;width:100%;margin:6px 0}
    button{background:#6c5ce7;color:#fff;border:none;cursor:pointer}
    pre{background:#000;padding:12px;border-radius:10px;white-space:pre-wrap}
  </style>
</head>
<body>
<div class="box">
  <h2>Painel Admin</h2>
  <p>Gera keys e vê stats.</p>

  <h3>Gerar Keys</h3>
  <input id="senha" type="password" placeholder="Senha admin">
  <select id="tipo">
    <option value="1d">1d</option>
    <option value="7d">7d</option>
    <option value="30d" selected>30d</option>
    <option value="90d">90d</option>
    <option value="perm">perm</option>
  </select>
  <input id="qtd" type="number" min="1" max="100" value="1">
  <button onclick="gerar()">Gerar</button>

  <h3>Saída</h3>
  <pre id="out">Aguardando...</pre>

  <h3>Stats</h3>
  <button onclick="stats()">Atualizar stats</button>
  <pre id="stats">-</pre>
</div>

<script>
function gerar(){
  const senha=document.getElementById('senha').value;
  const tipo=document.getElementById('tipo').value;
  const quantidade=parseInt(document.getElementById('qtd').value||"1",10);
  fetch('/gerar-key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({senha,tipo,quantidade})})
    .then(r=>r.json()).then(d=>{
      document.getElementById('out').textContent=JSON.stringify(d,null,2);
    });
}
function stats(){
  const senha=document.getElementById('senha').value;
  fetch('/stats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({senha})})
    .then(r=>r.json()).then(d=>{
      document.getElementById('stats').textContent=JSON.stringify(d,null,2);
    });
}
</script>
</body>
</html>
"""
    return render_template_string(html)


# =====================================================
# Start
# =====================================================

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
