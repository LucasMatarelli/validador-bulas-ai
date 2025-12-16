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
    page_title="Validador Ultimate",
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
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

def auto_select_best_model():
    """
    SELEÇÃO INTELIGENTE:
    1. Lista TUDO que existe na API.
    2. Ordena por 'Maior Cota' (Flash) -> 'Maior Poder' (Pro/Exp).
    3. Se der erro de cota, ESPERA (backoff) e tenta o próximo.
    """
    try:
        # Pega a lista real da API (nada inventado)
        all_models_obj = list(genai.list_models())
        candidates = []
        
        for m in all_models_obj:
            if 'generateContent' in m.supported_generation_methods:
                candidates.append(m.name)
        
        if not candidates:
            st.error("❌ A API não retornou nenhum modelo. Verifique sua Chave API.")
            return None
            
        # Sistema de Pontuação para Priorizar Estabilidade (Flash)
        def scoring_algo(name):
            score = 0
            n = name.lower()
            
            # --- MODELOS DE ALTA COTA (PRIORIDADE MÁXIMA) ---
            if "gemini-1.5-flash" in n: 
                score += 500  # O rei da estabilidade
                if "8b" in n: score += 50 # Versão 8b é ainda mais leve
                if "002" in n or "latest" in n: score += 20 # Versões mais novas
                
            elif "gemini-2.0-flash" in n:
                score += 400  # Muito rápido, mas cota um pouco menor que o 1.5
                if "lite" in n: score += 50
            
            # --- MODELOS POTENTES (COTA BAIXA - USAR SÓ SE FLASH FALHAR) ---
            elif "gemini-1.5-pro" in n: score += 100
            elif "gemini-2.0-pro" in n: score += 100
            elif "exp" in n: score += 50  # Experimentais falham muito
            
            # --- PENALIDADES (NÃO USAR) ---
            if "vision" in n: score -= 1000 # Modelos antigos só de visão
            if "gemma" in n: score -= 2000 # Gemma não aceita imagens (dá erro 400)
            if "tts" in n or "robotics" in n: score -= 5000 # Modelos de áudio/robô
            
            return score

        # Ordena a lista
        candidates.sort(key=scoring_algo, reverse=True)
        
        st.info(f"🔍 Encontrados {len(candidates)} modelos. Testando os mais estáveis primeiro...")
        
        test_prompt = '{"test": "ok"}'
        
        # Loop de teste
        for i, model_name in enumerate(candidates):
            # Se o score for muito baixo (modelo ruim), pula
            if scoring_algo(model_name) < 0: continue
            
            try:
                st.write(f"🧪 [{i+1}/{len(candidates)}] Testando: **{model_name}** ...")
                
                model = genai.GenerativeModel(model_name)
                # Teste rápido e barato (1 token)
                response = model.generate_content(
                    test_prompt,
                    generation_config={"max_output_tokens": 10},
                    request_options={"timeout": 10}
                )
                
                if response:
                    st.success(f"✅ CONECTADO! Modelo escolhido: {model_name}")
                    return model_name
                    
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "quota" in err or "exhausted" in err:
                    st.warning(f"⚠️ Cota cheia no {model_name}. Aguardando 2s...")
                    time.sleep(2.0) # Espera para limpar a API
                elif "404" in err:
                    st.caption(f"⏭️ Modelo não encontrado/depreciado: {model_name}")
                else:
                    st.caption(f"⏭️ Erro no {model_name}: {err[:50]}...")
                continue
        
        st.error("❌ Todos os modelos falharam.")
        
        # Tentativa de Resgate: Pega o primeiro 'Flash' que existir na lista, independente de teste
        fallback = next((m for m in candidates if "flash" in m.lower()), candidates[0])
        st.warning(f"⚠️ Forçando uso do modelo: {fallback} (Tentativa final)")
        return fallback

    except Exception as e:
        st.error(f"Erro crítico na seleção: {e}")
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
            
            if len(full_text.strip()) > 800:
                doc.close()
                return {"type": "text", "data": full_text}
            
            images = []
            limit = min(15, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.5, 2.5), dpi=200)
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro arquivo: {e}")
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
            start = cleaned.find('{')
            end = cleaned.rfind('}') + 1
            if start != -1 and end != -1:
                return json.loads(cleaned[start:end], strict=False)
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
    st.markdown("<h2 style='text-align: center; color: #55a68e;'>Validador Blindado</h2>", unsafe_allow_html=True)
    pagina = st.radio("Nav:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conf. MKT", "🎨 Gráfica"], label_visibility="collapsed")
    st.divider()
    is_connected = configure_gemini()
    if is_connected: st.success("✅ API Conectada")
    else: st.error("❌ API Key Off")

