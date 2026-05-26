import os
import jwt
import random
import datetime
import threading
from flask import Flask, jsonify, request, make_response, send_from_directory
from main import app, get_db_connection
from funcao import (
        verificar_senha,
        criptografar,
        checar_senha,
        gerar_token,
        enviando_email
    )

SECRET_KEY = "segredo_super"
UPLOAD_FOLDER = os.path.join(app.config.get('UPLOAD_FOLDER', 'static/uploads'), "usuarios")

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def verificar_reuso_senha(id_usuario, senha_nova, cur):
    cur.execute("SELECT SENHA_HASH FROM HISTORICO_SENHAS WHERE ID_USUARIO = ?", (id_usuario,))
    historico = cur.fetchall()
    for (hash_antigo,) in historico[-3:]:
        if checar_senha(senha_nova, hash_antigo):
            return True
    return False


# lista de usuarios
@app.route('/usuarios', methods=['GET'])
def listar_usuarios():
    con = None
    cur = None

    try:
        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT ID_USUARIO, NOME, EMAIL, TIPO_NOME, BLOQUEADO FROM USUARIO")
        usuarios = cur.fetchall()

        resultado = []
        for u in usuarios:
            resultado.append({
                'id': u[0],
                'nome': u[1],
                'email': u[2],
                'tipo': u[3],
                'bloqueado': "Sim" if u[4] else "Não",
            })

        return jsonify(resultado), 200

    except Exception as e:
        return jsonify({'erro': str(e)}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


# buscar o usuario
@app.route('/admin/buscar_nome', methods=['GET'])
def buscar_usuario_nome():
    from main import app
    con = None
    cur = None

    token = request.cookies.get('access_token')

    if not token:
        return jsonify({'erro': 'Acesso negado. Token não fornecido.'}), 401

    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        id_quem_chamou = payload.get('id_usuario')

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT ID_TIPO FROM USUARIO WHERE ID_USUARIO = ?", (id_quem_chamou,))
        usuario_adm = cur.fetchone()

        if not usuario_adm or usuario_adm[0] != 1:
            return jsonify({'erro': 'Acesso negado. Apenas administradores podem buscar usuários.'}), 403

        nome_busca = request.args.get('nome', '')

        cur.execute("""
                    SELECT ID_USUARIO, NOME, EMAIL, TIPO_NOME, BLOQUEADO
                    FROM USUARIO
                    WHERE UPPER(NOME) LIKE UPPER(?)
                    """, (f'%{nome_busca}%',))

        usuarios = cur.fetchall()

        resultado = [
            {
                'id': u[0],
                'nome': u[1],
                'email': u[2],
                'tipo': u[3],
                'bloqueado': bool(u[4])
            } for u in usuarios
        ]

        return jsonify(resultado), 200

    except jwt.ExpiredSignatureError:
        return jsonify({'erro': 'Sua sessão expirou. Logue novamente.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'erro': 'Token inválido.'}), 401
    except Exception as e:
        return jsonify({'erro': f'Erro interno: {str(e)}'}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/criar_usuario', methods=['POST'])
def criar_usuario_novo(id_user=None):
    con = None
    cur = None

    try:
        nome = request.form.get('nome')
        email = request.form.get('email')
        senha = request.form.get('senha')
        id_tipo = int(request.form.get('id_tipo', 2))

        nome = nome.strip()
        if not nome:
            return jsonify({'erro': 'Nome é obrigatório.'}), 400

        foto = request.files.get('foto')

        if not all([nome, email, senha]):
            return jsonify({'erro': 'Nome, email e senha são obrigatórios.'}), 400

        tipo_nome = 'admin' if id_tipo == 1 else 'garcom'

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT id_usuario FROM USUARIO WHERE email=?", (email,))
        if cur.fetchone():
            return jsonify({'erro': 'Email já cadastrado.'}), 409

        erro_v = verificar_senha(senha)
        if erro_v:
            return jsonify({'erro': erro_v}), 400

        senha_hash = criptografar(senha)

        foto_caminho = None
        if foto and foto.filename:
            nome_arquivo = f"{id_user}_{foto.filename}"
            caminho_pasta = app.config['UPLOAD_FOLDER']
            caminho_completo = os.path.join(caminho_pasta, nome_arquivo)
            foto.save(caminho_completo)
            foto_caminho = f"/{caminho_pasta}/{nome_arquivo}"

        cur.execute("""
                    INSERT INTO USUARIO (nome, email, senha, id_tipo, tipo_nome, conta_confirmada, bloqueado,
                                         tentativas_login)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id_usuario
                    """, (nome, email, senha_hash, id_tipo, tipo_nome, False, False, 0))

        id_user = cur.fetchone()[0]

        # ✅ INSERT corrigido com GEN_ID
        cur.execute(
            "INSERT INTO HISTORICO_SENHAS (ID_HISTORICO, ID_USUARIO, SENHA_HASH) VALUES (GEN_ID(GEN_HISTORICO_ID, 1), ?, ?)",
            (id_user, senha_hash)
        )

        codigo = str(random.randint(100000, 999999))
        cur.execute("INSERT INTO CODIGOS (id_usuario, codigo, tipo) VALUES (?, ?, 'confirmacao')", (id_user, codigo))

        con.commit()

        threading.Thread(target=enviando_email,
                         args=(email, "Confirmação", f"Olá {nome}, seu código: {codigo}")).start()

        return jsonify({'mensagem': f'Conta de {tipo_nome} criada!', 'id_usuario': id_user, 'foto': foto_caminho}), 201

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f"Erro interno: {str(e)}"}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/reenviar_codigo_confirmacao', methods=['POST'])
def reenviar_codigo_confirmacao():
    con = None
    cur = None

    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Os dados devem ser enviados em formato JSON.'}), 400

        id_usuario = dados.get('id_usuario')
        if not id_usuario:
            return jsonify({'erro': 'ID do usuário é obrigatório.'}), 400

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT EMAIL, NOME FROM USUARIO WHERE ID_USUARIO = ?", (id_usuario,))
        usuario = cur.fetchone()
        if not usuario:
            return jsonify({'erro': 'Usuário não encontrado.'}), 404

        email, nome = usuario

        codigo = str(random.randint(100000, 999999))

        cur.execute(
            "INSERT INTO CODIGOS (id_usuario, codigo, tipo) VALUES (?, ?, 'confirmacao')",
            (id_usuario, codigo)
        )
        con.commit()

        threading.Thread(
            target=enviando_email,
            args=(email, "Confirmação de Conta", f"Olá {nome}, seu novo código de confirmação é: {codigo}")
        ).start()

        return jsonify({'mensagem': 'Código reenviado com sucesso! Verifique seu e-mail.'}), 200

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f'Erro interno: {str(e)}'}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/editar_usuario/<int:id_usuario>', methods=['PUT', 'POST'])
def editar_usuario(id_usuario):
    from main import app
    con = None
    cur = None

    token = request.cookies.get('access_token')

    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Os dados devem ser enviados em formato JSON.'}), 400

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT SENHA, NOME, EMAIL FROM USUARIO WHERE ID_USUARIO = ?", (id_usuario,))
        res = cur.fetchone()
        if not res:
            return jsonify({'erro': 'Usuário não encontrado'}), 404

        hash_atual, nome_at, email_at = res

        nome = dados.get('nome') or nome_at
        email = dados.get('email') or email_at
        senha_nova = dados.get('senha')

        # ✅ Verifica se o email já está em uso por outro usuário
        if email != email_at:
            cur.execute("SELECT ID_USUARIO FROM USUARIO WHERE EMAIL = ? AND ID_USUARIO != ?", (email, id_usuario))
            if cur.fetchone():
                return jsonify({'erro': 'Este e-mail já está sendo usado por outro usuário.'}), 409

        senha_final = hash_atual

        if senha_nova and str(senha_nova).strip() != "":
            if verificar_reuso_senha(id_usuario, senha_nova, cur):
                return jsonify({'erro': 'Senha já usada recentemente. Escolha outra.'}), 400

            cur.execute(
                "INSERT INTO HISTORICO_SENHAS (ID_HISTORICO, ID_USUARIO, SENHA_HASH) VALUES (GEN_ID(GEN_HISTORICO_ID, 1), ?, ?)",
                (id_usuario, hash_atual)
            )

            senha_final = criptografar(senha_nova)

        cur.execute("""
                    UPDATE USUARIO
                    SET NOME  = ?,
                        EMAIL = ?,
                        SENHA = ?
                    WHERE ID_USUARIO = ?
                    """, (nome, email, senha_final, id_usuario))

        con.commit()
        return jsonify({'mensagem': 'Dados atualizados com sucesso!'}), 200

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f"Erro ao editar: {str(e)}"}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/excluir_usuario/<int:id_alvo>', methods=['DELETE'])
def excluir_usuario(id_alvo):
    from main import app
    con = None
    cur = None

    token = request.cookies.get('access_token')

    if not token:
        return jsonify({'erro': 'Acesso negado. Token não fornecido.'}), 401

    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        id_quem_chamou = payload.get('id_usuario')

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT ID_TIPO FROM USUARIO WHERE ID_USUARIO = ?", (id_quem_chamou,))
        usuario_logado = cur.fetchone()

        if not usuario_logado or usuario_logado[0] != 1:
            return jsonify({'erro': 'Acesso negado. Apenas administradores podem excluir usuários.'}), 403

        cur.execute("DELETE FROM CODIGOS WHERE ID_USUARIO = ?", (id_alvo,))
        cur.execute("DELETE FROM HISTORICO_SENHAS WHERE ID_USUARIO = ?", (id_alvo,))
        cur.execute("DELETE FROM USUARIO WHERE ID_USUARIO = ?", (id_alvo,))

        if cur.rowcount == 0:
            return jsonify({'erro': 'Usuário alvo não encontrado.'}), 404

        con.commit()
        return jsonify({'mensagem': f'Usuário {id_alvo} removido com sucesso pelo administrador.'}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({'erro': 'Sua sessão expirou. Faça login novamente.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'erro': 'Token inválido ou corrompido.'}), 401
    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f"Erro ao excluir: {str(e)}"}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


from flask import make_response


@app.route('/login', methods=['POST'])
def login():
    print("🔵 ROTA /login FOI CHAMADA!")

    con = None
    cur = None
    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Os dados devem ser enviados em formato JSON.'}), 400

        email = dados.get('email')
        senha = dados.get('senha')

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("""
                    SELECT id_usuario, senha, nome, conta_confirmada,
                           id_tipo, tipo_nome, bloqueado, tentativas_login
                    FROM USUARIO WHERE email = ?
                    """, (email,))

        user = cur.fetchone()
        if not user:
            return jsonify({'erro': 'Usuário não encontrado.'}), 404

        id_u, s_db, nome, conf, id_t, t_nome, bloqueado, tentativas = user

        if bloqueado:
            return jsonify({'erro': 'Sua conta está bloqueada. Procure um administrador.'}), 403

        if not conf:
            return jsonify({'erro': 'Conta não confirmada. Verifique seu e-mail.'}), 403

        if checar_senha(senha, s_db):
            cur.execute("UPDATE USUARIO SET tentativas_login = 0 WHERE id_usuario = ?", (id_u,))
            con.commit()

            token = gerar_token(id_u)

            # ✅ Depois
            resposta = make_response(jsonify({
                'mensagem': 'Login realizado com sucesso!',
                'token': token,
                'usuario': {
                    'id': id_u,
                    'nome': nome,
                    'tipo': t_nome,
                    'id_tipo': id_t,
                    'email': email  # ✅ linha adicionada
                }
            }))

            resposta.set_cookie(
                'access_token', token,
                httponly=True,
                secure=False,
                samesite='Lax',
                max_age=86400
            )

            return resposta, 200

        else:
            novas_tentativas = tentativas + 1

            if novas_tentativas >= 3:
                cur.execute("UPDATE USUARIO SET tentativas_login = ?, bloqueado = ? WHERE id_usuario = ?",
                            (novas_tentativas, True, id_u))
                con.commit()
                return jsonify({'erro': 'Senha incorreta. Conta bloqueada!'}), 403
            else:
                cur.execute("UPDATE USUARIO SET tentativas_login = ? WHERE id_usuario = ?",
                            (novas_tentativas, id_u))
                con.commit()
                return jsonify({'erro': f'Senha incorreta. Tentativa {novas_tentativas} de 3.'}), 401

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f"Erro no login: {str(e)}"}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/confirmar_codigo', methods=['POST'])
def confirmar_codigo():
    from main import app
    con = None
    cur = None

    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Os dados devem ser enviados em formato JSON.'}), 400

        email = str(dados.get('email', '')).strip()
        codigo_enviado = str(dados.get('codigo', '')).strip()
        nova_senha = dados.get('senha')

        if not email or not codigo_enviado:
            return jsonify({'erro': 'E-mail e código são obrigatórios.'}), 400

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT ID_USUARIO, CONTA_CONFIRMADA, SENHA FROM USUARIO WHERE EMAIL = ?", (email,))
        usuario = cur.fetchone()

        if not usuario:
            return jsonify({'erro': 'Usuário não encontrado com este e-mail.'}), 404

        id_user, conta_confirmada, senha_atual_hash = usuario

        tabela_origem = None

        cur.execute("""
            SELECT ID_USUARIO FROM RECUPERAR_SENHA 
            WHERE TRIM(CODIGO) = ? AND ID_USUARIO = ? AND UTILIZADO = 0
        """, (codigo_enviado, id_user))

        if cur.fetchone():
            tabela_origem = 'recuperar_senha'
        else:
            cur.execute("""
                SELECT ID_USUARIO FROM CODIGOS 
                WHERE TRIM(CODIGO) = ? AND ID_USUARIO = ? AND TIPO = 'confirmacao'
            """, (codigo_enviado, id_user))

            if cur.fetchone():
                tabela_origem = 'codigos'

        if not tabela_origem:
            return jsonify({'erro': 'Código inválido ou já utilizado.'}), 400

        if tabela_origem == 'codigos' and conta_confirmada == 1:
            return jsonify({'erro': 'Esta conta já foi confirmada anteriormente.'}), 400

        if nova_senha and str(nova_senha).strip() != "":
            erro_v = verificar_senha(nova_senha)
            if erro_v:
                return jsonify({'erro': erro_v}), 400

            if checar_senha(nova_senha, senha_atual_hash):
                return jsonify({'erro': 'Você não pode usar uma das suas últimas 3 senhas.'}), 400

            cur.execute("""
                SELECT FIRST 3 SENHA_HASH FROM HISTORICO_SENHAS
                WHERE ID_USUARIO = ? ORDER BY ID_HISTORICO DESC
            """, (id_user,))
            historico = cur.fetchall()

            for (senha_velha_hash,) in historico:
                if checar_senha(nova_senha, senha_velha_hash):
                    return jsonify({'erro': 'Você não pode usar uma das suas últimas 3 senhas.'}), 400

            # ✅ INSERT corrigido com GEN_ID
            cur.execute(
                "INSERT INTO HISTORICO_SENHAS (ID_HISTORICO, ID_USUARIO, SENHA_HASH) VALUES (GEN_ID(GEN_HISTORICO_ID, 1), ?, ?)",
                (id_user, senha_atual_hash)
            )

            senha_hash = criptografar(nova_senha)

            cur.execute("""
                UPDATE USUARIO 
                SET CONTA_CONFIRMADA = ?, SENHA = ? 
                WHERE ID_USUARIO = ?
            """, (1, senha_hash, id_user))
            mensagem_sucesso = 'Senha alterada e conta confirmada com sucesso!'
        else:
            cur.execute("UPDATE USUARIO SET CONTA_CONFIRMADA = ? WHERE ID_USUARIO = ?", (1, id_user))
            mensagem_sucesso = 'Conta confirmada com sucesso!'

        if tabela_origem == 'recuperar_senha':
            cur.execute("""
                UPDATE RECUPERAR_SENHA 
                SET UTILIZADO = ? 
                WHERE TRIM(CODIGO) = ? AND ID_USUARIO = ?
            """, (1, codigo_enviado, id_user))
        else:
            cur.execute("DELETE FROM CODIGOS WHERE TRIM(CODIGO) = ? AND ID_USUARIO = ?", (codigo_enviado, id_user))

        con.commit()
        return jsonify({
            'mensagem': mensagem_sucesso,
            'id_usuario': id_user
        }), 200

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f"Erro interno: {str(e)}"}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/solicitar_recuperacao', methods=['POST'])
def solicitar_recuperacao():
    from main import app
    con = None
    cur = None

    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Os dados devem ser enviados em formato JSON.'}), 400

        email = str(dados.get('email', '')).strip()

        if not email or email == "":
            return jsonify({'erro': 'O e-mail é obrigatório.'}), 400

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT ID_USUARIO, NOME FROM USUARIO WHERE TRIM(UPPER(EMAIL)) = UPPER(?)", (email,))
        usuario = cur.fetchone()

        if not usuario:
            return jsonify({'erro': 'Este e-mail não está cadastrado no sistema.'}), 404

        id_usuario, nome_usuario = usuario

        codigo = str(random.randint(100000, 999999))
        expiracao = datetime.datetime.now() + datetime.timedelta(minutes=15)

        cur.execute("""
            INSERT INTO RECUPERAR_SENHA (ID_USUARIO, CODIGO, EXPIRACAO, UTILIZADO)
            VALUES (?, ?, ?, ?)
        """, (id_usuario, codigo, expiracao, 0))

        con.commit()

        threading.Thread(
            target=enviando_email,
            args=(email, "Recuperação de Senha", f"Olá {nome_usuario}, seu código: {codigo}")
        ).start()

        return jsonify({"mensagem": "Código enviado! Verifique sua caixa de entrada."}), 200

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f"Erro no servidor: {str(e)}"}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/redefinir_senha', methods=['POST'])
def redefinir_senha():
    from main import app
    con = None
    cur = None

    token = request.cookies.get('access_token')
    if not token:
        return jsonify({'erro': 'Acesso negado. Token não fornecido.'}), 401

    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return jsonify({'erro': 'Sessão expirada.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'erro': 'Token inválido.'}), 401

    try:
        email = request.form.get('email')
        codigo = request.form.get('codigo')
        nova_senha = request.form.get('nova_senha')

        if not all([email, codigo, nova_senha]):
            return jsonify({'erro': 'Preencha email, código e nova senha.'}), 400

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT ID_USUARIO, SENHA FROM USUARIO WHERE EMAIL = ?", (email,))
        user = cur.fetchone()
        if not user:
            return jsonify({'erro': 'Usuário não encontrado.'}), 404

        id_usuario, senha_atual_hash = user

        cur.execute("""
            SELECT ID_USUARIO FROM RECUPERAR_SENHA
            WHERE ID_USUARIO = ? AND CODIGO = ? AND UTILIZADO = 0 AND EXPIRACAO > ?
        """, (id_usuario, codigo, datetime.datetime.now()))

        if not cur.fetchone():
            return jsonify({'erro': 'Código inválido ou expirado.'}), 400

        erro_senha = verificar_senha(nova_senha)
        if erro_senha:
            return jsonify({'erro': erro_senha}), 400

        if checar_senha(nova_senha, senha_atual_hash):
            return jsonify({'erro': 'A nova senha não pode ser igual à atual.'}), 400

        cur.execute("""
            SELECT FIRST 3 SENHA_HASH FROM HISTORICO_SENHAS
            WHERE ID_USUARIO = ? ORDER BY ID_HISTORICO DESC
        """, (id_usuario,))
        historico = cur.fetchall()

        for (senha_velha_hash,) in historico:
            if checar_senha(nova_senha, senha_velha_hash):
                return jsonify({'erro': 'Você não pode usar uma das suas últimas 3 senhas.'}), 400

        # ✅ INSERT corrigido com GEN_ID
        cur.execute(
            "INSERT INTO HISTORICO_SENHAS (ID_HISTORICO, ID_USUARIO, SENHA_HASH) VALUES (GEN_ID(GEN_HISTORICO_ID, 1), ?, ?)",
            (id_usuario, senha_atual_hash)
        )

        novo_hash = criptografar(nova_senha)

        cur.execute("""
            UPDATE USUARIO
            SET SENHA = ?, BLOQUEADO = ?, tentativas_login = ?
            WHERE ID_USUARIO = ?
        """, (novo_hash, False, 0, id_usuario))

        cur.execute(
            "UPDATE RECUPERAR_SENHA SET UTILIZADO = 1 WHERE ID_USUARIO = ? AND CODIGO = ?",
            (id_usuario, codigo)
        )

        con.commit()
        return jsonify({"mensagem": "Senha alterada com sucesso!"}), 200

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': str(e)}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/admin/desbloquear/<int:id_alvo>', methods=['POST'])
def desbloquear_usuario(id_alvo):
    con = None
    cur = None

    try:
        con = get_db_connection()
        cur = con.cursor()

        cur.execute(
            "UPDATE USUARIO SET BLOQUEADO = ?, tentativas_login = ? WHERE ID_USUARIO = ?",
            (False, 0, id_alvo)
        )

        if cur.rowcount == 0:
            return jsonify({'erro': 'Usuário alvo não encontrado.'}), 404

        con.commit()
        return jsonify({'mensagem': f'Usuário {id_alvo} desbloqueado com sucesso!'}), 200

    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f'Erro interno: {str(e)}'}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'mensagem': 'Logout realizado'}), 200)
    resp.delete_cookie('access_token')
    return resp


