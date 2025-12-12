import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import unicodedata

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Validador Pro (Gemini 2.5)", page_icon="🧠", layout="wide")

# ----------------- CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main { background-color: #f4f6f8; }
    .stCard { background-color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    .stButton>button { width: 100%; background-color: #6f42c1; color: white; font-weight: bold; } /* Roxo para Pro */
</style>
""", unsafe_allow_html=True)

# ----------------- CONFIGURAÇÃO GEMINI -----------------
def configure_gemini():
    api_key = None
    try: api_key = st.secrets["GOOGLE_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

# ----------------- EXTRAÇÃO PURA (REGEX/PYTHON) -----------------
def clean_noise(text):
    if not text: return ""
    text = text.replace('\xa0', ' ').replace('\r', '')
    # Remove lixo técnico
    patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$',
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\s*:\s*\d{1,3}\s*[xX]\s*\d{1,3}\s*$', 
        r'\b\d{1,3}\s*mm\b', r'\b\d{1,3}\s*cm\b',
        r'.*:\s*19\s*,\s*0\s*x\s*45\s*,\s*0.*',
        r'^\s*\d{1,3}\s*,\s*00\s*$',
        r'.*Impess[ãa]o:.*', r'.*Negrito\s*[\.,]?\s*Corpo\s*\d+.*',
        r'.*artes.*belfar.*', r'.*Cor:\s*Preta.*', r'.*Papel:.*',
        r'.*Times New Roman.*', r'.*Cores?:.*', r'.*Pantone.*',
        r'.*Laetus.*', r'.*Pharmacode.*', r'^\s*BELFAR\s*$',
        r'.*CNPJ:.*', r'.*SAC:.*', r'.*Farm\. Resp\..*'
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE | re.MULTILINE)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def extract_full_text(file_bytes, filename):
    try:
        text = ""
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
        else:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc: text += page.get_text() + "\n"
        
        if len(text) < 100: return None # Imagem detectada
        return clean_noise(text)
    except: return None

# ----------------- SMART SLICE -----------------
def find_section_start(text, section_name):
    text_lower = text.lower()
    match = re.search(re.escape(section_name.lower().split('?')[0]), text_lower)
    if match: return match.start()
    
    # Fallback numérico
    if section_name[0].isdigit():
        num = section_name.split('.')[0]
        match = re.search(rf"\n\s*{num}\.\s", text_lower)
        if match: return match.start()
    return -1

def get_section_text(full_text, section, all_sections):
    if not full_text: return "Texto não detectado (Scan/Imagem?)"
    start = find_section_start(full_text, section)
    if start == -1: return "Seção não encontrada"
    
    end = len(full_text)
    try:
        idx = all_sections.index(section)
        for i in range(idx+1, len(all_sections)):
            next_start = find_section_start(full_text, all_sections[i])
            if next_start > start:
                end = next_start
                break
    except: pass
    
    return full_text[start:end].strip()

# ----------------- IA JUIZ (GEMINI 2.5 PRO) -----------------
def ai_judge_diff(ref_text, bel_text, secao):
    if len(ref_text) < 10 or len(bel_text) < 10: return "⚠️ Texto insuficiente."
    
    # Configurações de segurança no ZERO
    safety = {
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    # MUDANÇA CRÍTICA: Chamando o modelo 2.5 Pro
    # Model ID: gemini-2.5-pro (Estável)
    model = genai.GenerativeModel('gemini-2.5-pro', safety_settings=safety)
    
    prompt = f"""
    Tarefa: Auditoria de Conformidade de Bula (ANVISA).
    Seção: "{secao}"
    
    Texto A (Referência/Arte):
    {ref_text[:20000]}
    
    Texto B (Gráfica/Prova):
    {bel_text[:20000]}
    
    INSTRUÇÕES DE RACIOCÍNIO:
    1. Compare o conteúdo semântico e técnico.
    2. Ignore quebras de linha ou formatação.
    3. Foque em: Números, Unidades (mg, ml), Nomes de substâncias, Avisos de alerta (Negrito/Atenção).
    
    SAÍDA:
    Se idêntico: Responda apenas "CONFORME".
    Se diferente: Liste as diferenças cruciais de forma resumida.
    """
    
    try:
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Erro 2.5 Pro: {str(e)}"

# ----------------- UI -----------------
st.title("🧠 Validador Pro (Engine: Gemini 2.5 Pro)")
st.caption("Usando o modelo mais inteligente do Google para 'pensar' antes de comparar.")

if configure_gemini(): st.success("✅ Gemini 2.5 Pro Online")
else: st.error("❌ Configure GOOGLE_API_KEY")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência", key="f1")
f2 = c2.file_uploader("Gráfica", key="f2")

SECOES_PACIENTE = [
    "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "2. COMO ESTE MEDICAMENTO FUNCIONA?",
    "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "6. COMO DEVO USAR ESTE MEDICAMENTO?",
    "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
    "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"
]

if f1 and f2 and st.button("🔍 EXECUTAR AUDITORIA PRO"):
    with st.spinner("Extraindo textos e raciocinando... (Isso pode levar alguns segundos a mais que o Flash)"):
        t1 = extract_full_text(f1.getvalue(), f1.name)
        t2 = extract_full_text(f2.getvalue(), f2.name)
        
        if not t1 or not t2:
            st.error("🚨 Imagem detectada. Este modo precisa de texto selecionável.")
        else:
            prog = st.progress(0)
            for i, sec in enumerate(SECOES_PACIENTE):
                txt_ref = get_section_text(t1, sec, SECOES_PACIENTE)
                txt_bel = get_section_text(t2, sec, SECOES_PACIENTE)
                
                veredito = "..."
                if "Seção não encontrada" in txt_ref:
                     veredito = "❌ Seção não localizada (Ref)"
                     color = "orange"
                elif "Seção não encontrada" in txt_bel:
                     veredito = "❌ Seção não localizada (Gráfica)"
                     color = "orange"
                else:
                     analise = ai_judge_diff(txt_ref, txt_bel, sec)
                     if "CONFORME" in analise.upper() and len(analise) < 60:
                         veredito = "✅ CONFORME"
                         color = "green"
                     else:
                         veredito = analise
                         color = "red"

                with st.expander(f"{sec}", expanded=(color=="red")):
                    st.markdown(f":{color}[**VEREDITO: {veredito}**]")
                    c_a, c_b = st.columns(2)
                    c_a.text_area("Ref (Extracao Python)", txt_ref, height=150)
                    c_b.text_area("Gráfica (Extracao Python)", txt_bel, height=150)
                
                prog.progress((i + 1) / len(SECOES_PACIENTE))