# ----------------- LÓGICA PRINCIPAL -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='color:#55a68e;text-align:center;'>Validador Farmacêutico</h1>", unsafe_allow_html=True)
    st.info("💡 Algoritmo de seleção otimizado para evitar erros de Cota (429).")

else:
    st.markdown(f"## {pagina}")
    lista_secoes = SECOES_PACIENTE
    if pagina == "💊 Ref x BELFAR":
        if st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Ref", type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader("Cand", type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if f1 and f2 and is_connected:
            with st.spinner("🤖 Selecionando melhor IA disponível (Aguarde)..."):
                best_model = auto_select_best_model()
            
            if best_model:
                with st.spinner(f"📖 Lendo arquivos com {best_model}..."):
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                if d1 and d2:
                    model = genai.GenerativeModel(best_model)
                    
                    payload = ["CONTEXTO: Auditoria de Bulas."]
                    if d1['type']=='text': payload.append(f"REF (TXT):\n{d1['data']}")
                    else: payload.extend(["REF (IMG):"] + d1['data'])
                    if d2['type']=='text': payload.append(f"CAND (TXT):\n{d2['data']}")
                    else: payload.extend(["CAND (IMG):"] + d2['data'])

                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                    prompt = f"""
                    Você é um Auditor de Qualidade Farmacêutica.
                    SEÇÕES ALVO:
                    {secoes_str}
                    
                    REGRAS:
                    1. Extraia o texto COMPLETO de cada seção encontrada.
                    2. Compare REF vs CAND letra por letra.
                    3. Use <mark class='diff'>DIFERENCA</mark> para divergências.
                    4. Use <mark class='ort'>ERRO</mark> para erros de português.
                    5. Use <mark class='anvisa'>DATA</mark> para datas na seção DIZERES LEGAIS.
                    6. Status: "OK", "DIVERGENTE", "ERRO", "FALTANTE".
                    
                    SAIDA JSON:
                    {{ "METADADOS": {{ "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "..." }} ] }}
                    """
                    
                    try:
                        with st.spinner("🔍 Processando comparação..."):
                            response = model.generate_content(
                                [prompt] + payload,
                                generation_config={"response_mime_type": "application/json", "max_output_tokens": 20000},
                                safety_settings=SAFETY_SETTINGS,
                                request_options={"timeout": 1000}
                            )
                            data = extract_json(response.text)
                            
                            if data:
                                norm = normalize_sections(data, lista_secoes)
                                secs = norm.get("SECOES", [])
                                dates = data.get("METADADOS", {}).get("datas", [])
                                
                                st.success("✅ Auditoria Concluída!")
                                st.divider()
                                
                                cM1, cM2, cM3 = st.columns(3)
                                errs = sum(1 for s in secs if "DIVERGENTE" in s['status'] or "ERRO" in s['status'])
                                score = 100 - int((errs/max(1, len(secs)))*100) if secs else 0
                                cM1.metric("Score", f"{score}%")
                                cM2.metric("Seções", f"{len(secs)}/{len(lista_secoes)}")
                                cM3.markdown(f"**Data**<br><mark class='anvisa'>{dates[0] if dates else 'N/A'}</mark>", unsafe_allow_html=True)
                                
                                st.markdown("---")
                                for s in secs:
                                    icon = "✅"
                                    if "DIVERGENTE" in s['status']: icon = "❌"
                                    elif "FALTANTE" in s['status']: icon = "🚨"
                                    
                                    with st.expander(f"{icon} {s['titulo']} - {s['status']}"):
                                        cA, cB = st.columns(2)
                                        cA.markdown(f"**Ref**\n<div style='background:#f9f9f9;padding:10px;'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                                        cB.markdown(f"**Cand**\n<div style='background:#eaffea;padding:10px;'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                            else:
                                st.error("Falha ao estruturar JSON.")
                    except Exception as e:
                        st.error(f"Erro fatal: {e}")
        else:
            st.warning("Envie os arquivos e verifique a API.")
