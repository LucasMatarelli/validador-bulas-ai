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
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

def auto_select_best_model():
    """
    VARRE TODOS OS MODELOS E TESTA COM AUDITORIA REAL.
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
            if "gemini" in name_lower: score += 10
            if "exp" in name_lower: score += 60
            if "2.0" in name_lower or "2-0" in name_lower: score += 100
            if "1206" in name_lower or "1217" in name_lower: score += 90
            if "pro" in name_lower: score += 40
            if "flash" in name_lower: score += 25
            if "8b" in name_lower: score += 5
            return score
        
        candidates.sort(key=priority_score, reverse=True)
        
        test_prompt = """Você é um auditor. Teste rápido:
        REF: "COMPOSIÇÃO: Cada comprimido contém 500mg de paracetamol."
        CAND: "COMPOSIÇÃO: Cada comprimido contem 500mg de paracetamol."
        
        Retorne JSON:
        {"SECOES": [{"titulo": "COMPOSIÇÃO", "ref": "Cada comprimido contém 500mg de paracetamol.", "bel": "Cada comprimido contem 500mg de paracetamol.", "status": "DIVERGENTE"}]}
        """
        
        for model_name in candidates:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    test_prompt,
                    generation_config={
                        "response_mime_type": "application/json",
                        "max_output_tokens": 500,
                        "temperature": 0.0
                    },
                    safety_settings=SAFETY_SETTINGS,
                    request_options={"timeout": 30}
                )
                
                if response and response.text:
                    data = extract_json(response.text)
                    if data and "SECOES" in data and len(data["SECOES"]) > 0:
                        return model_name
            except:
                continue
        
        return None
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
            
            if len(full_text.strip()) > 800:
                doc.close(); return {"type": "text", "data": full_text}
            
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
    st.markdown("<h2 style='text-align: center; color: #55a68e;'>Validador Auto</h2>", unsafe_allow_html=True)
    
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"], label_visibility="collapsed")
    st.divider()
    
    is_connected = configure_gemini()
    if is_connected:
        st.success("✅ Conectado")
        st.caption("Seleção de IA: Automática")
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
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if f1 and f2 and is_connected:
            
            # --- FASE 1: ESCOLHA DA IA ---
            with st.spinner("🔍 Testando todas as IAs disponíveis..."):
                best_model = auto_select_best_model()
            
            if not best_model:
                st.error("❌ Nenhuma IA conseguiu processar. Verifique sua cota.")
            else:
                st.success(f"✅ IA Selecionada: **{best_model}**", icon="🤖")
                time.sleep(0.5)
                
                # --- FASE 2: LEITURA ---
                with st.spinner("📖 Lendo arquivos..."):
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                if d1 and d2:
                    model = genai.GenerativeModel(best_model)
                    
                    final_sections = []
                    final_dates = []
                    success = False
                    
                    # --- PAYLOAD ---
                    payload = ["🔬 AUDITORIA FARMACÊUTICA COMPLETA"]
                    
                    if d1['type'] == 'text': payload.append(f"📄 REFERÊNCIA (TEXTO):\n{d1['data']}")
                    else: payload.extend(["📄 REFERÊNCIA (IMAGENS):"] + d1['data'])
                    
                    if d2['type'] == 'text': payload.append(f"📋 CANDIDATO (TEXTO):\n{d2['data']}")
                    else: payload.extend(["📋 CANDIDATO (IMAGENS):"] + d2['data'])

                    secoes_str = "\n".join([f"   {i+1}. {s}" for i, s in enumerate(lista_secoes)])
                    
                    prompt = f"""
🎯 MISSÃO CRÍTICA: Auditor Farmacêutico de Máxima Precisão

═══════════════════════════════════════════════════════════════════

📋 SEÇÕES OBRIGATÓRIAS (EXTRAIR TODAS COMPLETAMENTE):
{secoes_str}

═══════════════════════════════════════════════════════════════════

