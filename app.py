import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import re
import os
import time
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Pro (Anti-Erro 429)",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main { background-color: #f4f6f8; }
    .stCard { background-color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    .stButton>button { width: 100%; background-color: #28a745; color: white; font-weight: bold; border-radius: 8px; height: 50px; font-size: 16px; }
    .stButton>button:hover { background-color: #218838; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONFIGURAÇÃO API -----------------
def configure_api():
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key:
        api_key = "AIzaSyBcPfO6nlsy1vCvKW_VNofEmG7GaSdtiLE"
    
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

# ----------------- FUNÇÕES DE LIMPEZA -----------------
def clean_noise(text):
    if not text: return ""
    text = text.replace('\xa0', ' ').replace('\r', '')
    patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$',
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\s*:\s*\d{1,3}\s*[xX]\s*\d{1,3}\s*$', r'\b\d{1,3}\s*mm\b',
        r'.*Impess[ãa]o:.*', r'.*Negrito\s*[\.,]?\s*Corpo\s*\d+.*',
        r'.*artes.*belfar.*', r'.*Cor:\s*Preta.*', r'.*Papel:.*',
        r'.*Times New Roman.*', r'.*Cores?:.*', r'.*Pantone.*',
        r'.*Laetus.*', r'.*Pharmacode.*', r'^\s*BELFAR\s*$',
        r'.*CNPJ:.*', r'.*SAC:.*', r'.*Farm\. Resp\..*'
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE | re.MULTILINE)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def extract_content(file_bytes, filename):
    try:
        # 1. DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": clean_noise(text)}
        
        # 2. PDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        for page in doc: full_text += page.get_text() + "\n"
        
        # Se tem texto suficiente -> PDF NATIVO
        if len(full_text.strip()) > 200:
            doc.close()
            return {"type": "text", "data": clean_noise(full_text)}
        
        # Se não -> IMAGEM (SCAN)
        images = []
        limit_pages = min(8, len(doc)) 
        for i in range(limit_pages):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            try:
                img_data = pix.tobytes("jpeg")
                img = Image.open(io.BytesIO(img_data))
                images.append(img)
            except: pass
        doc.close()
        
        if images: return {"type": "image", "data": images}
        else: return {"type": "error", "data": "Arquivo vazio/corrompido."}

    except Exception as e:
        return {"type": "error", "data": str(e)}

# ----------------- RECORTE TEXTO (PYTHON) -----------------
def find_section_start(text, section_name):
    text_lower = text.lower()
    core_title = section_name.lower().split('?')[0]
    match = re.search(re.escape(core_title), text_lower)
    if match: return match.start()
    
    if section_name[0].isdigit():
        num = section_name.split('.')[0]
        match = re.search(rf"\n\s*{num}\.\s", text_lower)
        if match: return match.start()
    return -1

def get_section_text_python(full_text, section, all_sections):
    if not full_text: return ""
    start = find_section_start(full_text, section)
    if start == -1: return "Seção não encontrada (Texto)"
    
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

# ----------------- OCR SEGURO COM RETRY -----------------
def get_section_text_ocr(images, section):
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    
    prompt = [
        f"Transcreva o texto da seção '{section}'. Copie até a próxima seção.",
        "Se não achar, responda 'Seção não encontrada'."
    ]
    prompt.extend(images)
    
    # RETRY LOGIC (Tentativas automáticas)
    for attempt in range(3):
        try:
            resp = model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            if "429" in str(e): # Se for erro de cota
                time.sleep(20) # Espera 20s
                continue # Tenta de novo
            return f"Erro OCR: {str(e)}"
    return "Erro OCR: Limite excedido após tentativas."

# ----------------- JUIZ COM FREIO AUTOMÁTICO (RETRY) -----------------
def ai_judge_diff(ref_text, bel_text, secao):
    if len(ref_text) < 10 or len(bel_text) < 10: return "⚠️ Texto insuficiente."
    
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    
    prompt = f"""
    Comparação de Bula da ANVISA (Seção: {secao}).
    
    REF:
    {ref_text[:10000]}
    
    GRÁFICA:
    {bel_text[:10000]}
    
    Tarefa:
    1. Verifique se o conteúdo da GRÁFICA está fiel à REF.
    2. Ignore formatação. Foque em números e avisos.
    3. Responda APENAS "CONFORME" se estiver ok. Caso contrário, liste o erro.
    """
    
    # SISTEMA DE TENTATIVAS (ANTI-ERRO 429)
    for attempt in range(4): # Tenta até 4 vezes
        try:
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            if "429" in str(e): # Erro de Cota/Quota
                wait_time = 20 * (attempt + 1) # 20s, 40s, 60s...
                st.toast(f"⏳ Cota atingida. Esperando {wait_time}s para tentar seção '{secao}' de novo...", icon="⏸️")
                time.sleep(wait_time)
                continue
            return f"Erro API: {str(e)}"
            
    return "❌ Falha: Limite de cota excedido persistentemente."

# ----------------- UI -----------------
st.title("🛡️ Validador Pro (Anti-Bloqueio 429)")
st.markdown("**Status:** Protegido contra Rate Limit | **Engine:** Gemini 2.5 Flash")

if configure_api(): st.success("✅ API Conectada")
else: st.error("❌ Erro API Key")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência", key="f1")
f2 = c2.file_uploader("Gráfica", key="f2")

SECOES = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "2. COMO ESTE MEDICAMENTO FUNCIONA?",
    "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "6. COMO DEVO USAR ESTE MEDICAMENTO?",
    "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
    "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

if f1 and f2 and st.button("🚀 INICIAR AUDITORIA SEGURA"):
    with st.spinner("Lendo arquivos..."):
        d1 = extract_content(f1.getvalue(), f1.name)
        d2 = extract_content(f2.getvalue(), f2.name)
        
        m1 = "TEXTO" if d1['type'] == 'text' else "OCR"
        m2 = "TEXTO" if d2['type'] == 'text' else "OCR"
        st.info(f"Modo: {m1} vs {m2}")
        
        if d1['type'] == 'error' or d2['type'] == 'error':
            st.error("Erro na leitura.")
        else:
            prog = st.progress(0)
            
            for i, sec in enumerate(SECOES):
                # Extração
                txt_ref = get_section_text_python(d1['data'], sec, SECOES) if d1['type'] == 'text' else get_section_text_ocr(d1['data'], sec)
                txt_bel = get_section_text_python(d2['data'], sec, SECOES) if d2['type'] == 'text' else get_section_text_ocr(d2['data'], sec)
                
                # Validação
                if "não encontrada" in txt_ref and "não encontrada" in txt_bel:
                    veredito = "❌ Seção não localizada"
                    color = "orange"
                else:
                    veredito = ai_judge_diff(txt_ref, txt_bel, sec)
                    if "CONFORME" in veredito.upper() and len(veredito) < 50:
                        veredito = "✅ CONFORME"
                        color = "green"
                    else:
                        color = "red"

                with st.expander(f"{sec}", expanded=(color=="red")):
                    st.markdown(f":{color}[**{veredito}**]")
                    ca, cb = st.columns(2)
                    ca.text_area("Ref", txt_ref, height=150, key=f"r{i}")
                    cb.text_area("Gráfica", txt_bel, height=150, key=f"b{i}")
                
                prog.progress((i + 1) / len(SECOES))
                
                # PAUSA ESTRATÉGICA ENTRE SEÇÕES (FREIO)
                # Espera 5 segundos entre cada seção para evitar o bloqueio 429
                time.sleep(5)
