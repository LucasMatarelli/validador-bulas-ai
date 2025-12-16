import streamlit as st
import google.generativeai as genai
from groq import Groq
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
    page_title="Validador Híbrido",
    page_icon="⚡",
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
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; font-weight: 500; }
    mark.ort { background-color: #ffcccc; color: #cc0000; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
    mark.anvisa { background-color: #cce5ff; color: #004085; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }

    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #eee; }
    
    .ia-badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; margin-bottom: 10px; display: inline-block; }
    .groq-badge { background-color: #ffe0b2; color: #e65100; border: 1px solid #ffcc80; }
    .gemini-badge { background-color: #e1f5fe; color: #01579b; border: 1px solid #b3e5fc; }
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

def configure_apis():
    # Configura Gemini
    gemini_key = None
    try: gemini_key = st.secrets["GEMINI_API_KEY"]
    except: gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if gemini_key: genai.configure(api_key=gemini_key)
    
    # Configura Groq
    groq_client = None
    try: 
        groq_key = st.secrets["GROQ_API_KEY"]
        groq_client = Groq(api_key=groq_key)
    except: 
        groq_key = os.environ.get("GROQ_API_KEY")
        if groq_key: groq_client = Groq(api_key=groq_key)
        
    return (gemini_key is not None), groq_client

def auto_select_best_gemini_model():
    """
    SELECIONA O MELHOR GEMINI (COM PRIORIDADE PARA O 1.5 FLASH QUE TEM MAIS COTA)
    """
    try:
        all_models = list(genai.list_models())
        candidates = []
        
        for m in all_models:
            if 'generateContent' in m.supported_generation_methods:
                candidates.append(m.name)
        
        def priority_score(name):
            score = 0
            name_lower = name.lower()
            # Prioriza 1.5 Flash (Estabilidade e Cota Alta)
            if "1.5-flash" in name_lower and "8b" not in name_lower: score += 500
            
            # Penaliza modelos 2.5 ou preview (Cota Baixa - Erro 429)
            if "2.5" in name_lower: score -= 100
            if "exp" in name_lower: score -= 50
            if "preview" in name_lower: score -= 50
            
            # Penaliza modelos que não leem imagem bem ou são muito caros
            if "pro" in name_lower: score += 10 # Menos que o flash
            
            return score
        
        candidates.sort(key=priority_score, reverse=True)
        
        # Teste rápido
        test_prompt = '{"test": "ok"}'
        for model_name in candidates:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(test_prompt, request_options={"timeout": 5})
                if response: return model_name
            except: continue
        
        return "models/gemini-1.5-flash"
    except:
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
            
            # Tenta pegar texto mesmo se for pouco, para priorizar Groq
            if len(full_text.strip()) > 300: # Reduzi para 300 para pegar mais PDFs como texto
                doc.close(); return {"type": "text", "data": full_text}
            
            # Se realmente não tiver texto, extrai imagens (aí só Gemini resolve)
            images = []
            limit = min(15, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.5, 2.5), dpi=200)
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
    st.markdown("<h2 style='text-align: center; color: #55a68e;'>Validador Híbrido</h2>", unsafe_allow_html=True)
    
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"], label_visibility="collapsed")
    st.divider()
    
    gemini_ok, groq_client = configure_apis()
    
    if groq_client: st.success("⚡ Groq: Ativo (Prioridade)")
    else: st.warning("⚠️ Groq: Off")

    if gemini_ok: st.success("💎 Gemini: Ativo (Backup/Imagens)")
    else: st.error("❌ Gemini: Off")

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
        if f1 and f2:
            
            # --- FASE 1: PREPARAÇÃO ---
            with st.spinner("📖 Lendo arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if d1 and d2:
                # --- DECISOR DE IA ---
                # Padrão: Tentar Groq primeiro
                use_groq = True
                
                # Exceção 1: Página Gráfica (Exige visual)
                if pagina == "🎨 Gráfica x Arte":
                    use_groq = False
                # Exceção 2: Arquivos são imagens (Groq não lê imagem)
                elif d1['type'] == 'images' or d2['type'] == 'images':
                    use_groq = False
                # Exceção 3: Groq não configurado
                elif not groq_client:
                    use_groq = False
                
                
                # Prepara o Prompt
                secoes_str = "\n".join([f"   {i+1}. {s}" for i, s in enumerate(lista_secoes)])
                prompt = f"""
🎯 MISSÃO CRÍTICA: Auditor Farmacêutico de Máxima Precisão
📋 SEÇÕES OBRIGATÓRIAS (EXTRAIR TODAS COMPLETAMENTE):
{secoes_str}

🔴 REGRAS ABSOLUTAS:
1️⃣ EXTRAÇÃO 100% COMPLETA: Extraia TODO o texto. NÃO resuma.
2️⃣ COMPARAÇÃO PALAVRA POR PALAVRA: Identifique diferenças.
3️⃣ MARCAÇÕES HTML NO CAMPO 'bel' (Candidato):
   - Divergências: <mark class='diff'>palavra_candidato</mark>
   - Erros PT-BR: <mark class='ort'>erro</mark>
   - Data Anvisa (Dizeres Legais): <mark class='anvisa'>DD/MM/YYYY</mark>

📤 FORMATO JSON DE SAÍDA:
{{
    "METADADOS": {{ "datas": ["DD/MM/YYYY"] }},
    "SECOES": [
        {{ "titulo": "TÍTULO EXATO", "ref": "Texto REF...", "bel": "Texto CAND com marcas...", "status": "OK/DIVERGENTE/FALTANTE" }}
    ]
}}
"""
                
                final_response_text = None
                success = False
                active_model_name = "Desconhecido"
                
                # --- TENTATIVA 1: GROQ (Se aplicável) ---
                if use_groq:
                    try:
                        with st.spinner("⚡ Processando com GROQ (Llama 3)..."):
                            full_groq_prompt = f"{prompt}\n\nCONTEXTO:\n\n--- REF ---\n{d1['data']}\n\n--- CAND ---\n{d2['data']}"
                            
                            chat_completion = groq_client.chat.completions.create(
                                messages=[
                                    {"role": "system", "content": "Você é um validador de bulas que retorna APENAS JSON. Não inclua comentários."},
                                    {"role": "user", "content": full_groq_prompt}
                                ],
                                model="llama-3.3-70b-versatile",
                                temperature=0.0,
                                response_format={"type": "json_object"}
                            )
                            final_response_text = chat_completion.choices[0].message.content
                            active_model_name = "⚡ Groq (Llama 3.3)"
                            success = True
                    except Exception as e:
                        st.warning(f"⚠️ Groq achou difícil ou falhou: {e}. Passando para Gemini...")
                        use_groq = False # Falhou, força Gemini
                        success = False

                # --- TENTATIVA 2: GEMINI (Fallback ou Imagens) ---
                if not success:
                    if not gemini_ok:
                        st.error("❌ Groq não pôde ser usado e Gemini não está configurado.")
                    else:
                        try:
                            # Seleciona modelo Gemini (Prioriza 1.5 Flash estável)
                            best_model_gemini = auto_select_best_gemini_model()
                            
                            with st.spinner(f"💎 Processando com GEMINI ({best_model_gemini})..."):
                                model = genai.GenerativeModel(best_model_gemini)
                                
                                payload = ["CONTEXTO: Auditoria Farmacêutica"]
                                if d1['type'] == 'text': payload.append(f"REF (TXT):\n{d1['data']}")
                                else: payload.extend(["REF (IMG):"] + d1['data'])
                                if d2['type'] == 'text': payload.append(f"CAND (TXT):\n{d2['data']}")
                                else: payload.extend(["CAND (IMG):"] + d2['data'])
                                
                                response = model.generate_content(
                                    [prompt] + payload,
                                    generation_config={"response_mime_type": "application/json", "max_output_tokens": 20000, "temperature": 0.0},
                                    safety_settings=SAFETY_SETTINGS,
                                    request_options={"timeout": 1200}
                                )
                                final_response_text = response.text
                                active_model_name = f"💎 Gemini ({best_model_gemini})"
                                success = True
                        except Exception as e:
                            st.error(f"❌ Gemini falhou: {e}")

                # --- PROCESSAMENTO DO RESULTADO ---
                if success and final_response_text:
                    st.toast(f"Processado via: {active_model_name}", icon="✅")
                    st.markdown(f"<div class='ia-badge {'groq-badge' if 'Groq' in active_model_name else 'gemini-badge'}'>Processado por: {active_model_name}</div>", unsafe_allow_html=True)
                    
                    data = extract_json(final_response_text)
                    if data and "SECOES" in data:
                        norm = normalize_sections(data, lista_secoes)
                        final_sections = norm.get("SECOES", [])
                        final_dates = data.get("METADADOS", {}).get("datas", [])
                        
                        st.success(f"✅ Auditoria Completa!")
                        st.divider()
                        
                        secs = final_sections
                        cM1, cM2, cM3 = st.columns(3)
                        divs = sum(1 for s in secs if "DIVERGENTE" in s.get('status', 'OK') or "ERRO" in s.get('status', 'OK'))
                        score = 100 - int((divs/max(1, len(secs)))*100) if len(secs) > 0 else 0
                        
                        cM1.metric("Score", f"{score}%")
                        cM2.metric("Seções", f"{len(secs)}/{len(lista_secoes)}")
                        
                        if final_dates and final_dates[0] != "N/A":
                            cM3.markdown(f"**Data Anvisa**<br><mark class='anvisa'>{final_dates[0]}</mark>", unsafe_allow_html=True)
                        else:
                            cM3.metric("Data Anvisa", "N/A")
                        
                        st.markdown("---")
                        
                        for sec in secs:
                            status = sec.get('status', 'OK')
                            icon = "✅"
                            if "DIVERGENTE" in status or "ERRO" in status: icon = "❌"
                            elif "FALTANTE" in status: icon = "🚨"
                            
                            with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                cA, cB = st.columns(2)
                                cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                cB.markdown(f"**Candidato**\n<div style='background:#f1f8e9;padding:15px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                    else:
                        st.error("Erro ao estruturar JSON. Tente novamente.")
                else:
                    st.error("Falha ao obter resposta de qualquer IA.")
