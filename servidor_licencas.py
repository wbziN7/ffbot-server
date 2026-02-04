from flask import Flask, jsonify, request, render_template_string
import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta
import json

app = Flask(__name__)

# Senha do admin (MUDE ISSO!)
ADMIN_PASSWORD = "Wb03122008!"

# =====================================================
# BANCO DE DADOS
# =====================================================

def init_db():
    """Inicializa o banco de dados"""
    conn = sqlite3.connect('licencas.db')
    c = conn.cursor()
    
    # Tabela de keys
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (key TEXT PRIMARY KEY,
                  tipo TEXT NOT NULL,
                  dias INTEGER NOT NULL,
                  ativada INTEGER DEFAULT 0,
                  hwid TEXT,
                  nome_discord TEXT,
                  telegram_id TEXT,
                  data_ativacao TEXT,
                  data_expiracao TEXT,
                  data_criacao TEXT NOT NULL)''')
    
    conn.commit()
    conn.close()
    print("✅ Banco de dados inicializado!")

# =====================================================
# FUNÇÕES DE LICENÇA
# =====================================================

def gerar_key_unica():
    """Gera uma key única"""
    return secrets.token_hex(16).upper()

def calcular_expiracao(dias):
    """Calcula data de expiração"""
    if dias == -1:  # Permanente
        return "PERMANENTE"
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")

def verificar_expiracao(data_expiracao):
    """Verifica se a licença expirou"""
    if data_expiracao == "PERMANENTE":
        return False
    
    data_exp = datetime.strptime(data_expiracao, "%Y-%m-%d %H:%M:%S")
    return datetime.now() > data_exp

# =====================================================
# ROTAS DA API
# =====================================================

@app.route('/')
def home():
    """Página inicial"""
    return jsonify({
        "status": "online",
        "sistema": "API de Licenças - Free Fire Bot",
        "rotas": {
            "POST /gerar-key": "Gera uma nova key",
            "POST /ativar-key": "Ativa uma key no HWID",
            "POST /validar-licenca": "Valida se licença está ativa",
            "POST /listar-licencas": "Lista todas as licenças",
            "GET /admin": "Painel administrativo"
        }
    })

@app.route('/gerar-key', methods=['POST'])
def gerar_key():
    """
    Gera uma nova key
    Body: {"senha": "admin123", "tipo": "1d|7d|30d|90d|perm", "quantidade": 1}
    """
    try:
        data = request.json
        senha = data.get('senha')
        tipo = data.get('tipo', '1d')
        quantidade = data.get('quantidade', 1)
        
        # Verificar senha admin
        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401
        
        # Mapear tipo para dias
        tipos_dias = {
            '1d': 1,
            '7d': 7,
            '30d': 30,
            '90d': 90,
            'perm': -1
        }
        
        if tipo not in tipos_dias:
            return jsonify({"success": False, "error": "Tipo inválido"}), 400
        
        dias = tipos_dias[tipo]
        
        # Gerar keys
        keys_geradas = []
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        for _ in range(quantidade):
            key = gerar_key_unica()
            data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            c.execute('''INSERT INTO keys (key, tipo, dias, data_criacao)
                        VALUES (?, ?, ?, ?)''',
                     (key, tipo, dias, data_criacao))
            
            keys_geradas.append(key)
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "keys": keys_geradas,
            "tipo": tipo,
            "quantidade": quantidade
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/ativar-key', methods=['POST'])
def ativar_key():
    """
    Ativa uma key no HWID do usuário
    Body: {"key": "ABC123...", "hwid": "HWID-DO-PC", "nome_discord": "User#1234", "telegram_id": "123456"}
    """
    try:
        data = request.json
        key = data.get('key', '').upper().strip()
        hwid = data.get('hwid', '').strip()
        nome_discord = data.get('nome_discord', '').strip()
        telegram_id = data.get('telegram_id', '').strip()
        
        if not key or not hwid:
            return jsonify({"success": False, "error": "Key e HWID são obrigatórios"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        # Buscar key
        c.execute('SELECT * FROM keys WHERE key = ?', (key,))
        resultado = c.fetchone()
        
        if not resultado:
            conn.close()
            return jsonify({"success": False, "error": "Key não encontrada"}), 404
        
        # Desempacotar resultado com novos campos
        key_db, tipo, dias, ativada, hwid_db, nome_disc_db, tg_id_db, data_ativ, data_exp, data_cria = resultado
        
        # Verificar se já foi ativada
        if ativada == 1:
            conn.close()
            return jsonify({"success": False, "error": "Key já foi ativada em outro PC"}), 403
        
        # Ativar key
        data_ativacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data_expiracao = calcular_expiracao(dias)
        
        c.execute('''UPDATE keys 
                    SET ativada = 1, hwid = ?, nome_discord = ?, telegram_id = ?, 
                        data_ativacao = ?, data_expiracao = ?
                    WHERE key = ?''',
                 (hwid, nome_discord, telegram_id, data_ativacao, data_expiracao, key))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Key ativada com sucesso!",
            "tipo": tipo,
            "data_expiracao": data_expiracao
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/validar-licenca', methods=['POST'])
def validar_licenca():
    """
    Valida se uma licença está ativa
    Body: {"hwid": "HWID-DO-PC"}
    """
    try:
        data = request.json
        hwid = data.get('hwid', '').strip()
        
        if not hwid:
            return jsonify({"success": False, "error": "HWID é obrigatório"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        # Buscar licença ativa no HWID
        c.execute('SELECT * FROM keys WHERE hwid = ? AND ativada = 1', (hwid,))
        resultado = c.fetchone()
        
        conn.close()
        
        if not resultado:
            return jsonify({
                "success": False,
                "valida": False,
                "error": "Nenhuma licença encontrada para este PC"
            }), 404
        
        key_db, tipo, dias, ativada, hwid_db, nome_discord, telegram_id, data_ativ, data_exp, data_cria = resultado
        
        # Verificar se expirou
        if verificar_expiracao(data_exp):
            return jsonify({
                "success": True,
                "valida": False,
                "error": "Licença expirada",
                "data_expiracao": data_exp
            })
        
        return jsonify({
            "success": True,
            "valida": True,
            "tipo": tipo,
            "data_expiracao": data_exp
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/listar-licencas', methods=['POST'])
def listar_licencas():
    """Lista todas as licenças com detalhes"""
    try:
        data = request.json
        senha = data.get('senha')
        
        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        c.execute('SELECT * FROM keys ORDER BY data_criacao DESC')
        resultados = c.fetchall()
        
        conn.close()
        
        licencas = []
        total = len(resultados)
        ativas = 0
        pendentes = 0
        expiradas = 0
        
        for row in resultados:
            key, tipo, dias, ativada, hwid, nome_discord, telegram_id, data_ativ, data_exp, data_cria = row
            
            # Calcular dias restantes
            dias_restantes = "N/A"
            status = "Pendente"
            status_color = "gray"
            
            if ativada == 1:
                if data_exp == "PERMANENTE":
                    dias_restantes = "∞"
                    status = "Ativa"
                    status_color = "green"
                    ativas += 1
                else:
                    try:
                        data_expiracao_obj = datetime.strptime(data_exp, "%Y-%m-%d %H:%M:%S")
                        dias_faltam = (data_expiracao_obj - datetime.now()).days
                        
                        if dias_faltam < 0:
                            dias_restantes = "Expirada"
                            status = "Expirada"
                            status_color = "red"
                            expiradas += 1
                        else:
                            dias_restantes = f"{dias_faltam}d"
                            status = "Ativa"
                            status_color = "green"
                            ativas += 1
                    except:
                        dias_restantes = "Erro"
                        status = "Erro"
                        status_color = "orange"
            else:
                pendentes += 1
            
            licencas.append({
                'key': key,
                'tipo': tipo,
                'status': status,
                'status_color': status_color,
                'nome_discord': nome_discord or "N/A",
                'telegram_id': telegram_id or "N/A",
                'hwid': hwid[:20] + "..." if hwid else "N/A",
                'dias_restantes': dias_restantes,
                'data_ativacao': data_ativ or "N/A",
                'data_expiracao': data_exp or "N/A",
                'data_criacao': data_cria
            })
        
        return jsonify({
            "success": True,
            "licencas": licencas,
            "stats": {
                "total": total,
                "ativas": ativas,
                "pendentes": pendentes,
                "expiradas": expiradas
            }
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/deletar-key', methods=['POST'])
def deletar_key():
    """Deleta uma key completamente"""
    try:
        data = request.json
        senha = data.get('senha')
        key = data.get('key', '').upper().strip()
        
        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401
        
        if not key:
            return jsonify({"success": False, "error": "Key é obrigatória"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        c.execute('DELETE FROM keys WHERE key = ?', (key,))
        
        if c.rowcount == 0:
            conn.close()
            return jsonify({"success": False, "error": "Key não encontrada"}), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Key deletada com sucesso!"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/desativar-key', methods=['POST'])
def desativar_key():
    """Desativa uma key (libera para uso em outro PC)"""
    try:
        data = request.json
        senha = data.get('senha')
        key = data.get('key', '').upper().strip()
        
        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401
        
        if not key:
            return jsonify({"success": False, "error": "Key é obrigatória"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        c.execute('''UPDATE keys 
                    SET ativada = 0, hwid = NULL, nome_discord = NULL, 
                        telegram_id = NULL, data_ativacao = NULL, data_expiracao = NULL
                    WHERE key = ?''', (key,))
        
        if c.rowcount == 0:
            conn.close()
            return jsonify({"success": False, "error": "Key não encontrada"}), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Key desativada! Agora pode ser usada novamente."
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/admin')
def admin_panel():
    """Painel administrativo"""
    html = '''