🔴 REGRAS ABSOLUTAS - LEIA COM ATENÇÃO:

1️⃣ EXTRAÇÃO 100% COMPLETA:
   ✓ Extraia TODO o texto de cada seção
   ✓ Comece EXATAMENTE após o número/título da seção
   ✓ Continue até encontrar o PRÓXIMO número/título de seção
   ✓ NUNCA pare no meio de uma frase
   ✓ NUNCA omita parágrafos
   ✓ Se o texto continua em outra coluna/página, CONTINUE até o fim
   ✓ Preserve TODAS as quebras de linha originais
   ✓ NÃO invente palavras - copie EXATAMENTE como está escrito
   ✓ Se não conseguir ler algo, marque como [ILEGÍVEL]

2️⃣ EXEMPLO DE EXTRAÇÃO CORRETA:
   
   Documento diz:
   "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?
   Caso você se esqueça de tomar Belcomplex B conforme as recomendações 
   da bula ou orientação médica. Se você deixou de tomar uma dose, deverá 
   tomar a dose seguinte do costume, isto é, na hora regular e sem dobrar a dose.
   
   Em caso de dúvidas, procure orientação do farmacêutico ou de seu médico, ou
   cirurgião-dentista."
   
   Você DEVE extrair:
   "Caso você se esqueça de tomar Belcomplex B conforme as recomendações da bula ou orientação médica. Se você deixou de tomar uma dose, deverá tomar a dose seguinte do costume, isto é, na hora regular e sem dobrar a dose.

Em caso de dúvidas, procure orientação do farmacêutico ou de seu médico, ou cirurgião-dentista."

3️⃣ COMPARAÇÃO PALAVRA POR PALAVRA:
   ✓ Compare REF vs CAND letra por letra
   ✓ Identifique até vírgulas e acentos diferentes
   ✓ Marque TODAS as diferenças encontradas

4️⃣ MARCAÇÕES COLORIDAS (OBRIGATÓRIO):

   🟡 DIVERGÊNCIAS (use: <mark class='diff'>TEXTO</mark>):
      - Qualquer diferença entre REF e CAND
      - Palavras diferentes, acentos faltando, vírgulas a mais/menos
      - Exemplo: REF tem "contém" e CAND tem "contem" 
        → marque no CAND: <mark class='diff'>contem</mark>

   🔴 ERROS DE PORTUGUÊS (use: <mark class='ort'>ERRO</mark>):
      - Erros ortográficos evidentes
      - Falta de acentuação obrigatória
      - Exemplo: "contem" (sem acento) → <mark class='ort'>contem</mark>
      
   🔵 DATA ANVISA (use: <mark class='anvisa'>DD/MM/YYYY</mark>):
      - Apenas na seção "DIZERES LEGAIS"
      - Formatos aceitos: DD/MM/YYYY, DD.MM.YYYY, DD-MM-YYYY
      - Se não houver data: retorne ["N/A"] em "datas"

5️⃣ STATUS DA SEÇÃO:
   - "OK" = Textos 100% idênticos
   - "DIVERGENTE" = Tem diferenças entre REF e CAND
   - "ERRO ORTOGRÁFICO" = Tem erros de português no CAND
   - "FALTANTE" = Não encontrou a seção

═══════════════════════════════════════════════════════════════════

📤 FORMATO JSON DE SAÍDA (OBRIGATÓRIO):

{{
    "METADADOS": {{
        "datas": ["DD/MM/YYYY"] ou ["N/A"]
    }},
    "SECOES": [
        {{
            "titulo": "NOME_EXATO_DA_SECAO",
            "ref": "Texto COMPLETO da REF (pode ter marcações se for mostrar diferenças)",
            "bel": "Texto COMPLETO do CAND com <mark class='diff'> e <mark class='ort'> onde tiver diferenças",
            "status": "OK" ou "DIVERGENTE" ou "ERRO ORTOGRÁFICO"
        }}
    ]
}}

