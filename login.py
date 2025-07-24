import base64
import sqlite3
from datetime import datetime
from uuid import uuid4

import bcrypt
import streamlit as st
from altair import Padding

from db import conectar_banco

# -----------------------------
# Funções auxiliares
# -----------------------------

def autenticar_usuario(email, senha):
    """
    Autentica o usuário comparando o hash da senha.
    Retorna tupla do usuário se válido, ou None.
    """
    conn = conectar_banco()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM usuarios WHERE email = ? AND status IN ('aprovado', 'trocar_senha')",
        (email.lower(),)
    )
    usuario = c.fetchone()
    conn.close()

    if not usuario:
        return None

    stored_hash = usuario[10]
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode('utf-8')

    if bcrypt.checkpw(senha.encode('utf-8'), stored_hash):
        if usuario[12] == "trocar_senha":
            st.session_state["forcar_troca"] = True
        atualizar_ultimo_acesso(email)
        return usuario
    return None


def atualizar_ultimo_acesso(email):
    """
    Atualiza timestamp de último acesso do usuário.
    """
    conn = conectar_banco()
    c = conn.cursor()
    c.execute(
        "UPDATE usuarios SET ultimo_acesso = ? WHERE email = ?",
        (datetime.now().isoformat(), email.lower())
    )
    conn.commit()
    conn.close()


