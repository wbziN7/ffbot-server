# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request, render_template_string
import sqlite3
import secrets
from datetime import datetime, timedelta
import requests
import os

app = Flask(__name__)

# =====================================================
# CONFIGURACOES (RECOMENDADO: usar variaveis do Railway)
# =====================================================

# Senha do admin (recomendado setar no Railway Variables: ADMIN_PASSWORD)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wb03122008!")

# API Key SalasFF (recomendado setar no Railway Variables: SALASFF_API_KEY)
SALASFF_API_KEY = os.getenv("SALASFF_API_KEY", "46qr8zgei33wpudgimsc")
SALASFF_API_URL = "https://salasff.com"

DB_NAME = "licencas.db"
REQUEST_TIMEOUT = 10


# =====================================================
# BANCO DE DADOS
# =====================================================

def init_db():
    """Inicializa o banco de dados"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Tabela de keys
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

    # Tabela de logs
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
    print("Banco de dados inicializado!")


# =====================================================
# FUNCOES DE LICENCA
# =====================================================

def gerar_key_unica():
    """Gera uma key unica"""
    return secrets.token_hex(16).upper()


def calcular_expiracao(dias):
    """Calcula data de expiracao"""
    if dias == -1:
        return "PERMANENTE"
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")


def verificar_expiracao(data_expiracao):
    """Verifica se a licenca expirou"""
    if data_expiracao == "PERMANENTE":
        return False

    data_exp = datetime.strptime(data_expiracao, "%Y-%m-%d %H:%M:%S")
    return datetime.now() > data_exp


def validar_licenca_interna(hwid):
    """Valida licenca internamente (usada pelas rotas proxy)"""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT * FROM keys WHERE hwid = ? AND ativada = 1", (hwid,))
        resultado = c.fetchone()
        conn.close()

        if not resultado:
            return False

        _key_db, _tipo, _dias, _ativada, _hwid_db, _data_ativ, data_exp, _data_cria = resultado

        if verificar_expiracao(data_exp):
            return False

        return True

    except Exception as e:
        print(f"Erro ao validar licenca: {e}")
        return False


def registrar_log(hwid, acao, detalhes=""):
    """Registra acoes no log"""
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
    except Exception as e:
        print(f"Erro ao registrar log: {e}")


# =====================================================
# ROTAS DE PROXY (PROTEGEM SUA API KEY)
# =====================================================

@app.route("/proxy-criar-sala", methods=["POST"])
def proxy_criar_sala():
    """
    Proxy para criar sala - protege a API KEY
    Body: {"hwid": "HWID-DO-PC", "modo_id": "...", "iniciar_em": 4}
    """
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

        url = f"{SALASFF_API_URL}/criar?key={SALASFF_API_KEY}&salaid={modo_id}&iniciar={iniciar_em}"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = response.json()

        registrar_log(hwid, "CRIAR_SALA", f"Modo: {modo_id}, Sucesso: {resultado.get('success')}")
        return jsonify(resultado)

    except Exception as e:
        registrar_log((locals().get("hwid") or "DESCONHECIDO"), "CRIAR_SALA_ERRO", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/proxy-info-sala", methods=["POST"])
def proxy_info_sala():
    """
    Proxy para consultar info da sala
    Body: {"hwid": "HWID-DO-PC", "pedido_id": "..."}
    """
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()
        pedido_id = data.get("pedido_id")

        if not hwid or not pedido_id:
            return jsonify({"success": False, "error": "hwid e pedido_id sao obrigatorios"}), 400

        if not validar_licenca_interna(hwid):
            return jsonify({"success": False, "error": "Licenca invalida ou expirada"}), 403

        url = f"{SALASFF_API_URL}/info?pedidoid={pedido_id}"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = response.json()
        return jsonify(resultado)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/proxy-iniciar-partida", methods=["POST"])
def proxy_iniciar_partida():
    """
    Proxy para iniciar partida
    Body: {"hwid": "HWID-DO-PC", "pedido_id": "..."}
    """
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()
        pedido_id = data.get("pedido_id")

        if not hwid or not pedido_id:
            return jsonify({"success": False, "error": "hwid e pedido_id sao obrigatorios"}), 400

        if not validar_licenca_interna(hwid):
            return jsonify({"success": False, "error": "Licenca invalida ou expirada"}), 403

        url = f"{SALASFF_API_URL}/iniciar?pedidoid={pedido_id}"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        resultado = response.json()

        registrar_log(hwid, "INICIAR_PARTIDA", f"Pedido: {pedido_id}")
        return jsonify(resultado)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =====================================================
# ROTAS DA API DE LICENCA
# =====================================================

@app.route("/")
def home():
    """Pagina inicial"""
    return jsonify(
        {
            "status": "online",
            "sistema": "API de Licencas - Free Fire Bot",
            "versao": "2.0 - Sistema Proxy",
            "rotas": {
                "POST /gerar-key": "Gera uma nova key (admin)",
                "POST /ativar-key": "Ativa uma key no HWID",
                "POST /validar-licenca": "Valida se licenca esta ativa",
                "POST /proxy-criar-sala": "Proxy para criar sala (protegido)",
                "POST /proxy-info-sala": "Proxy para info da sala (protegido)",
                "POST /proxy-iniciar-partida": "Proxy para iniciar partida (protegido)",
                "GET /admin": "Painel administrativo",
                "POST /stats": "Estatisticas (admin)",
            },
        }
    )


@app.route("/gerar-key", methods=["POST"])
def gerar_key():
    """
    Gera uma nova key
    Body: {"senha": "...", "tipo": "1d|7d|30d|90d|perm", "quantidade": 1}
    """
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

        keys_geradas = []
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        for _ in range(max(1, quantidade)):
            key = gerar_key_unica()
            data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO keys (key, tipo, dias, data_criacao) VALUES (?, ?, ?, ?)",
                (key, tipo, dias, data_criacao),
            )
            keys_geradas.append(key)

        conn.commit()
        conn.close()

        return jsonify({"success": True, "keys": keys_geradas, "tipo": tipo, "quantidade": len(keys_geradas)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/ativar-key", methods=["POST"])
def ativar_key():
    """
    Ativa uma key no HWID do usuario
    Body: {"key": "ABC123...", "hwid": "HWID-DO-PC"}
    """
    try:
        data = request.get_json(silent=True) or {}
        key = (data.get("key") or "").upper().strip()
        hwid = (data.get("hwid") or "").strip()

        if not key or not hwid:
            return jsonify({"success": False, "error": "Key e HWID sao obrigatorios"}), 400

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT * FROM keys WHERE key = ?", (key,))
        resultado = c.fetchone()

        if not resultado:
            conn.close()
            return jsonify({"success": False, "error": "Key nao encontrada"}), 404

        key_db, tipo, dias, ativada, _hwid_db, _data_ativ, _data_exp, _data_cria = resultado

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

        registrar_log(hwid, "KEY_ATIVADA", f"Key: {key_db[:8]}..., Tipo: {tipo}")

        return jsonify(
            {
                "success": True,
                "message": "Key ativada com sucesso!",
                "tipo": tipo,
                "data_expiracao": data_expiracao,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/validar-licenca", methods=["POST"])
def validar_licenca():
    """
    Valida se uma licenca esta ativa
    Body: {"hwid": "HWID-DO-PC"}
    """
    try:
        data = request.get_json(silent=True) or {}
        hwid = (data.get("hwid") or "").strip()

        if not hwid:
            return jsonify({"success": False, "error": "HWID e obrigatorio"}), 400

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT * FROM keys WHERE hwid = ? AND ativada = 1", (hwid,))
        resultado = c.fetchone()
        conn.close()

        if not resultado:
            return jsonify({"success": False, "valida": False, "error": "Nenhuma licenca encontrada para este PC"}), 404

        _key_db, tipo, _dias, _ativada, _hwid_db, _data_ativ, data_exp, _data_cria = resultado

        if verificar_expiracao(data_exp):
            return jsonify(
                {"success": True, "valida": False, "error": "Licenca expirada", "data_expiracao": data_exp}
            )

        return jsonify({"success": True, "valida": True, "tipo": tipo, "data_expiracao": data_exp})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/stats", methods=["POST"])
def stats():
    """
    Estatisticas do sistema (protegido por senha)
    Body: {"senha": "..."}
    """
    try:
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

        keys_pendentes = total_keys - keys_ativas

        c.execute("SELECT * FROM logs ORDER BY data DESC LIMIT 50")
        logs_raw = c.fetchall()
        conn.close()

        logs = []
        for log in logs_raw:
            logs.append(
                {
                    "id": log[0],
                    "hwid": (log[1][:16] + "...") if log[1] else "N/A",
                    "acao": log[2],
                    "data": log[3],
                    "detalhes": log[4],
                }
            )

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_keys": total_keys,
                    "keys_ativas": keys_ativas,
                    "keys_pendentes": keys_pendentes,
                },
                "logs": logs,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin")
def admin_panel():
    """Painel administrativo"""
    html = r"""
