import os
import sqlite3
from datetime import datetime
from uuid import uuid4

import bcrypt
import pandas as pd
import streamlit as st

BANCO = 'oraculo.db'
UPLOAD_DIR = 'uploads'

# Cria diretório de uploads se não existir
def aplicar_estilo_upload():
    st.markdown("""
    <style>
    .css-import-btn input[type=\"file\"] {
        display: none;
    }
    .css-import-btn label {
        display: inline-block;
        background-color: #0454a4;
        color: white;
        padding: 8px 20px;
        font-size: 14px;
        border-radius: 6px;
        cursor: pointer;
        margin-top: 6px;
    }
    .css-import-btn label:hover {
        background-color: #0454a4;
    }
    </style>
    """, unsafe_allow_html=True)

# Inicialização da tabela de funcionários
def inicializa_funcionarios():
    conn = sqlite3.connect(BANCO)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS funcionarios (
            id TEXT PRIMARY KEY,
            nome TEXT,
            cargo TEXT,
            setor TEXT,
            matricula TEXT,
            email TEXT,
            telefone TEXT,
            data_admissao TEXT,
            tipo_contrato TEXT,
            unidade TEXT,
            foto TEXT,
            estrangeiro INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# Painel administrativo com abas
def painel_administrativo():
    aplicar_estilo_upload()

    user = st.session_state.get("usuario", {})
    perfil = user.get("perfil")
    if perfil != "admin":
        st.error("🚫 Você não tem permissão para acessar o gerenciamento.")
        return

    st.subheader("🔧 Área Administrativa")
    abas = st.tabs(["Usuários", "Funcionários", "Aprovações"])
    with abas[0]:
        exibir_usuarios_layout()
    with abas[1]:
        gerenciar_funcionarios()
    with abas[2]:
        exibir_aprovacoes_pendentes()

# Lista de usuários cadastrados (todos os status)
def exibir_usuarios_layout():
    st.markdown("### 👥 Lista de Usuários")
    conn = sqlite3.connect(BANCO)
    c = conn.cursor()
    c.execute("SELECT id, nome_completo, email, perfil, status, ultimo_acesso FROM usuarios")
    usuarios = c.fetchall()
    conn.close()

    # 7 colunas: +1 para o delete
    cols_header = st.columns([3, 4, 2, 2, 2, 1, 1])
    headers = ["Nome", "Email", "Perfil", "Status", "Último Acesso", "Ações", "Excluir"]
    for col, title in zip(cols_header, headers):
        col.markdown(f"**{title}**")
    st.markdown("<hr style='margin-top: -10px; margin-bottom: 10px;'>", unsafe_allow_html=True)

    for idx, (uid, nome, email, perfil, status, acesso) in enumerate(usuarios):
        row = st.columns([3, 4, 2, 2, 2, 1, 1])
        row[0].markdown(f"**{nome}**")
        row[1].markdown(email)
        row[2].markdown(perfil)
        row[3].markdown(status)
        acesso_fmt = (
            datetime.fromisoformat(acesso).strftime("%d/%m/%Y %H:%M") if acesso else "N/A"
        )
        row[4].markdown(acesso_fmt)

        # Promover / Rebaixar
        if perfil != "admin":
            if row[5].button("🔰", key=f"prom-{uid}-{idx}", help="Promover a administrador"):
                conn = sqlite3.connect(BANCO)
                c = conn.cursor()
                c.execute("UPDATE usuarios SET perfil = 'admin' WHERE id = ?", (uid,))
                conn.commit()
                conn.close()
                st.success(f"Usuário **{nome}** promovido a admin!")
                st.rerun()
        else:
            if row[5].button("⬇️", key=f"dem-{uid}-{idx}", help="Rebaixar a usuário"):
                conn = sqlite3.connect(BANCO)
                c = conn.cursor()
                c.execute("UPDATE usuarios SET perfil = 'usuario' WHERE id = ?", (uid,))
                conn.commit()
                conn.close()
                st.success(f"Usuário **{nome}** rebaixado a usuário padrão!")
                st.rerun()

        # Excluir usuário
        if row[6].button("🗑️", key=f"delete-user-{uid}-{idx}", help="Excluir usuário"):
            conn = sqlite3.connect(BANCO)
            c = conn.cursor()
            c.execute("DELETE FROM usuarios WHERE id = ?", (uid,))
            c.execute("DELETE FROM funcionarios WHERE id = ?", (uid,))
            conn.commit()
            conn.close()
            st.success(f"Usuário **{nome}** excluído com sucesso!")
            st.rerun()

# Solicitações pendentes de acesso
def exibir_aprovacoes_pendentes():
    st.markdown("### ⏳ Solicitações de Acesso Pendentes")
    conn = sqlite3.connect(BANCO)
    c = conn.cursor()
    c.execute(
        "SELECT id, nome_completo, email, cargo, setor, matricula, unidade "
        "FROM usuarios WHERE status = 'pendente'"
    )
    pendentes = c.fetchall()
    conn.close()

    if not pendentes:
        st.info("Nenhuma solicitação pendente.")
        return

    cols_header = st.columns([3, 4, 3, 2, 2])
    labels = ["Nome", "Email", "Cargo / Setor / Matrícula", "Aprovar", "Rejeitar"]
    for col, title in zip(cols_header, labels):
        col.markdown(f"**{title}**")
    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)

    for idx, (uid, nome, email, cargo, setor, matricula, unidade) in enumerate(pendentes):
        cols = st.columns([3, 4, 3, 2, 2])
        cols[0].markdown(nome)
        cols[1].markdown(email)
        cols[2].markdown(f"{cargo} / {setor}\n`{matricula}` / {unidade}")

        if cols[3].button("✅ Aprovar", key=f"aprovar-{uid}-{idx}"):
            conn = sqlite3.connect(BANCO)
            c = conn.cursor()
            c.execute("UPDATE usuarios SET status = 'trocar_senha' WHERE id = ?", (uid,))
            c.execute(
                "SELECT cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade FROM usuarios WHERE id = ?",
                (uid,)
            )
            cargo_db, setor_db, matricula_db, email_db, telefone_db, data_adm_db, tipo_contr_db, unidade_db = c.fetchone()
            c.execute(
                "INSERT OR IGNORE INTO funcionarios (id, nome, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade, foto, estrangeiro) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, nome, cargo_db, setor_db, matricula_db, email_db, telefone_db, data_adm_db, tipo_contr_db, unidade_db, "", 0)
            )
            conn.commit()
            conn.close()
            st.success(f"Usuário **{nome}** aprovado e cadastrado como funcionário!")
            st.rerun()
            return

        if cols[4].button("❌ Rejeitar", key=f"rejeitar-{uid}-{idx}"):
            conn = sqlite3.connect(BANCO)
            c = conn.cursor()
            c.execute("UPDATE usuarios SET status = 'rejeitado' WHERE id = ?", (uid,))
            conn.commit()
            conn.close()
            st.success(f"Usuário **{nome}** rejeitado!")
            st.rerun()
            return
