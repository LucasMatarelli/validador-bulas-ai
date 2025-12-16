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
    page_title="Validador Auto-Select",
    page_icon="🤖",
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
    try: 
        api_key = st.secrets["GEMINI_API_KEY"]
    except: 
        api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: 
        return False
    
    genai.configure(api_key=api_key)
    return True

def auto_select_best_model():
    """
    VERSÃO OTIMIZADA PARA COTA: Prioriza modelos leves e faz pausas para evitar bloqueio.
    """
    try:
        all_models = list(genai.list_models())
        candidates = []
        
        # Filtra modelos que suportam generateContent
        for m in all_models:
            if 'generateContent' in m.supported_generation_methods:
                candidates.append(m.name)
        
        if not candidates:
            st.error("❌ Nenhum modelo encontrado na API")
            return None
        
        st.info(f"🔍 Encontrados {len(candidates)} modelos. Testando os mais estáveis primeiro...")
        
        # Sistema de prioridade FOCADO EM ESTABILIDADE E COTA
        def priority_score(name):
            score = 0
            name_lower = name.lower()
            
            # Prioriza modelos "Flash" e "Lite" (Maior Cota)
            if "gemini-1.5-flash" in name_lower and "8b" not in name_lower: score += 200 # O mais estável de todos
            if "gemini-2.0-flash-lite" in name_lower: score += 190
            if "gemini-1.5-flash-8b" in name_lower: score += 180
            if "gemini-2.0-flash" in name_lower and "lite" not in name_lower: score += 150
            
            # Modelos Pro/Exp (Cota menor, deixa pro final)
            if "gemini-1.5-pro" in name_lower: score += 100
            if "exp" in name_lower: score += 50 # Experimental cai muito a cota
            
            # Penaliza modelos problemáticos para essa tarefa
            if "thinking" in name_lower: score -= 500
            if "vision" in name_lower: score -= 100
            if "image" in name_lower: score -= 100
            if "robotics" in name_lower: score -= 1000
            if "tts" in name_lower: score -= 1000
            if "gemma" in name_lower: score -= 2000 # Gemma não lê imagens (erro 400)
            
            return score
        
        candidates.sort(key=priority_score, reverse=True)
        
        # Mostra os top 5 candidatos
        with st.expander("📋 Top 5 Modelos Prioritários"):
            for i, model_name in enumerate(candidates[:5], 1):
                st.caption(f"{i}. {model_name}")
        
        test_prompt = 'Responda em JSON: {"status": "ok"}'
        
        tested_count = 0
        failed_quota = []
        
        # TESTA COM PAUSA DE SEGURANÇA
        for model_name in candidates:
            tested_count += 1
            
            # Pula modelos obviamente ruins baseados no nome
            if "robotics" in model_name or "tts" in model_name or "gemma" in model_name:
                continue

            try:
                st.caption(f"🧪 Testando [{tested_count}]: {model_name}")
                
                model = genai.GenerativeModel(model_name)
                
                response = model.generate_content(
                    test_prompt,
                    generation_config={"max_output_tokens": 50, "temperature": 0.0},
                    safety_settings=SAFETY_SETTINGS,
                    request_options={"timeout": 15}
                )
                
                if response and hasattr(response, 'text'):
                     st.success(f"✅ ENCONTRADO! Modelo funcional: {model_name}")
                     return model_name
                    
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "quota" in error_msg or "resource_exhausted" in error_msg:
                    failed_quota.append(model_name)
                    st.warning(f"⏭️ Cota cheia: {model_name}")
                    time.sleep(1.0) # PAUSA IMPORTANTE: Espera 1s para recuperar fôlego da API
                else:
                    st.caption(f"⚠️ Erro: {model_name} ({str(e)[:50]})")
                
                continue
        
        # Se todos falharem por cota, tenta o 1.5 Flash na marra (costuma voltar rápido)
        st.error(f"❌ Todos os {tested_count} modelos falharam.")
        st.warning("⚠️ Forçando uso do 'gemini-1.5-flash' (é o que recupera mais rápido)")
        return "models/gemini-1.5-flash"
        
    except Exception as e:
        st.error(f"❌ Erro fatal: {e}")
        return "models/gemini-1.5-flash"

def process_uploaded_file(uploaded_file):
    if not uploaded_file: 
        return None
    
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
            for page in doc: 
                full_text += page.get_text() + "\n"
            
            # Se tem muito texto, usa modo texto
            if len(full_text.strip()) > 800:
                doc.close()
                return {"type": "text", "data": full_text}
            
            # Caso contrário, extrai imagens
            images = []
            limit = min(15, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.5, 2.5), dpi=200)
                try: 
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
                except: 
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
        return None
    
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    return re.sub(r'//.*', '', text)

def extract_json(text):
    cleaned = clean_json_response(text)
    try: 
        return json.loads(cleaned, strict=False)
    except: 
        pass
    try:
        if '"SECOES":' in cleaned:
            last_bracket = cleaned.rfind("}")
            if last_bracket != -1:
                fixed = cleaned[:last_bracket+1]
                if not fixed.strip().endswith("]}"): 
                    if fixed.strip().endswith("]"): fixed += "}"
                    else: fixed += "]}"
                return json.loads(fixed, strict=False)
    except: 
        pass
    return None