@app.route('/uploads/usuarios/<path:filename>')
def servir_foto_usuario(filename):
    pasta = app.config.get('UPLOAD_FOLDER', os.path.join('uploads', 'usuarios'))
    return send_from_directory(pasta, filename)












# ==========================================
# ROTA: LISTAR PRODUTOS
# ==========================================
@app.route('/produtos', methods=['GET'])
def listar_produtos():
    con = None
    cur = None
    try:
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT ID_PRODUTO, NOME, DESCRICAO, PRECO_UNITARIO, CATEGORIA, DISPONIVEL FROM PRODUTO")
        produtos = cur.fetchall()
        resultado = []
        for p in produtos:
            resultado.append({
                'id': p[0],
                'nome': p[1],
                'descricao': p[2],
                'preco': float(p[3]) if p[3] else 0,
                'categoria': p[4],
                'disponivel': bool(p[5])
            })
        return jsonify(resultado), 200
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


# ==========================================
# ROTA: EXCLUIR PRODUTO (APENAS ADM)
# ==========================================
@app.route('/produto/<int:id_produto>', methods=['DELETE'])
def excluir_produto(id_produto):
    from main import app
    con = None
    cur = None
    token = request.cookies.get('access_token')
    if not token:
        return jsonify({'erro': 'Acesso negado. Token não fornecido.'}), 401
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        id_quem_chamou = payload.get('id_usuario')
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT ID_TIPO FROM USUARIO WHERE ID_USUARIO = ?", (id_quem_chamou,))
        usuario = cur.fetchone()
        if not usuario or usuario[0] != 1:
            return jsonify({'erro': 'Acesso negado. Apenas administradores.'}), 403
        cur.execute("DELETE FROM PRODUTO WHERE ID_PRODUTO = ?", (id_produto,))
        if cur.rowcount == 0:
            return jsonify({'erro': 'Produto não encontrado.'}), 404
        con.commit()
        return jsonify({'mensagem': 'Produto excluído com sucesso!'}), 200
    except jwt.ExpiredSignatureError:
        return jsonify({'erro': 'Sessão expirada.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'erro': 'Token inválido.'}), 401
    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f'Erro ao excluir: {str(e)}'}), 500
    finally:
        if cur: cur.close()
        if con: con.close()