# Gerenciamento de funcionários: cadastro, importação, listagem e edição
def gerenciar_funcionarios():
    inicializa_funcionarios()
    default_pass = "Palavrapasse@001"

    # inicializa chave de edição se não existir
    if 'edit' not in st.session_state:
        st.session_state['edit'] = None

    # se existe um funcionário selecionado para edição, abre o form de edição e sai
    if st.session_state.get('edit'):
        editar_funcionario(st.session_state['edit'])
        return


    st.markdown("### ➕ Adcionar Funcionários")
    # Botão para mostrar/ocultar formulário de novo funcionário
    if st.button("➕ Novo Funcionário"):
        st.session_state['show_form'] = not st.session_state.get('show_form', False)

    if st.session_state.get('show_form'):
        with st.form('form_func'):  # formulário de cadastro
            col1, col2 = st.columns([3, 1])
            with col1:
                nome = st.text_input("*Nome completo")
                cargo = st.text_input("*Cargo")
                setor = st.text_input("Setor")
                matricula = st.text_input("*Matrícula")
                email = st.text_input("*E-mail corporativo")
                telefone = st.text_input("Telefone")
                data_admissao = st.date_input("Data de admissão")
                tipo_contrato = st.selectbox(
                    "Tipo de contrato",
                    ["CLT", "PJ", "Estagiário", "Outro"]
                )
                unidade = st.text_input("*Unidade")
                estrangeiro = st.checkbox("Funcionário estrangeiro (Interface em inglês)?")
            with col2:
                foto = st.file_uploader(
                    "Foto de perfil", type=["jpg", "jpeg", "png"]
                )
            submit = st.form_submit_button("Cadastrar funcionário")
        if submit:
            # Validação de campos obrigatórios
            if not all([nome, cargo, matricula, email, unidade]):
                st.warning("Preencha todos os campos obrigatórios marcados com *.")
            else:
                foto_path = ""
                if foto:
                    ext = os.path.splitext(foto.name)[1]
                    foto_path = os.path.join(UPLOAD_DIR, f"{uuid4()}{ext}")
                    with open(foto_path, "wb") as f:
                        f.write(foto.getbuffer())
                # Insere no banco funcionários
                conn = sqlite3.connect(BANCO)
                c = conn.cursor()
                func_id = str(uuid4())
                c.execute(
                    "INSERT INTO funcionarios"
                    "(id,nome,cargo,setor,matricula,email,telefone,"
                    "data_admissao,tipo_contrato,unidade,foto,estrangeiro)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        func_id, nome, cargo, setor, matricula,
                        email.lower(), telefone,
                        data_admissao.isoformat(), tipo_contrato,
                        unidade, foto_path, int(estrangeiro)
                    )
                )
                # Cria usuário vinculado
