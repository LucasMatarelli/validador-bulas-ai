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

# ----------------- ESTILOS CSS (Para ficar bonito) -----------------
st.markdown("""
<style>
    /* Remove cabeçalho padrão */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Estilo dos Cards */
    .stCard {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        text-align: center;
        height: 100%;
    }
    
    /* Botão Principal */
    .stButton > button {
        width: 100%;
        background-color: #55a68e;
        color: white;
        font-weight: bold;
        height: 60px;
        font-size: 18px;
        border-radius: 10px;
        border: none;
    }
    .stButton > button:hover {
        background-color: #448c75;
    }
    
    /* Marcações de Texto no Resultado */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 5px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 5px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 5px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
    
    /* Títulos */
    h1, h2, h3 { color: #2c3e50; }
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

# ----------------- FUNÇÕES BACKEND -----------------

def get_gemini_model(api_key):
    if not api_key: return None
    try:
        genai.configure(api_key=api_key)
        # Tenta conectar no 2.5 Flash (Mais novo e rápido)
        try: return genai.GenerativeModel('models/gemini-2.5-flash')
        except: 
            # Se falhar, tenta o 1.5 Flash (Padrão robusto)
            return genai.GenerativeModel('models/gemini-1.5-flash')
    except:
        return None

def process_uploaded_file(uploaded_file):
    """Lê o arquivo (PDF/DOCX) com otimização de memória."""
    if not uploaded_file: return None
    
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        # PDF (Imagem para Visão Computacional)
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            images = []
            
            # OTIMIZAÇÃO:
            # 1. Lê até 4 páginas (Suficiente para a maioria das análises)
            # 2. Qualidade média (1.5x) - Bom equilíbrio entre legibilidade e peso
            limit_pages = min(4, len(doc))
            
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg", quality=80))
                images.append(Image.open(img_byte_arr))
                pix = None # Libera memória
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
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

# ----------------- INTERFACE -----------------

# Barra Lateral
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador")
    
    # Tenta pegar a chave dos "Secrets" do Streamlit (Segurança)
    # Se não tiver, pede na tela
    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        api_key = st.text_input("Chave API Google:", type="password")
    
    if api_key:
        st.success("Conectado!")
    
    st.divider()
    
    pagina = st.radio(
        "Ferramenta:",
        ["🏠 Início", "💊 Ref x Belfar", "📋 Conferência MKT", "🎨 Gráfica x Arte"]
    )

# Página Inicial
if pagina == "🏠 Início":
    st.title("🔬 Validador Inteligente de Bulas")
    st.markdown("Bem-vindo à central de auditoria de documentos farmacêuticos.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="stCard">
            <h3>💊 Ref x Belfar</h3>
            <p>Comparação de texto técnico, posologia e contraindicações.</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class="stCard">
            <h3>📋 Conferência MKT</h3>
            <p>Validação rápida de itens obrigatórios (Logos, SAC).</p>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class="stCard">
            <h3>🎨 Gráfica x Arte</h3>
            <p>Validação visual pixel-a-pixel para impressão.</p>
        </div>
        """, unsafe_allow_html=True)

# Páginas de Ferramenta
else:
    st.header(f"{pagina}")
    
    # Configurações
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    
    if pagina == "💊 Ref x Belfar":
        tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
        if tipo_bula == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            nome_tipo = "Profissional"
    
    st.markdown("---")
    
    # Uploads
    c1, c2 = st.columns(2)
    with c1:
        f1 = st.file_uploader("📄 Documento Referência / Padrão", type=["pdf", "docx"], key="f1")
    with c2:
        f2 = st.file_uploader("📄 Documento Belfar / Candidato", type=["pdf", "docx"], key="f2")
    
    # Botão de Ação
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not api_key:
            st.error("⚠️ Chave API não encontrada. Configure nos Secrets ou na barra lateral.")
        elif not f1 or not f2:
            st.warning("⚠️ Por favor, faça o upload dos dois arquivos.")
        else:
            with st.spinner("🤖 A Inteligência Artificial está analisando os documentos..."):
                try:
                    model = get_gemini_model(api_key)
                    
                    # Processamento
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect() # Limpa memória

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
                    Compare os documentos. Extraia o texto COMPLETO das seções abaixo.
                    
                    LISTA ({nome_tipo}):
                    {secoes_str}
                    
                    REGRAS DE FORMATAÇÃO (Use HTML no texto):
                    1. Divergências: <mark class='diff'>texto diferente</mark> (IGNORE em {SECOES_NAO_COMPARAR}).
                    2. Erros PT: <mark class='ort'>erro</mark>
                    3. Datas: <mark class='anvisa'>dd/mm/aaaa</mark>
                    
                    SAÍDA JSON (Obrigatório):
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
                        st.error("Erro na resposta da IA. Tente novamente.")
                    else:
                        # Exibição dos Resultados
                        meta = data.get("METADADOS", {})
                        
                        k1, k2, k3 = st.columns(3)
                        k1.metric("Conformidade", f"{meta.get('score', 0)}%")
                        k2.metric("Seções", len(data.get("SECOES", [])))
                        k3.metric("Datas", ", ".join(meta.get("datas", [])) or "-")
                        
                        st.divider()
                        
                        for sec in data.get("SECOES", []):
                            status = sec.get('status', 'N/A')
                            icon = "✅"
                            if "DIVERGENTE" in status: icon = "❌"
                            elif "FALTANTE" in status: icon = "🚨"
                            elif "INFORMATIVO" in status: icon = "ℹ️"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                colA, colB = st.columns(2)
                                with colA:
                                    st.markdown("**Referência**")
                                    st.markdown(sec.get('ref', ''), unsafe_allow_html=True)
                                with colB:
                                    st.markdown("**Belfar**")
                                    st.markdown(sec.get('bel', ''), unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro: {e}")
