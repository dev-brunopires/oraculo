from __future__ import annotations

import mimetypes
import os
import sqlite3
from functools import lru_cache
from typing import Optional
from uuid import uuid4

import streamlit as st

from db import conectar_banco, extract_text_from_file

# Caminhos / constantes
BANCO = "oraculo.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DEFAULT_ICONS = {
    "Procedimento": "📁",
    "Formulário": "📄",
    "Manual": "📘",
    "Outro": "📌",
}

# Número de caracteres a exibir no preview da descrição
PREVIEW_CHARS = 80

# =========================================================
# Inicialização defensiva (caso app chame direto a página)
# =========================================================
@st.cache_data(show_spinner=False)
def inicializa_biblioteca() -> bool:
    conn = conectar_banco(); c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS biblioteca (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            descricao TEXT,
            tag TEXT,
            arquivo TEXT NOT NULL,
            data_envio TEXT NOT NULL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS biblioteca_text (
            id TEXT PRIMARY KEY,
            conteudo TEXT NOT NULL,
            FOREIGN KEY(id) REFERENCES biblioteca(id)
        )
        """
    )
    c.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS biblioteca_fts
        USING fts5(id UNINDEXED, conteudo, titulo, descricao);
        """
    )
    conn.commit(); conn.close()
    return True


# =========================================================
# Helpers de download / nome / preview
# =========================================================
@lru_cache(maxsize=512)
def _load_upload_bytes(fname: str) -> tuple[bytes, str]:
    """Carrega bytes do arquivo salvo em *uploads* e tenta inferir MIME."""
    path = os.path.join(UPLOAD_DIR, fname)
    if not os.path.exists(path):
        return b"", "application/octet-stream"
    with open(path, "rb") as f:
        data = f.read()
    mime, _ = mimetypes.guess_type(fname)
    return data, (mime or "application/octet-stream")


def _nome_exibicao(fname: str) -> str:
    """Remove UUID prefix ``<uuid>_`` ao exibir para download."""
    base = os.path.basename(fname)
    if "_" in base:
        return base.split("_", 1)[1]
    return base


def _preview(texto: str, n: int = PREVIEW_CHARS) -> str:
    if not texto:
        return "Sem descrição"
    txt = texto.strip().replace("\n", " ")
    if len(txt) <= n:
        return txt
    return txt[: n - 1] + "…"


# =========================================================
# Página Biblioteca
# =========================================================

def pagina_biblioteca():
    inicializa_biblioteca()
    st.subheader("📁 Meus Arquivos")

    usuario = st.session_state.get("usuario", {})

    # -----------------------------------------------------
    # Upload (somente admin)
    # -----------------------------------------------------
    if usuario.get("perfil") == "admin":
        with st.expander("➕ Adicionar novo material", expanded=False):
            with st.form("form_biblio", clear_on_submit=True):
                titulo = st.text_input("Título do material")
                descricao = st.text_area("Descrição (resumo curto ajuda o Oráculo!)")
                tag = st.selectbox("Tag", list(DEFAULT_ICONS.keys()))
                arquivo = st.file_uploader("Upload do arquivo")
                enviar = st.form_submit_button("Salvar material")

            if enviar:
                if not titulo or not arquivo:
                    st.warning("Preencha título e arquivo.")
                else:
                    novo_id = str(uuid4())
                    arquivo_path = os.path.join(UPLOAD_DIR, f"{novo_id}_{arquivo.name}")
                    with open(arquivo_path, "wb") as f:
                        f.write(arquivo.read())
                    texto = extract_text_from_file(arquivo_path)
                    conn = conectar_banco(); c = conn.cursor()
                    c.execute(
                        "INSERT INTO biblioteca (id, titulo, descricao, tag, arquivo, data_envio)"
                        " VALUES (?, ?, ?, ?, ?, datetime('now'))",
                        (novo_id, titulo, descricao, tag, os.path.basename(arquivo_path)),
                    )
                    c.execute(
                        "INSERT INTO biblioteca_text (id, conteudo) VALUES (?, ?)",
                        (novo_id, texto),
                    )
                    c.execute(
                        "INSERT INTO biblioteca_fts (id, conteudo, titulo, descricao) VALUES (?, ?, ?, ?)",
                        (novo_id, texto, titulo, descricao),
                    )
                    conn.commit(); conn.close()
                    st.success("Material salvo com sucesso!")
                    st.rerun()

    # -----------------------------------------------------
    # Abas por tag
    # -----------------------------------------------------
    tab_labels = ["📂 Todos"] + [f"{icone} {t}" for t, icone in DEFAULT_ICONS.items()]
    tabs = st.tabs(tab_labels)
    filtros = [None] + list(DEFAULT_ICONS.keys())

    for idx, (tab, filtro_tag) in enumerate(zip(tabs, filtros)):
        with tab:
            prefix = f"t{idx}"
            renderizar_lista(prefix=prefix, filtro_tag=filtro_tag)


# =========================================================
# Renderização de lista
# =========================================================

