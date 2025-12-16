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
import time
from PIL import Image
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas (Lite & NextGen)",
    page_icon="🚀",
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
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; 
    }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; text-decoration: none; }
    mark.ort { background-color: #ffc9c9; color: #9c0000; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; font-weight: bold; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }

    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #eee; }
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

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DE BACKEND -----------------

def configure_gemini():
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

def get_strict_model_queue():
    """
    Retorna APENAS os modelos solicitados (2.5+ e Lite).
    Mapeia nomes técnicos para nomes amigáveis.
    """
    return [
        # Tentativas Futuras (Se sua API tiver acesso)
        {"id": "gemini-3.0-pro", "name": "Gemini 3.0 (NextGen)"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 (NextGen)"},
        
        # O "Lite" oficial (Flash 8B - Rápido e Eficiente)
        {"id": "gemini-1.5-flash-8b", "name": "Gemini Lite (8B)"}
    ]

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
            
            if len(full_text.strip()) > 800:
                doc.close(); return {"type": "text", "data": full_text}
            
            images = []
            limit = min(12, len(doc)) 
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close(); gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro no arquivo: {e}")
        return None
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    return re.sub(r'//.*', '', text)

def extract_json(text):
    cleaned = clean_json_response(text)
    try: return json.loads(cleaned, strict=False)
    except: pass
    
    try:
        if '"SECOES":' in cleaned:
            last_bracket = cleaned.rfind("}")
            if last_bracket != -1:
                fixed = cleaned[:last_bracket+1]
                if not fixed.strip().endswith("]}"): 
                    if fixed.strip().endswith("]"): fixed += "}"
                    else: fixed += "]}"
                return json.loads(fixed, strict=False)
    except: pass
    return None

def normalize_sections(data_json, allowed_titles):
    if not data_json or "SECOES" not in data_json: return data_json
    clean = []
    
    def normalize(t): return re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ]', '', t.upper())
    allowed_norm = {normalize(t): t for t in allowed_titles}
    
    for sec in data_json["SECOES"]:
        raw_title = sec.get("titulo", "")
        t_ia = normalize(raw_title)
        
        match = allowed_norm.get(t_ia)
        if not match:
            for k, v in allowed_norm.items():
                if k in t_ia or t_ia in k or SequenceMatcher(None, k, t_ia).ratio() > 0.8:
                    match = v; break
        
        if match:
            sec["titulo"] = match
            clean.append(sec)
            
    data_json["SECOES"] = clean
    return data_json

# ----------------- UI LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.markdown("<h2 style='text-align: center; color: #55a68e;'>Validador de Bulas</h2>", unsafe_allow_html=True)
    
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"], label_visibility="collapsed")
    st.divider()
    
    is_connected = configure_gemini()
    if is_connected:
        st.success("✅ API Conectada")
    else:
        st.error("❌ Verifique API Key")

# ----------------- LÓGICA PRINCIPAL -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='color:#55a68e;text-align:center;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("💊 Ref x BELFAR"); c2.info("📋 Conf. MKT"); c3.info("🎨 Gráfica")

else:
    st.markdown(f"## {pagina}")
    lista_secoes = SECOES_PACIENTE
    if pagina == "💊 Ref x BELFAR":
        if st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Referência", type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader("Candidato", type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA (LITE & 2.5+)"):
        if f1 and f2 and is_connected:
            with st.spinner("Carregando arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                model_queue = get_strict_model_queue()
                
                payload = ["CONTEXTO: Auditoria Farmacêutica Rigorosa (OCR)."]
                if d1['type'] == 'text': payload.append(f"--- REF TEXTO ---\n{d1['data']}")
                else: payload.extend(["--- REF IMAGENS ---"] + d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- CAND TEXTO ---\n{d2['data']}")
                else: payload.extend(["--- CAND IMAGENS ---"] + d2['data'])

                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                prompt = f"""
                Você é um Auditor de Qualidade Farmacêutica.
                
                OBJETIVO: Extrair e comparar as seções da bula.
                
                SEÇÕES OBRIGATÓRIAS (Extraia o conteúdo de TODAS que encontrar):
                {secoes_str}
                
                REGRAS:
                1. Extraia o texto EXATAMENTE como está na imagem (IPSIS LITTERIS).
                2. Compare o texto da Referência com o Candidato.
                3. No Candidato: envolva diferenças com <mark class='diff'>TEXTO DIFERENTE</mark>.
                4. No Candidato: envolva erros ortográficos com <mark class='ort'>ERRO</mark>.
                5. Extraia a Data de Aprovação da Anvisa se houver.
                
                SAÍDA JSON ESTRITA:
                {{
                    "METADADOS": {{ "datas": [] }},
                    "SECOES": [
                        {{ "titulo": "TITULO DA SEÇÃO", "ref": "Texto original...", "bel": "Texto candidato...", "status": "OK" or "DIVERGENTE" }}
                    ]
                }}
                """
                
                success = False
                final_data = None
                used_model_display = ""
                
                progress_bar = st.progress(0)
                
                # LOOP DE ROTAÇÃO ESTRITA
                for idx, model_info in enumerate(model_queue):
                    try:
                        # st.toast(f"Testando: {model_info['name']}...", icon="🤖") # Opcional: Debug
                        
                        model = genai.GenerativeModel(model_info['id'])
                        
                        # Timeout alto para arquivos grandes
                        response = model.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json", "max_output_tokens": 8192, "temperature": 0.0},
                            safety_settings=SAFETY_SETTINGS,
                            request_options={"timeout": 600}
                        )
                        
                        data = extract_json(response.text)
                        
                        if data and "SECOES" in data and len(data["SECOES"]) > 0:
                            final_data = normalize_sections(data, lista_secoes)
                            used_model_display = model_info['name']
                            success = True
                            break 
                            
                    except Exception as e:
                        # Silencia erros de modelos inexistentes (404) ou cota (429) e tenta o próximo
                        continue
                    
                    progress_bar.progress((idx + 1) / len(model_queue))
                
                progress_bar.empty()
                
                if success and final_data:
                    st.success(f"✅ Processado com sucesso via: {used_model_display}")
                    st.divider()
                    
                    secs = final_data.get("SECOES", [])
                    cM1, cM2, cM3 = st.columns(3)
                    
                    divs = sum(1 for s in secs if "DIVERGENTE" in s.get('status', 'OK'))
                    score = 100 - int((divs/max(1, len(secs)))*100) if len(secs) > 0 else 0
                    
                    cM1.metric("Score", f"{score}%")
                    cM2.metric("Seções", f"{len(secs)}/{len(lista_secoes)}")
                    datas = final_data.get("METADADOS", {}).get("datas", [])
                    cM3.metric("Data Anvisa", datas[0] if datas else "N/A")
                    
                    st.markdown("---")
                    
                    for sec in secs:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status: icon = "❌"
                        elif "FALTANTE" in status: icon = "🚨"
                        
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    st.error("Não foi possível processar. O Gemini Lite (8B) pode estar ocupado.")
                    st.info("Aguarde alguns segundos e tente novamente.")