<!DOCTYPE html>
<html>
<head>
    <title>Painel Admin - Licencas v2.0</title>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 {
            color: #667eea;
            margin-bottom: 10px;
            text-align: center;
            font-size: 2.5em;
        }
        .version {
            text-align: center;
            color: #999;
            margin-bottom: 30px;
        }
        .form-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 30px;
        }
        .form-group { margin-bottom: 20px; }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }
        input, select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 16px;
            transition: border 0.3s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 30px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            font-weight: 600;
            transition: transform 0.2s;
            margin-right: 10px;
        }
        button:hover { transform: translateY(-2px); }
        .keys-output {
            background: #1e1e1e;
            color: #0f0;
            padding: 20px;
            border-radius: 10px;
            font-family: 'Courier New', monospace;
            margin-top: 20px;
            min-height: 100px;
            max-height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
        }
        .stat-number { font-size: 2.5em; font-weight: bold; margin: 10px 0; }
        .stat-label { font-size: 1.1em; opacity: 0.9; }
        .logs-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 15px;
            margin-top: 20px;
        }
        .log-item {
            background: white;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .log-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
            font-weight: 600;
        }
        .log-details { color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Painel de Licencas</h1>
        <div class="version">v2.0 - Sistema Proxy Seguro</div>

        <div class="stats" id="stats">
            <div class="stat-card">
                <div class="stat-label">Total de Keys</div>
                <div class="stat-number" id="total-keys">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Keys Ativas</div>
                <div class="stat-number" id="keys-ativas">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Keys Pendentes</div>
                <div class="stat-number" id="keys-pendentes">-</div>
            </div>
        </div>

        <div class="form-section">
            <h2>Gerar Novas Keys</h2>
            <div class="form-group">
                <label>Senha Admin:</label>
                <input type="password" id="senha" placeholder="Digite a senha admin">
            </div>
            <div class="form-group">
                <label>Tipo de Licenca:</label>
                <select id="tipo">
                    <option value="1d">1 Dia (Teste)</option>
                    <option value="7d">7 Dias</option>
                    <option value="30d" selected>30 Dias</option>
                    <option value="90d">90 Dias</option>
                    <option value="perm">Permanente (VIP)</option>
                </select>
            </div>
            <div class="form-group">
                <label>Quantidade:</label>
                <input type="number" id="quantidade" value="1" min="1" max="100">
            </div>
            <button onclick="gerarKeys()">Gerar Keys</button>
            <button onclick="carregarStats()" style="background: #28a745;">Atualizar Stats</button>

            <div class="keys-output" id="output">Aguardando...</div>
        </div>

        <div class="logs-section">
            <h2>Ultimos Logs (50)</h2>
            <div id="logs-container">
                <p style="text-align: center; color: #999;">Carregando logs...</p>
            </div>
        </div>
    </div>

<script>
function gerarKeys() {
    const senha = document.getElementById('senha').value;
    const tipo = document.getElementById('tipo').value;
    const quantidade = document.getElementById('quantidade').value;
    const output = document.getElementById('output');

    if (!senha) {
        output.textContent = 'ERRO: Digite a senha admin!';
        return;
    }

    output.textContent = 'Gerando keys...';

    fetch('/gerar-key', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({senha, tipo, quantidade: parseInt(quantidade)})
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            let txt = `${data.quantidade} key(s) gerada(s) com sucesso!\n\n`;
            txt += `TIPO: ${data.tipo}\n\n`;
            txt += `KEYS:\n`;
            data.keys.forEach(key => { txt += key + '\n'; });
            output.textContent = txt;
            carregarStats();
        } else {
            output.textContent = `ERRO: ${data.error}`;
        }
    })
    .catch(err => {
        output.textContent = `ERRO: ${err}`;
    });
}

