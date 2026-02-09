from flask import Flask, jsonify, request, render_template_string
import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta
import json
import requests
import time
import os

app = Flask(__name__)

# Senha do admin (MUDE ISSO!)
ADMIN_PASSWORD = "Wb03122008!"

# Configurações da API SalasFF
API_KEY = "46qr8zgei33wpudgimsc"
API_BASE_URL = "https://salasff.com"

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
    
    # Tabela de atalhos/modos salvos
    c.execute('''CREATE TABLE IF NOT EXISTS atalhos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  nome TEXT NOT NULL,
                  salaid TEXT NOT NULL,
                  senha TEXT NOT NULL,
                  tipo TEXT DEFAULT 'publico',
                  criado_em TEXT NOT NULL)''')
    
    # Tabela de salas ativas
    c.execute('''CREATE TABLE IF NOT EXISTS salas_ativas
                 (pedidoid TEXT PRIMARY KEY,
                  salaid TEXT,
                  senha TEXT,
                  nome_modo TEXT,
                  status INTEGER DEFAULT 1,
                  url_inicio TEXT,
                  criado_em TEXT NOT NULL,
                  atualizado_em TEXT)''')
    
    conn.commit()
    conn.close()
    print("✅ Banco de dados inicializado!")

# =====================================================
# FUNÇÕES DA API SALASFF
# =====================================================

def listar_modos_api():
    """Lista todos os modos disponíveis na API"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/modos",
            params={"key": API_KEY},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return {
                    "success": True,
                    "modos": data.get("modos", []),
                    "modos_publicos": data.get("modos_publicos", []),
                    "saldo": data.get("salas", 0)
                }
        
        return {"success": False, "error": "Erro ao buscar modos"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def criar_sala_api(salaid, senha=None, callback_url=None):
    """Cria uma sala via API"""
    try:
        payload = {
            "key": API_KEY,
            "salaid": salaid
        }
        
        if senha:
            payload["senha"] = senha
        
        if callback_url:
            payload["callback_url"] = callback_url
        
        response = requests.post(
            f"{API_BASE_URL}/criar",
            json=payload,
            timeout=15
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def consultar_sala_api(pedidoid):
    """Consulta status de uma sala"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/info",
            params={"pedidoid": pedidoid},
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def iniciar_sala_api(pedidoid):
    """Inicia uma sala (força início imediato)"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/iniciar",
            params={"key": API_KEY, "pedidoid": pedidoid},
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def expulsar_jogador_api(pedidoid, jogador_id):
    """Expulsa um jogador da sala"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/expulsar",
            params={"key": API_KEY, "pedidoid": pedidoid, "jogador_id": jogador_id},
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
# ROTAS DA API (LICENÇAS)
# =====================================================

@app.route('/')
def home():
    """Página inicial"""
    return jsonify({
        "status": "online",
        "sistema": "API de Licenças + Bot Free Fire",
        "versao": "2.0",
        "rotas": {
            "Licenças": {
                "POST /gerar-key": "Gera uma nova key",
                "POST /ativar-key": "Ativa uma key no HWID",
                "POST /validar-licenca": "Valida se licença está ativa",
                "POST /listar-licencas": "Lista todas as licenças",
                "GET /admin": "Painel administrativo"
            },
            "Salas FF": {
                "GET /api/modos": "Lista modos disponíveis",
                "POST /api/criar-sala": "Cria uma sala",
                "GET /api/consultar-sala": "Consulta status da sala",
                "POST /api/iniciar-sala": "Força início da sala",
                "POST /api/expulsar": "Expulsa jogador"
            },
            "Atalhos": {
                "GET /api/atalhos": "Lista atalhos salvos",
                "POST /api/salvar-atalho": "Salva novo atalho",
                "DELETE /api/deletar-atalho": "Deleta atalho"
            }
        }
    })

