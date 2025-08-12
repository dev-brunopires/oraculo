import os
from datetime import datetime
from uuid import uuid4

import bcrypt
import pandas as pd
import streamlit as st

from db import conectar_banco  # usa o Neon
# se quiser usar também um diretório local para fotos antigas
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ------------------------------ CSS ------------------------------
def aplicar_estilo_upload():
    st.markdown(
        """
        <style>
        .css-import-btn input[type="file"] { display: none; }
        .css-import-btn label {
            display:inline-block;background-color:#0454a4;color:white;
            padding:8px 20px;font-size:14px;border-radius:6px;cursor:pointer;margin-top:6px;
        }
        .css-import-btn label:hover { background-color:#0454a4; }
        </style>
        """,
        unsafe_allow_html=True
    )


# ------------------------- DDL / inicialização -------------------------
def inicializa_funcionarios():
    """
    Cria tabela funcionarios no Postgres (se não existir).
    Mantemos 'foto' como TEXT (caminho ou URL), mas sincronizamos bytes em usuarios.foto.
    """
    with conectar_banco() as conn, conn.cursor() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS funcionarios (
                id UUID PRIMARY KEY,
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
            """
        )
        conn.commit()


# ----------------------------- Painel admin -----------------------------
def painel_administrativo():
    aplicar_estilo_upload()

    user = st.session_state.get("usuario", {})
    if user.get("perfil") != "admin":
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


# ----------------------------- Usuários -----------------------------
def exibir_usuarios_layout():
    st.markdown("### 👥 Lista de Usuários")
    with conectar_banco() as conn, conn.cursor() as c:
        c.execute("SELECT id, nome_completo, email, perfil, status, ultimo_acesso FROM usuarios")
        usuarios = c.fetchall()

    cols_header = st.columns([3, 4, 2, 2, 2, 1, 1])
    for col, title in zip(cols_header, ["Nome", "Email", "Perfil", "Status", "Último Acesso", "Ações", "Excluir"]):
        col.markdown(f"**{title}**")
    st.markdown("<hr style='margin-top:-10px;margin-bottom:10px;'>", unsafe_allow_html=True)

    for idx, (uid, nome, email, perfil, status, acesso) in enumerate(usuarios):
        row = st.columns([3, 4, 2, 2, 2, 1, 1])
        row[0].markdown(f"**{nome}**")
        row[1].markdown(email)
        row[2].markdown(perfil)
        row[3].markdown(status)
        acesso_fmt = (datetime.fromisoformat(acesso).strftime("%d/%m/%Y %H:%M") if acesso else "N/A")
        row[4].markdown(acesso_fmt)

        # Promover / Rebaixar
        if perfil != "admin":
            if row[5].button("🔰", key=f"prom-{uid}-{idx}", help="Promover a administrador"):
                with conectar_banco() as conn, conn.cursor() as c:
                    c.execute("UPDATE usuarios SET perfil='admin' WHERE id=%s", (uid,))
                    conn.commit()
                st.success(f"Usuário **{nome}** promovido a admin!")
                st.rerun()
        else:
            if row[5].button("⬇️", key=f"dem-{uid}-{idx}", help="Rebaixar a usuário"):
                with conectar_banco() as conn, conn.cursor() as c:
                    c.execute("UPDATE usuarios SET perfil='usuario' WHERE id=%s", (uid,))
                    conn.commit()
                st.success(f"Usuário **{nome}** rebaixado a usuário padrão!")
                st.rerun()

        # Excluir usuário
        if row[6].button("🗑️", key=f"delete-user-{uid}-{idx}", help="Excluir usuário"):
            with conectar_banco() as conn, conn.cursor() as c:
                c.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
                c.execute("DELETE FROM funcionarios WHERE id=%s", (uid,))
                conn.commit()
            st.success(f"Usuário **{nome}** excluído com sucesso!")
            st.rerun()


# ------------------------ Aprovações pendentes ------------------------
def exibir_aprovacoes_pendentes():
    st.markdown("### ⏳ Solicitações de Acesso Pendentes")
    with conectar_banco() as conn, conn.cursor() as c:
        c.execute(
            "SELECT id, nome_completo, email, cargo, setor, matricula, unidade FROM usuarios WHERE status='pendente'"
        )
        pendentes = c.fetchall()

    if not pendentes:
        st.info("Nenhuma solicitação pendente.")
        return

    cols_header = st.columns([3, 4, 3, 2, 2])
    for col, title in zip(cols_header, ["Nome", "Email", "Cargo / Setor / Matrícula", "Aprovar", "Rejeitar"]):
        col.markdown(f"**{title}**")
    st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

    for idx, (uid, nome, email, cargo, setor, matricula, unidade) in enumerate(pendentes):
        cols = st.columns([3, 4, 3, 2, 2])
        cols[0].markdown(nome)
        cols[1].markdown(email)
        cols[2].markdown(f"{cargo} / {setor}\n`{matricula}` / {unidade}")

        if cols[3].button("✅ Aprovar", key=f"aprovar-{uid}-{idx}"):
            with conectar_banco() as conn, conn.cursor() as c:
                c.execute("UPDATE usuarios SET status='trocar_senha' WHERE id=%s", (uid,))
                # cria registro em funcionarios (ignora se já existir)
                c.execute(
                    """
                    INSERT INTO funcionarios (id, nome, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade, foto, estrangeiro)
                    SELECT id, nome_completo, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade, '', 0
                      FROM usuarios
                     WHERE id=%s
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid,)
                )
                conn.commit()
            st.success(f"Usuário **{nome}** aprovado e cadastrado como funcionário!")
            st.rerun()
            return

        if cols[4].button("❌ Rejeitar", key=f"rejeitar-{uid}-{idx}"):
            with conectar_banco() as conn, conn.cursor() as c:
                c.execute("UPDATE usuarios SET status='rejeitado' WHERE id=%s", (uid,))
                conn.commit()
            st.success(f"Usuário **{nome}** rejeitado!")
            st.rerun()
            return