function carregarStats() {
    const senha = document.getElementById('senha').value;
    if (!senha) {
        alert('Digite a senha admin primeiro!');
        return;
    }

    fetch('/stats', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({senha})
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            document.getElementById('total-keys').textContent = data.stats.total_keys;
            document.getElementById('keys-ativas').textContent = data.stats.keys_ativas;
            document.getElementById('keys-pendentes').textContent = data.stats.keys_pendentes;

            const logsContainer = document.getElementById('logs-container');
            if (!data.logs || data.logs.length === 0) {
                logsContainer.innerHTML = '<p style="text-align: center; color: #999;">Nenhum log ainda</p>';
            } else {
                logsContainer.innerHTML = '';
                data.logs.forEach(log => {
                    const logDiv = document.createElement('div');
                    logDiv.className = 'log-item';
                    logDiv.innerHTML = `
                        <div class="log-header">
                            <span>${log.acao}</span>
                            <span>${log.data}</span>
                        </div>
                        <div class="log-details">
                            HWID: ${log.hwid} | ${log.detalhes}
                        </div>
                    `;
                    logsContainer.appendChild(logDiv);
                });
            }
        } else {
            alert('Erro ao carregar stats: ' + data.error);
        }
    })
    .catch(err => {
        alert('Erro ao carregar stats: ' + err);
    });
}
</script>
</body>
</html>
"""
    return render_template_string(html)


# =====================================================
# EXECUCAO
# =====================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SISTEMA DE LICENCAS v2.0 - FREE FIRE BOT")
    print("=" * 60)

    init_db()

    print("Rotas disponiveis:")
    print("  POST /gerar-key")
    print("  POST /ativar-key")
    print("  POST /validar-licenca")
    print("  POST /proxy-criar-sala")
    print("  POST /proxy-info-sala")
    print("  POST /proxy-iniciar-partida")
    print("  GET  /admin")
    print("  POST /stats")
    print("Sistema proxy ativo. API Key protegida no servidor.")
    print("ATENCAO: MUDE A SENHA ADMIN E A API KEY (ou use Variables no Railway).")
    print("=" * 60)

    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
