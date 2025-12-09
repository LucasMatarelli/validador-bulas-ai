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
    page_title="Validador de Bulas",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (RESTAURADOS E COMPLETOS) -----------------
st.markdown("""
<style>
    /* OCULTA A BARRA SUPERIOR (TOOLBAR) */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }

    /* Ajuste de Fundo e Fontes */
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* ESTILO DO MENU DE NAVEGAÇÃO (SIDEBAR) */
    .stRadio > div[role="radiogroup"] > label {
        background-color: white;
        border: 1px solid #e1e4e8;
        padding: 12px 15px;
        border-radius: 8px;
        margin-bottom: 8px;
        transition: all 0.2s;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #f0fbf7;
        border-color: #55a68e;
        color: #55a68e;
        cursor: pointer;
    }

    /* CARDS DA HOME (RESTAURADOS) */
    .stCard {
        background-color: white;
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05);
        margin-bottom: 25px;
        border: 1px solid #e1e4e8;
        transition: transform 0.2s;
        height: 100%;
    }
    .stCard:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 30px rgba(0,0,0,0.1);
        border-color: #55a68e;
    }

    /* Títulos dos Cards */
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    
    /* Destaques (Marca-textos) */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Box de Curva */
    .curve-box { background-color: #f8f9fa; border-left: 4px solid #55a68e; padding: 10px 15px; margin-top: 15px; font-size: 0.9rem; color: #666; }

    /* Botões */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }

    /* Marcações de Texto na Comparação */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
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
SECOES_SEM_DIVERGENCIA = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- FUNÇÕES DE BACKEND (IA) -----------------

def get_gemini_model():
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None, "Chave API não configurada!"

    genai.configure(api_key=api_key)
    
    # Auto-Discovery: Lista e escolhe automaticamente o melhor modelo
    try:
        modelos_disponiveis = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                modelos_disponiveis.append(m.name)
        
        if not modelos_disponiveis: return None, "Sem modelos disponíveis."

        preferencias = [
            'models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 
            'models/gemini-1.5-pro', 'models/gemini-pro', 'models/gemini-1.0-pro'
        ]

        modelo_escolhido = None
        for pref in preferencias:
            if pref in modelos_disponiveis:
                modelo_escolhido = pref
                break
        
        if not modelo_escolhido: modelo_escolhido = modelos_disponiveis[0]

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        return genai.GenerativeModel(modelo_escolhido, safety_settings=safety_settings), modelo_escolhido

    except Exception as e:
        return None, f"Erro Google AI: {e}"

def process_uploaded_file(uploaded_file):
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
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close(); gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro arquivo: {e}")
        return None
    return None

def extract_json(text):
    """
    Extrai JSON validando com Regex para evitar erros de texto extra.
    """
    try:
        text = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match: text = match.group(0)
        return json.loads(text)
    except:
        return None

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    model_instance, model_name_used = get_gemini_model()
    
    if model_instance:
        st.success(f"✅ Conectado: {model_name_used.replace('models/', '')}")
    else:
        st.error("❌ Erro de Conexão")
        if model_name_used: st.caption(f"{model_name_used}")
    
    st.divider()
    
    pagina = st.radio(
        "Navegação:",
        ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"]
    )
    
    st.divider()

# ----------------- PÁGINA INICIAL (LAYOUT RESTAURADO) -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e; font-size: 3rem; margin-bottom: 10px;">Validador Inteligente</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Central de auditoria e conformidade de bulas farmacêuticas com IA.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">💊 Medicamento Referência x BELFAR</div>
            <div class="card-text">
                Compara a bula de referência com a bula BELFAR.
                <br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">📋 Conferência MKT</div>
            <div class="card-text">
                Compara arquivo ANVISA com PDF MKT.
                <br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">🎨 Gráfica x Arte Vigente</div>
            <div class="card-text">
                Compara PDF Gráfica com Arte Vigente (Lê curvas).
                <br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ----------------- FERRAMENTA -----------------
else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE; nome_tipo = "Paciente"
    label_box1 = "Arquivo 1"; label_box2 = "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Documento de Referência"; label_box2 = "📄 Documento BELFAR"
        col, _ = st.columns([1, 2])
        if col.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL; nome_tipo = "Profissional"
    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 Arquivo ANVISA"; label_box2 = "📄 Arquivo MKT"
    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"; label_box2 = "📄 PDF da Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
    
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not f1 or not f2: st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"🤖 Analisando com {model_name_used.split('/')[-1]}..."):
                try:
                    d1 = process_uploaded_file(f1); d2 = process_uploaded_file(f2)
                    gc.collect()
                    if not d1 or not d2: st.error("Falha ao ler arquivos."); st.stop()

                    payload = ["CONTEXTO: Auditoria de Bulas. Saída estritamente JSON."]
                    n1 = label_box1.replace("📄 ", "").upper(); n2 = label_box2.replace("📄 ", "").upper()
                    
                    if d1['type']=='text': payload.append(f"--- {n1} ---\n{d1['data']}")
                    else: payload.append(f"--- {n1} ---"); payload.extend(d1['data'])
                    if d2['type']=='text': payload.append(f"--- {n2} ---\n{d2['data']}")
                    else: payload.append(f"--- {n2} ---"); payload.extend(d2['data'])

                    prompt = f"""
                    Atue como Auditor Farmacêutico RÍGIDO.
                    DOC 1: {n1} | DOC 2: {n2}
                    SEÇÕES ({nome_tipo}): {", ".join(lista_secoes)}

                    TAREFA: Compare as seções.
                    - Copie APENAS o parágrafo de texto (sem títulos).
                    - Use <mark class='diff'> para divergências.
                    - Use <mark class='ort'> para erros ortográficos.
                    - Busque data "Aprovado em" nos Dizeres Legais -> <mark class='anvisa'>data</mark>.

                    IMPORTANTE: RESPONDA APENAS O JSON. NÃO ESCREVA TEXTO ANTES OU DEPOIS.
                    JSON: {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE" }} ] }}
                    """

                    response = model_instance.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    
                    if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                        st.error("⚠️ Bloqueio de Copyright. Tente enviar apenas texto.")
                    else:
                        data = extract_json(response.text)
                        
                        if not data:
                            st.error("A IA não retornou um JSON válido.")
                            with st.expander("🛠️ Ver Resposta Bruta da IA (Debug)"):
                                st.code(response.text)
                        else:
                            meta = data.get("METADADOS", {})
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                            m2.metric("Seções Analisadas", len(data.get("SECOES", [])))
                            m3.metric("Datas Encontradas", ", ".join(meta.get("datas", [])) or "Nenhuma data")
                            
                            st.divider()
                            for sec in data.get("SECOES", []):
                                stt = sec.get('status', 'N/A')
                                icon = "✅"
                                if "DIVERGENTE" in stt: icon = "❌"
                                elif "FALTANTE" in stt: icon = "🚨"
                                if any(x in sec.get('titulo','').upper() for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                                
                                with st.expander(f"{icon} {sec.get('titulo')} — {stt}"):
                                    ca, cb = st.columns(2)
                                    with ca:
                                        st.markdown(f"**{n1}**")
                                        st.markdown(f"<div style='background:#f9f9f9;padding:10px;border-radius:5px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                    with cb:
                                        st.markdown(f"**{n2}**")
                                        st.markdown(f"<div style='background:#f0fff4;padding:10px;border-radius:5px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)

                except Exception as e: st.error(f"Erro: {e}")
