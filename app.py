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

# ----------------- CONFIGURAÇÃO DA CHAVE API -----------------
# Adicionei um fallback extra caso o secrets não esteja configurado
MINHA_API_KEY = st.secrets.get("GOOGLE_API_KEY", "AIzaSyBcPfO6nlsy1vCvKW_VNofEmG7GaSdtiLE")

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Pro (Auto-OCR Fallback)",
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
    .stButton>button { width: 100%; background-color: #007bff; color: white; font-weight: bold; border-radius: 8px; height: 50px; font-size: 16px; }
    .stButton>button:hover { background-color: #0056b3; }
</style>
""", unsafe_allow_html=True)

# ----------------- SETUP API -----------------
if MINHA_API_KEY:
    genai.configure(api_key=MINHA_API_KEY)

# ----------------- LEITURA DE ARQUIVO (TEXTO + IMAGENS) -----------------
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
    """
    Retorna um objeto com TEXTO e IMAGENS (para fallback).
    Structure: {'text': str, 'images': [PIL.Image], 'is_scan': bool}
    """
    try:
        # 1. DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"text": clean_noise(text), "images": [], "is_scan": False}
        
        # 2. PDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        
        # Extrai Texto
        for page in doc:
            full_text += page.get_text() + "\n"
        
        # Gera Imagens (SEMPRE gera imagens agora, para ter como Fallback)
        images = []
        limit_pages = min(8, len(doc)) 
        for i in range(limit_pages):
            page = doc[i]
            # Zoom 2.0 para OCR legível
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            try:
                img_data = pix.tobytes("jpeg")
                img = Image.open(io.BytesIO(img_data))
                images.append(img)
            except: pass
        doc.close()
        
        is_scan = len(full_text.strip()) < 200
        
        return {
            "text": clean_noise(full_text), 
            "images": images, 
            "is_scan": is_scan
        }

    except Exception as e:
        return {"error": str(e)}

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
    if start == -1: return "" # Retorna vazio para ativar o Fallback
    
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

# ----------------- OCR COM FALLBACK -----------------
def get_section_text_ocr(images, section):
    """OCR do Gemini 2.5 Flash"""
    if not images: return "Imagens não disponíveis para OCR."
    
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    
    prompt = [
        f"Transcreva o texto da seção '{section}'. Copie até a próxima seção.",
        "Se não achar, responda 'Seção não encontrada'."
    ]
    prompt.extend(images)
    
    # Retry Logic para evitar erro 429
    for attempt in range(3):
        try:
            resp = model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            if "429" in str(e): 
                time.sleep(20)
                continue
            return f"Erro OCR: {str(e)}"
    return "Erro OCR: Limite excedido."

# ----------------- JUIZ COM FREIO AUTOMÁTICO -----------------
def ai_judge_diff(ref_text, bel_text, secao):
    if len(ref_text) < 5 or len(bel_text) < 5: 
        return "⚠️ Texto insuficiente para comparação."
    
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
    
    for attempt in range(4): 
        try:
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            if "429" in str(e):
                wait_time = 15 * (attempt + 1)
                st.toast(f"⏳ Cota atingida. Pausa de {wait_time}s...", icon="⏸️")
                time.sleep(wait_time)
                continue
            return f"Erro API: {str(e)}"
    return "❌ Falha persistente na API."

# ----------------- UI -----------------
st.title("🛡️ Validador Pro (Auto-Fallback OCR)")
st.markdown("**Status:** Online | **Modo:** Híbrido Automático (Texto -> se falhar -> OCR)")

if MINHA_API_KEY: st.success("✅ API Conectada")
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

if f1 and f2 and st.button("🚀 INICIAR AUDITORIA"):
    with st.spinner("Processando arquivos..."):
        d1 = extract_content(f1.getvalue(), f1.name)
        d2 = extract_content(f2.getvalue(), f2.name)
        
        if "error" in d1 or "error" in d2:
            st.error("Erro na leitura dos arquivos.")
        else:
            prog = st.progress(0)
            
            for i, sec in enumerate(SECOES):
                
                # --- DOCUMENTO 1 (REF) ---
                # Tenta Python primeiro
                txt_ref = get_section_text_python(d1['text'], sec, SECOES)
                # Se falhar (vazio ou erro), e tiver imagens, usa OCR
                if (not txt_ref or "Seção não encontrada" in txt_ref) and d1['images']:
                    # st.toast(f"Usando OCR para Ref: {sec}") # Debug
                    txt_ref = get_section_text_ocr(d1['images'], sec)
                
                # --- DOCUMENTO 2 (GRÁFICA) ---
                txt_bel = get_section_text_python(d2['text'], sec, SECOES)
                if (not txt_bel or "Seção não encontrada" in txt_bel) and d2['images']:
                    # st.toast(f"Usando OCR para Gráfica: {sec}") # Debug
                    txt_bel = get_section_text_ocr(d2['images'], sec)

                # --- VALIDAÇÃO ---
                if (not txt_ref or "não encontrada" in txt_ref) and (not txt_bel or "não encontrada" in txt_bel):
                    veredito = "❌ Seção não localizada (nem via OCR)"
                    color = "orange"
                else:
                    veredito = ai_judge_diff(txt_ref, txt_bel, sec)
                    if "CONFORME" in veredito.upper() and len(veredito) < 50:
                        veredito = "✅ CONFORME"
                        color = "green"
                    else:
                        color = "red"

                # --- EXIBIÇÃO ---
                with st.expander(f"{sec}", expanded=(color=="red")):
                    st.markdown(f":{color}[**{veredito}**]")
                    ca, cb = st.columns(2)
                    ca.text_area("Ref (Final)", txt_ref, height=150, key=f"r{i}")
                    cb.text_area("Gráfica (Final)", txt_bel, height=150, key=f"b{i}")
                
                prog.progress((i + 1) / len(SECOES))
                time.sleep(5) # Pausa estratégica