═══════════════════════════════════════════════════════════════════

⚠️ ATENÇÃO MÁXIMA:
- NÃO resuma
- NÃO simplifique
- NÃO corte frases
- NÃO invente palavras
- COPIE EXATAMENTE como está escrito
- Se o texto tem 500 palavras, extraia as 500 palavras
- LEIA ATÉ O FIM DE CADA SEÇÃO (mesmo que mude de coluna/página)

═══════════════════════════════════════════════════════════════════
"""
                    
                    try:
                        with st.spinner(f"🔍 Auditando com {best_model}..."):
                            response = model.generate_content(
                                [prompt] + payload,
                                generation_config={
                                    "response_mime_type": "application/json", 
                                    "max_output_tokens": 20000,
                                    "temperature": 0.0
                                },
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
                        if "429" in str(e):
                            st.error(f"❌ Erro de Cota (429). Aguarde 1 minuto e tente novamente.")
                        elif "quota" in str(e).lower():
                            st.error(f"❌ Limite de requisições atingido. Aguarde alguns minutos.")
                        else:
                            st.error(f"❌ Erro na auditoria: {str(e)}")
                    
                    # --- RESULTADOS ---
                    if success and final_sections:
                        st.success(f"✅ Auditoria Completa com {best_model}")
                        st.divider()
                        
                        secs = final_sections
                        cM1, cM2, cM3 = st.columns(3)
                        divs = sum(1 for s in secs if "DIVERGENTE" in s.get('status', 'OK') or "ERRO" in s.get('status', 'OK'))
                        score = 100 - int((divs/max(1, len(secs)))*100) if len(secs) > 0 else 0
                        
                        cM1.metric("Score", f"{score}%")
                        cM2.metric("Seções", f"{len(secs)}/{len(lista_secoes)}")
                        
                        if final_dates and final_dates[0] != "N/A":
                            data_formatted = f"<mark class='anvisa'>{final_dates[0]}</mark>"
                            cM3.markdown(f"**Data Anvisa**<br>{data_formatted}", unsafe_allow_html=True)
                        else:
                            cM3.metric("Data Anvisa", "N/A")
                        
                        st.markdown("---")
                        
                        for sec in secs:
                            status = sec.get('status', 'OK')
                            icon = "✅"
                            if "DIVERGENTE" in status or "ERRO" in status: 
                                icon = "❌"
                            elif "FALTANTE" in status: 
                                icon = "🚨"
                            
                            with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                cA, cB = st.columns(2)
                                ref_text = sec.get('ref', 'Não encontrado')
                                bel_text = sec.get('bel', 'Não encontrado')
                                
                                cA.markdown(f"**📄 Referência**\n<div style='background:#f8f9fa;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;line-height:1.6;'>{ref_text}</div>", unsafe_allow_html=True)
                                cB.markdown(f"**📋 Candidato**\n<div style='background:#f1f8e9;padding:15px;border-radius:5px;font-size:0.9em;white-space: pre-wrap;line-height:1.6;'>{bel_text}</div>", unsafe_allow_html=True)
                                
                                if "DIVERGENTE" in status or "ERRO" in status:
                                    st.markdown("""
                                    <div style='margin-top:10px;padding:10px;background:#f0f0f0;border-radius:5px;font-size:0.85em;'>
                                    📌 <b>Legenda:</b> 
                                    <mark class='diff'>🟡 Amarelo = Divergência</mark> | 
                                    <mark class='ort'>🔴 Vermelho = Erro Português</mark> | 
                                    <mark class='anvisa'>🔵 Azul = Data Anvisa</mark>
                                    </div>
                                    """, unsafe_allow_html=True)
                    elif success:
                        st.warning("⚠️ IA processou mas não encontrou seções compatíveis.")
                    else:
                        st.error("❌ Falha na auditoria. Tente novamente.")