def normalize_sections(data_json, allowed_titles):
    if not data_json or "SECOES" not in data_json: 
        return data_json
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
                    match = v
                    break
        if match:
            sec["titulo"] = match
            clean.append(sec)
    data_json["SECOES"] = clean
    return data_json

# ----------------- UI LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.markdown("<h2 style='text-align: center; color: #55a68e;'>Validador Auto</h2>", unsafe_allow_html=True)
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"], label_visibility="collapsed")
    st.divider()
    is_connected = configure_gemini()
    if is_connected:
        st.success("✅ Conectado à API")
    else:
        st.error("❌ API Key não encontrada")

# ----------------- LÓGICA PRINCIPAL -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='color:#55a68e;text-align:center;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    st.info("💡 Este sistema testa os modelos disponíveis priorizando os mais estáveis (Flash).")
    c1, c2, c3 = st.columns(3)
    c1.info("💊 Ref x BELFAR")
    c2.info("📋 Conf. MKT")
    c3.info("🎨 Gráfica")

else:
    st.markdown(f"## {pagina}")
    lista_secoes = SECOES_PACIENTE
    if pagina == "💊 Ref x BELFAR":
        tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
        if tipo_bula == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("📄 Arquivo Referência", type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader("📋 Arquivo Candidato", type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2:
            st.error("❌ Por favor, envie os dois arquivos")
        elif not is_connected:
            st.error("❌ API não configurada.")
        else:
            with st.spinner("🔍 Buscando modelo com cota disponível..."):
                best_model = auto_select_best_model()
            
            st.success(f"✅ IA Selecionada: **{best_model}**", icon="🤖")
            time.sleep(0.5)
            
            with st.spinner("📖 Processando arquivos..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

            if not d1 or not d2:
                st.error("❌ Erro ao processar um dos arquivos")
            else:
                model = genai.GenerativeModel(best_model)
                final_sections = []
                final_dates = []
                success = False
                
                payload = ["🔬 AUDITORIA FARMACÊUTICA COMPLETA"]
                if d1['type'] == 'text': payload.append(f"📄 REFERÊNCIA (TEXTO):\n{d1['data']}")
                else: payload.extend(["📄 REFERÊNCIA (IMAGENS):"] + d1['data'])
                if d2['type'] == 'text': payload.append(f"📋 CANDIDATO (TEXTO):\n{d2['data']}")
                else: payload.extend(["📋 CANDIDATO (IMAGENS):"] + d2['data'])

                secoes_str = "\n".join([f"   {i+1}. {s}" for i, s in enumerate(lista_secoes)])
                prompt = f"""
🎯 MISSÃO CRÍTICA: Auditor Farmacêutico de Máxima Precisão
📋 SEÇÕES OBRIGATÓRIAS (EXTRAIR TODAS COMPLETAMENTE):
{secoes_str}
🔴 REGRAS ABSOLUTAS:
1️⃣ EXTRAÇÃO 100% COMPLETA (Copie TODO o texto).
2️⃣ COMPARAÇÃO PALAVRA POR PALAVRA (Identifique diferenças).
3️⃣ MARCAÇÕES: <mark class='diff'>DIVERGÊNCIA</mark>, <mark class='ort'>ERRO ORTOGRÁFICO</mark>, <mark class='anvisa'>DATA</mark>.
📤 FORMATO JSON: {{ "METADADOS": {{ "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "..." }} ] }}
"""
                try:
                    with st.spinner(f"🔍 Auditando com {best_model}..."):
                        response = model.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json", "max_output_tokens": 20000, "temperature": 0.0},
                            safety_settings=SAFETY_SETTINGS,
                            request_options={"timeout": 1200}
                        )
                        data = extract_json(response.text)
                        if data and "SECOES" in data:
                            norm = normalize_sections(data, lista_secoes)
                            final_sections = norm.get("SECOES", [])
                            final_dates = data.get("METADADOS", {}).get("datas", [])
                            success = True
                except Exception as e:
                    st.error(f"❌ Erro na auditoria: {str(e)}")

                if success and final_sections:
                    st.success(f"✅ Auditoria Completa!")
                    st.divider()
                    secs = final_sections
                    cM1, cM2, cM3 = st.columns(3)
                    divs = sum(1 for s in secs if "DIVERGENTE" in s.get('status', 'OK') or "ERRO" in s.get('status', 'OK'))
                    score = 100 - int((divs/max(1, len(secs)))*100) if len(secs) > 0 else 0
                    cM1.metric("Score", f"{score}%")
                    cM2.metric("Seções", f"{len(secs)}/{len(lista_secoes)}")
                    cM3.markdown(f"**Data Anvisa**<br><mark class='anvisa'>{final_dates[0] if final_dates else 'N/A'}</mark>", unsafe_allow_html=True)
                    st.markdown("---")
                    for sec in secs:
                        status = sec.get('status', 'OK')
                        icon = "✅"
                        if "DIVERGENTE" in status or "ERRO" in status: icon = "❌"
                        elif "FALTANTE" in status: icon = "🚨"
                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:15px;font-size:0.9em;white-space:pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato**\n<div style='background:#f1f8e9;padding:15px;font-size:0.9em;white-space:pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                            if icon == "❌": st.caption("Legenda: 🟡 Divergência | 🔴 Erro Português | 🔵 Data")
                elif success:
                    st.warning("⚠️ IA não encontrou seções.")
                else:
                    st.error("❌ Falha na auditoria.")
