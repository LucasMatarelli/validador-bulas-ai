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

# ----------------- ESTILOS CSS (ORIGINAIS) -----------------
st.markdown("""
<style>
    /* OCULTA A BARRA SUPERIOR (TOOLBAR) */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }

    /* Ajuste de Fundo e Fontes */
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* ESTILO DO MENU DE NAVEGAÇÃO */
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

    /* Card Estilizado */
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
    
    /* Destaques */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Botões */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }

    /* Marcações de Texto */
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
    # 1. TENTA LER A CHAVE
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None, "Chave API não configurada!"

    genai.configure(api_key=api_key)
    
    # 2. CONFIGURAÇÃO DE SEGURANÇA (CRUCIAL PARA EVITAR COPYRIGHT)
    safety_config = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    # 3. TENTATIVA DE MODELOS (DO MAIS NOVO PARA O ANTIGO)
    modelos = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
    
    for m in modelos:
        try:
            model = genai.GenerativeModel(m, safety_settings=safety_config)
            return model, m
        except:
            continue
            
    # Fallback final
    return genai.GenerativeModel('gemini-pro', safety_settings=safety_config), "gemini-pro"

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
            
            # Tenta texto primeiro (Mais rápido e seguro)
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 50:
                 doc.close()
                 return {"type": "text", "data": full_text}

            # Fallback Imagem
            images = []
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro no arquivo: {e}")
        return None
    return None

def extract_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(text[start:end])
        return json.loads(text)
    except: return None

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    model_instance, model_name_used = get_gemini_model()
    
    if model_instance:
        st.success(f"✅ Conectado: {model_name_used}")
    else:
        st.error("❌ Erro de Conexão")
    
    st.divider()
    
    pagina = st.radio(
        "Navegação:",
        ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"]
    )
    st.divider()

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e; font-size: 3rem; margin-bottom: 10px;">Validador Inteligente</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Central de auditoria e conformidade de bulas farmacêuticas com IA.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""<div class="stCard"><div class="card-title">💊 Medicamento Ref x BELFAR</div><div class="card-text">Compara Bula Referência com Bula BELFAR.</div></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="stCard"><div class="card-title">📋 Conferência MKT</div><div class="card-text">Compara arquivo ANVISA com PDF MKT.</div></div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""<div class="stCard"><div class="card-title">🎨 Gráfica x Arte Vigente</div><div class="card-text">Compara PDF Gráfica com Arte Vigente.</div></div>""", unsafe_allow_html=True)

# ----------------- FERRAMENTA -----------------
else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    label_box1 = "Arquivo 1"
    label_box2 = "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Documento de Referência"
        label_box2 = "📄 Documento BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            if st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL
                nome_tipo = "Profissional"
    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 Arquivo ANVISA"
        label_box2 = "📄 Arquivo MKT"
    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"
        label_box2 = "📄 PDF da Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"##### {label_box1}")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2:
        st.markdown(f"##### {label_box2}")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not f1 or not f2:
            st.warning("⚠️ Faça o upload dos dois arquivos.")
        else:
            with st.spinner(f"🤖 Analisando com {model_name_used}..."):
                try:
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if not d1 or not d2:
                        st.error("Falha ao ler arquivos.")
                        st.stop()

                    payload = ["CONTEXTO: Auditoria Regulatória ANVISA. Documentos públicos."]
                    n1 = label_box1.replace("📄 ", "").upper()
                    n2 = label_box2.replace("📄 ", "").upper()

                    if d1['type'] == 'text': payload.append(f"--- {n1} ---\n{d1['data']}")
                    else: payload.append(f"--- {n1} ---"); payload.extend(d1['data'])
                    
                    if d2['type'] == 'text': payload.append(f"--- {n2} ---\n{d2['data']}")
                    else: payload.append(f"--- {n2} ---"); payload.extend(d2['data'])

                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                    
                    prompt = f"""
                    Atue como Auditor Farmacêutico (ANVISA).
                    DOC 1: {n1} | DOC 2: {n2}
                    SEÇÕES ({nome_tipo}):
                    {secoes_str}

                    === REGRA ZERO: LIMPEZA ABSOLUTA DE TEXTO ===
                    1. Copie APENAS O PARÁGRAFO DE TEXTO.
                    2. PROIBIDO TÍTULOS: NÃO inclua o título da seção.

                    === COMPARAÇÃO ===
                    - Divergências: <mark class='diff'>
                    - Ortografia: <mark class='ort'>
                    - Data (Dizeres Legais): <mark class='anvisa'>

                    SAÍDA JSON: {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE|FALTANTE" }} ] }}
                    """

                    response = model_instance.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    
                    if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                        st.error("⚠️ Alerta de Conteúdo Protegido. Tente enviar apenas texto.")
                    else:
                        data = extract_json(response.text)
                        if not data: st.error("Erro no JSON da IA.")
                        else:
                            meta = data.get("METADADOS", {})
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Score", f"{meta.get('score', 0)}%")
                            m2.metric("Seções", len(data.get("SECOES", [])))
                            m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                            st.divider()
                            
                            for sec in data.get("SECOES", []):
                                stt = sec.get('status', 'N/A')
                                icon = "✅"
                                if "DIVERGENTE" in stt: icon = "❌"
                                elif "FALTANTE" in stt: icon = "🚨"
                                if any(x in sec.get('titulo', '').upper() for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                                
                                with st.expander(f"{icon} {sec.get('titulo', 'SEÇÃO')} — {stt}"):
                                    ca, cb = st.columns(2)
                                    ca.markdown(f"**{n1}**"); ca.markdown(f"<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                    cb.markdown(f"**{n2}**"); cb.markdown(f"<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro durante a análise: {e}")
