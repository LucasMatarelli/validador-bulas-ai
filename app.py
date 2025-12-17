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
st.set_page_config(
    page_title="Validador Pro (Mistral Large)",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CSS GERAL -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    .stButton>button { 
        width: 100%; 
        background-color: #2e7d32; 
        color: white; 
        font-weight: bold; 
        height: 60px; 
        border-radius: 8px; 
        font-size: 18px;
        border: none; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: all 0.3s;
    }
    .stButton>button:hover { background-color: #1b5e20; transform: translateY(-2px); }
    
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
        background-color: #e3f2fd;
        color: #0d47a1;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.85em;
        margin-bottom: 10px;
        display: inline-block;
        border: 1px solid #90caf9;
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

SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- INTELIGÊNCIA PYTHON (PRÉ-PROCESSAMENTO) -----------------

def clean_text(text):
    """Remove quebras de linha ruins de colunas"""
    # Une palavras quebradas por hífen (ex: medica- mento)
    text = re.sub(r'([a-zà-ú])- \n([a-zà-ú])', r'\1\2', text)
    # Une frases quebradas abruptamente
    text = re.sub(r'([a-zà-ú,])\n([a-zà-ú])', r'\1 \2', text)
    return text

def mark_sections_hardcoded(text, section_list):
    """
    ESSENCIAL: O Python acha os títulos e coloca marcadores gigantes.
    Isso impede que o Mistral Large perca tempo procurando.
    """
    lines = text.split('\n')
    enhanced_text = []
    
    # Mapa de palavras-chave para títulos longos que costumam falhar
    keywords = {
        "QUANTIDADE MAIOR": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "SUPERDOSE": "SUPERDOSE",
        "MALES QUE": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "COMO FUNCIONA": "COMO ESTE MEDICAMENTO FUNCIONA?",
        "ARMAZENAMENTO": "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO"
    }

    clean_titles = {re.sub(r'[^A-Z]', '', t).upper(): t for t in section_list}

    for line in lines:
        line_clean = re.sub(r'[^A-Z]', '', line).upper()
        found = None
        
        # 1. Busca Exata
        if line_clean in clean_titles:
            found = clean_titles[line_clean]
        
        # 2. Busca por Palavras-Chave (Salva-vidas)
        if not found:
            for kw, full_t in keywords.items():
                if kw in re.sub(r'[^A-Z ]', '', line.upper()):
                    found = full_t
                    break
        
        if found:
            # INSERE MARCADOR DESTRUTIVO PARA A IA VER
            enhanced_text.append(f"\n\n👉👉👉 SEÇÃO IDENTIFICADA: {found} 👈👈👈\n")
        else:
            enhanced_text.append(line)
            
    return "\n".join(enhanced_text)

# ----------------- EXTRAÇÃO -----------------
def get_ocr_gemini(images):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(["Transcreva TUDO. Não pule nada. Mantenha tabelas.", *images], safety_settings=SAFETY)
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
            
            # Se tiver texto selecionável
            if len(full_txt) / max(1, len(doc)) > 200:
                text = full_txt
                doc.close()
            else:
                # OCR Rápido
                st.toast(f"OCR Ativado: {name}", icon="👁️")
                imgs = []
                for i in range(min(12, len(doc))):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
                doc.close()
                text = get_ocr_gemini(imgs)

        # Limpeza e Marcação
        text = clean_text(text)
        text = mark_sections_hardcoded(text, section_list)
        return text
    except: return ""

# ----------------- UI & CONFIG -----------------
def get_config():
    k1 = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    k2 = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if k2: genai.configure(api_key=k2)
    return (Mistral(api_key=k1) if k1 else None), (k2 is not None)

mistral, gemini_ok = get_config()

st.sidebar.title("Validador Pro")
page = st.sidebar.radio("Navegação", ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"])

list_secs = SECOES_PACIENTE
if page == "Ref x BELFAR":
    if st.radio("Tipo de Bula", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
        list_secs = SECOES_PROFISSIONAL

st.markdown(f"## 🚀 {page}")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência")
f2 = c2.file_uploader("Candidato")

if st.button("🚀 AUDITAR COM MISTRAL FORTE"):
    if not f1 or not f2:
        st.warning("Arquivos faltando.")
        st.stop()
    
    if page in ["Ref x BELFAR", "Conferência MKT"] and not mistral:
        st.error("Chave Mistral não encontrada.")
        st.stop()
        
    bar = st.progress(0, "Processando...")
    
    # 1. Extração
    t1 = extract_text(f1, list_secs)
    bar.progress(30, "Referência OK")
    t2 = extract_text(f2, list_secs)
    bar.progress(60, "Candidato OK")
    
    # 2. PROMPT BLINDADO (Com Style Inline Obrigatório)
    secoes_ignorar_str = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor Sênior de Bulas.
    
    MISSÃO: Encontrar as seções marcadas com "👉👉👉 SEÇÃO IDENTIFICADA: ... 👈👈👈" e comparar os textos.
    
    LISTA DE SEÇÕES OBRIGATÓRIAS (Você deve preencher todas no JSON):
    {json.dumps(list_secs, ensure_ascii=False)}

    REGRAS DE CONTEÚDO:
    1. Traga o texto COMPLETO. Não resuma.
    2. Nas seções [{secoes_ignorar_str}], APENAS COPIE o texto. Status "OK".
    
    REGRAS VISUAIS (MARCA-TEXTO OBRIGATÓRIO):
    Nas divergências, você NÃO PODE usar classes CSS. Você DEVE usar o atributo STYLE inline.
    
    Use EXATAMENTE estes códigos HTML:
    - Diferença: <span style="background-color: #ffeb3b; color: black; font-weight: bold; padding: 2px;">TEXTO ERRADO</span>
    - Erro Ortográfico: <span style="background-color: #ff1744; color: white; font-weight: bold; padding: 2px;">ERRO</span>
    - Data Anvisa: <span style="background-color: #00e5ff; color: black; font-weight: bold; padding: 2px;">DATA</span>

    SAÍDA JSON:
    {{
        "METADADOS": {{ "datas": [], "produto": "" }},
        "SECOES": [
            {{
                "titulo": "TITULO EXATO DA LISTA",
                "ref": "Texto referência...",
                "bel": "Texto candidato com tags <span>...",
                "status": "OK" ou "DIVERGENTE"
            }}
        ]
    }}
    """
    
    json_res = ""
    model_name = ""
    start_t = time.time()
    
    try:
        if page in ["Ref x BELFAR", "Conferência MKT"]:
            # MISTRAL LARGE (O Forte) com Streaming para não travar
            model_name = "Mistral Large (Latest)"
            bar.progress(70, "🧠 Mistral Large Analisando (Streaming)...")
            
            stream = mistral.chat.stream(
                model="mistral-large-latest", # O mais forte
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"REF:\n{t1}\n\nCAND:\n{t2}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout_ms=600000 # 10 min de timeout (streaming segura a conexão)
            )
            
            chunks = []
            for chunk in stream:
                if chunk.data.choices[0].delta.content:
                    chunks.append(chunk.data.choices[0].delta.content)
            json_res = "".join(chunks)

        else: # Gemini para Gráfica
            if not gemini_ok: st.error("Gemini Key missing"); st.stop()
            model_name = "Gemini 1.5 Pro"
            bar.progress(70, "💎 Gemini Analisando...")
            resp = genai.GenerativeModel("gemini-1.5-pro").generate_content(
                f"{prompt}\n\nREF:\n{t1}\n\nCAND:\n{t2}",
                generation_config={"response_mime_type": "application/json"}
            )
            json_res = resp.text
            
    except Exception as e:
        st.error(f"Erro IA: {e}")
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
            st.error("Erro no JSON da IA. Tente novamente.")
            st.stop()
            
        secs = []
        raw_secs = data.get("SECOES", [])
        
        # Reconstrói a lista garantindo a ordem
        for target in list_secs:
            # Procura na resposta
            found = next((s for s in raw_secs if SequenceMatcher(None, target, s.get('titulo','').upper()).ratio() > 0.8), None)
            
            if found:
                found['titulo'] = target
                secs.append(found)
            else:
                secs.append({
                    "titulo": target,
                    "ref": "Não encontrado / Não identificado.",
                    "bel": "Não encontrado / Não identificado.",
                    "status": "FALTANTE"
                })

        diverg = sum(1 for s in secs if s['status'] != "OK" and s['titulo'] not in SECOES_IGNORAR_DIFF)
        
        st.markdown(f"<div class='ia-badge'>Motor: {model_name} ({time.time()-start_t:.1f}s)</div>", unsafe_allow_html=True)
        
        # Legenda Manual (já que agora é inline style)
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
