import streamlit as st

# 1) Configuração da página deve ser a primeira interação com Streamlit
st.set_page_config(page_title="Oráculo", layout="wide")

import base64
import os
import re
import time
from textwrap import dedent

from dotenv import load_dotenv

from db import conectar_banco

# ===================== CONFIGURAÇÃO DE CHAVES =====================
load_dotenv()  # carrega variáveis do .env
GROQ_KEY = os.getenv("GROQ_API_KEY")

# Captura exceções genéricas de API
APIError = Exception

# ===================== IMPORTS LANGCHAIN E GROQ =====================
from langchain_groq import ChatGroq

try:
    from langchain.memory import ConversationBufferMemory
    from langchain.prompts import ChatPromptTemplate
except ImportError:
    ConversationBufferMemory = None
    ChatPromptTemplate = None
    st.warning("⚠️ LangChain não instalado; funcionalidades de chat estarão indisponíveis.")

# ===================== IMPORTS E INICIALIZAÇÃO =====================
from streamlit_option_menu import option_menu

from admin import painel_administrativo
from biblioteca import pagina_biblioteca
from db import buscar_procedimentos, inicializa_banco, salvar_conversa
from login import exibir_login, exibir_trocar_senha, exibir_usuarios

# from neworaculo import pagina_neworaculo

# Modelo default
MODELO_PADRAO = "meta-llama/llama-4-scout-17b-16e-instruct"
MEMORIA = ConversationBufferMemory()
inicializa_banco()

# ===================== FUNÇÃO DE RETRY PARA STREAM =====================
def stream_with_retry(chain, args, max_retries=3):
    for attempt in range(max_retries):
        try:
            return chain.stream(args)
        except APIError as e:
            wait = 2 ** attempt
            st.warning(f"Erro na API (tentativa {attempt+1}/{max_retries}): {e}. Retentando em {wait}s…")
            time.sleep(wait)
    return chain.stream(args)

# ===================== PEGAR FOTO DO USUÁRIO =====================
def obter_foto_usuario(email: str) -> str:
    # Busca foto na coluna BYTEA (usuarios.foto). Se for URL salva em texto, também aceita.
    try:
        with conectar_banco() as conn, conn.cursor() as c:
            c.execute("SELECT foto FROM usuarios WHERE email = %s", (email.lower(),))
            row = c.fetchone()
    except Exception:
        row = None

    if row and row[0]:
        blob = row[0]
        # Se estiver salvo como URL em texto
        if isinstance(blob, str) and blob.startswith(("http://", "https://")):
            return blob
        # Caso típico: BYTEA -> bytes
        try:
            b = bytes(blob)
        except Exception:
            b = blob  # já é bytes
        b64 = base64.b64encode(b).decode()
        # Sem MIME salvo, assuma png (ou troque para jpeg se preferir)
        return f"data:image/png;base64,{b64}"

    # fallback: imagem padrão do projeto
    default_path = "img/circle-user.png"
    if os.path.exists(default_path):
        ext = os.path.splitext(default_path)[1].lower().lstrip('.') or 'png'
        with open(default_path, "rb") as img_f:
            b64 = base64.b64encode(img_f.read()).decode()
        return f"data:image/{ext};base64,{b64}"
    return ""

