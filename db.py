import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import uuid4

# Diretório de uploads e banco de dados
BANCO = "oraculo.db"
UPLOAD_DIR = "uploads"
# Assegura diretório de uploads existe
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===================== Conexão =====================
def conectar_banco() -> sqlite3.Connection:
    """Retorna conexão SQLite para o banco principal."""
    return sqlite3.connect(BANCO)

# ===================== Inicialização com FTS5 =====================
def inicializa_banco():
    """
    Cria tabelas base e índice FTS5 para buscas full-text.
    Não destrói dados existentes.
    """
    conn = conectar_banco()
    c = conn.cursor()

    # Metadados de arquivos
    c.execute("""
        CREATE TABLE IF NOT EXISTS biblioteca (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            descricao TEXT,
            tag TEXT,
            arquivo TEXT NOT NULL,
            data_envio TEXT NOT NULL
        )
    """)

    # Conteúdo extraído
    c.execute("""
        CREATE TABLE IF NOT EXISTS biblioteca_text (
            id TEXT PRIMARY KEY,
            conteudo TEXT NOT NULL,
            FOREIGN KEY(id) REFERENCES biblioteca(id)
        )
    """)

    # Índice full-text
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS biblioteca_fts
        USING fts5(
            id UNINDEXED,
            conteudo,
            titulo,
            descricao
        );
    """)

    # Conversas
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT,
            pergunta TEXT,
            resposta TEXT,
            data TEXT DEFAULT (datetime('now'))
        )
    """)

    # Usuários
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id TEXT PRIMARY KEY,
            nome_completo TEXT NOT NULL,
            cargo TEXT,
            setor TEXT,
            matricula TEXT,
            email TEXT UNIQUE NOT NULL,
            telefone TEXT,
            data_admissao TEXT,
            tipo_contrato TEXT,
            unidade TEXT,
            senha_hash TEXT NOT NULL,
            perfil TEXT DEFAULT 'usuario',
            status TEXT DEFAULT 'pendente',
            ultimo_acesso TEXT
        )
    """)

    conn.commit()
    conn.close()

# ===================== Salvar conversa =====================
def salvar_conversa(usuario: str, pergunta: str, resposta: str):
    conn = conectar_banco()
    c = conn.cursor()
    c.execute(
        "INSERT INTO conversas (usuario, pergunta, resposta) VALUES (?, ?, ?)",
        (usuario, pergunta, resposta)
    )
    conn.commit()
    conn.close()

# ===================== Extração de texto =====================
def extract_text_from_file(caminho: str) -> str:
    """
    Extrai texto de arquivos suportados e retorna string.
    Falha silenciosa -> string vazia (para não quebrar o fluxo do upload).
    """
    ext = os.path.splitext(caminho)[1].lower()
    try:
        if ext == '.pdf':
            from PyPDF2 import PdfReader
            reader = PdfReader(caminho)
            return '\n'.join(page.extract_text() or '' for page in reader.pages)

        if ext in ('.txt', '.md'):
            with open(caminho, encoding='utf-8') as f:
                return f.read()

        if ext == '.csv':
            import pandas as pd
            return pd.read_csv(caminho).to_csv(index=False)

        if ext in ('.xls', '.xlsx'):
            import pandas as pd
            return pd.read_excel(caminho).to_csv(index=False)

        if ext == '.docx':
            from docx import Document
            return '\n'.join(p.text for p in Document(caminho).paragraphs)

    except Exception:
        return ''

    return ''

# ===================== Helpers FTS =====================
def _fts_sanitize_query(q: str) -> str:
    """
    Sanitiza termo para uso em FTS5 MATCH:
      - Remove aspas duplas
      - Envolve em aspas para busca por frase (melhora precisão, evita erro)
    """
    if not q:
        return ""
    q = q.strip().replace('"', ' ')
    return f'"{q}"'


def upsert_biblioteca_fts(id_: str, conteudo: str, titulo: str, descricao: str):
    """Remove e reinsere registro no índice FTS5 (uso após editar metadados)."""
    conn = conectar_banco(); c = conn.cursor()
    c.execute("DELETE FROM biblioteca_fts WHERE id=?", (id_,))
    c.execute(
        "INSERT INTO biblioteca_fts (id, conteudo, titulo, descricao) VALUES (?, ?, ?, ?)",
        (id_, conteudo, titulo, descricao)
    )
    conn.commit(); conn.close()

# ===================== Registrar arquivo e indexar =====================
def registrar_arquivo(id_: str, titulo: str, descricao: str, tag: str, buffer):
    """
    Salva arquivo, insere metadados, extrai conteúdo e popula FTS5.
    Chamador deve gerar o id_ (uuid4 no biblioteca.py).
    """
    nome = f"{uuid4()}_{buffer.name}"
    caminho = os.path.join(UPLOAD_DIR, nome)
    with open(caminho, 'wb') as f:
        f.write(buffer.read())

    conteudo = extract_text_from_file(caminho)

    conn = conectar_banco(); c = conn.cursor()
    # metadados
    c.execute(
        "INSERT INTO biblioteca (id, titulo, descricao, tag, arquivo, data_envio) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (id_, titulo, descricao, tag, nome)
    )
    # conteúdo extraído
    c.execute(
        "INSERT INTO biblioteca_text (id, conteudo) VALUES (?, ?)",
        (id_, conteudo)
    )
    # indexação FTS5
    c.execute(
        "INSERT INTO biblioteca_fts (id, conteudo, titulo, descricao) VALUES (?, ?, ?, ?)",
        (id_, conteudo, titulo, descricao)
    )
    conn.commit(); conn.close()

# ===================== Buscar procedimentos =====================
def buscar_procedimentos(
    query: Optional[str] = None,
    top_k: int = 5,
    truncate_chars: Optional[int] = None,
    mode: str = "full",              # "full" | "desc" | "mixed"
    fallback_chars: int = 2000,       # usado p/ mode="desc"/"mixed"
) -> List[Tuple[str, str]]:
    """Recupera procedimentos para o agente.

    Quando *query* é fornecida: faz busca FTS5 em (conteudo, titulo, descricao).
    Sem *query*: retorna últimos *top_k* por data_envio.

    *mode* controla o texto retornado:
      - "full": usa conteúdo integral (respeitando *truncate_chars* se dado).
      - "desc": usa apenas a descrição; se vazia -> primeiros *fallback_chars* do conteúdo.
      - "mixed": usa descrição + duas quebras de linha + primeiro *fallback_chars* do conteúdo.

    Retorna lista [(titulo, texto_para_prompt)].
    """
    conn = conectar_banco(); c = conn.cursor()

    if query:
        q = _fts_sanitize_query(query)
        sql = (
            "SELECT b.titulo, b.descricao, bt.conteudo "
            "FROM biblioteca_fts AS fts "
            "JOIN biblioteca      AS b  ON fts.id = b.id "
            "JOIN biblioteca_text AS bt ON b.id = bt.id "
            "WHERE fts MATCH ? "
            "ORDER BY b.data_envio DESC LIMIT ?"
        )
        try:
            c.execute(sql, (q, top_k))
        except sqlite3.OperationalError:
            # fallback super defensivo: lista por data sem filtro
            c.execute(
                "SELECT b.titulo, b.descricao, bt.conteudo FROM biblioteca b JOIN biblioteca_text bt ON b.id = bt.id ORDER BY b.data_envio DESC LIMIT ?",
                (top_k,)
            )
    else:
        c.execute(
            "SELECT b.titulo, b.descricao, bt.conteudo FROM biblioteca b JOIN biblioteca_text bt ON b.id = bt.id ORDER BY b.data_envio DESC LIMIT ?",
            (top_k,)
        )

    rows = c.fetchall(); conn.close()

    out: List[Tuple[str, str]] = []
    mode = (mode or "full").lower()
    for titulo, descricao, conteudo in rows:
        texto: str
        if mode == "desc":
            if descricao and descricao.strip():
                texto = descricao.strip()
            else:
                texto = (conteudo or "")[:fallback_chars]
        elif mode == "mixed":
            desc_part = (descricao or "").strip()
            cont_part = (conteudo or "")[:fallback_chars]
            if desc_part:
                texto = desc_part + "\n\n" + cont_part
            else:
                texto = cont_part
        else:  # full (default)
            texto = conteudo or ""
            if truncate_chars and truncate_chars > 0:
                texto = texto[:truncate_chars]
        out.append((titulo, texto))

    return out

# ===================== Reindex manual (opcional) =====================
def reindex_biblioteca_from_uploads(default_tag: str = "Outro"):
    """
    Reconstrói biblioteca*/biblioteca_fts a partir dos arquivos físicos em uploads/.
    Use com cuidado: apaga registros atuais dessas tabelas.
    (Q3: chamada manual)
    """
    conn = conectar_banco()
    c = conn.cursor()

    c.execute("DELETE FROM biblioteca")
    c.execute("DELETE FROM biblioteca_text")
    c.execute("DELETE FROM biblioteca_fts")
    conn.commit()

    for fname in os.listdir(UPLOAD_DIR):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        doc_id = str(uuid4())
        titulo = os.path.splitext(fname)[0]
        descricao = ""
        tag = default_tag
        conteudo = extract_text_from_file(fpath)

        c.execute(
            "INSERT INTO biblioteca (id, titulo, descricao, tag, arquivo, data_envio) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (doc_id, titulo, descricao, tag, fname),
        )
        c.execute(
            "INSERT INTO biblioteca_text (id, conteudo) VALUES (?, ?)",
            (doc_id, conteudo),
        )
        c.execute(
            "INSERT INTO biblioteca_fts (id, conteudo, titulo, descricao) VALUES (?, ?, ?, ?)",
            (doc_id, conteudo, titulo, descricao),
        )

    conn.commit()
    conn.close()


def buscar_procedimentos_prior_descricao(
    query: str,
    top_k_descricao: int = 3,
    top_k_full: int = 5,
    truncate_chars: int | None = None,
) -> list[tuple[str, str]]:
    """
    Estratégia em 2 estágios:

    1) Busca rápida em campos curtos (titulo, descricao) usando FTS5.
       Retorna até `top_k_descricao` IDs ordenados por data_envio recente.
    2) Se nada encontrado, cai na busca completa (conteudo + titulo + descricao)
       retornando até `top_k_full`.

    Retorna lista [(titulo, conteudo), ...].
    """
    if not query:
        # Sem query: delega pro buscar_procedimentos padrão (últimos por data)
        return buscar_procedimentos(query=None, top_k=top_k_full, truncate_chars=truncate_chars)

    q = _fts_sanitize_query(query)
    conn = conectar_banco(); c = conn.cursor()

    # --- Estágio 1: FTS só em titulo+descricao ---
    try:
        c.execute(
            """
            SELECT b.id, b.titulo
              FROM biblioteca_fts AS fts
              JOIN biblioteca AS b ON b.id = fts.id
             WHERE fts MATCH ?
             ORDER BY b.data_envio DESC
             LIMIT ?
            """,
            (q, top_k_descricao)
        )
        cand_rows = c.fetchall()
    except sqlite3.OperationalError:
        # se der erro no parser MATCH, zera candidatos
        cand_rows = []

    ids_escolhidos = [row[0] for row in cand_rows]

    # Se encontramos pelo menos 1 candidato, coleta os textos completos só desses
    if ids_escolhidos:
        # usa placeholders variáveis p/ IN
        ph = ",".join("?" for _ in ids_escolhidos)
        c.execute(
            f"""
            SELECT b.titulo, bt.conteudo
              FROM biblioteca_text bt
              JOIN biblioteca b ON b.id = bt.id
             WHERE bt.id IN ({ph})
             ORDER BY b.data_envio DESC
            """,
            ids_escolhidos
        )
        rows = c.fetchall()
        conn.close()
    else:
        # fallback estágio 2: busca completa (conteudo + titulo + descricao)
        conn.close()
        rows = buscar_procedimentos(
            query=query,
            top_k=top_k_full,
            truncate_chars=truncate_chars,
        )

    # truncamento final
    if truncate_chars and truncate_chars > 0:
        rows = [(t, c[:truncate_chars]) for t, c in rows]

    return rows