# ==========================================
# ROTA: EDITAR PRODUTO (APENAS ADM)
# ==========================================
@app.route('/produto/<int:id_produto>', methods=['PUT'])
def editar_produto(id_produto):
    from main import app
    con = None
    cur = None
    token = request.cookies.get('access_token')
    if not token:
        return jsonify({'erro': 'Acesso negado. Token não fornecido.'}), 401
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        id_quem_chamou = payload.get('id_usuario')
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT ID_TIPO FROM USUARIO WHERE ID_USUARIO = ?", (id_quem_chamou,))
        usuario = cur.fetchone()
        if not usuario or usuario[0] != 1:
            return jsonify({'erro': 'Acesso negado. Apenas administradores.'}), 403
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Dados inválidos.'}), 400
        cur.execute("SELECT NOME, DESCRICAO, PRECO_UNITARIO, CATEGORIA, DISPONIVEL FROM PRODUTO WHERE ID_PRODUTO = ?", (id_produto,))
        res = cur.fetchone()
        if not res:
            return jsonify({'erro': 'Produto não encontrado.'}), 404
        nome = dados.get('nome') or res[0]
        descricao = dados.get('descricao') or res[1]
        preco = dados.get('preco') or res[2]
        categoria = dados.get('categoria') or res[3]
        disponivel = dados.get('disponivel') if 'disponivel' in dados else res[4]
        cur.execute("""
            UPDATE PRODUTO SET NOME = ?, DESCRICAO = ?, PRECO_UNITARIO = ?, CATEGORIA = ?, DISPONIVEL = ?
            WHERE ID_PRODUTO = ?
        """, (nome, descricao, preco, categoria, disponivel, id_produto))
        con.commit()
        return jsonify({'mensagem': 'Produto atualizado com sucesso!'}), 200
    except jwt.ExpiredSignatureError:
        return jsonify({'erro': 'Sessão expirada.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'erro': 'Token inválido.'}), 401
    except Exception as e:
        if con: con.rollback()
        return jsonify({'erro': f'Erro ao editar: {str(e)}'}), 500
    finally:
        if cur: cur.close()
        if con: con.close()










if __name__ == '__main__':
    app.run(debug=True)