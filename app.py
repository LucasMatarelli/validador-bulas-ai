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
    page_title="Validador de Bulas (Auto)",
    page_icon="💊",
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

def get_fallback_models():
    """Retorna lista de modelos funcionais em ordem de preferência."""
    # 1. Flash (Aguenta arquivos gigantes)
    # 2. Pro (Mais inteligente, mas mais lento)
    return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.5-flash-8b"]

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
            # Tenta extrair texto primeiro (mais rápido e preciso)
            for page in doc: full_text += page.get_text() + "\n"
            
            # Se tiver bastante texto, usa modo TEXTO (Melhor que imagem)
            if len(full_text.strip()) > 500:
                doc.close(); return {"type": "text", "data": full_text}
            
            # Se for PDF escaneado (imagem), converte
            images = []
            limit = min(10, len(doc)) # Aumentei o limite para 10 páginas
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0)) # 2.0 é suficiente e economiza memória
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
    # Tentativa de recuperação de JSON quebrado
    try:
        start = cleaned.find('{')
        end = cleaned.rfind('}') + 1
        if start != -1 and end != -1:
            return json.loads(cleaned[start:end], strict=False)
    except: pass
    return None

def normalize_sections(data_json, allowed_titles):
    """Normalização 'Fuzzy' para aceitar títulos mesmo com pequenas variações."""
    if not data_json or "SECOES" not in data_json: return data_json
    clean = []
    
    def normalize(t): return re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ]', '', t.upper())
    
    allowed_norm = {normalize(t): t for t in allowed_titles}
    
    for sec in data_json["SECOES"]:
        raw_title = sec.get("titulo", "")
        t_ia = normalize(raw_title)
        
        # Tenta match exato
        match = allowed_norm.get(t_ia)
        
        # Se falhar, tenta match parcial (similaridade > 80%)
        if not match:
            for k, v in allowed_norm.items():
                if k in t_ia or t_ia in k or SequenceMatcher(None, k, t_ia).ratio() > 0.8:
                    match = v
                    break
        
        if match:
            sec["titulo"] = match # Corrige o título para o oficial
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
        st.success("✅ IA Conectada")
    else:
        st.error("❌ Sem Chave API")

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
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if f1 and f2 and is_connected:
            with st.spinner("Lendo arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                # ESTRATÉGIA ARQUIVO ÚNICO (Para evitar cortes de chunks)
                models_to_try = get_fallback_models()
                
                payload = ["CONTEXTO: Auditoria Farmacêutica. Compare Referência vs Candidato."]
                if d1['type'] == 'text': payload.append(f"--- DOC REFERÊNCIA (TEXTO) ---\n{d1['data']}")
                else: payload.extend(["--- DOC REFERÊNCIA (IMAGENS) ---"] + d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- DOC CANDIDATO (TEXTO) ---\n{d2['data']}")
                else: payload.extend(["--- DOC CANDIDATO (IMAGENS) ---"] + d2['data'])

                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                prompt = f"""
                Você é um Auditor de Qualidade (OCR Rigoroso).
                
                TAREFA:
                1. Encontre e extraia TODAS as seções presentes nos documentos que correspondam à lista abaixo.
                2. Compare o texto da REFERÊNCIA com o CANDIDATO.
                
                LISTA DE SEÇÕES (Procure por todas):
                {secoes_str}
                
                REGRAS:
                - Extraia o texto EXATAMENTE como está (IPSIS LITTERIS).
                - Diferenças no Candidato: Envolva com <mark class='diff'>TEXTO AQUI</mark>.
                - Erros ortográficos: Envolva com <mark class='ort'>ERRO AQUI</mark>.
                - Se não encontrar uma seção, NÃO a inclua no JSON.
                
                SAÍDA JSON:
                {{
                    "METADADOS": {{ "datas": [] }},
                    "SECOES": [
                        {{ "titulo": "TITULO", "ref": "Texto Ref", "bel": "Texto Cand...", "status": "OK" ou "DIVERGENTE" }}
                    ]
                }}
                """
                
                st.toast("Iniciando análise completa...", icon="🔍")
                
                success = False
                final_data = None
                used_model = ""
                
                # Loop de Modelos
                for model_name in models_to_try:
                    try:
                        # st.write(f"Tentando: {model_name}") # Debug
                        model = genai.GenerativeModel(model_name)
                        response = model.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json", "max_output_tokens": 8192}, # Maximo tokens
                            safety_settings=SAFETY_SETTINGS,
                            request_options={"timeout": 600}
                        )
                        data = extract_json(response.text)
                        
                        if data and "SECOES" in data and len(data["SECOES"]) > 0:
                            final_data = normalize_sections(data, lista_secoes)
                            success = True
                            used_model = model_name
                            break # Achou dados, para de tentar
                            
                    except Exception as e:
                        if "429" in str(e):
                            time.sleep(5) # Espera cota
                            continue
                        continue # Tenta próximo modelo se der erro 404 ou outro
                
                if success and final_data:
                    st.success(f"Análise concluída com sucesso via {used_model}")
                    st.divider()
                    
                    secs = final_data.get("SECOES", [])
                    cM1, cM2, cM3 = st.columns(3)
                    
                    divs = sum(1 for s in secs if "DIVERGENTE" in s.get('status', 'OK'))
                    score = 100 - int((divs/max(1, len(secs)))*100) if len(secs) > 0 else 0
                    
                    cM1.metric("Score", f"{score}%")
                    cM2.metric("Seções Encontradas", f"{len(secs)}/{len(lista_secoes)}")
                    datas = final_data.get("METADADOS", {}).get("datas", [])
                    cM3.metric("Data Anvisa", datas[0] if datas else "N/A")
                    
                    st.markdown("---")
                    
                    for sec in secs:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status: icon = "❌"
                        
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    st.error("Não foi possível extrair dados válidos.")
                    st.info("Dica: Se o PDF for escaneado (imagem), verifique a qualidade. Se for texto, verifique se os títulos das seções correspondem à norma.")