<!DOCTYPE html>
<html>
<head>
    <title>Painel Admin - Licenças</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            margin-bottom: 30px;
            text-align: center;
            font-size: 2.5em;
        }
        h2 {
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        .form-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
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
        button:hover {
            transform: translateY(-2px);
        }
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
        .stat-number {
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }
        .stat-label {
            font-size: 1.1em;
            opacity: 0.9;
        }
        .table-container {
            overflow-x: auto;
            margin-top: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border-radius: 10px;
            overflow: hidden;
        }
        th {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
            font-size: 14px;
        }
        td {
            padding: 12px 15px;
            border-bottom: 1px solid #f0f0f0;
            font-size: 13px;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: inline-block;
        }
        .status-green {
            background: #d4edda;
            color: #155724;
        }
        .status-red {
            background: #f8d7da;
            color: #721c24;
        }
        .status-gray {
            background: #e2e3e5;
            color: #383d41;
        }
        .key-cell {
            font-family: 'Courier New', monospace;
            font-size: 11px;
            color: #667eea;
            font-weight: 600;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #667eea;
            font-size: 18px;
        }
        .btn-small {
            padding: 8px 15px;
            font-size: 14px;
            margin: 0 3px;
            cursor: pointer;
            border: none;
            border-radius: 5px;
            transition: all 0.2s;
        }
        .btn-warning {
            background: #ffc107;
            color: #000;
        }
        .btn-warning:hover {
            background: #ffb300;
            transform: scale(1.05);
        }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover {
            background: #c82333;
            transform: scale(1.05);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 Painel de Licenças</h1>
        
        <div class="stats" id="stats">
            <div class="stat-card">
                <div class="stat-label">Total de Keys</div>
                <div class="stat-number" id="total-keys">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Keys Ativas</div>
                <div class="stat-number" id="keys-ativas">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Keys Pendentes</div>
                <div class="stat-number" id="keys-pendentes">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Keys Expiradas</div>
                <div class="stat-number" id="keys-expiradas">0</div>
            </div>
        </div>
        
        <div class="form-section">
            <h2>🔑 Gerar Novas Keys</h2>
            <div class="form-group">
                <label>Senha Admin:</label>
                <input type="password" id="senha" placeholder="Digite a senha admin">
            </div>
            <div class="form-group">
                <label>Tipo de Licença:</label>
                <select id="tipo">
                    <option value="1d">1 Dia</option>
                    <option value="7d">7 Dias</option>
                    <option value="30d" selected>30 Dias</option>
                    <option value="90d">90 Dias</option>
                    <option value="perm">Permanente</option>
                </select>
            </div>
            <div class="form-group">
                <label>Quantidade:</label>
                <input type="number" id="quantidade" value="1" min="1" max="100">
            </div>
            <button onclick="gerarKeys()">🚀 Gerar Keys</button>
            
            <div class="keys-output" id="output">
Aguardando geração de keys...
            </div>
        </div>
        
        <div class="form-section">
            <h2>📊 Lista de Licenças</h2>
            <button onclick="carregarLicencas()">🔄 Atualizar Lista</button>
            
            <div class="table-container" id="tabela-container">
                <div class="loading">Clique em "Atualizar Lista" para carregar...</div>
            </div>
        </div>
    </div>
    
    <script>
        let senhaGlobal = '';
        
        function gerarKeys() {
            const senha = document.getElementById('senha').value;
            const tipo = document.getElementById('tipo').value;
            const quantidade = document.getElementById('quantidade').value;
            const output = document.getElementById('output');
            
            if (!senha) {
                output.innerHTML = '❌ ERRO: Digite a senha admin!';
                return;
            }
            
            senhaGlobal = senha;
            output.innerHTML = '⏳ Gerando keys...';
            
            fetch('/gerar-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha, tipo, quantidade: parseInt(quantidade)})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ ${data.quantidade} key(s) gerada(s) com sucesso!\\n\\n`;
                    output.innerHTML += `📋 TIPO: ${data.tipo}\\n\\n`;
                    output.innerHTML += '🔑 KEYS:\\n';
                    data.keys.forEach(key => {
                        output.innerHTML += key + '\\n';
                    });
                    carregarLicencas();
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => {
                output.innerHTML = `❌ ERRO: ${err}`;
            });
        }
        
        function carregarLicencas() {
            const senha = senhaGlobal || document.getElementById('senha').value;
            const container = document.getElementById('tabela-container');
            
            if (!senha) {
                container.innerHTML = '<div class="loading">❌ Digite a senha admin primeiro!</div>';
                return;
            }
            
            container.innerHTML = '<div class="loading">⏳ Carregando licenças...</div>';
            
            fetch('/listar-licencas', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Atualizar stats
                    document.getElementById('total-keys').innerText = data.stats.total;
                    document.getElementById('keys-ativas').innerText = data.stats.ativas;
                    document.getElementById('keys-pendentes').innerText = data.stats.pendentes;
                    document.getElementById('keys-expiradas').innerText = data.stats.expiradas;
                    
                    // Criar tabela
                    if (data.licencas.length === 0) {
                        container.innerHTML = '<div class="loading">Nenhuma licença cadastrada ainda.</div>';
                        return;
                    }
                    
                    let html = '<table><thead><tr>';
                    html += '<th>Status</th>';
                    html += '<th>Discord</th>';
                    html += '<th>Telegram</th>';
                    html += '<th>Key</th>';
                    html += '<th>Tipo</th>';
                    html += '<th>Dias Restantes</th>';
                    html += '<th>Data Ativação</th>';
                    html += '<th>Expira em</th>';
                    html += '<th>Ações</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.licencas.forEach(lic => {
                        const statusClass = lic.status_color === 'green' ? 'status-green' : 
                                          lic.status_color === 'red' ? 'status-red' : 'status-gray';
                        
                        html += '<tr>';
                        html += `<td><span class="status-badge ${statusClass}">${lic.status}</span></td>`;
                        html += `<td>${lic.nome_discord}</td>`;
                        html += `<td>${lic.telegram_id}</td>`;
                        html += `<td class="key-cell">${lic.key}</td>`;
                        html += `<td>${lic.tipo}</td>`;
                        html += `<td><strong>${lic.dias_restantes}</strong></td>`;
                        html += `<td>${lic.data_ativacao}</td>`;
                        html += `<td>${lic.data_expiracao}</td>`;
                        html += `<td style="white-space: nowrap;">`;
                        html += `<button class="btn-small btn-warning" onclick="desativarKey('${lic.key}')" title="Desativar (libera para usar novamente)">🔄</button> `;
                        html += `<button class="btn-small btn-danger" onclick="deletarKey('${lic.key}')" title="Deletar permanentemente">🗑️</button>`;
                        html += `</td>`;
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = `<div class="loading">❌ ${data.error}</div>`;
                }
            })
            .catch(err => {
                container.innerHTML = `<div class="loading">❌ Erro: ${err}</div>`;
            });
        }
        
        function desativarKey(key) {
            if (!confirm(`Deseja DESATIVAR a key ${key}?\\n\\nIsso vai liberar ela para ser usada novamente em outro PC.`)) {
                return;
            }
            
            const senha = senhaGlobal || document.getElementById('senha').value;
            
            fetch('/desativar-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha, key})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ ' + data.message);
                    carregarLicencas();
                } else {
                    alert('❌ ' + data.error);
                }
            })
            .catch(err => {
                alert('❌ Erro: ' + err);
            });
        }
        
        function deletarKey(key) {
            if (!confirm(`⚠️ ATENÇÃO!\\n\\nDeseja DELETAR PERMANENTEMENTE a key ${key}?\\n\\nIsso NÃO PODE ser desfeito!`)) {
                return;
            }
            
            const senha = senhaGlobal || document.getElementById('senha').value;
            
            fetch('/deletar-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha, key})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ ' + data.message);
                    carregarLicencas();
                } else {
                    alert('❌ ' + data.error);
                }
            })
            .catch(err => {
                alert('❌ Erro: ' + err);
            });
        }
    </script>
</body>
</html>
    '''
    return render_template_string(html)

# =====================================================
# EXECUÇÃO
# =====================================================

if __name__ == '__main__':
    print("="*60)
    print("🚀 SISTEMA DE LICENÇAS - FREE FIRE BOT")
    print("="*60)
    
    # Inicializar banco
    init_db()
    
    print("\n📡 Rotas disponíveis:")
    print("  POST /gerar-key - Gera novas keys")
    print("  POST /ativar-key - Ativa uma key")
    print("  POST /validar-licenca - Valida licença")
    print("  POST /listar-licencas - Lista todas as licenças")
    print("  POST /deletar-key - Deleta uma key permanentemente")
    print("  POST /desativar-key - Desativa uma key (libera para reuso)")
    print("  GET /admin - Painel administrativo")
    print("\n🔐 Senha admin: Wb03122008!")
    print("⚠️  MUDE A SENHA NA LINHA 11 DO CÓDIGO!")
    print("\n" + "="*60)
    
    # Railway fornece a porta via variável de ambiente
    import os
    port = int(os.environ.get('PORT', 5000))
    
    app.run(debug=False, host='0.0.0.0', port=port)
