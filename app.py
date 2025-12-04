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

# ----------------- CHAVE API (FIXA) -----------------
# Inserida diretamente para facilitar o uso imediato
API_KEY_FIXA = "GEMINI_API_KEY"

# ----------------- ESTILOS CSS PERSONALIZADOS -----------------
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

    /* Box de Curva */
    .curve-box { background-color: #f8f9fa; border-left: 4px solid #55a68e; padding: 10px 15px; margin-top: 15px; font-size: 0.9rem; color: #666; }

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
    if not API_KEY_FIXA: return None, "Sem Chave"

    genai.configure(api_key=API_KEY_FIXA)
    
    # LISTA DE MODELOS (Priorizando Pro para evitar Copyright)
    modelos_para_testar = [
        'models/gemini-1.5-pro',         # Mais robusto contra Copyright
        'models/gemini-2.5-flash', 
        'models/gemini-2.0-flash-exp', 
        'models/gemini-1.5-flash'
    ]
    
    for model_name in modelos_para_testar:
        try:
            model = genai.GenerativeModel(model_name)
            return model, model_name
        except Exception:
            continue
    return genai.GenerativeModel('models/gemini-1.5-flash'), "models/gemini-1.5-flash (Fallback)"

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
            
            # --- CONFIGURAÇÃO: 12 PÁGINAS ---
            limit_pages = min(12, len(doc))
            
            for i in range(limit_pages):
                page = doc[i]
                # --- ZOOM 2.0 (Mantido do seu código) ---
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                
                # --- CORREÇÃO DE COMPATIBILIDADE (JPG vs PNG) ---
                try:
                    # Tenta usar jpg_quality (versões novas) ou quality (antigas)
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except Exception:
                    # Se falhar qualquer parâmetro de qualidade, usa PNG (infalível)
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                    
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
        if start != -1 and end != -1: return json.loads(clean[start:end])
        return json.loads(clean)
    except: return None

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    # Inicializa modelo
    model_instance, model_name_used = get_gemini_model()
    
    if model_instance:
        st.success(f"✅ Conectado: {model_name_used.replace('models/', '')}")
    else:
        st.error("❌ Erro de Conexão")
    
    st.divider()
    
    # Menu de Navegação
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