def renderizar_lista(prefix: str, filtro_tag: Optional[str] = None):
    termo = st.text_input(
        "🔎 Buscar título/descrição/conteúdo:", key=f"{prefix}_busca",
    ).strip()

    pagina_key = f"{prefix}_pagina"
    pagina = st.session_state.get(pagina_key, 0)
    limite = 20
    offset = pagina * limite

    sql = (
        "SELECT b.id, b.titulo, b.descricao, b.tag, b.arquivo, b.data_envio "
        "FROM biblioteca AS b JOIN biblioteca_text AS bt ON b.id = bt.id "
    )
    filtros_sql = []
    params = []
    if filtro_tag:
        filtros_sql.append("b.tag = ?"); params.append(filtro_tag)
    if termo:
        filtros_sql.append("(b.titulo LIKE ? OR b.descricao LIKE ?)")
        params.extend([f"%{termo}%"] * 2)
    if filtros_sql:
        sql += " WHERE " + " AND ".join(filtros_sql)
    sql += " ORDER BY b.data_envio DESC LIMIT ? OFFSET ?"
    params.extend([limite, offset])

    conn = conectar_banco(); c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()

    if termo and not rows:
        q = termo.replace('"', ' ')
        fts_sql = (
            "SELECT b.id, b.titulo, b.descricao, b.tag, b.arquivo, b.data_envio "
            "FROM biblioteca AS b JOIN biblioteca_text AS bt ON b.id = bt.id "
            "JOIN biblioteca_fts ON b.id = biblioteca_fts.id "
            "WHERE biblioteca_fts MATCH ? ORDER BY b.data_envio DESC LIMIT ? OFFSET ?"
        )
        c.execute(fts_sql, (f'"{q}"', limite, offset))
        rows = c.fetchall()
    conn.close()

    col_prev, col_next = st.columns([1, 1])
    if pagina > 0 and col_prev.button("< Anterior", key=f"{prefix}_prev"):
        st.session_state[pagina_key] = pagina - 1; st.rerun()
    if len(rows) == limite and col_next.button("Próxima >", key=f"{prefix}_next"):
        st.session_state[pagina_key] = pagina + 1; st.rerun()

    usuario = st.session_state.get("usuario", {})
    edit_id = st.session_state.get("editando_id")
    del_id  = st.session_state.get("exclusao_id")

    for idx, (id_, titulo, descricao, tag, arquivo, data_envio) in enumerate(rows):
        row_prefix = f"{prefix}_row{idx}_{id_}"
        with st.container():
            c1, c2, c3 = st.columns([0.05, 0.65, 0.1])
            with c1:
                st.checkbox("", key=f"sel_{row_prefix}")
            with c2:
                icon = DEFAULT_ICONS.get(tag, "📎")
                st.markdown(f"{icon} **{titulo}**")
                st.caption(f"{_preview(descricao)} | `{data_envio[:10]}` | 🏷️ {tag}")
            with c3:
                bc1, bc2, bc3 = st.columns([1, 1, 1])
                data_bytes, mime = _load_upload_bytes(arquivo)
                dl_name = _nome_exibicao(arquivo)
                bc1.download_button("⬇️", data=data_bytes, file_name=dl_name, mime=mime,
                                     key=f"dl_{row_prefix}")
                if usuario.get("perfil") == "admin":
                    if bc2.button("✏️", key=f"ed_{row_prefix}"):
                        st.session_state["editando_id"] = id_; st.rerun()
                    if bc3.button("🗑️", key=f"ex_{row_prefix}"):
                        st.session_state["exclusao_id"] = id_; st.rerun()
                else:
                    bc2.write(""); bc3.write("")

        if edit_id == id_:
            with st.expander("✏️ Editando", expanded=True):
                with st.form(f"form_edit_{row_prefix}"):
                    novo_titulo = st.text_input("Novo título", value=titulo)
                    nova_descricao = st.text_area("Nova descrição", value=descricao)
                    tags = list(DEFAULT_ICONS.keys())
                    current = tags.index(tag) if tag in tags else tags.index("Outro")
                    nova_tag = st.selectbox("Nova tag", tags, index=current)
                    if st.form_submit_button("Salvar alterações"):
                        conn = conectar_banco(); c = conn.cursor()
                        c.execute("UPDATE biblioteca SET titulo=?, descricao=?, tag=? WHERE id=?",
                                  (novo_titulo, nova_descricao, nova_tag, id_))
                        c.execute("UPDATE biblioteca_fts SET titulo=?, descricao=? WHERE id=?",
                                  (novo_titulo, nova_descricao, id_))
                        conn.commit(); conn.close()
                        st.success("Material atualizado!")
                        st.session_state["editando_id"] = None; st.rerun()

        if del_id == id_:
            with st.expander("🗑️ Confirmar exclusão?", expanded=True):
                with st.form(f"form_del_{row_prefix}"):
                    confirmar = st.form_submit_button("✅ Confirmar")
                    cancelar  = st.form_submit_button("❌ Cancelar")
                if confirmar:
                    caminho = os.path.join(UPLOAD_DIR, arquivo)
                    if os.path.exists(caminho):
                        os.remove(caminho)
                    conn = conectar_banco(); c = conn.cursor()
                    c.execute("DELETE FROM biblioteca WHERE id=?", (id_,))
                    c.execute("DELETE FROM biblioteca_text WHERE id=?", (id_,))
                    c.execute("DELETE FROM biblioteca_fts WHERE id=?", (id_,))
                    conn.commit(); conn.close()
                    st.success("Material excluído!")
                    st.session_state["exclusao_id"] = None; st.rerun()
                elif cancelar:
                    st.session_state["exclusao_id"] = None; st.info("Exclusão cancelada."); st.rerun()

        st.markdown("<hr style='margin:0.5rem 0;'>", unsafe_allow_html=True)