# ---------------------- Funcionários: CRUD + CSV ----------------------
def gerenciar_funcionarios():
    inicializa_funcionarios()
    default_pass = "Palavrapasse@001"

    if "edit" not in st.session_state:
        st.session_state["edit"] = None

    if st.session_state.get("edit"):
        editar_funcionario(st.session_state["edit"])
        return

    st.markdown("### ➕ Adicionar Funcionários")
    if st.button("➕ Novo Funcionário"):
        st.session_state["show_form"] = not st.session_state.get("show_form", False)

    if st.session_state.get("show_form"):
        with st.form("form_func"):
            col1, col2 = st.columns([3, 1])
            with col1:
                nome = st.text_input("*Nome completo")
                cargo = st.text_input("*Cargo")
                setor = st.text_input("Setor")
                matricula = st.text_input("*Matrícula")
                email = st.text_input("*E-mail corporativo")
                telefone = st.text_input("Telefone")
                data_adm = st.date_input("Data de admissão")
                tipo_contrato = st.selectbox("Tipo de contrato", ["CLT", "PJ", "Estagiário", "Outro"])
                unidade = st.text_input("*Unidade")
                estrangeiro = st.checkbox("Funcionário estrangeiro (Interface em inglês)?")
            with col2:
                foto = st.file_uploader("Foto de perfil", type=["jpg", "jpeg", "png"])
            submitted = st.form_submit_button("Cadastrar funcionário")

        if submitted:
            if not all([nome, cargo, matricula, email, unidade]):
                st.warning("Preencha todos os campos obrigatórios marcados com *.")
            else:
                func_id = str(uuid4())

                # bytes da foto para usuarios.foto (BYTEA)
                foto_bytes = None
                if foto is not None:
                    foto_bytes = foto.getvalue()
                    # opcional: ainda salvar no disco, se quiser manter
                    ext = os.path.splitext(foto.name)[1]
                    foto_path = os.path.join(UPLOAD_DIR, f"{func_id}{ext}")
                    with open(foto_path, "wb") as f:
                        f.write(foto_bytes)
                else:
                    foto_path = ""

                senha_hash = bcrypt.hashpw(default_pass.encode(), bcrypt.gensalt())

                with conectar_banco() as conn, conn.cursor() as c:
                    # cria usuário vinculado
                    c.execute(
                        """
                        INSERT INTO usuarios
                        (id, nome_completo, cargo, setor, matricula, email, telefone, data_admissao,
                         tipo_contrato, unidade, senha_hash, perfil, status, ultimo_acesso, foto)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'usuario','trocar_senha',%s,%s)
                        """,
                        (
                            func_id, nome, cargo, setor, matricula, email.lower(), telefone,
                            data_adm.isoformat(), tipo_contrato, unidade, senha_hash,
                            datetime.now().isoformat(), foto_bytes
                        )
                    )
                    # cria funcionário espelho (mantemos foto TEXT por compatibilidade)
                    c.execute(
                        """
                        INSERT INTO funcionarios
                        (id, nome, cargo, setor, matricula, email, telefone, data_admissao,
                         tipo_contrato, unidade, foto, estrangeiro)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            func_id, nome, cargo, setor, matricula, email.lower(), telefone,
                            data_adm.isoformat(), tipo_contrato, unidade, foto_path, int(estrangeiro)
                        )
                    )
                    conn.commit()

                st.success("Funcionário cadastrado e usuário criado com senha padrão!")
                st.session_state.pop("show_form", None)
                st.rerun()

    # Importação/Exportação CSV
    st.markdown("---")
    st.markdown("### 📂 Importação/Exportação de Funcionários")
    col_export, col_import = st.columns([1, 2])
    with col_export:
        if st.button("📄 Exportar CSV"):
            with conectar_banco() as conn, conn.cursor() as c:
                c.execute(
                    "SELECT nome, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade FROM funcionarios"
                )
                rows = c.fetchall()
            df = pd.DataFrame(rows, columns=["nome","cargo","setor","matricula","email","telefone","data_admissao","tipo_contrato","unidade"])
            st.download_button("📁 Baixar lista", data=df.to_csv(index=False).encode("utf-8"),
                               file_name="funcionarios.csv", mime="text/csv")
    with col_import:
        if st.button("📥 Importar CSV"):
            st.session_state["up"] = True
    if st.session_state.get("up"):
        up_file = st.file_uploader("Selecionar arquivo CSV", type=["csv"])
        if up_file:
            df = pd.read_csv(up_file)
            with conectar_banco() as conn, conn.cursor() as c:
                for _, row in df.iterrows():
                    fid = str(uuid4())
                    # funcionario
                    c.execute(
                        """
                        INSERT INTO funcionarios
                        (id, nome, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade, foto, estrangeiro)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'',0)
                        """,
                        (
                            fid, row["nome"], row["cargo"], row.get("setor",""),
                            row["matricula"], row["email"].lower(), row.get("telefone",""),
                            row["data_admissao"], row["tipo_contrato"], row["unidade"]
                        )
                    )
                    # usuário espelho
                    sh = bcrypt.hashpw("Palavrapasse@001".encode(), bcrypt.gensalt())
                    c.execute(
                        """
                        INSERT INTO usuarios
                        (id, nome_completo, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade, senha_hash, perfil, status, ultimo_acesso, foto)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'usuario','trocar_senha',%s,NULL)
                        """,
                        (
                            fid, row["nome"], row["cargo"], row.get("setor",""),
                            row["matricula"], row["email"].lower(), row.get("telefone",""),
                            row["data_admissao"], row["tipo_contrato"], row["unidade"],
                            sh, datetime.now().isoformat()
                        )
                    )
                conn.commit()
            st.success("Funcionários importados com sucesso!")
            st.session_state.pop("up", None)
            st.rerun()

    # Listagem, filtro e ações
    st.markdown("<hr style='margin-top:10px;margin-bottom:20px;'>", unsafe_allow_html=True)
    st.markdown("### 👥 Funcionários cadastrados")
    filtro = st.text_input("Filtrar por nome, matrícula, cargo ou unidade")

    with conectar_banco() as conn, conn.cursor() as c:
        c.execute("SELECT id, nome, matricula, unidade, cargo FROM funcionarios")
        all_funcs = c.fetchall()

    if filtro:
        filtro_low = filtro.lower()
        funcs = [f for f in all_funcs if filtro_low in " ".join([str(x) for x in f]).lower()]
    else:
        funcs = all_funcs

    cols = st.columns([3, 2, 2, 1, 1])
    for col, title in zip(cols, ["Nome", "Cargo", "Unidade", "Editar", "Excluir"]):
        col.markdown(f"**{title}**")
    st.markdown("<hr style='margin:0 0 10px 0;'>", unsafe_allow_html=True)

    for fid, nome, mat, uni, carg in funcs:
        row_cols = st.columns([3, 2, 2, 1, 1])
        row_cols[0].markdown(f"**{nome}**\n`{mat}`")
        row_cols[1].markdown(carg or "")
        row_cols[2].markdown(uni or "")
        if row_cols[3].button("✏️", key=f"edit-{fid}"):
            st.session_state["edit"] = fid
            st.rerun()
        if row_cols[4].button("🗑️", key=f"del-{fid}"):
            with conectar_banco() as conn, conn.cursor() as c:
                c.execute("DELETE FROM funcionarios WHERE id=%s", (fid,))
                c.execute("DELETE FROM usuarios      WHERE id=%s", (fid,))
                conn.commit()
            st.success("Funcionário removido com sucesso!")
            st.rerun()


def editar_funcionario(fid):
    with conectar_banco() as conn, conn.cursor() as c:
        c.execute(
            """
            SELECT nome, cargo, setor, matricula, email, telefone, data_admissao, tipo_contrato, unidade, foto, estrangeiro
              FROM funcionarios
             WHERE id = %s
            """,
            (fid,)
        )
        row = c.fetchone()

    if not row:
        st.error("Funcionário não encontrado.")
        return

    (nome_atual, cargo_atual, setor_atual, mat_atual, email_atual, tel_atual,
     da_atual, tc_atual, uni_atual, foto_atual, estr_atual) = row

    st.markdown("### ✏️ Editando Funcionário")
    with st.form(f"form_edit_{fid}"):
        nome_novo = st.text_input("Nome completo", value=nome_atual or "")
        cargo_novo = st.text_input("Cargo", value=cargo_atual or "")
        setor_novo = st.text_input("Setor", value=setor_atual or "")
        mat_novo = st.text_input("Matrícula", value=mat_atual or "")
        email_novo = st.text_input("E-mail corporativo", value=email_atual or "")
        tel_novo = st.text_input("Telefone", value=tel_atual or "")
        da_novo = st.date_input("Data de admissão", value=datetime.fromisoformat(da_atual) if da_atual else datetime.now())
        tc_opts = ["CLT", "PJ", "Estagiário", "Outro"]
        tc_idx = tc_opts.index(tc_atual) if tc_atual in tc_opts else 0
        tc_novo = st.selectbox("Tipo de contrato", tc_opts, index=tc_idx)
        uni_novo = st.text_input("Unidade", value=uni_atual or "")
        estr_novo = st.checkbox("Funcionário estrangeiro?", value=bool(estr_atual))
        foto_upl = st.file_uploader("Alterar foto de perfil", type=["jpg", "jpeg", "png"])

        col1, col2 = st.columns(2)
        with col1:
            salvar = st.form_submit_button("Salvar alterações")
        with col2:
            cancelar = st.form_submit_button("Cancelar")

    if salvar:
        novo_path = foto_atual or ""
        foto_bytes = None
        if foto_upl:
            foto_bytes = foto_upl.getvalue()
            ext = os.path.splitext(foto_upl.name)[1]
            novo_path = os.path.join(UPLOAD_DIR, f"{uuid4()}{ext}")
            with open(novo_path, "wb") as f:
                f.write(foto_bytes)

        with conectar_banco() as conn, conn.cursor() as c:
            # atualiza funcionarios
            c.execute(
                """
                UPDATE funcionarios
                   SET nome=%s, cargo=%s, setor=%s, matricula=%s, email=%s, telefone=%s,
                       data_admissao=%s, tipo_contrato=%s, unidade=%s, foto=%s, estrangeiro=%s
                 WHERE id=%s
                """,
                (
                    nome_novo, cargo_novo, setor_novo, mat_novo, email_novo.lower(), tel_novo,
                    da_novo.isoformat(), tc_novo, uni_novo, novo_path, int(estr_novo), fid
                )
            )
            # mantém sincronizado em usuarios (exceto senha)
            c.execute(
                """
                UPDATE usuarios
                   SET nome_completo=%s, cargo=%s, setor=%s, matricula=%s, email=%s, telefone=%s,
                       data_admissao=%s, tipo_contrato=%s, unidade=%s
                 WHERE id=%s
                """,
                (
                    nome_novo, cargo_novo, setor_novo, mat_novo, email_novo.lower(), tel_novo,
                    da_novo.isoformat(), tc_novo, uni_novo, fid
                )
            )
            if foto_bytes is not None:
                # grava bytes da foto também em usuarios.foto (BYTEA)
                c.execute("UPDATE usuarios SET foto=%s WHERE id=%s", (foto_bytes, fid))
            conn.commit()

        st.success("Funcionário atualizado com sucesso!")
        st.session_state["edit"] = None
        st.rerun()

    if cancelar:
        st.session_state["edit"] = None
        st.rerun()
