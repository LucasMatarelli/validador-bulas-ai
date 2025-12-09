import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF (Isso funciona pois instalamos o PyMuPDF)
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

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .stCard { background-color: white; padding: 25px; border-radius: 15px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----------------- FUNÇÃO DE CONEXÃO BLINDADA (A SOLUÇÃO) -----------------
def get_gemini_model():
    # 1. Pega a chave
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None, "Chave Ausente"

    genai.configure(api_key=api_key)

    # 2. Configuração de Segurança (Evita Copyright)
    safety_config = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # 3. Lógica de Tentativa e Erro (Fallback)
    # Tenta o modelo novo (Flash). Se der 404, cai para o modelo antigo (Pro) automaticamente.
    
    lista_tentativas = [
        'gemini-1.5-flash', # O ideal (Rápido e Barato)
        'gemini-pro'        # O "Velho de Guerra" (Funciona em libs antigas)
    ]

    model_final = None
    nome_final = ""

    # Teste de conexão silencioso
    for modelo in lista_tentativas:
        try:
            teste_model = genai.GenerativeModel(modelo, safety_settings=safety_config)
            # Tenta gerar um "oi" simples para ver se o modelo responde ou dá erro 404
            # Se a lib for velha, isso vai dar erro aqui e pular para o próximo
            teste_model.generate_content("oi") 
            
            # Se chegou aqui, funcionou!
            model_final = teste_model
            nome_final = modelo
            break
        except Exception:
            continue # Se deu erro, tenta o próximo da lista

    if model_final:
        return model_final, nome_final
    else:
        # Se tudo falhar, retorna o genérico
        return genai.GenerativeModel('gemini-pro', safety_settings=safety_config), "gemini-pro (Fallback)"

# ----------------- FUNÇÕES AUXILIARES -----------------
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
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            if len(full_text.strip()) > 50:
                 doc.close(); return {"type": "text", "data": full_text}
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
    except Exception as e: st.error(f"Erro arquivo: {e}"); return None
    return None

def extract_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        start = text.find('{'); end = text.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(text[start:end])
        return json.loads(text)
    except: return None

# ----------------- INTERFACE -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    # Mostra a versão da lib para debug
    st.caption(f"Versão IA: {genai.__version__}") 
    
    model_instance, model_name_used = get_gemini_model()
    if model_instance: st.success(f"✅ Conectado: {model_name_used}")
    else: st.error("❌ Erro Conexão")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 MKT", "🎨 Gráfica"])

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.info("💊 Ref x BELFAR")
    with c2: st.info("📋 MKT")
    with c3: st.info("🎨 Gráfica")

else:
    st.markdown(f"## {pagina}")
    label_box1 = "Arquivo 1"; label_box2 = "Arquivo 2"
    if pagina == "💊 Ref x BELFAR": label_box1 = "Ref"; label_box2 = "BELFAR"
    elif pagina == "📋 MKT": label_box1 = "ANVISA"; label_box2 = "MKT"
    elif pagina == "🎨 Gráfica": label_box1 = "Arte"; label_box2 = "Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
    
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2: st.warning("Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"Analisando com {model_name_used}..."):
                d1 = process_uploaded_file(f1); d2 = process_uploaded_file(f2)
                gc.collect()
                if not d1 or not d2: st.error("Erro leitura."); st.stop()

                payload = ["CONTEXTO: Auditoria Regulatória ANVISA. Documentos públicos."]
                n1 = label_box1.upper(); n2 = label_box2.upper()
                if d1['type']=='text': payload.append(f"--- {n1} ---\n{d1['data']}")
                else: payload.append(f"--- {n1} ---"); payload.extend(d1['data'])
                if d2['type']=='text': payload.append(f"--- {n2} ---\n{d2['data']}")
                else: payload.append(f"--- {n2} ---"); payload.extend(d2['data'])

                prompt = f"""
                Atue como Auditor Farmacêutico (ANVISA).
                DOC 1: {n1} | DOC 2: {n2}
                SEÇÕES: APRESENTAÇÕES, COMPOSIÇÃO, INDICAÇÕES, POSOLOGIA, DIVERGENCIAS
                
                REGRA: Compare os textos.
                - Use <mark class='diff'> para divergências.
                - Use <mark class='ort'> para erros ortográficos.
                - Se encontrar "Aprovado em dd/mm/aaaa", use <mark class='anvisa'>.

                JSON: {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE|FALTANTE" }} ] }}
                """

                try:
                    response = model_instance.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    data = extract_json(response.text)
                    if not data: st.error("Erro JSON IA.")
                    else:
                        meta = data.get("METADADOS", {})
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Score", f"{meta.get('score', 0)}%")
                        m2.metric("Seções", len(data.get("SECOES", [])))
                        m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                        st.divider()
                        for sec in data.get("SECOES", []):
                            icon = "✅" if "CONFORME" in sec.get('status','') else "❌"
                            with st.expander(f"{icon} {sec.get('titulo')} — {sec.get('status')}"):
                                ca, cb = st.columns(2)
                                ca.markdown(f"**{n1}**"); ca.markdown(f"<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                cb.markdown(f"**{n2}**"); cb.markdown(f"<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                except Exception as e: st.error(f"Erro: {e}")