# Cria usuário vinculado
def gerenciar_funcionarios():
    inicializa_funcionarios()
    default_pass = "Palavrapasse@001"

    # inicializa chave de edição se não existir
    if 'edit' not in st.session_state:
        st.session_state['edit'] = None

    # edição de funcionário existente
    if st.session_state.get('edit'):
        editar_funcionario(st.session_state['edit'])
        return

    st.markdown("### ➕ Adicionar Funcionários")
    # alterna exibição do form
    if st.button("➕ Novo Funcionário"):
        st.session_state['show_form'] = not st.session_state.get('show_form', False)

    if st.session_state.get('show_form'):
        with st.form('form_func'):
            col1, col2 = st.columns([3, 1])
            with col1:
                nome = st.text_input("*Nome completo")
                cargo = st.text_input("*Cargo")
                setor = st.text_input("Setor")
                matricula = st.text_input("*Matrícula")
                email = st.text_input("*E-mail corporativo")
                telefone = st.text_input("Telefone")
                data_admissao = st.date_input("Data de admissão")
                tipo_contrato = st.selectbox(
                    "Tipo de contrato", ["CLT", "PJ", "Estagiário", "Outro"]
                )
                unidade = st.text_input("*Unidade")
                estrangeiro = st.checkbox("Funcionário estrangeiro (Interface em inglês)?")
            with col2:
                foto = st.file_uploader("Foto de perfil", type=["jpg", "jpeg", "png"])
            submitted = st.form_submit_button("Cadastrar funcionário")

        if submitted:
            # valida campos obrigatórios
            if not all([nome, cargo, matricula, email, unidade]):
                st.warning("Preencha todos os campos obrigatórios marcados com *.")
            else:
                # prepara armazenamento
                conn = sqlite3.connect(BANCO)
                c = conn.cursor()
                func_id = str(uuid4())
                # insere funcionário
                foto_path = ""
                if foto:
                    ext = os.path.splitext(foto.name)[1]
                    foto_path = os.path.join(UPLOAD_DIR, f"{func_id}{ext}")
                    with open(foto_path, "wb") as f:
                        f.write(foto.getbuffer())
                c.execute(
                    "INSERT INTO funcionarios (id,nome,cargo,setor,matricula,email,telefone,"
                    "data_admissao,tipo_contrato,unidade,foto,estrangeiro)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (func_id, nome, cargo, setor, matricula,
                     email.lower(), telefone,
                     data_admissao.isoformat(), tipo_contrato,
                     unidade, foto_path, int(estrangeiro))
                )
                # cria usuário vinculado com tratamento de erro
                senha_hash = bcrypt.hashpw(default_pass.encode(), bcrypt.gensalt())
                try:
                    c.execute(
                        "INSERT INTO usuarios (id,nome_completo,cargo,setor,matricula,email,telefone,"
                        "data_admissao,tipo_contrato,unidade,senha_hash,perfil,status,ultimo_acesso)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (func_id, nome, cargo, setor, matricula,
                         email.lower(), telefone,
                         data_admissao.isoformat(), tipo_contrato,
                         unidade, senha_hash,
                         "usuario", "trocar_senha",
                         datetime.now().isoformat())
                    )
                    conn.commit()
                    # sucesso: limpa estado e rerun
                    st.success("Funcionário cadastrado e usuário criado com senha padrão!")
                    del st.session_state['show_form']
                    st.rerun()
                except sqlite3.IntegrityError as e:
                    conn.rollback()
                    # aviso persiste, não limpa o form
                    if 'usuarios.email' in str(e):
                        st.warning(f"Já existe um usuário com o e-mail '{email}'.")
                    else:
                        st.error(f"Erro ao criar usuário: {e}")
                finally:
                    conn.close()


    # Importação/Exportação CSV
    st.markdown("---")
    st.markdown("### 📂 Importação/Exportação de Funcionários")
    col_export, col_import = st.columns([1, 2])
    with col_export:
        if st.button("📄 Exportar CSV"):
            df = pd.read_sql_query(
                "SELECT nome,cargo,setor,matricula,email,telefone,data_admissao,tipo_contrato,unidade"
                " FROM funcionarios",
                sqlite3.connect(BANCO)
            )
            csv_data = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📁 Baixar lista", data=csv_data,
                file_name="funcionarios.csv",
                mime="text/csv"
            )
    with col_import:
        if st.button("📥 Importar CSV"):
            st.session_state['up'] = True
    if st.session_state.get('up'):
        up_file = st.file_uploader("Selecionar arquivo CSV", type=["csv"])
        if up_file:
            df = pd.read_csv(up_file)
            conn = sqlite3.connect(BANCO)
            c = conn.cursor()
            for _, row in df.iterrows():
                fid = str(uuid4())
                c.execute(
                    "INSERT INTO funcionarios"
                    "(id,nome,cargo,setor,matricula,email,telefone,data_admissao,tipo_contrato,unidade,foto,estrangeiro)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                    (
                        fid, row['nome'], row['cargo'], row.get('setor',''),
                        row['matricula'], row['email'].lower(), row.get('telefone',''),
                        row['data_admissao'], row['tipo_contrato'], row['unidade']
                    )
                )
                sh = bcrypt.hashpw(default_pass.encode(), bcrypt.gensalt())
                c.execute(
                    "INSERT INTO usuarios"
                    "(id,nome_completo,cargo,setor,matricula,email,telefone,data_admissao,tipo_contrato,unidade,senha_hash,perfil,status,ultimo_acesso)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fid, row['nome'], row['cargo'], row.get('setor',''),
                        row['matricula'], row['email'].lower(), row.get('telefone',''),
                        row['data_admissao'], row['tipo_contrato'], row['unidade'],
                        sh, 'usuario', 'trocar_senha', datetime.now().isoformat()
                    )
                )
            conn.commit()
            conn.close()
            st.success("Funcionários importados com sucesso!")
            del st.session_state['up']
            st.rerun()

    # Listagem, filtro e ações de edição/exclusão
    st.markdown("<hr style='margin-top:10px;margin-bottom:20px;'>", unsafe_allow_html=True)
    st.markdown("### 👥 Funcionários cadastrados")
    filtro = st.text_input("Filtrar por nome, matrícula, cargo ou unidade")
    all_funcs = sqlite3.connect(BANCO).cursor().execute(
        "SELECT id,nome,matricula,unidade,cargo FROM funcionarios"
    ).fetchall()
    if filtro:
        funcs = [f for f in all_funcs if filtro.lower() in str(f).lower()]
    else:
        funcs = all_funcs
    cols = st.columns([3,2,2,1,1])
    for col, title in zip(cols,["Nome","Cargo","Unidade","Editar","Excluir"]):
        col.markdown(f"**{title}**")
    st.markdown("<hr style='margin:0 0 10px 0;'>", unsafe_allow_html=True)
    for fid, nome, mat, uni, carg in funcs:
        row_cols = st.columns([3,2,2,1,1])
        row_cols[0].markdown(f"**{nome}**\n`{mat}`")
        row_cols[1].markdown(carg)
        row_cols[2].markdown(uni)
        if row_cols[3].button("✏️", key=f"edit-{fid}"):
            st.session_state['edit'] = fid
            st.rerun()
        if row_cols[4].button("🗑️", key=f"del-{fid}"):
            conn = sqlite3.connect(BANCO)
            c = conn.cursor()
            c.execute("DELETE FROM funcionarios WHERE id=?", (fid,))
            c.execute("DELETE FROM usuarios WHERE id=?", (fid,))
            conn.commit()
            conn.close()
            st.success("Funcionário removido com sucesso!")
            st.rerun()