# ===================== CSS =====================
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] {
        background-color: #FDFDFD !important;
        border-right: 1px solid #E7E7E7;
        width: 500px !important;
        min-width: 400px !important;
        max-width: 600px !important;
    }
    .perfil-box {display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px 0;width:100%;}
    .perfil-img {width:80px;height:80px;border-radius:50%;object-fit:cover;object-position:center;background-color:#eee;margin-bottom:15px;border:2px solid #d3d3d3;box-shadow:0 0 6px rgba(0,0,0,.1);display:block;margin:0 auto 20px;}
    .perfil-nome-email{display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1.4;margin-bottom:20px;}
    .perfil-nome-email strong{font-size:1rem;margin-bottom:5px;}
    .perfil-nome-email small{font-size:.8rem;color:#555;}
    .streamlit-option-menu .option-menu-container{border-radius:15px !important;overflow:hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ===================== AUTENTICAÇÃO =====================
if "usuario" not in st.session_state:
    exibir_login(); st.stop()
usuario = st.session_state.get("usuario")

# ===================== TROCA DE SENHA =====================
if usuario.get("status") == "trocar_senha":
    st.warning("⚠️ Você precisa trocar sua senha antes de continuar.")
    exibir_trocar_senha(); st.stop()

# ===================== IDIOMA =====================
def obter_idioma_usuario() -> str:
    # Se tiver coluna 'idioma' (pt/en) ou 'estrangeiro' (bool), usa; senão, default 'pt'
    try:
        with conectar_banco() as conn, conn.cursor() as c:
            # tente ler 'idioma' (ex.: 'pt'/'en')
            c.execute("SELECT idioma FROM usuarios WHERE email = %s", (usuario["email"].lower(),))
            row = c.fetchone()
            if row and row[0]:
                val = str(row[0]).strip().lower()
                if val in ("pt", "en"):
                    return val
            # fallback: tente 'estrangeiro' (true => 'en')
            c.execute("SELECT estrangeiro FROM usuarios WHERE email = %s", (usuario["email"].lower(),))
            row = c.fetchone()
            if row and (row[0] in (1, True, "1", "t", "true", "True")):
                return "en"
    except Exception:
        pass
    return "pt"

if "idioma" not in st.session_state:
    st.session_state["idioma"] = obter_idioma_usuario()
IDIOMA = st.session_state["idioma"]
if "lang" in st.query_params:
    st.session_state["idioma"] = st.query_params["lang"]
    st.experimental_set_query_params(); st.rerun()

# ===================== TRADUÇÃO =====================
TEXTO = {
    "pt": {
        "titulo": "🤖 Oráculo da Empresa",
        "usuario_logado": "**Usuário logado:**",
        "navegacao": "Navegação",
        "oraculo": "Oráculo",
        "teste":   "Oráculo de Teste",
        "biblioteca": "Biblioteca",
        "gerenciamento": "Gerenciamento",
        "logout": "Logout",
        "pergunta": "Digite sua pergunta sobre os procedimentos",
        "acesso_admin": "⚙️ Acesso Administrativo",
    },
    "en": {
        "titulo": "🤖 Company Oracle",
        "usuario_logado": "**Logged user:**",
        "navegacao": "Navigation",
        "oraculo": "Oracle",
        "teste":   "Test Oracle",
        "biblioteca": "Library",
        "gerenciamento": "Admin",
        "logout": "Logout",
        "pergunta": "Type your question about the procedures",
        "acesso_admin": "⚙️ Admin Access",
    },
}[IDIOMA]

# ===================== SIDEBAR =====================
with st.sidebar:
    foto_perfil = obter_foto_usuario(usuario["email"])
    st.markdown("<div class='perfil-box'>", unsafe_allow_html=True)
    if foto_perfil:
        st.markdown(f"<img src='{foto_perfil}' class='perfil-img'/>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class='perfil-nome-email'>
            <strong>{usuario['nome']}</strong>
            <small>{usuario['email']}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    selected = option_menu(
        menu_title=TEXTO["navegacao"],
        options=[TEXTO["gerenciamento"], TEXTO["biblioteca"], TEXTO["oraculo"]],
        icons=["gear","book","robot"],
        menu_icon="cast",
        default_index=2,
        styles={
            "container": {"padding": "5px", "background-color": "#f8f9fa", "border": "1px solid #d3d3d3"},
            "icon": {"color": "black", "font-size": "18px"},
            "nav-link": {"font-size": "16px", "text-align": "left", "margin": "2px", "border-radius": "15px !important"},
            "nav-link-selected": {"background-color": "#F36F27", "color": "white"},
        },
    )
    st.markdown("""<div style='position: absolute; bottom: 2rem; width: 90%;'>""", unsafe_allow_html=True)
    if st.button(TEXTO["logout"] + " 🔒", use_container_width=True):
        st.session_state.clear(); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ===================== CONTEÚDO =====================
st.title(TEXTO["titulo"])

if selected == TEXTO["gerenciamento"]:
    if usuario.get("perfil") == "admin":
        with st.expander(TEXTO["acesso_admin"], expanded=True):
            painel_administrativo()
    else:
        st.error("🚫 Você não tem permissão para acessar o gerenciamento.")
elif selected == TEXTO["biblioteca"]:
    pagina_biblioteca()
elif selected == TEXTO["oraculo"]:
    MAX_HISTORY = 10
    memoria = st.session_state.get('memoria', MEMORIA)
    hist = memoria.buffer_as_messages[-MAX_HISTORY:] if memoria else []

    for mensagem in hist:
        st.chat_message(mensagem.type).markdown(mensagem.content)

    raw = st.chat_input(TEXTO["pergunta"])
    if raw:
        entrada = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # pre-filtro por nome de procedimento
        m = re.search(r"procedimentos? de ([\wÀ-ÿ ]+)", entrada, re.IGNORECASE)
        if m:
            nome = m.group(1).strip()
            procedimentos = buscar_procedimentos(query=nome, top_k=1, truncate_chars=None)
        else:
            procedimentos = buscar_procedimentos(query=entrada, top_k=10, truncate_chars=None)

        # orçamento de contexto
        MAX_TOTAL_CHARS = 30000
        MIN_PER_DOC = 500
        tot = sum(len(c) for _, c in procedimentos)
        if tot > MAX_TOTAL_CHARS and procedimentos:
            per_doc = max(MIN_PER_DOC, MAX_TOTAL_CHARS // len(procedimentos))
            procedimentos = [(t, c[:per_doc]) for t, c in procedimentos]

        if usuario.get("perfil") == "admin":
            total_chars = sum(len(c) for _, c in procedimentos)
            st.caption(f"DEBUG: {len(procedimentos)} docs ({total_chars:,} chars)")
            with st.expander("DEBUG: docs no prompt", expanded=False):
                for i, (t, c) in enumerate(procedimentos, 1):
                    st.write(f"{i}. {t} — {len(c):,} chars")

        docs_contexto = "\n\n".join(f"### {t}\n{c}" for t, c in procedimentos)
        system_message = dedent(f"""
Quando o usuário enviar apenas uma saudação, responda de forma calorosa e profissional.

Você é o Oráculo, consultor especialista em segurança do trabalho, focado em fortalecer a cultura de segurança na empresa. Sua missão:

• **Esclarecer dúvidas** sobre procedimentos internos e NRs.
• **Elaborar análises de riscos** detalhadas para atividades específicas.
• **Sugerir tópicos para cartões de observação** que auxiliem na criação de treinamentos.
• **Propor melhorias** nos procedimentos com base nas normas nacionais (NRs) e melhores práticas.
• **Fornecer planos de ação** e recomendações para elevar o padrão de segurança.

Antes de responder, pense passo a passo (chain-of-thought), identifique as seções relevantes do(s) documento(s) e as NRs aplicáveis.

Documentos internos relevantes:
{docs_contexto}

### Exemplos de saída desejada:

**Usuário:** Quais riscos no procedimento de Trabalho em Altura?
**Oráculo:**
1. **Identificação do risco:** Queda de altura (>2m) — NR-35 Art. 35.3.
2. **Medidas preventivas:** Uso de cinto de segurança com talabarte (EPI) e âncoras certificadas.
3. **Cartão de observação:** Verificar posicionamento do talabarte antes da subida.
4. **Treinamento sugerido:** Simulação de resgate em altura.

**Usuário:** Preciso de melhorias no procedimento de Espaços Confinados.
**Oráculo:**
1. **Adotar checklist de leitura de gases:** incluir detecção de H2S (NR-33 Art. 33.6).
2. **Fluxo de autorização:** detalhar responsáveis em cada etapa.
3. **Tópico para cartão de observação:** Verificar sinalização de área restrita.
4. **Plano de ação:** treinamento trimestral de resgate.

### Agora, sua vez:
""")

        template = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("placeholder", "{chat_history}"),
            ("user", "{input}")
        ])

        llm = ChatGroq(
            model=MODELO_PADRAO,
            api_key=GROQ_KEY,
            temperature=0.7,
            max_tokens=2048,
        )
        chain = template | llm

        st.chat_message('human').markdown(entrada)
        bot = st.chat_message('ai')
        raw_stream = stream_with_retry(chain, {'input': entrada, 'chat_history': hist})
        def filter_think(chunks):
            for chunk in chunks:
                txt = getattr(chunk, 'content', str(chunk))
                yield re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL)
        try:
            resposta = bot.write_stream(filter_think(raw_stream))
        except Exception as e:
            st.error(f"⚠️ Erro: {e}")
            resposta = "Desculpe, tente novamente mais tarde."

        try:
            memoria.chat_memory.add_user_message(entrada)
            memoria.chat_memory.add_ai_message(resposta)
        except:
            pass
        st.session_state['memoria'] = memoria

        salvar_conversa(usuario['email'], entrada, resposta)
#elif selected == TEXTO["teste"]:
    #pagina_neworaculo()  
