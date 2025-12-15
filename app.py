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
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    
    /* MARCADORES DE TEXTO */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; text-decoration: none; }
    mark.ort { background-color: #ffc9c9; color: #9c0000; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; font-weight: bold; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }

    /* MENU LATERAL */
    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #eee; }
    section[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] { gap: 10px; }
    section[data-testid="stSidebar"] .stRadio label {
        background-color: #f8f9fa !important; padding: 15px 20px !important;
        border-radius: 10px !important; border: 1px solid #e9ecef !important;
        cursor: pointer; margin: 0 !important; color: #495057 !important;
        transition: all 0.2s ease; display: flex; align-items: center;
    }
    section[data-testid="stSidebar"] .stRadio label:hover {
        background-color: #e8f5e9 !important; border-color: #55a68e !important; color: #55a68e !important;
    }
    section[data-testid="stSidebar"] .stRadio div[aria-checked="true"] label {
        background-color: #55a68e !important; color: white !important;
        border-color: #448c75 !important; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.3);
    }
    section[data-testid="stSidebar"] .stRadio label p {
        color: inherit !important; font-weight: 600 !important; font-size: 16px !important;
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

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DE BACKEND -----------------

def configure_gemini():
    """Conecta e verifica API."""
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

def get_smart_model_list():
    """Gera lista de prioridade baseada no que existe na conta."""
    try:
        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Ordem de preferência: 
        # 1. Gemini 1.5 Pro (Melhor raciocínio)
        # 2. Gemini 1.5 Flash (Melhor velocidade/cota)
        # 3. Gemini Pro (Fallback)
        priority_queue = []
        
        # Procura versões específicas
        pro_15 = next((m for m in available if 'gemini-1.5-pro' in m and 'latest' in m), None)
        if not pro_15: pro_15 = next((m for m in available if 'gemini-1.5-pro' in m), None)
        
        flash_15 = next((m for m in available if 'gemini-1.5-flash' in m and 'latest' in m), None)
        if not flash_15: flash_15 = next((m for m in available if 'gemini-1.5-flash' in m), None)
        
        if pro_15: priority_queue.append(pro_15)
        if flash_15: priority_queue.append(flash_15)
        
        # Se não achou os principais, tenta qualquer 'gemini'
        if not priority_queue:
            priority_queue = [m for m in available if 'gemini' in m]
            
        return priority_queue
    except:
        # Lista de segurança absoluta se a API de listagem falhar
        return ["models/gemini-1.5-flash", "models/gemini-1.5-pro"]

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        keywords_curva = ["curva", "traço", "outline", "convertido", "vetor"]
        is_curva = any(k in filename for k in keywords_curva)
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            if not is_curva:
                for page in doc: full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 100 and not is_curva:
                doc.close(); return {"type": "text", "data": full_text}
            
            images = []
            limit = min(8, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
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
            last_comma = cleaned.rfind("},")
            if last_comma != -1: return json.loads(cleaned[:last_comma+1] + "]}", strict=False)
    except: pass
    return None

def normalize_sections(data_json, allowed_titles):
    if not data_json or "SECOES" not in data_json: return data_json
    clean = []
    def clean_title(t): return re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ ]', '', t.upper().strip())
    allowed_set = {clean_title(t) for t in allowed_titles}
    
    for sec in data_json["SECOES"]:
        t_ia = clean_title(sec.get("titulo", ""))
        match = next((t for t in allowed_set if t_ia == t or (len(t_ia) > 5 and t_ia in t)), None)
        if match:
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
        st.markdown(f"<div style='text-align:center;padding:10px;background:#e8f5e9;border-radius:8px;color:#2e7d32;font-size:0.8em'>✅ IA Conectada (Auto)</div>", unsafe_allow_html=True)
        st.caption("Modo Piloto Automático ativado.")
    else:
        st.error("❌ Verifique a Chave API")

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
        
    if st.button("🚀 INICIAR AUDITORIA (AUTO)"):
        if f1 and f2 and is_connected:
            with st.spinner("Lendo arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                # 1. OBTÉM LISTA DE MODELOS REAIS E ORDENADOS
                model_queue = get_smart_model_list()
                
                final_sections = []
                final_dates = []
                success = False
                used_model = ""

                payload = ["CONTEXTO: Auditoria de Texto Farmacêutico (OCR e Comparação)."]
                if d1['type'] == 'text': payload.append(f"--- TEXTO ORIGINAL (REFERÊNCIA) ---\n{d1['data']}")
                else: payload.extend(["--- IMAGEM ORIGINAL (REFERÊNCIA) ---"] + d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- TEXTO CANDIDATO (BELFAR) ---\n{d2['data']}")
                else: payload.extend(["--- IMAGEM CANDIDATO (BELFAR) ---"] + d2['data'])

                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                # PROMPT
                prompt = f"""
                ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO DE TEXTO.
                
                SUA MISSÃO:
                1. Ler o texto da IMAGEM ORIGINAL e da IMAGEM CANDIDATO.
                2. Extrair o texto EXATAMENTE como está escrito (IPSIS LITTERIS).
                3. NÃO corrija erros de português. NÃO complete frases. NÃO invente palavras.
                
                TAREFA DE COMPARAÇÃO:
                Compare o texto extraído das seções abaixo.
                Se houver QUALQUER diferença (letra, palavra, número):
                - Envolva a diferença no texto do Candidato com <mark class='diff'>TEXTO ERRADO</mark>.
                - Se parecer erro ortográfico, envolva com <mark class='ort'>ERRO</mark>.
                
                SEÇÕES ALVO:
                {secoes_str}
                
                SAÍDA JSON ESTRITA:
                {{
                    "METADADOS": {{ "datas": ["dd/mm/aaaa"] }},
                    "SECOES": [
                        {{ 
                           "titulo": "TITULO EXATO", 
                           "ref": "Texto copiado fielmente da Referência...", 
                           "bel": "Texto copiado fielmente do Candidato com <mark>...", 
                           "status": "OK" ou "DIVERGENTE" 
                        }}
                    ]
                }}
                """
                
                st.toast("Iniciando auditoria automática...", icon="🤖")
                
                # 2. TENTA A LISTA DE MODELOS EM ORDEM
                for model_name in model_queue:
                    try:
                        # st.caption(f"Tentando motor: {model_name}...") # Debug visual opcional
                        model_instance = genai.GenerativeModel(model_name)
                        
                        response = model_instance.generate_content(
                            [prompt] + payload,
                            generation_config={
                                "response_mime_type": "application/json", 
                                "max_output_tokens": 8192,
                                "temperature": 0.0
                            },
                            safety_settings=SAFETY_SETTINGS,
                            request_options={"timeout": 600}
                        )
                        full_data = extract_json(response.text)
                        
                        if full_data:
                            norm = normalize_sections(full_data, lista_secoes)
                            final_sections = norm.get("SECOES", [])
                            final_dates = full_data.get("METADADOS", {}).get("datas", [])
                            success = True
                            used_model = model_name
                            break # SUCESSO! Sai do loop.
                            
                    except Exception as e:
                        error_msg = str(e)
                        # Se for 429 (Cota), continua tentando o próximo da lista
                        if "429" in error_msg:
                            continue 
                        # Se for 404 (Não existe na região), continua
                        if "404" in error_msg:
                            continue
                
                if success:
                    st.toast(f"Sucesso! Processado por {used_model}", icon="✅")
                    st.divider()
                    cM1, cM2, cM3 = st.columns(3)
                    divs = sum(1 for s in final_sections if "DIVERGENTE" in s['status'])
                    total = len(final_sections)
                    score = 100 - int((divs/max(1, total))*100) if total > 0 else 0
                    
                    cM1.metric("Score Aprovação", f"{score}%")
                    cM2.metric("Seções", f"{total}/{len(lista_secoes)}")
                    data_anvisa = next((d for d in final_dates if d), "N/A")
                    cM3.metric("Data Anvisa", str(data_anvisa))
                    
                    st.markdown("---")
                    
                    if not final_sections:
                        st.warning("O documento foi processado, mas nenhuma seção foi encontrada.")
                    
                    for sec in final_sections:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status: icon = "❌"
                        elif "FALTANTE" in status: icon = "🚨"
                        
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência (Original)**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;font-family:monospace;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato (Auditado)**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;font-family:monospace;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                     st.error("Não foi possível processar com nenhum modelo de IA disponível no momento.")
                     st.info("Pode ser um bloqueio temporário de cota (Erro 429). Aguarde 1 minuto e tente novamente.")
