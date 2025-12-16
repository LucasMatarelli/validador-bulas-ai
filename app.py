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
    page_title="Validador de Bulas",
    page_icon="🛡️",
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

# --- BLOQUEIO ZERO (IMPORTANTE PARA NÃO TRAVAR EM BULAS) ---
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

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # Palavras-chave para forçar modo imagem (OCR)
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
            
            # Se tem bastante texto e não é curva, usa texto (mais rápido)
            if len(full_text.strip()) > 500 and not is_curva:
                doc.close(); return {"type": "text", "data": full_text}
            
            # Se for imagem ou pouco texto, converte para imagem
            images = []
            limit = min(12, len(doc)) 
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
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
        st.success("✅ Conectado")
    else:
        st.error("❌ Verifique API Key")

# ----------------- LÓGICA PRINCIPAL -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='color:#55a68e;text-align:center;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("💊 Ref x BELFAR"); c2.info("📋 Conf. MKT"); c3.info("🎨 Gráfica")

else:
    st.markdown(f"## {pagina}")
    
    # Inicializa Session State para não perder os dados se a tela piscar
    if 'resultado_auditoria' not in st.session_state:
        st.session_state['resultado_auditoria'] = None
        
    lista_secoes = SECOES_PACIENTE
    if pagina == "💊 Ref x BELFAR":
        if st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Referência", type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader("Candidato", type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA"):
        # Limpa resultado anterior
        st.session_state['resultado_auditoria'] = None
        
        if f1 and f2 and is_connected:
            with st.spinner("Processando arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                # LISTA DE MODELOS NA FORÇA BRUTA (Tenta um por um)
                models_to_try = [
                    "gemini-1.5-flash",       # Padrão Rápido
                    "gemini-1.5-flash-8b",    # Lite
                    "gemini-1.5-pro"          # Inteligente
                ]
                
                payload = ["CONTEXTO: Auditoria Farmacêutica Rigorosa (OCR)."]
                if d1['type'] == 'text': payload.append(f"--- REF TEXTO ---\n{d1['data']}")
                else: payload.extend(["--- REF IMAGENS ---"] + d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- CAND TEXTO ---\n{d2['data']}")
                else: payload.extend(["--- CAND IMAGENS ---"] + d2['data'])

                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                prompt = f"""
                ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO DE TEXTO.
                
                TAREFA: Extrair TODAS as seções presentes e comparar.
                
                SEÇÕES ALVO (Procure por todas elas):
                {secoes_str}
                
                REGRAS:
                1. Extraia o texto EXATAMENTE como está na imagem (IPSIS LITTERIS).
                2. Compare Referência vs Candidato.
                3. Diferenças: marque com <mark class='diff'>TEXTO DIFERENTE</mark>.
                4. Erros ortográficos: marque com <mark class='ort'>ERRO</mark>.
                5. Data Anvisa: extraia se houver.
                
                IMPORTANTE: Não pare no meio. Gere o JSON completo.
                
                SAÍDA JSON:
                {{
                    "METADADOS": {{ "datas": [] }},
                    "SECOES": [
                        {{ "titulo": "TITULO", "ref": "Texto original...", "bel": "Texto candidato...", "status": "OK" or "DIVERGENTE" }}
                    ]
                }}
                """
                
                success = False
                final_data = None
                
                progress = st.progress(0)
                
                for idx, model_name in enumerate(models_to_try):
                    try:
                        st.toast(f"Tentando IA: {model_name}...", icon="🤖")
                        model = genai.GenerativeModel(model_name)
                        
                        # Timeout alto para não cortar
                        response = model.generate_content(
                            [prompt] + payload,
                            generation_config={
                                "response_mime_type": "application/json", 
                                "max_output_tokens": 8192, 
                                "temperature": 0.0
                            },
                            safety_settings=SAFETY_SETTINGS,
                            request_options={"timeout": 600}
                        )
                        
                        # Verifica se houve bloqueio de segurança
                        if response.prompt_feedback and response.prompt_feedback.block_reason:
                            st.warning(f"Modelo {model_name} bloqueou o conteúdo. Tentando próximo...")
                            continue
                            
                        data = extract_json(response.text)
                        
                        if data and "SECOES" in data and len(data["SECOES"]) > 0:
                            final_data = normalize_sections(data, lista_secoes)
                            success = True
                            st.success(f"Sucesso via {model_name}")
                            break # SUCESSO!
                            
                    except Exception as e:
                        if "429" in str(e): # Se for Cota, tenta o próximo rápido
                            time.sleep(2)
                            continue
                        elif "404" in str(e): # Modelo não existe, tenta o próximo
                            continue
                        else:
                            st.write(f"Erro no {model_name}: {e}") # Debug silencioso
                    
                    progress.progress((idx+1)/len(models_to_try))
                
                progress.empty()
                
                if success and final_data:
                    # SALVA NO SESSION STATE PARA NÃO SUMIR
                    st.session_state['resultado_auditoria'] = final_data
                else:
                    st.error("Não foi possível processar o arquivo. Tente novamente em 1 minuto.")

    # --- EXIBIÇÃO DO RESULTADO (FORA DO BOTÃO PARA PERSISTIR) ---
    if st.session_state['resultado_auditoria']:
        final_data = st.session_state['resultado_auditoria']
        secs = final_data.get("SECOES", [])
        
        st.divider()
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
