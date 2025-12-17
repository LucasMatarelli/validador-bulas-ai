import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import time
from PIL import Image
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Pro (Auto-Fix)",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS (CSS) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    .stButton>button { 
        width: 100%; 
        background: linear-gradient(90deg, #2e7d32 0%, #4caf50 100%);
        color: white; 
        font-weight: bold; 
        height: 60px; 
        border-radius: 8px; 
        font-size: 18px;
        border: none; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: all 0.3s;
    }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 8px rgba(0,0,0,0.2); }
    
    .box-content { 
        background-color: #ffffff; 
        padding: 15px; 
        border-radius: 8px; 
        border: 1px solid #ddd; 
        line-height: 1.6; 
        color: #111;
        font-family: sans-serif;
    }
    .box-ref { border-left: 5px solid #757575; background-color: #f5f5f5; }
    .box-bel { border-left: 5px solid #2e7d32; background-color: #f1f8e9; }
    
    .ia-badge {
        padding: 5px 12px;
        background-color: #fff3e0;
        color: #e65100;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.85em;
        margin-bottom: 10px;
        display: inline-block;
        border: 1px solid #ffe0b2;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- LISTAS OBRIGATÓRIAS -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
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

SECOES_IGNORAR_DIFF = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# Configurações de Segurança
SAFETY_SETTINGS = {
    genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- INTELIGÊNCIA PYTHON (PRÉ-PROCESSAMENTO) -----------------

def clean_text(text):
    text = re.sub(r'([a-zà-ú])- \n([a-zà-ú])', r'\1\2', text)
    text = re.sub(r'([a-zà-ú,])\n([a-zà-ú])', r'\1 \2', text)
    return text

def mark_sections_hardcoded(text, section_list):
    lines = text.split('\n')
    enhanced_text = []
    
    keywords = {
        "QUANTIDADE MAIOR": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "SUPERDOSE": "SUPERDOSE",
        "MALES QUE": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "COMO FUNCIONA": "COMO ESTE MEDICAMENTO FUNCIONA?",
        "ARMAZENAMENTO": "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
        "ESQUECER": "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?"
    }

    clean_titles = {re.sub(r'[^A-Z]', '', t).upper(): t for t in section_list}

    for line in lines:
        line_clean = re.sub(r'[^A-Z]', '', line).upper()
        found = None
        
        if line_clean in clean_titles:
            found = clean_titles[line_clean]
        
        if not found:
            for kw, full_t in keywords.items():
                if kw in re.sub(r'[^A-Z ]', '', line.upper()):
                    found = full_t
                    break
        
        if found:
            enhanced_text.append(f"\n\n👉👉👉 SEÇÃO IDENTIFICADA: {found} 👈👈👈\n")
        else:
            enhanced_text.append(line)
            
    return "\n".join(enhanced_text)

# ----------------- EXTRAÇÃO & MODELOS -----------------

def try_generate_content(model_name, contents, config=None):
    try:
        model = genai.GenerativeModel(model_name, generation_config=config)
        return model.generate_content(contents, safety_settings=SAFETY_SETTINGS), model_name
    except Exception as e:
        # Se for erro de "Não encontrado", ignora e tenta o próximo
        if "404" in str(e) or "not found" in str(e).lower():
            return None, None
        raise e # Erro real (autenticação, cota)

def get_robust_response(contents, prefer_flash=True, config=None):
    # LISTA EXPANDIDA DE MODELOS (Tenta todos até funcionar)
    if prefer_flash:
        candidates = [
            "gemini-1.5-flash", 
            "models/gemini-1.5-flash",
            "gemini-1.5-flash-latest", 
            "gemini-1.5-flash-001", 
            "gemini-1.5-flash-002",
            "gemini-1.0-pro",
            "gemini-pro"
        ]
    else:
        candidates = ["gemini-1.5-pro", "models/gemini-1.5-pro", "gemini-1.5-pro-latest"]

    last_error_msg = "Nenhum modelo foi tentado."
    
    for model_name in candidates:
        try:
            resp, used_model = try_generate_content(model_name, contents, config)
            if resp:
                return resp, used_model
        except Exception as e:
            last_error_msg = str(e)
            continue
            
    # Se falhar em todos, retorna o último erro real
    return None, f"Todos falharam. Último erro: {last_error_msg}"

def get_ocr_gemini(images):
    try:
        resp, _ = get_robust_response(["Transcreva TUDO. Não pule nada. Mantenha tabelas.", *images], prefer_flash=True)
        return resp.text if resp and hasattr(resp, 'text') else ""
    except: return ""

def extract_text(file, section_list):
    if not file: return None
    try:
        data = file.read()
        name = file.name.lower()
        text = ""
        
        if name.endswith('.docx'):
            text = "\n".join([p.text for p in docx.Document(io.BytesIO(data)).paragraphs])
        
        elif name.endswith('.pdf'):
            doc = fitz.open(stream=data, filetype="pdf")
            full_txt = ""
            for p in doc: full_txt += p.get_text() + "\n"
            
            if len(full_txt) / max(1, len(doc)) > 200:
                text = full_txt
                doc.close()
            else:
                st.toast(f"OCR Ativado: {name}", icon="👁️")
                imgs = []
                for i in range(min(12, len(doc))):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
                doc.close()
                text = get_ocr_gemini(imgs)

        text = clean_text(text)
        text = mark_sections_hardcoded(text, section_list)
        return text
    except: return ""

# ----------------- UI & CONFIG -----------------
def configure_api():
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        return True, "Chave Configurada"
    return False, "Chave NÃO Encontrada"

st.sidebar.title("Validador Pro")
key_status, key_msg = configure_api()

if key_status:
    st.sidebar.success(f"🔑 {key_msg}")
    # BOTÃO DE DIAGNÓSTICO
    if st.sidebar.button("🔍 Testar Chave API"):
        try:
            with st.spinner("Verificando modelos disponíveis..."):
                models = genai.list_models()
                names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
                st.sidebar.success("Modelos Ativos:")
                st.sidebar.code("\n".join(names))
        except Exception as e:
            st.sidebar.error(f"Erro ao listar modelos: {e}")
else:
    st.sidebar.error("🚫 Sem Chave API")

page = st.sidebar.radio("Navegação", ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"])

list_secs = SECOES_PACIENTE
if page == "Ref x BELFAR":
    if st.radio("Tipo de Bula", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
        list_secs = SECOES_PROFISSIONAL

st.markdown(f"## 🚀 {page}")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência")
f2 = c2.file_uploader("Candidato")

if st.button("🚀 AUDITAR AGORA"):
    if not f1 or not f2:
        st.warning("Arquivos faltando.")
        st.stop()
    
    if not key_status:
        st.error("Configure a GEMINI_API_KEY para continuar.")
        st.stop()
        
    bar = st.progress(0, "Processando...")
    
    # 1. Extração
    t1 = extract_text(f1, list_secs)
    bar.progress(30, "Referência OK")
    t2 = extract_text(f2, list_secs)
    bar.progress(60, "Candidato OK")
    
    # 2. PROMPT
    secoes_ignorar_str = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor Sênior.
    
    MISSÃO: Encontrar as seções marcadas com "👉👉👉 SEÇÃO IDENTIFICADA: ... 👈👈👈" e comparar.
    
    LISTA OBRIGATÓRIA:
    {json.dumps(list_secs, ensure_ascii=False)}

    REGRAS:
    1. Traga o texto COMPLETO.
    2. Nas seções [{secoes_ignorar_str}], APENAS COPIE. Status "OK".
    
    REGRAS VISUAIS (STYLE INLINE OBRIGATÓRIO):
    - Diferença: <span style="background-color: #ffeb3b; color: black; font-weight: bold; padding: 2px;">TEXTO ERRADO</span>
    - Erro PT: <span style="background-color: #ff1744; color: white; font-weight: bold; padding: 2px;">ERRO</span>
    - Data: <span style="background-color: #00e5ff; color: black; font-weight: bold; padding: 2px;">DATA</span>

    SAÍDA JSON:
    {{
        "METADADOS": {{ "datas": [], "produto": "" }},
        "SECOES": [
            {{
                "titulo": "TITULO DA LISTA",
                "ref": "Texto...",
                "bel": "Texto com tags...",
                "status": "OK" ou "DIVERGENTE"
            }}
        ]
    }}
    """
    
    json_res = ""
    model_name = ""
    start_t = time.time()
    
    try:
        bar.progress(70, "⚡ IA Analisando (Tentando modelos)...")
        
        prefer_flash = True
        if page == "Gráfica x Arte": prefer_flash = False
            
        resp, model_name = get_robust_response(
            [prompt, f"--- TEXTO REFERÊNCIA ---\n{t1}", f"--- TEXTO CANDIDATO ---\n{t2}"],
            prefer_flash=prefer_flash,
            config={"response_mime_type": "application/json"}
        )
        
        if resp and hasattr(resp, 'text'):
            json_res = resp.text
        else:
            st.error(f"Falha Crítica: {model_name}") # Mostra o erro real capturado
            st.stop()
            
    except Exception as e:
        st.error(f"Erro Inesperado: {e}")
        st.stop()
        
    bar.progress(100, "Concluído!")
    time.sleep(0.5)
    bar.empty()
    
    # 3. RESULTADOS
    if json_res:
        json_res = json_res.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(json_res)
        except:
            st.error("Erro no JSON da IA.")
            st.code(json_res)
            st.stop()
            
        secs = []
        raw_secs = data.get("SECOES", [])
        
        for target in list_secs:
            found = next((s for s in raw_secs if SequenceMatcher(None, target, s.get('titulo','').upper()).ratio() > 0.8), None)
            
            if found:
                found['titulo'] = target
                secs.append(found)
            else:
                secs.append({
                    "titulo": target,
                    "ref": "Não encontrado.",
                    "bel": "Não encontrado.",
                    "status": "FALTANTE"
                })

        diverg = sum(1 for s in secs if s['status'] != "OK" and s['titulo'] not in SECOES_IGNORAR_DIFF)
        
        st.markdown(f"<div class='ia-badge'>Motor: {model_name} ({time.time()-start_t:.1f}s)</div>", unsafe_allow_html=True)
        
        st.markdown("### Legenda:")
        l1, l2, l3 = st.columns(3)
        l1.markdown("<span style='background-color: #ffeb3b; color: black; font-weight: bold; padding: 2px;'>Amarelo</span> = Diferença", unsafe_allow_html=True)
        l2.markdown("<span style='background-color: #ff1744; color: white; font-weight: bold; padding: 2px;'>Vermelho</span> = Erro Ortográfico", unsafe_allow_html=True)
        l3.markdown("<span style='background-color: #00e5ff; color: black; font-weight: bold; padding: 2px;'>Azul</span> = Data Anvisa", unsafe_allow_html=True)
        st.markdown("---")

        cM1, cM2 = st.columns(2)
        cM1.metric("Seções", len(secs))
        cM2.metric("Divergências", diverg)
        
        st.divider()
        
        for s in secs:
            tit = s['titulo']
            stat = s['status']
            
            icon = "✅"
            if "DIVERGENTE" in stat: icon = "❌"
            elif "FALTANTE" in stat: icon = "🚨"
            
            if tit in SECOES_IGNORAR_DIFF:
                icon = "🔒"
                stat = "OK (Conteúdo Extraído)"
            
            aberto = (stat != "OK" and "Conteúdo" not in stat)
            
            with st.expander(f"{icon} {tit} - {stat}", expanded=aberto):
                cR, cB = st.columns(2)
                cR.markdown(f"<div class='box-content box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                cB.markdown(f"<div class='box-content box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
