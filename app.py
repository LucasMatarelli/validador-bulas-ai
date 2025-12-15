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
    
    /* CARTÕES PRINCIPAIS */
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); border-color: #55a68e; }
    
    /* MARCADORES DE TEXTO (Destaques) */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; text-decoration: none; }
    mark.ort { background-color: #ffc9c9; color: #9c0000; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; font-weight: bold; }
    
    /* BOTÃO */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }

    /* --- MENU LATERAL OTIMIZADO --- */
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
    """Apenas configura a API Key."""
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

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
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close(); gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro: {e}")
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
    
    api_configured = configure_gemini()
    if api_configured:
        st.markdown(f"<div style='text-align:center;padding:10px;background:#e8f5e9;border-radius:8px;color:#2e7d32;font-size:0.8em'>✅ API Conectada</div>", unsafe_allow_html=True)
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
        
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if f1 and f2 and api_configured:
            # FIXAMOS O MODELO 1.5 FLASH (Melhor Cota e Contexto Gigante)
            model_name = "models/gemini-1.5-flash" 
            
            with st.spinner("Lendo documentos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                # Instância do modelo com retry nativo do python client se disponível, senão manual
                model_instance = genai.GenerativeModel(model_name)
                
                # MODO ÚNICO: Enviamos TUDO de uma vez.
                # O Gemini 1.5 Flash suporta 1 milhão de tokens, bulas têm ~50k.
                # Isso evita o erro de múltiplas requisições (429).
                
                final_sections = []
                final_dates = []
                
                payload = ["CONTEXTO: Auditoria de Bulas Farmacêuticas (Completa)."]
                if d1['type'] == 'text': payload.append(f"--- DOC REFERÊNCIA ---\n{d1['data']}")
                else: payload.extend(["--- DOC REFERÊNCIA (IMAGENS) ---"] + d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- DOC CANDIDATO ---\n{d2['data']}")
                else: payload.extend(["--- DOC CANDIDATO (IMAGENS) ---"] + d2['data'])

                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                prompt = f"""
                Você é um Auditor Farmacêutico Sênior. Sua tarefa é AUDITAR a bula completa de uma única vez.
                
                SEÇÕES PARA ANÁLISE (Extraia e Compare TODAS):
                {secoes_str}
                
                REGRAS OBRIGATÓRIAS:
                1. Extraia o texto do Doc Referência e compare com o Doc Candidato.
                2. Use tags HTML no texto do 'bel' (Candidato) para apontar erros:
                   - Palavras diferentes/extras/faltantes: <mark class='diff'>TEXTO AQUI</mark>
                   - Erros de ortografia/gramática: <mark class='ort'>ERRO AQUI</mark>
                3. Procure a Data de Aprovação da Anvisa (rodapé ou cabeçalho) e extraia no campo 'datas'.
                
                SAÍDA JSON (Mantenha a estrutura estrita):
                {{
                    "METADADOS": {{ "datas": ["dd/mm/aaaa"] }},
                    "SECOES": [
                        {{ "titulo": "NOME DA SEÇÃO", "ref": "Texto completo...", "bel": "Texto com <mark>...", "status": "OK" ou "DIVERGENTE" }}
                    ]
                }}
                """
                
                st.toast("Enviando para análise (pode levar uns segundos)...", icon="🚀")
                
                # --- TENTATIVA ÚNICA COM RETRY PARA O BLOCO GRANDE ---
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    try:
                        # Timeout maior para processar texto grande
                        response = model_instance.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json", "max_output_tokens": 8192},
                            safety_settings=SAFETY_SETTINGS,
                            request_options={"timeout": 600} 
                        )
                        full_data = extract_json(response.text)
                        
                        if full_data:
                            # Normaliza e exibe
                            norm = normalize_sections(full_data, lista_secoes)
                            final_sections = norm.get("SECOES", [])
                            final_dates = full_data.get("METADADOS", {}).get("datas", [])
                            success = True
                            break
                    except Exception as e:
                        if "429" in str(e) or "quota" in str(e).lower():
                            st.toast(f"Servidor ocupado. Tentando novamente em 30s... ({attempt+1}/{max_retries})", icon="⏳")
                            time.sleep(30)
                            continue
                        else:
                            st.error(f"Erro na análise: {str(e)}")
                            break
                
                if success:
                    st.divider()
                    
                    # --- EXIBIÇÃO FINAL ---
                    cM1, cM2, cM3 = st.columns(3)
                    divs = sum(1 for s in final_sections if "DIVERGENTE" in s['status'])
                    total = len(final_sections)
                    score = 100 - int((divs/max(1, total))*100) if total > 0 else 0
                    
                    cM1.metric("Score Aprovação", f"{score}%")
                    cM2.metric("Seções Analisadas", f"{total}/{len(lista_secoes)}")
                    data_anvisa = next((d for d in final_dates if d), "Não identificada")
                    cM3.metric("Data Anvisa", str(data_anvisa))
                    
                    st.markdown("---")
                    
                    if not final_sections:
                        st.warning("A IA processou o documento mas não retornou seções no formato esperado. Verifique a qualidade do PDF.")
                    
                    for sec in final_sections:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status: icon = "❌"
                        elif "FALTANTE" in status: icon = "🚨"
                        
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato (Auditoria)**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    if not final_sections:
                        st.error("Falha ao processar o documento após 3 tentativas.")
