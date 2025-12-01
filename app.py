import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Belfar",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS PERSONALIZADOS -----------------
st.markdown("""
<style>
    /* Ajuste de Fundo e Fontes */
    .main {
        background-color: #f8f9fa;
    }
    h1, h2, h3 {
        color: #2c3e50;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* Card Estilizado */
    .stCard {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }

    /* Botões */
    .stButton>button {
        width: 100%;
        background-color: #55a68e;
        color: white;
        font-weight: bold;
        border-radius: 8px;
        height: 50px;
        border: none;
    }
    .stButton>button:hover {
        background-color: #448c75;
    }

    /* Marcações de Texto */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }

    /* Upload Area */
    .uploadedFile {
        border: 2px dashed #55a68e;
        background-color: #e6fffa;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]
SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]
SECOES_NAO_COMPARAR = "APRESENTAÇÕES, COMPOSIÇÃO, DIZERES LEGAIS"

# ----------------- FUNÇÕES DE BACKEND (IA) -----------------

def get_gemini_model(api_key):
    if not api_key: return None
    try:
        genai.configure(api_key=api_key)
        # Tenta conectar no modelo mais novo disponível (2.5 Flash)
        try:
            return genai.GenerativeModel('models/gemini-2.5-flash')
        except:
            try:
                return genai.GenerativeModel('models/gemini-2.0-flash')
            except:
                # Fallback para o 1.5 Flash (Estável e Rápido)
                return genai.GenerativeModel('models/gemini-1.5-flash')
    except:
        return None

def process_uploaded_file(uploaded_file):
    """Processa o arquivo enviado (PDF ou DOCX) de forma otimizada."""
    if not uploaded_file: return None
    
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()

        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            images = []
            
            # OTIMIZAÇÃO: Limita a 4 páginas e reduz qualidade
            limit_pages = min(4, len(doc))
            
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0)) # 72 DPI
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg", quality=70))
                images.append(Image.open(img_byte_arr))
                pix = None
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo {uploaded_file.name}: {e}")
        return None
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"): text = text[4:]
    return text

def extract_json(text):
    try:
        clean = clean_json_response(text)
        start = clean.find('{')
        end = clean.rfind('}') + 1
        if start != -1 and end != -1:
            return json.loads(clean[start:end])
        return json.loads(clean)
    except: return None

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    # Logo (substitua pela URL correta ou remova se não tiver)
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Configuração")
    
    # Input de API Key Seguro
    # Tenta pegar do segredo do Streamlit ou pede input
    default_key = os.environ.get("GEMINI_API_KEY", "")
    api_key = st.text_input("Chave API Google:", value=default_key, type="password", help="Cole sua chave AIza...")
    
    if api_key:
        st.success("Chave inserida!")
    else:
        st.warning("Insira a chave para começar.")
    
    st.divider()
    
    # Menu de Navegação
    pagina = st.radio(
        "Ferramenta:",
        ["🏠 Início", "💊 Ref x Belfar", "📋 Conferência MKT", "🎨 Gráfica x Arte"]
    )
    
    st.info("v2.5 - Gemini 2.5 Flash Integration")

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 20px;">
        <h1 style="color: #55a68e;">🔬 Validador Inteligente</h1>
        <p style="font-size: 18px; color: #666;">Central de auditoria e conformidade de bulas farmacêuticas.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="stCard">
            <h3>💊 Ref x Belfar</h3>
            <p>Comparação semântica de texto técnico. Valida posologia e contraindicações.</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="stCard">
            <h3>📋 Conferência MKT</h3>
            <p>Validação rápida de itens obrigatórios (Logos, SAC, Frases Legais).</p>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="stCard">
            <h3>🎨 Gráfica x Arte</h3>
            <p>Validação visual pixel-a-pixel. Detecta erros de impressão e manchas.</p>
        </div>
        """, unsafe_allow_html=True)