def cadastrar_usuario(dados):
    """
    Cadastra novo usuário (primeiro acesso) com status pendente ou aprovado.
    """
    conn = conectar_banco()
    c = conn.cursor()
    user_id = dados.get("id", str(uuid4()))
    senha_hash = bcrypt.hashpw(dados["senha"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        c.execute(
            "INSERT INTO usuarios (id,nome_completo,cargo,setor,matricula,email,telefone,data_admissao,tipo_contrato,unidade,senha_hash,perfil,status,ultimo_acesso) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                dados["nome_completo"],
                dados["cargo"],
                dados["setor"],
                dados["matricula"],
                dados["email"].lower(),
                dados["telefone"],
                dados["data_admissao"],
                dados["tipo_contrato"],
                dados["unidade"],
                senha_hash,
                "usuario",
                dados["status"],
                datetime.now().isoformat()
            )
        )
        conn.commit()
    except sqlite3.IntegrityError:
        st.error("Usuário já cadastrado.")
    finally:
        conn.close()


def exibir_primeiro_acesso():
    
    """
    Exibe o form de primeiro acesso, com fundo branco só nesse bloco.
    """
    st.markdown("""
    <style>
    
          /* reduz o padding-top de toda a área principal (block-container) */
      section[data-testid="stMain"] .block-container {
        padding-top: 1rem !important;   /* pode ser 0.5rem, 1rem, conforme quiser */
      }
      /* ou, para afetar só o próprio form, reduz a margem acima dele */
      div[data-testid="stForm"] {
        margin-top: 0.5rem !important;   /* por exemplo */
      }
      /* Aplica fundo branco + padding + sombra só no container do form */
      div[data-testid="stForm"] {
        background-color: #fff !important;
        padding: 2rem !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
      }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <style>
      /* todo h2 dentro do block-container fica branco */
      section[data-testid="stMain"] .block-container h2 {
        color: #FFFFFF !important;
      }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<h2 style="color:#FFFFFF;">👤 Primeiro Acesso</h2>', unsafe_allow_html=True)
    """
    Exibe formulário de primeiro acesso e cadastra usuário.
    """

    with st.form("form_primeiro_acesso"):
        nome = st.text_input("*Nome completo")
        cargo = st.text_input("*Cargo")
        setor = st.text_input("Setor")
        matricula = st.text_input("*Matrícula")
        email = st.text_input("*E-mail corporativo")
        telefone = st.text_input("Telefone")
        admissao = st.date_input("Data de admissão")
        contrato = st.selectbox("Tipo de contrato", ["CLT", "PJ", "Estagiário", "Outro"])
        unidade = st.text_input("*Unidade")
        senha = st.text_input("*Senha", type="password")
        confirmar = st.text_input("*Confirmar senha", type="password")
        submitted = st.form_submit_button("Cadastrar")

    if submitted:
        obrigatorios = [nome, cargo, matricula, email, unidade, senha, confirmar]
        if not all(obrigatorios):
            st.warning("Preencha todos os campos obrigatórios.")
        elif senha != confirmar:
            st.warning("As senhas não coincidem.")
        else:
            user_id = str(uuid4())
            status = "aprovado" if email.lower().endswith("@empresa.com") else "pendente"
            dados = {
                "id": user_id,
                "nome_completo": nome,
                "cargo": cargo,
                "setor": setor,
                "matricula": matricula,
                "email": email,
                "telefone": telefone,
                "data_admissao": admissao.isoformat(),
                "tipo_contrato": contrato,
                "unidade": unidade,
                "senha": senha,
                "status": status,
            }
            cadastrar_usuario(dados)
            # limpa parâmetros e retorna para tela inicial de login
            st.query_params.clear()
            if status == "pendente":
                st.success(f"Cadastro enviado! Aguarde aprovação do administrador. Seu ID é {user_id}")
            else:
                st.success("Acesso liberado! Você já pode fazer login.")
            st.rerun()
def exibir_trocar_senha():
    """
    Formulário para trocar senha no primeiro acesso.
    """
    st.subheader("🔐 Trocar Senha (Primeiro Acesso)")
    email = st.session_state["usuario"]["email"]

    with st.form("form_trocar_senha"):
        nova_senha = st.text_input("*Nova senha", type="password")
        confirmar_senha = st.text_input("*Confirmar nova senha", type="password")
        enviar = st.form_submit_button("Atualizar senha")

    if enviar:
        if not nova_senha or not confirmar_senha:
            st.warning("Preencha os dois campos.")
        elif nova_senha != confirmar_senha:
            st.error("As senhas não coincidem.")
        elif len(nova_senha) < 6:
            st.warning("A senha deve ter ao menos 6 caracteres.")
        else:
            conn = conectar_banco()
            c = conn.cursor()
            senha_hash = bcrypt.hashpw(nova_senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            c.execute(
                "UPDATE usuarios SET senha_hash = ?, status = 'aprovado' WHERE email = ?",
                (senha_hash, email.lower())
            )
            conn.commit()
            conn.close()
            st.success("Senha atualizada com sucesso!")
            st.session_state["usuario"]["status"] = "aprovado"
            st.session_state["pagina"] = "oraculo"
            st.query_params.clear()
            st.rerun()

st.markdown("""
<style>
  /* Torna o header/toolbar transparente e remove sombra */
  [data-testid="stHeader"],
  [data-testid="stToolbar"] {
    background-color: transparent !important;
    box-shadow: none !important;
  }
</style>
""", unsafe_allow_html=True)


def exibir_login():
    
       
    params = st.query_params
    page = params.get("pagina", [""])[0]

    # === PRIMEIRO ACESSO: remove totalmente a imagem e pinta de branco ===
    if page == "primeiro_acesso":
        st.markdown("""
        <style>
          /* limpa qualquer background-image e coloca branco */
          html, body,
          [data-testid="stAppViewContainer"],
          [data-testid="stAppContentContainer"] {
            background-image: none !important;
            background-color: #FFFFFF !important;
            margin: 0; padding: 0;
            height: 100% !important;
          }
          [data-testid="stHeader"],
          [data-testid="stToolbar"] {
            background-image: none !important;
            background-color: #FFFFFF !important;
            box-shadow: none !important;
          }
        </style>
        """, unsafe_allow_html=True)

        exibir_primeiro_acesso()
        return

    # === LOGIN NORMAL: injeta o CSS da imagem e header transparente ===
    with open("img/bg6.jpg", "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    st.markdown(f"""
    <style>
      html, body,
      [data-testid="stAppViewContainer"],
      [data-testid="stAppContentContainer"] {{
        background-image: url("data:image/jpeg;base64,{img_b64}") !important;
        background-size: cover !important;
        background-position: center !important;
        margin: 0; padding: 0;
        height: 100% !important;
      }}
      [data-testid="stHeader"],
      [data-testid="stToolbar"] {{
        background-color: transparent !important;
        box-shadow: none !important;
      }}
    </style>
    """, unsafe_allow_html=True)
    st.markdown(f"""
    <style>
      /* garante altura total */
      html, body, [data-testid="stAppViewContainer"], [data-testid="stAppContentContainer"] {{
        height: 100% !important;
        margin: 0; padding: 0;
      }}

      /* aplica o background via Base64 */
      [data-testid="stAppViewContainer"] {{
        background-image: url("data:image/jpeg;base64,{img_b64}");
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
      }}

      /* mantém sidebar legível */
      [data-testid="stSidebar"] {{
        background-color: #F9F9F9;
        padding: 0px 0px;
      }}
    </style>
    """, unsafe_allow_html=True)

    # Parâmetros de query para alternar telas
    params = st.query_params
    if params.get("pagina") == "primeiro_acesso":
        exibir_primeiro_acesso()
        return
    # Detecta tema atual
    theme_base = st.get_option("theme.base")
    # Cor de fundo específica para dark mode
    DARK_SIDEBAR_BG = "#1E1E2E"  # defina aqui a cor desejada

    # Define background conforme tema
    if theme_base == "dark":
        sidebar_bg = "#FDFDFD"
        title_color = "#333"
        subtitle_color = "#666"
        link_color = "#4a60ff"
        eye_color = "#555555"
        footer_color = "#999"
    else:
        sidebar_bg = "#FDFDFD#"
        title_color = "#333"
        subtitle_color = "#666"
        link_color = "#4a60ff"
        eye_color = "#555555"
        footer_color = "#999"

    # CSS personalizado
    st.markdown(f"""
        <style>
        [data-testid=\"stSidebar\"] {{
            background-color: {sidebar_bg};
            padding: 60px 40px;
            border-right: 1px solid #E7E7E7;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center; /* centraliza todo conteúdo */
            min-height: 100vh;
            width: 500px !important;
            min-width: 400px !important;
            max-width: 600px !important;
        }}
        .sidebar-logo {{
            display: block;
            margin: 0 auto 20px;
            margin-bottom: 20px;
            width: 150px;
            filter: brightness({ '0.8' if theme_base=='dark' else '1'});
        }}
        .sidebar-title {{
            text-align: center;
            font-size: 1.8rem;
            font-weight: bold;
            color: {title_color};
        }}
        .sidebar-subtitle {{
            text-align: center;
            font-size: 0.9rem;
            color: {subtitle_color};
            margin-bottom: 30px;
        }}
        .sidebar-link a {{
            color: {link_color} !important;
            text-decoration: none;
        }}
        .sidebar-footer {{
            text-align: center;
            font-size: 0.75rem;
            color: {footer_color};
            margin-top: 30px;
        }}
           
        [data-testid="stSidebar"] input {{
        color: #333 !important;                    /* texto branco */
        background-color: #FFF !important;      /* fundo azul escuro */
        border-radius: 8px;
        padding: 8px;
        
        }}
        /* Placeholder mais suave */
        [data-testid="stSidebar"] input::placeholder {{
        color: #333 !important;
        }}
        /* Rótulos (labels) dentro do sidebar */
        [data-testid="stSidebar"] label {{
        color: #333 !important;                 /* rótulo turquesa */
        }}
            [data-testid="stSidebar"] {{
      /* suas outras regras… */
    }}



        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
                # Logo centralizada usando markdown com classe CSS
        # Carrega logo como base64 para garantir exibição
        try:
            import base64 as _b64
            _logo_bytes = open("img/logo.png", "rb").read()
            _logo_b64 = _b64.b64encode(_logo_bytes).decode()
            st.markdown(
                f"<div style='text-align: center;'><img src='data:image/png;base64,{_logo_b64}' class='sidebar-logo'/></div>",
                unsafe_allow_html=True
            )
        except Exception:
            # fallback para st.image caso dê erro
            st.image("img/logo.png", width=180, use_container_width=False)
        st.markdown(f"<div class='sidebar-title'>Welcome to Oracle!</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sidebar-subtitle'>Bem-vindo ao Oráculo!</div>", unsafe_allow_html=True)

        email = st.text_input("Email", key="login_email_sidebar", label_visibility="visible")
        senha = st.text_input("Senha", type="password", key="login_senha_sidebar", label_visibility="visible")

        col1, col2 = st.columns([1, 1])
        with col1:
            st.checkbox("Lembrar-me")
        with col2:
            st.markdown(f"<div style='text-align:right;'><a href='?pagina=esqueci_senha' class='sidebar-link'>Recovery Password</a></div>", unsafe_allow_html=True)

        if st.button("Login", use_container_width=True):
            usuario = autenticar_usuario(email, senha)
            if usuario:
                st.session_state["usuario"] = {"id": usuario[0], "nome": usuario[1], "email": usuario[5], "perfil": usuario[11], "status": usuario[12]}
                st.session_state["pagina"] = ("trocar_senha" if st.session_state.get("forcar_troca") else "oraculo")
                st.query_params.clear()
                st.rerun()
            else:
                # Verifica se o e‑mail existe e se está pendente
                conn = conectar_banco()
                c = conn.cursor()
                c.execute("SELECT status FROM usuarios WHERE email = ?", (email.lower(),))
                row = c.fetchone()
                conn.close()
                if row and row[0] == "pendente":
                    st.error("Aguardando aprovação da administração.")
                else:
                    st.error("Credenciais inválidas ou acesso não autorizado.")

        st.markdown('<div class="primeiro-acesso">', unsafe_allow_html=True)
        if st.button("Primeiro Acesso", key="btn_primeiro_acesso", use_container_width=True):
            st.query_params.clear()
            st.query_params.update({"pagina": "primeiro_acesso"})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown(f"<div class='sidebar-footer'>Powered by your company</div>", unsafe_allow_html=True)

def exibir_usuarios():
    """
    Exibe lista de usuários (para debug ou outra página).
    """
    conn = conectar_banco()
    c = conn.cursor()
    c.execute("SELECT id, nome_completo, email, perfil, status, ultimo_acesso FROM usuarios")
    usuarios = c.fetchall()
    conn.close()

    st.subheader("👥 Lista de Usuários")
    for u in usuarios:
        acesso = u[5] or 'N/A'
        st.markdown(f"**{u[1]}** ({u[2]}) — Perfil: {u[3]} | Status: {u[4]} | Último acesso: {acesso}")
