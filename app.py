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
    page_title="Validador de Bulas (Blindado)",
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

def get_robust_model():
    """Retorna o modelo mais estável e rápido para evitar cortes."""
    # Prioriza o Flash 1.5 por ter limite maior de requisições na camada gratuita
    return "models/gemini-1.5-flash"

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
            
            # Se tiver texto selecionável suficiente, usa o texto (mais leve)
            if len(full_text.strip()) > 500:
                doc.close(); return {"type": "text", "data": full_text}
            
            # Se for imagem scanneada, extrai imagens
            images = []
            limit = min(12, len(doc)) 
            for i in range(limit):
                # Matrix 2.0 é o equilíbrio ideal entre qualidade OCR e tamanho
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
    
    # Recuperação de JSON cortado (Truncado)
    try:
        if '"SECOES":' in cleaned:
            # Tenta encontrar o último fechamento de objeto válido
            last_bracket = cleaned.rfind("}")
            if last_bracket != -1:
                # Tenta fechar array e objeto principal se estiverem abertos
                fixed = cleaned[:last_bracket+1]
                if not fixed.endswith("]}"): fixed += "]}"
                try: return json.loads(fixed, strict=False)
                except: pass
                # Tenta fechar só o array
                if not fixed.endswith("]"): fixed += "]"
                if not fixed.endswith("}"): fixed += "}"
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
        
        # Match exato ou parcial
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
        st.success("✅ Sistema Online")
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
        
    if st.button("🚀 INICIAR AUDITORIA (SEM ERROS)"):
        if f1 and f2 and is_connected:
            with st.spinner("Lendo arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                model_name = get_robust_model()
                model = genai.GenerativeModel(model_name)
                
                final_sections = []
                final_dates = []
                
                # --- ESTRATÉGIA DE CHUNKS SEGURA ---
                # Dividir em 3 partes para garantir que leia tudo e não estoure memória
                chunk_size = 4 
                chunks = [lista_secoes[i:i + chunk_size] for i in range(0, len(lista_secoes), chunk_size)]
                
                payload_base = ["CONTEXTO: Auditoria Farmacêutica Rigorosa."]
                if d1['type'] == 'text': payload_base.append(f"--- REF TEXTO ---\n{d1['data']}")
                else: payload_base.extend(["--- REF IMAGENS ---"] + d1['data'])
                
                if d2['type'] == 'text': payload_base.append(f"--- CAND TEXTO ---\n{d2['data']}")
                else: payload_base.extend(["--- CAND IMAGENS ---"] + d2['data'])

                bar = st.progress(0)
                
                for i, chunk in enumerate(chunks):
                    # PAUSA OBRIGATÓRIA PARA EVITAR ERRO 429
                    if i > 0:
                        with st.spinner(f"Aguardando liberação da API (10s)..."):
                            time.sleep(10)
                    
                    st.toast(f"Processando lote {i+1}/{len(chunks)}...", icon="⏳")
                    secoes_str = "\n".join([f"- {s}" for s in chunk])
                    
                    prompt = f"""
                    Você é um Auditor de Qualidade.
                    
                    MISSÃO: Extrair o texto das SEÇÕES ALVO abaixo.
                    
                    SEÇÕES ALVO DESTA ETAPA:
                    {secoes_str}
                    
                    REGRAS:
                    1. Extraia o texto EXATAMENTE como está (IPSIS LITTERIS).
                    2. Compare Referência vs Candidato.
                    3. No texto do 'bel' (Candidato), marque diferenças com <mark class='diff'>DIFERENÇA</mark>.
                    4. Marque erros ortográficos com <mark class='ort'>ERRO</mark>.
                    5. Se encontrar Data de Aprovação (rodapé), extraia.
                    
                    SAÍDA JSON:
                    {{
                        "METADADOS": {{ "datas": [] }},
                        "SECOES": [
                            {{ "titulo": "TITULO DA LISTA", "ref": "Texto Ref", "bel": "Texto Cand...", "status": "OK" or "DIVERGENTE" }}
                        ]
                    }}
                    """
                    
                    # LOOP DE RETENTATIVA INFINITA ATÉ CONSEGUIR (Para erro 429)
                    success_part = False
                    wait_time = 20
                    
                    while not success_part:
                        try:
                            response = model.generate_content(
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
                            
                            success_part = True # Sai do loop
                            
                        except Exception as e:
                            err_msg = str(e)
                            if "429" in err_msg or "Quota" in err_msg:
                                st.warning(f"Limite de API atingido. Aguardando {wait_time}s para retomar...")
                                time.sleep(wait_time)
                                wait_time += 10 # Aumenta o tempo se falhar de novo
                            else:
                                st.error(f"Erro irrecuperável na parte {i+1}: {err_msg}")
                                success_part = True # Força saída para não travar eterno em erro 500
                    
                    bar.progress((i+1)/len(chunks))
                
                bar.empty()
                
                if final_sections:
                    st.divider()
                    cM1, cM2, cM3 = st.columns(3)
                    divs = sum(1 for s in final_sections if "DIVERGENTE" in s['status'])
                    total = len(final_sections)
                    score = 100 - int((divs/max(1, total))*100) if total > 0 else 0
                    
                    cM1.metric("Score", f"{score}%")
                    cM2.metric("Seções", f"{total}/{len(lista_secoes)}")
                    # Pega a data mais frequente ou a primeira
                    data_anvisa = "N/A"
                    if final_dates:
                        data_anvisa = max(set(final_dates), key=final_dates.count)
                    cM3.metric("Data Anvisa", str(data_anvisa))
                    
                    st.markdown("---")
                    
                    for sec in final_sections:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status: icon = "❌"
                        elif "FALTANTE" in status: icon = "🚨"
                        
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    st.error("Nenhuma seção foi identificada. Verifique se o PDF contém texto legível.")