# ----------------- PÁGINAS DE FERRAMENTA -----------------
else:
    st.markdown(f"## {pagina}")
    
    # Configurações específicas por página
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    
    if pagina == "💊 Ref x Belfar":
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL
                nome_tipo = "Profissional"
    
    st.divider()
    
    # Área de Upload
    c1, c2 = st.columns(2)
    with c1:
        f1 = st.file_uploader("📄 Documento Referência / Padrão", type=["pdf", "docx"], key="f1")
    with c2:
        f2 = st.file_uploader("📄 Documento Belfar / Candidato", type=["pdf", "docx"], key="f2")
        
    # Botão de Ação
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not api_key:
            st.error("⚠️ Por favor, insira a Chave API na barra lateral.")
        elif not f1 or not f2:
            st.warning("⚠️ Por favor, faça o upload dos dois arquivos.")
        else:
            with st.spinner("🤖 Analisando documentos com Inteligência Artificial..."):
                try:
                    model = get_gemini_model(api_key)
                    if not model:
                        st.error("Erro ao configurar o modelo. Verifique sua chave API.")
                        st.stop()

                    # Processamento
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if not d1 or not d2:
                        st.error("Falha ao ler os arquivos.")
                        st.stop()

                    # Payload
                    payload = []
                    if d1['type'] == 'text': payload.append(f"--- REFERÊNCIA ---\n{d1['data']}")
                    else: payload.append("--- REFERÊNCIA ---"); payload.extend(d1['data'])
                    
                    if d2['type'] == 'text': payload.append(f"--- BELFAR ---\n{d2['data']}")
                    else: payload.append("--- BELFAR ---"); payload.extend(d2['data'])

                    # Prompt
                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                    
                    prompt = f"""
                    Atue como Auditor de Qualidade Farmacêutica.
                    Analise os documentos (Ref vs Belfar).
                    
                    TAREFA: Extraia o texto COMPLETO de cada seção abaixo.
                    LISTA ({nome_tipo}):
                    {secoes_str}
                    
                    REGRAS DE FORMATAÇÃO (Retorne texto com estas tags HTML):
                    1. Divergências de sentido: <mark class='diff'>texto diferente</mark>
                       (IGNORE divergências nas seções: {SECOES_NAO_COMPARAR}).
                    2. Erros de Português: <mark class='ort'>erro</mark>
                    3. Datas ANVISA: <mark class='anvisa'>dd/mm/aaaa</mark>
                    
                    SAÍDA JSON OBRIGATÓRIA (Sem markdown ```json):
                    {{
                        "METADADOS": {{ "score": 90, "datas": ["..."] }},
                        "SECOES": [
                            {{ "titulo": "NOME SEÇÃO", "ref": "texto...", "bel": "texto...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" | "INFORMATIVO" }}
                        ]
                    }}
                    """

                    # Chamada IA
                    response = model.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"},
                        safety_settings={
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }
                    )
                    
                    data = extract_json(response.text)
                    if not data:
                        st.error("A IA não retornou um JSON válido. Tente novamente.")
                    else:
                        # Exibição
                        meta = data.get("METADADOS", {})
                        
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                        m2.metric("Seções Analisadas", len(data.get("SECOES", [])))
                        m3.metric("Datas", ", ".join(meta.get("datas", [])) or "-")
                        
                        st.divider()
                        
                        for sec in data.get("SECOES", []):
                            status = sec.get('status', 'N/A')
                            icon = "✅"
                            if "DIVERGENTE" in status: icon = "❌"
                            elif "FALTANTE" in status: icon = "🚨"
                            elif "INFORMATIVO" in status: icon = "ℹ️"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                cA, cB = st.columns(2)
                                with cA:
                                    st.markdown("**Referência**")
                                    st.markdown(sec.get('ref', ''), unsafe_allow_html=True)
                                with cB:
                                    st.markdown("**Belfar**")
                                    st.markdown(sec.get('bel', ''), unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro durante a análise: {e}")
