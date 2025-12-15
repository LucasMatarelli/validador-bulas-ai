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
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

def get_best_available_model():
    """
    Busca automaticamente o modelo mais potente disponível na conta.
    Prioridade: Experimental (Gemini 2.5/3 fake) > Pro > Flash
    """
    try:
        # Lista modelos que suportam geração
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 1. Tenta achar o Experimental (Muitas vezes é o Gemini 1.5 Pro Experimental ou Gemini 2.0 preview)
        exp_model = next((m for m in models if "exp" in m), None)
        if exp_model: return exp_model, "Gemini Experimental (Mais Potente)"
        
        # 2. Tenta o Pro 1.5 (Mais inteligente que o Flash)
        pro_model = next((m for m in models if "gemini-1.5-pro" in m), None)
        if pro_model: return pro_model, "Gemini 1.5 Pro"
        
        # 3. Tenta o Flash 1.5 (Mais rápido/estável)
        flash_model = next((m for m in models if "gemini-1.5-flash" in m), None)
        if flash_model: return flash_model, "Gemini 1.5 Flash"
        
        # 4. Fallback
        return "models/gemini-1.5-flash", "Gemini Padrão"
    except:
        return "models/gemini-1.5-flash", "Gemini Backup"

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
    model_name_real, model_display = "Indefinido", "Aguardando"
    
    if is_connected:
        model_name_real, model_display = get_best_available_model()
        st.markdown(f"<div style='text-align:center;padding:10px;background:#e8f5e9;border-radius:8px;color:#2e7d32;font-size:0.8em'>✅ IA Ativa: {model_display}</div>", unsafe_allow_html=True)
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
        
    if st.button("🚀 INICIAR AUDITORIA AUTOMÁTICA"):
        if f1 and f2 and is_connected:
            with st.spinner(f"Preparando análise com {model_display}..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                model_instance = genai.GenerativeModel(model_name_real)
                
                final_sections = []
                final_dates = []
                
                # --- ESTRATÉGIA DE 2 LOTES (Meio termo entre Cota e Completude) ---
                # Divide as seções em 2 metades. 
                # Metade 1 = Seções 0 a 6 (Geralmente até 'Como usar')
                # Metade 2 = Seções 7 até o fim (Inclui Dizeres Legais que costumava cortar)
                mid_point = len(lista_secoes) // 2
                chunks = [lista_secoes[:mid_point], lista_secoes[mid_point:]]
                
                payload_base = ["CONTEXTO: Auditoria de Texto Farmacêutico (OCR Rigoroso)."]
                if d1['type'] == 'text': payload_base.append(f"--- REF TEXTO ---\n{d1['data']}")
                else: payload_base.extend(["--- REF IMAGENS ---"] + d1['data'])
                
                if d2['type'] == 'text': payload_base.append(f"--- CAND TEXTO ---\n{d2['data']}")
                else: payload_base.extend(["--- CAND IMAGENS ---"] + d2['data'])

                bar = st.progress(0)
                
                for i, chunk in enumerate(chunks):
                    # Pausa de segurança para evitar 429 na segunda parte
                    if i > 0: 
                        with st.spinner("Pausa de segurança da API (5s)..."):
                            time.sleep(5)
                    
                    st.toast(f"Analisando parte {i+1}/2...", icon="🔍")
                    secoes_str = "\n".join([f"- {s}" for s in chunk])
                    
                    prompt = f"""
                    ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO DE TEXTO.
                    
                    MISSÃO: Ler as imagens/texto e extrair o conteúdo das SEÇÕES ALVO abaixo.
                    
                    SEÇÕES ALVO DESTA ETAPA (Extraia APENAS estas):
                    {secoes_str}
                    
                    REGRAS RIGOROSAS:
                    1. Extraia o texto EXATAMENTE como está (IPSIS LITTERIS). Não corrija nada.
                    2. Compare Referência vs Candidato.
                    3. Se houver diferença no Candidato, envolva com <mark class='diff'>TEXTO DIFERENTE</mark>.
                    4. Se houver erro ortográfico no Candidato, envolva com <mark class='ort'>ERRO</mark>.
                    5. Se encontrar DATA DA ANVISA (geralmente no fim), extraia.
                    
                    SAÍDA JSON:
                    {{
                        "METADADOS": {{ "datas": [] }},
                        "SECOES": [
                            {{ "titulo": "TITULO", "ref": "Texto Ref", "bel": "Texto Cand com marks", "status": "OK" ou "DIVERGENTE" }}
                        ]
                    }}
                    """
                    
                    # Tentativa com retry
                    for attempt in range(3):
                        try:
                            response = model_instance.generate_content(
                                [prompt] + payload_base,
                                generation_config={"response_mime_type": "application/json", "max_output_tokens": 8192, "temperature": 0.0},
                                safety_settings=SAFETY_SETTINGS
                            )
                            part_data = extract_json(response.text)
                            if part_data:
                                norm = normalize_sections(part_data, chunk)
                                final_sections.extend(norm.get("SECOES", []))
                                if part_data.get("METADADOS", {}).get("datas"):
                                    final_dates.extend(part_data["METADADOS"]["datas"])
                                break # Sucesso
                        except Exception as e:
                            if "429" in str(e) and attempt < 2:
                                time.sleep(15) # Espera maior se der cota
                                continue
                            elif "404" in str(e):
                                st.error("Erro fatal: Modelo não encontrado. API pode ter mudado.")
                                break
                            else:
                                break
                    
                    bar.progress((i+1)/2)
                
                bar.empty()
                
                if final_sections:
                    st.divider()
                    cM1, cM2, cM3 = st.columns(3)
                    divs = sum(1 for s in final_sections if "DIVERGENTE" in s['status'])
                    total = len(final_sections)
                    score = 100 - int((divs/max(1, total))*100) if total > 0 else 0
                    
                    cM1.metric("Score Aprovação", f"{score}%")
                    cM2.metric("Seções", f"{total}/{len(lista_secoes)}")
                    data_anvisa = next((d for d in final_dates if d), "Não encontrada")
                    cM3.metric("Data Anvisa", str(data_anvisa))
                    
                    st.markdown("---")
                    
                    for sec in final_sections:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status: icon = "❌"
                        elif "FALTANTE" in status: icon = "🚨"
                        
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;font-family:monospace;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;font-family:monospace;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                     st.error("Não foi possível extrair nenhuma seção. O arquivo pode estar ilegível para a IA.")
