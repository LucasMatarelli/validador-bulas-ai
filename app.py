import streamlit as st
import google.generativeai as genai
from mistralai import Mistral
from google.generativeai.types import HarmCategory, HarmBlockThreshold
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
st.set_page_config(page_title="Validador Turbo Pro", layout="wide")

# ----------------- CSS (Marca-texto Forte) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; height: 55px; border-radius: 10px; border: none; }
    .stButton>button:hover { background-color: #3d8070; }
    
    .box-content { background-color: white; padding: 15px; border-radius: 8px; border: 1px solid #ddd; line-height: 1.6; color: #333; }
    .box-ref { border-left: 5px solid #757575; background-color: #f9f9f9; }
    .box-bel { border-left: 5px solid #4caf50; background-color: #f1f8e9; }
    
    /* Highlight Real */
    mark.diff { background-color: #ffeb3b; color: black; font-weight: bold; padding: 2px 4px; border-radius: 3px; display: inline; }
    mark.ort { background-color: #ff5252; color: white; font-weight: bold; padding: 2px 4px; border-radius: 3px; display: inline; }
    mark.anvisa { background-color: #00bcd4; color: white; font-weight: bold; padding: 2px 4px; border-radius: 3px; display: inline; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
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

# ----------------- INTELIGÊNCIA PYTHON (PRÉ-IA) -----------------

def fuzzy_find_titles(text, allowed_list):
    """
    O PYTHON acha as seções antes da IA. Isso garante que nada falte.
    """
    lines = text.split('\n')
    enhanced_text = []
    
    # Mapa de palavras-chave para títulos longos que a IA erra
    keyword_map = {
        "QUANTIDADE MAIOR": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "SUPERDOSE": "SUPERDOSE",
        "MALES QUE ESTE": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?"
    }

    for line in lines:
        clean_line = re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ ]', '', line.upper()).strip()
        matched_title = None

        # 1. Tenta Match Exato/Fuzzy na lista oficial
        for title in allowed_list:
            clean_title = re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ ]', '', title.upper()).strip()
            # Se a linha for parecida com o título
            ratio = SequenceMatcher(None, clean_line, clean_title).ratio()
            if ratio > 0.85 or (len(clean_line) > 10 and clean_title in clean_line):
                matched_title = title
                break
        
        # 2. Tenta Palavras-Chave (Salva-vidas para títulos longos)
        if not matched_title:
            for kw, full_title in keyword_map.items():
                if kw in clean_line:
                    matched_title = full_title
                    break
        
        if matched_title:
            # INSERE MARCADOR PARA A IA NÃO SE PERDER
            enhanced_text.append(f"\n\n>>> SEÇÃO MESTRE: {matched_title} <<<\n")
        else:
            enhanced_text.append(line)
            
    return "\n".join(enhanced_text)

# ----------------- EXTRAÇÃO -----------------
def get_ocr_gemini(images):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(["Transcreva TUDO. Não pule nada.", *images])
        return resp.text if resp.text else ""
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
            
            if len(full_txt)/max(1,len(doc)) > 200:
                text = full_txt
                doc.close()
            else:
                imgs = []
                for i in range(min(12, len(doc))):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
                doc.close()
                text = get_ocr_gemini(imgs)

        # APLICA A INTELIGÊNCIA PYTHON
        return fuzzy_find_titles(text, section_list)
        
    except: return ""

# ----------------- UI & IA -----------------

def get_config():
    k1 = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    k2 = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if k2: genai.configure(api_key=k2)
    return (Mistral(api_key=k1) if k1 else None), (k2 is not None)

mistral, gemini_ok = get_config()

st.sidebar.title("Validador Pro")
page = st.sidebar.radio("Opção", ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"])
list_secs = SECOES_PACIENTE
if page == "Ref x BELFAR":
    if st.radio("Tipo", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
        list_secs = SECOES_PROFISSIONAL

st.markdown(f"## 🚀 {page}")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência")
f2 = c2.file_uploader("Candidato")

if st.button("🚀 AUDITAR AGORA"):
    if not f1 or not f2 or not mistral:
        st.error("Arquivos ou API Mistral faltando.")
        st.stop()
        
    bar = st.progress(0, "Processando...")
    t1 = extract_text(f1, list_secs)
    bar.progress(40, "Ref OK")
    t2 = extract_text(f2, list_secs)
    bar.progress(80, "Cand OK")
    
    # PROMPT BLINDADO PARA MISTRAL TURBO
    prompt = f"""Você é um Auditor JSON.
    
    SUA MISSÃO: Encontrar as seções marcadas com ">>> SEÇÃO MESTRE: ... <<<" e comparar os textos.
    
    REGRAS DE OURO:
    1. EXAUSTIVIDADE: Se o marcador ">>> SEÇÃO MESTRE" existe no texto, ele TEM QUE ESTAR NO JSON.
    2. HTML OBRIGATÓRIO: Use tags HTML <mark class='diff'>...</mark> para mostrar as diferenças no texto do Candidato (Bel).
    
    LISTA DE SEÇÕES ESPERADAS:
    {json.dumps(list_secs, ensure_ascii=False)}

    FORMATO JSON DE SAÍDA:
    {{
        "METADADOS": {{ "datas": [], "produto": "" }},
        "SECOES": [
            {{
                "titulo": "TITULO EXATO DA LISTA",
                "ref": "Texto da referência...",
                "bel": "Texto do candidato COM <mark class='diff'>TAGS</mark>...",
                "status": "DIVERGENTE"
            }}
        ]
    }}
    """
    
    try:
        # Usa Mistral Small (Turbo) com Streaming
        st.toast("IA Analisando...", icon="🤖")
        stream = mistral.chat.stream(
            model="mistral-small-latest",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"REF:\n{t1}\n\nCAND:\n{t2}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        full_resp = ""
        for chunk in stream:
            if chunk.data.choices[0].delta.content:
                full_resp += chunk.data.choices[0].delta.content
        
        # Parse
        try:
            data = json.loads(full_resp)
        except:
            # Tenta limpar markdown se houver
            clean = full_resp.replace("```json", "").replace("```", "")
            data = json.loads(clean)
            
        # Render
        bar.progress(100)
        time.sleep(0.5)
        bar.empty()
        
        secs = data.get("SECOES", [])
        diverg = 0
        
        # Ordena para garantir que a ordem da lista seja respeitada
        secs.sort(key=lambda x: list_secs.index(x['titulo']) if x['titulo'] in list_secs else 999)
        
        for s in secs:
            if s['status'] != "OK" and s['titulo'] not in SECOES_IGNORAR_DIFF: diverg += 1
            
        col1, col2 = st.columns(2)
        col1.metric("Seções", len(secs))
        col2.metric("Divergências", diverg)
        
        for s in secs:
            # Lógica visual simples e direta
            icon = "✅"
            if "DIVERGENTE" in s['status']: icon = "❌"
            elif "FALTANTE" in s['status']: icon = "🚨"
            
            if s['titulo'] in SECOES_IGNORAR_DIFF:
                icon = "🔒"
                s['status'] = "OK (Conteúdo Extraído)"
            
            with st.expander(f"{icon} {s['titulo']} - {s['status']}"):
                cR, cB = st.columns(2)
                cR.markdown(f"**Referência:**\n<div class='box-content box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                # O segredo do highlight: allow_html=True
                cB.markdown(f"**Candidato:**\n<div class='box-content box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                
    except Exception as e:
        st.error(f"Erro: {e}")
        st.write(full_resp if 'full_resp' in locals() else "")