def editar_funcionario(fid):
    conn = sqlite3.connect(BANCO)
    c = conn.cursor()
    c.execute(
        "SELECT nome,cargo,setor,matricula,email,telefone,data_admissao,tipo_contrato,unidade,foto,estrangeiro "
        "FROM funcionarios WHERE id = ?", (fid,)
    )
    row = c.fetchone()
    conn.close()

    if not row:
        st.error("Funcionário não encontrado.")
        return

    nome_atual, cargo_atual, setor_atual, mat_atual, email_atual, tel_atual, da_atual, tc_atual, uni_atual, foto_atual, estr_atual = row

    st.markdown("### ✏️ Editando Funcionário")
    with st.form(f"form_edit_{fid}"):
        nome_novo = st.text_input("Nome completo", value=nome_atual)
        cargo_novo = st.text_input("Cargo", value=cargo_atual)
        setor_novo = st.text_input("Setor", value=setor_atual)
        mat_novo = st.text_input("Matrícula", value=mat_atual)
        email_novo = st.text_input("E-mail corporativo", value=email_atual)
        tel_novo = st.text_input("Telefone", value=tel_atual)
        da_novo = st.date_input("Data de admissão", value=datetime.fromisoformat(da_atual))
        tc_opts = ["CLT","PJ","Estagiário","Outro"]
        tc_novo = st.selectbox("Tipo de contrato", tc_opts, index=tc_opts.index(tc_atual))
        uni_novo = st.text_input("Unidade", value=uni_atual)
        estr_novo = st.checkbox("Funcionário estrangeiro?", value=bool(estr_atual))
        foto_upl = st.file_uploader("Alterar foto de perfil", type=["jpg","jpeg","png"])

        col1, col2 = st.columns(2)
        with col1:
            salvar = st.form_submit_button("Salvar alterações")
        with col2:
            cancelar = st.form_submit_button("Cancelar")

    if salvar:
        novo_path = foto_atual
        if foto_upl:
            ext = os.path.splitext(foto_upl.name)[1]
            novo_path = os.path.join(UPLOAD_DIR, f"{uuid4()}{ext}")
            with open(novo_path, "wb") as f:
                f.write(foto_upl.getbuffer())

        conn = sqlite3.connect(BANCO)
        c = conn.cursor()
        c.execute(
            "UPDATE funcionarios SET nome=?,cargo=?,setor=?,matricula=?,email=?,telefone=?,"
            "data_admissao=?,tipo_contrato=?,unidade=?,foto=?,estrangeiro=? WHERE id=?",
            (
                nome_novo, cargo_novo, setor_novo, mat_novo,
                email_novo.lower(), tel_novo,
                da_novo.isoformat(), tc_novo, uni_novo,
                novo_path, int(estr_novo), fid
            )
        )
        conn.commit()
        conn.close()
        st.success("Funcionário atualizado com sucesso!")
        # limpa estado de edição e volta à lista
        st.session_state['edit'] = None
        st.rerun()

    if cancelar:
        # cancela edição e volta à lista
        st.session_state['edit'] = None
        st.rerun()