@app.route('/gerar-key', methods=['POST'])
def gerar_key():
    """Gera uma nova key"""
    try:
        data = request.json
        senha = data.get('senha')
        tipo = data.get('tipo', '1d')
        quantidade = data.get('quantidade', 1)
        
        if senha != ADMIN_PASSWORD:
            return jsonify({"success": False, "error": "Senha incorreta"}), 401
        
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
    """Ativa uma key no HWID do usuário"""
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
        
        c.execute('SELECT * FROM keys WHERE key = ?', (key,))
        resultado = c.fetchone()
        
        if not resultado:
            conn.close()
            return jsonify({"success": False, "error": "Key não encontrada"}), 404
        
        key_db, tipo, dias, ativada, hwid_db, nome_disc_db, tg_id_db, data_ativ, data_exp, data_cria = resultado
        
        if ativada == 1:
            conn.close()
            return jsonify({"success": False, "error": "Key já foi ativada em outro PC"}), 403
        
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
    """Valida se uma licença está ativa"""
    try:
        data = request.json
        hwid = data.get('hwid', '').strip()
        
        if not hwid:
            return jsonify({"success": False, "error": "HWID é obrigatório"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
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
            "data_expiracao": data_exp,
            "api_key": API_KEY
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/listar-licencas', methods=['POST'])
def listar_licencas():
    """Lista todas as licenças"""
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
    """Deleta uma key"""
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
    """Desativa uma key"""
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

# =====================================================
# ROTAS DA API (SALAS FREE FIRE)
# =====================================================

@app.route('/api/modos', methods=['GET'])
def api_modos():
    """Lista todos os modos disponíveis"""
    resultado = listar_modos_api()
    return jsonify(resultado)

@app.route('/api/criar-sala', methods=['POST'])
def api_criar_sala():
    """Cria uma nova sala"""
    try:
        data = request.json
        salaid = data.get('salaid')
        senha = data.get('senha', '')
        callback_url = data.get('callback_url')
        nome_modo = data.get('nome_modo', 'Sala Personalizada')
        
        if not salaid:
            return jsonify({"success": False, "error": "salaid é obrigatório"}), 400
        
        resultado = criar_sala_api(salaid, senha, callback_url)
        
        # Salvar no banco se sucesso
        if resultado.get('success'):
            conn = sqlite3.connect('licencas.db')
            c = conn.cursor()
            
            pedidoid = resultado.get('pedidoid', '')
            url_inicio = resultado.get('urlstart', '')
            criado_em = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            c.execute('''INSERT INTO salas_ativas 
                        (pedidoid, salaid, senha, nome_modo, url_inicio, criado_em)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     (pedidoid, salaid, senha, nome_modo, url_inicio, criado_em))
            
            conn.commit()
            conn.close()
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/consultar-sala', methods=['GET'])
def api_consultar_sala():
    """Consulta status de uma sala"""
    pedidoid = request.args.get('pedidoid')
    
    if not pedidoid:
        return jsonify({"success": False, "error": "pedidoid é obrigatório"}), 400
    
    resultado = consultar_sala_api(pedidoid)
    
    # Atualizar status no banco
    if resultado.get('success'):
        try:
            conn = sqlite3.connect('licencas.db')
            c = conn.cursor()
            
            status = resultado.get('status', 0)
            atualizado_em = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            c.execute('''UPDATE salas_ativas 
                        SET status = ?, atualizado_em = ?
                        WHERE pedidoid = ?''',
                     (status, atualizado_em, pedidoid))
            
            conn.commit()
            conn.close()
        except:
            pass
    
    return jsonify(resultado)

@app.route('/api/iniciar-sala', methods=['POST'])
def api_iniciar_sala():
    """Força início de uma sala"""
    try:
        data = request.json
        pedidoid = data.get('pedidoid')
        
        if not pedidoid:
            return jsonify({"success": False, "error": "pedidoid é obrigatório"}), 400
        
        resultado = iniciar_sala_api(pedidoid)
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/expulsar', methods=['POST'])
def api_expulsar():
    """Expulsa um jogador da sala"""
    try:
        data = request.json
        pedidoid = data.get('pedidoid')
        jogador_id = data.get('jogador_id')
        
        if not pedidoid or not jogador_id:
            return jsonify({"success": False, "error": "pedidoid e jogador_id são obrigatórios"}), 400
        
        resultado = expulsar_jogador_api(pedidoid, jogador_id)
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/salas-ativas', methods=['GET'])
def api_salas_ativas():
    """Lista salas ativas criadas"""
    try:
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        c.execute('''SELECT * FROM salas_ativas 
                    WHERE status < 4 
                    ORDER BY criado_em DESC 
                    LIMIT 20''')
        
        resultados = c.fetchall()
        conn.close()
        
        salas = []
        for row in resultados:
            pedidoid, salaid, senha, nome_modo, status, url_inicio, criado_em, atualizado_em = row
            
            status_msg = {
                0: "Não encontrada",
                1: "Processando",
                2: "Criando sala",
                3: "Sala criada",
                4: "Sala finalizada",
                5: "Saldo insuficiente",
                6: "Erro no servidor",
                7: "Erro ao criar sala"
            }.get(status, f"Status {status}")
            
            salas.append({
                'pedidoid': pedidoid,
                'salaid': salaid,
                'senha': senha,
                'nome_modo': nome_modo,
                'status': status,
                'status_msg': status_msg,
                'url_inicio': url_inicio,
                'criado_em': criado_em,
                'atualizado_em': atualizado_em or "N/A"
            })
        
        return jsonify({
            "success": True,
            "salas": salas,
            "total": len(salas)
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================================
# ROTAS DE ATALHOS
# =====================================================

@app.route('/api/atalhos', methods=['GET'])
def api_listar_atalhos():
    """Lista atalhos salvos"""
    try:
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        c.execute('SELECT * FROM atalhos ORDER BY nome')
        resultados = c.fetchall()
        
        conn.close()
        
        atalhos = []
        for row in resultados:
            id_atalho, nome, salaid, senha, tipo, criado_em = row
            atalhos.append({
                'id': id_atalho,
                'nome': nome,
                'salaid': salaid,
                'senha': senha,
                'tipo': tipo,
                'criado_em': criado_em
            })
        
        return jsonify({
            "success": True,
            "atalhos": atalhos,
            "total": len(atalhos)
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/salvar-atalho', methods=['POST'])
def api_salvar_atalho():
    """Salva um novo atalho"""
    try:
        data = request.json
        nome = data.get('nome', '').strip()
        salaid = data.get('salaid', '').strip()
        senha = data.get('senha', '').strip()
        tipo = data.get('tipo', 'publico')
        
        if not nome or not salaid:
            return jsonify({"success": False, "error": "Nome e salaid são obrigatórios"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        criado_em = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute('''INSERT INTO atalhos (nome, salaid, senha, tipo, criado_em)
                    VALUES (?, ?, ?, ?, ?)''',
                 (nome, salaid, senha, tipo, criado_em))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Atalho '{nome}' salvo com sucesso!"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deletar-atalho', methods=['DELETE'])
def api_deletar_atalho():
    """Deleta um atalho"""
    try:
        id_atalho = request.args.get('id')
        
        if not id_atalho:
            return jsonify({"success": False, "error": "ID do atalho é obrigatório"}), 400
        
        conn = sqlite3.connect('licencas.db')
        c = conn.cursor()
        
        c.execute('DELETE FROM atalhos WHERE id = ?', (id_atalho,))
        
        if c.rowcount == 0:
            conn.close()
            return jsonify({"success": False, "error": "Atalho não encontrado"}), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Atalho deletado com sucesso!"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================================
# PAINEL ADMINISTRATIVO
# =====================================================

@app.route('/admin')
def admin_panel():
    """Painel administrativo completo"""
    html = '''
<!DOCTYPE html>
<html>
<head>
    <title>Painel Admin - Bot Free Fire</title>
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
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            border-bottom: 2px solid #ddd;
        }
        .tab {
            padding: 15px 30px;
            background: #f8f9fa;
            border: none;
            border-radius: 10px 10px 0 0;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s;
        }
        .tab.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
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
        .output {
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
        .status-green { background: #d4edda; color: #155724; }
        .status-red { background: #f8d7da; color: #721c24; }
        .status-gray { background: #e2e3e5; color: #383d41; }
        .status-yellow { background: #fff3cd; color: #856404; }
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
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-success {
            background: #28a745;
            color: white;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #667eea;
            font-size: 18px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎮 Painel Admin - Bot Free Fire</h1>
        
        <div class="tabs">
            <button class="tab active" onclick="mudaTab('licencas')">🔐 Licenças</button>
            <button class="tab" onclick="mudaTab('salas')">🎯 Salas FF</button>
            <button class="tab" onclick="mudaTab('atalhos')">⚡ Atalhos</button>
        </div>
        
        <!-- TAB LICENÇAS -->
        <div id="tab-licencas" class="tab-content active">
            <div class="stats" id="stats-licencas">
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
                
                <div class="output" id="output-keys">Aguardando geração de keys...</div>
            </div>
            
            <div class="form-section">
                <h2>📊 Lista de Licenças</h2>
                <button onclick="carregarLicencas()">🔄 Atualizar Lista</button>
                
                <div class="table-container" id="tabela-licencas">
                    <div class="loading">Clique em "Atualizar Lista" para carregar...</div>
                </div>
            </div>
        </div>
        
        <!-- TAB SALAS -->
        <div id="tab-salas" class="tab-content">
            <div class="form-section">
                <h2>🎯 Criar Nova Sala</h2>
                <div class="form-group">
                    <label>ID da Sala (sala_id):</label>
                    <input type="text" id="salaid-criar" placeholder="Ex: 100000000000001">
                </div>
                <div class="form-group">
                    <label>Senha (opcional):</label>
                    <input type="text" id="senha-sala" placeholder="Ex: 99">
                </div>
                <div class="form-group">
                    <label>Nome do Modo:</label>
                    <input type="text" id="nome-modo" placeholder="Ex: Duelo 1v1">
                </div>
                <button onclick="criarSala()">✨ Criar Sala</button>
                <button onclick="listarModos()">📋 Ver Modos Disponíveis</button>
                
                <div class="output" id="output-sala">Aguardando criação de sala...</div>
            </div>
            
            <div class="form-section">
                <h2>🔍 Consultar/Gerenciar Sala</h2>
                <div class="form-group">
                    <label>Pedido ID:</label>
                    <input type="text" id="pedidoid-consulta" placeholder="Cole o pedido ID aqui">
                </div>
                <button onclick="consultarSala()">🔍 Consultar Status</button>
                <button onclick="iniciarSala()">🚀 Iniciar Agora</button>
                
                <div class="output" id="output-consulta">Aguardando consulta...</div>
            </div>
            
            <div class="form-section">
                <h2>👥 Expulsar Jogador</h2>
                <div class="form-group">
                    <label>Pedido ID:</label>
                    <input type="text" id="pedidoid-expulsar" placeholder="ID da sala">
                </div>
                <div class="form-group">
                    <label>ID do Jogador:</label>
                    <input type="text" id="jogador-id" placeholder="ID numérico do jogador">
                </div>
                <button onclick="expulsarJogador()">❌ Expulsar Jogador</button>
                
                <div class="output" id="output-expulsar">Aguardando expulsão...</div>
            </div>
            
            <div class="form-section">
                <h2>📜 Salas Recentes</h2>
                <button onclick="carregarSalasAtivas()">🔄 Atualizar Lista</button>
                
                <div class="table-container" id="tabela-salas">
                    <div class="loading">Clique em "Atualizar Lista" para carregar...</div>
                </div>
            </div>
        </div>
        
        <!-- TAB ATALHOS -->
        <div id="tab-atalhos" class="tab-content">
            <div class="form-section">
                <h2>⚡ Criar Novo Atalho</h2>
                <div class="form-group">
                    <label>Nome do Atalho:</label>
                    <input type="text" id="atalho-nome" placeholder="Ex: Duelo 1v1">
                </div>
                <div class="form-group">
                    <label>ID da Sala:</label>
                    <input type="text" id="atalho-salaid" placeholder="Ex: 100000000000001">
                </div>
                <div class="form-group">
                    <label>Senha:</label>
                    <input type="text" id="atalho-senha" placeholder="Ex: 99">
                </div>
                <div class="form-group">
                    <label>Tipo:</label>
                    <select id="atalho-tipo">
                        <option value="publico">Público</option>
                        <option value="personalizado">Personalizado</option>
                    </select>
                </div>
                <button onclick="salvarAtalho()">💾 Salvar Atalho</button>
                
                <div class="output" id="output-atalho">Aguardando criação de atalho...</div>
            </div>
            
            <div class="form-section">
                <h2>📋 Atalhos Salvos</h2>
                <button onclick="carregarAtalhos()">🔄 Atualizar Lista</button>
                
                <div class="table-container" id="tabela-atalhos">
                    <div class="loading">Clique em "Atualizar Lista" para carregar...</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let senhaGlobal = '';
        
        // ========== FUNÇÕES DE TAB ==========
        function mudaTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
            
            if (tab === 'licencas') carregarLicencas();
            if (tab === 'salas') carregarSalasAtivas();
            if (tab === 'atalhos') carregarAtalhos();
        }
        
        // ========== LICENÇAS ==========
        function gerarKeys() {
            const senha = document.getElementById('senha').value;
            const tipo = document.getElementById('tipo').value;
            const quantidade = document.getElementById('quantidade').value;
            const output = document.getElementById('output-keys');
            
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
                    output.innerHTML = `✅ ${data.quantidade} key(s) gerada(s)!\\n\\n`;
                    output.innerHTML += `📋 TIPO: ${data.tipo}\\n\\n🔑 KEYS:\\n`;
                    data.keys.forEach(key => output.innerHTML += key + '\\n');
                    carregarLicencas();
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function carregarLicencas() {
            const senha = senhaGlobal || document.getElementById('senha').value;
            const container = document.getElementById('tabela-licencas');
            
            if (!senha) {
                container.innerHTML = '<div class="loading">❌ Digite a senha admin primeiro!</div>';
                return;
            }
            
            container.innerHTML = '<div class="loading">⏳ Carregando...</div>';
            
            fetch('/listar-licencas', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('total-keys').innerText = data.stats.total;
                    document.getElementById('keys-ativas').innerText = data.stats.ativas;
                    document.getElementById('keys-pendentes').innerText = data.stats.pendentes;
                    document.getElementById('keys-expiradas').innerText = data.stats.expiradas;
                    
                    if (data.licencas.length === 0) {
                        container.innerHTML = '<div class="loading">Nenhuma licença cadastrada.</div>';
                        return;
                    }
                    
                    let html = '<table><thead><tr>';
                    html += '<th>Status</th><th>Discord</th><th>Telegram</th><th>Key</th>';
                    html += '<th>Tipo</th><th>Dias</th><th>Ativação</th><th>Expira</th><th>Ações</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.licencas.forEach(lic => {
                        const statusClass = lic.status_color === 'green' ? 'status-green' : 
                                          lic.status_color === 'red' ? 'status-red' : 'status-gray';
                        
                        html += '<tr>';
                        html += `<td><span class="status-badge ${statusClass}">${lic.status}</span></td>`;
                        html += `<td>${lic.nome_discord}</td>`;
                        html += `<td>${lic.telegram_id}</td>`;
                        html += `<td style="font-family: monospace; font-size: 11px;">${lic.key}</td>`;
                        html += `<td>${lic.tipo}</td>`;
                        html += `<td><strong>${lic.dias_restantes}</strong></td>`;
                        html += `<td>${lic.data_ativacao}</td>`;
                        html += `<td>${lic.data_expiracao}</td>`;
                        html += `<td><button class="btn-small btn-warning" onclick="desativarKey('${lic.key}')">🔄</button> `;
                        html += `<button class="btn-small btn-danger" onclick="deletarKey('${lic.key}')">🗑️</button></td>`;
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = `<div class="loading">❌ ${data.error}</div>`;
                }
            });
        }
        
        function desativarKey(key) {
            if (!confirm(`Desativar key ${key}?`)) return;
            
            const senha = senhaGlobal || document.getElementById('senha').value;
            
            fetch('/desativar-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha, key})
            })
            .then(res => res.json())
            .then(data => {
                alert(data.success ? '✅ ' + data.message : '❌ ' + data.error);
                if (data.success) carregarLicencas();
            });
        }
        
        function deletarKey(key) {
            if (!confirm(`⚠️ DELETAR PERMANENTEMENTE a key ${key}?`)) return;
            
            const senha = senhaGlobal || document.getElementById('senha').value;
            
            fetch('/deletar-key', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({senha, key})
            })
            .then(res => res.json())
            .then(data => {
                alert(data.success ? '✅ ' + data.message : '❌ ' + data.error);
                if (data.success) carregarLicencas();
            });
        }
        
        // ========== SALAS ==========
        function criarSala() {
            const salaid = document.getElementById('salaid-criar').value.trim();
            const senha = document.getElementById('senha-sala').value.trim();
            const nome_modo = document.getElementById('nome-modo').value.trim();
            const output = document.getElementById('output-sala');
            
            if (!salaid) {
                output.innerHTML = '❌ ERRO: Digite o ID da sala!';
                return;
            }
            
            output.innerHTML = '⏳ Criando sala...';
            
            fetch('/api/criar-sala', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({salaid, senha, nome_modo})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ SALA CRIADA!\\n\\n`;
                    output.innerHTML += `📌 Status: ${data.status}\\n`;
                    output.innerHTML += `🆔 Pedido ID: ${data.pedidoid}\\n`;
                    output.innerHTML += `🕐 Tempo: ${data.time}\\n\\n`;
                    if (data.urlstart) {
                        output.innerHTML += `🔗 URL Início: ${data.urlstart}\\n`;
                    }
                    output.innerHTML += `\\n💡 Use o Pedido ID para consultar o status!`;
                    
                    carregarSalasAtivas();
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error || 'Erro desconhecido'}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function listarModos() {
            const output = document.getElementById('output-sala');
            output.innerHTML = '⏳ Carregando modos...';
            
            fetch('/api/modos')
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ MODOS DISPONÍVEIS\\n\\n`;
                    output.innerHTML += `💰 Saldo: ${data.saldo} salas\\n\\n`;
                    
                    if (data.modos_publicos && data.modos_publicos.length > 0) {
                        output.innerHTML += `📋 MODOS PÚBLICOS:\\n`;
                        data.modos_publicos.forEach(modo => {
                            output.innerHTML += `  • ${modo.nome} (ID: ${modo.salaid}, Senha: ${modo.senha})\\n`;
                        });
                    }
                    
                    if (data.modos && data.modos.length > 0) {
                        output.innerHTML += `\\n🎨 MODOS PERSONALIZADOS:\\n`;
                        data.modos.forEach(modo => {
                            output.innerHTML += `  • ${modo.nome} (ID: ${modo.salaid}, Senha: ${modo.senha})\\n`;
                        });
                    }
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function consultarSala() {
            const pedidoid = document.getElementById('pedidoid-consulta').value.trim();
            const output = document.getElementById('output-consulta');
            
            if (!pedidoid) {
                output.innerHTML = '❌ ERRO: Digite o Pedido ID!';
                return;
            }
            
            output.innerHTML = '⏳ Consultando...';
            
            fetch(`/api/consultar-sala?pedidoid=${pedidoid}`)
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ STATUS DA SALA\\n\\n`;
                    output.innerHTML += `📊 Status: ${data.status} - ${data.msg}\\n`;
                    output.innerHTML += `🆔 Pedido ID: ${data.pedidoid}\\n`;
                    
                    if (data.sala) {
                        const sala = data.sala;
                        output.innerHTML += `\\n📋 DETALHES:\\n`;
                        output.innerHTML += `  ID Sala: ${sala.id}\\n`;
                        output.innerHTML += `  Senha: ${sala.senha}\\n`;
                        output.innerHTML += `  Nome: ${sala.nome}\\n`;
                    }
                    
                    if (data.urlstart) {
                        output.innerHTML += `\\n🔗 URL Início: ${data.urlstart}`;
                    }
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function iniciarSala() {
            const pedidoid = document.getElementById('pedidoid-consulta').value.trim();
            const output = document.getElementById('output-consulta');
            
            if (!pedidoid) {
                output.innerHTML = '❌ ERRO: Digite o Pedido ID!';
                return;
            }
            
            output.innerHTML = '⏳ Iniciando sala...';
            
            fetch('/api/iniciar-sala', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({pedidoid})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ ${data.msg}\\n\\n`;
                    output.innerHTML += `📊 Status: ${data.status}\\n`;
                    output.innerHTML += `🆔 Pedido ID: ${data.pedidoid}`;
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function expulsarJogador() {
            const pedidoid = document.getElementById('pedidoid-expulsar').value.trim();
            const jogador_id = document.getElementById('jogador-id').value.trim();
            const output = document.getElementById('output-expulsar');
            
            if (!pedidoid || !jogador_id) {
                output.innerHTML = '❌ ERRO: Preencha todos os campos!';
                return;
            }
            
            output.innerHTML = '⏳ Expulsando jogador...';
            
            fetch('/api/expulsar', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({pedidoid, jogador_id})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ ${data.msg}\\n\\n`;
                    output.innerHTML += `📊 Status: ${data.status}`;
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function carregarSalasAtivas() {
            const container = document.getElementById('tabela-salas');
            container.innerHTML = '<div class="loading">⏳ Carregando...</div>';
            
            fetch('/api/salas-ativas')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.salas.length > 0) {
                    let html = '<table><thead><tr>';
                    html += '<th>Status</th><th>Nome</th><th>Pedido ID</th><th>Sala ID</th>';
                    html += '<th>Senha</th><th>Criado em</th><th>Ações</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.salas.forEach(sala => {
                        const statusClass = sala.status === 3 ? 'status-green' : 
                                          sala.status >= 5 ? 'status-red' : 'status-yellow';
                        
                        html += '<tr>';
                        html += `<td><span class="status-badge ${statusClass}">${sala.status_msg}</span></td>`;
                        html += `<td>${sala.nome_modo}</td>`;
                        html += `<td style="font-family: monospace; font-size: 11px;">${sala.pedidoid}</td>`;
                        html += `<td>${sala.salaid}</td>`;
                        html += `<td>${sala.senha}</td>`;
                        html += `<td>${sala.criado_em}</td>`;
                        html += `<td><button class="btn-small btn-success" onclick="copiarPedidoId('${sala.pedidoid}')">📋</button></td>`;
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<div class="loading">Nenhuma sala ativa no momento.</div>';
                }
            })
            .catch(err => {
                container.innerHTML = `<div class="loading">❌ Erro: ${err}</div>`;
            });
        }
        
        function copiarPedidoId(pedidoid) {
            navigator.clipboard.writeText(pedidoid);
            alert('✅ Pedido ID copiado: ' + pedidoid);
        }
        
        // ========== ATALHOS ==========
        function salvarAtalho() {
            const nome = document.getElementById('atalho-nome').value.trim();
            const salaid = document.getElementById('atalho-salaid').value.trim();
            const senha = document.getElementById('atalho-senha').value.trim();
            const tipo = document.getElementById('atalho-tipo').value;
            const output = document.getElementById('output-atalho');
            
            if (!nome || !salaid) {
                output.innerHTML = '❌ ERRO: Preencha nome e ID da sala!';
                return;
            }
            
            output.innerHTML = '⏳ Salvando atalho...';
            
            fetch('/api/salvar-atalho', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({nome, salaid, senha, tipo})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    output.innerHTML = `✅ ${data.message}`;
                    carregarAtalhos();
                    
                    // Limpar campos
                    document.getElementById('atalho-nome').value = '';
                    document.getElementById('atalho-salaid').value = '';
                    document.getElementById('atalho-senha').value = '';
                } else {
                    output.innerHTML = `❌ ERRO: ${data.error}`;
                }
            })
            .catch(err => output.innerHTML = `❌ ERRO: ${err}`);
        }
        
        function carregarAtalhos() {
            const container = document.getElementById('tabela-atalhos');
            container.innerHTML = '<div class="loading">⏳ Carregando...</div>';
            
            fetch('/api/atalhos')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.atalhos.length > 0) {
                    let html = '<table><thead><tr>';
                    html += '<th>Nome</th><th>Tipo</th><th>Sala ID</th><th>Senha</th>';
                    html += '<th>Criado em</th><th>Ações</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.atalhos.forEach(atalho => {
                        html += '<tr>';
                        html += `<td><strong>${atalho.nome}</strong></td>`;
                        html += `<td><span class="status-badge ${atalho.tipo === 'publico' ? 'status-green' : 'status-yellow'}">${atalho.tipo}</span></td>`;
                        html += `<td>${atalho.salaid}</td>`;
                        html += `<td>${atalho.senha}</td>`;
                        html += `<td>${atalho.criado_em}</td>`;
                        html += `<td>`;
                        html += `<button class="btn-small btn-success" onclick="usarAtalho('${atalho.salaid}', '${atalho.senha}', '${atalho.nome}')">🚀</button> `;
                        html += `<button class="btn-small btn-danger" onclick="deletarAtalho(${atalho.id})">🗑️</button>`;
                        html += `</td>`;
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<div class="loading">Nenhum atalho salvo ainda.</div>';
                }
            })
            .catch(err => {
                container.innerHTML = `<div class="loading">❌ Erro: ${err}</div>`;
            });
        }
        
        function usarAtalho(salaid, senha, nome) {
            mudaTab('salas');
            
            setTimeout(() => {
                document.getElementById('salaid-criar').value = salaid;
                document.getElementById('senha-sala').value = senha;
                document.getElementById('nome-modo').value = nome;
                
                if (confirm(`🚀 Criar sala "${nome}" agora?`)) {
                    criarSala();
                }
            }, 100);
        }
        
        function deletarAtalho(id) {
            if (!confirm('Deletar este atalho?')) return;
            
            fetch(`/api/deletar-atalho?id=${id}`, {
                method: 'DELETE'
            })
            .then(res => res.json())
            .then(data => {
                alert(data.success ? '✅ ' + data.message : '❌ ' + data.error);
                if (data.success) carregarAtalhos();
            });
        }
        
        // Carregar dados inicial
        setTimeout(() => {
            carregarLicencas();
        }, 500);
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
    print("🚀 BOT FREE FIRE - SISTEMA COMPLETO v2.0")
    print("="*60)
    
    init_db()
    
    print("\n📡 Recursos disponíveis:")
    print("  ✅ Sistema de licenças")
    print("  ✅ Integração com API SalasFF")
    print("  ✅ Criação automática de salas")
    print("  ✅ Atalhos personalizados")
    print("  ✅ Painel web administrativo")
    
    print("\n🔑 Configurações:")
    print(f"  Senha admin: {ADMIN_PASSWORD}")
    print(f"  API Key: {API_KEY}")
    
    print("\n🌐 Acesse:")
    print("  Painel Admin: http://localhost:5000/admin")
    print("  API Docs: http://localhost:5000/")
    
    print("\n" + "="*60)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
