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
    page_title="Validador Pro (Scan Support)",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main { background-color: #f4f6f8; }
    .stCard { background-color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    .stButton>button { width: 100%; background-color: #6f42c1; color: white; font-weight: bold; border-radius: 8px; height: 50px; font-size: 16px; }
    .stButton>button:hover { background-color: #5a32a3; }
</style>
""", unsafe_allow_html=True)

# ----------------- SETUP DA API -----------------
def configure_api():
    # Tenta pegar do secrets do Streamlit, senão usa a variável direta (fallback)
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key:
        # Fallback caso o secrets falhe
        api_key = "AIzaSyBcPfO6nlsy1vCvKW_VNofEmG7GaSdtiLE"
    
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

# ----------------- LEITURA DE ARQUIVO (TEXTO E IMAGEM) -----------------
def clean_noise(text):
    """Limpeza técnica básica"""
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
    Lê o arquivo. Retorna um dicionário indicando se é TEXTO ou IMAGEM.
    """
    try:
        # CASO 1: DOCX (Sempre texto)
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": clean_noise(text)}
        
        # CASO 2: PDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        
        # Tenta extrair texto primeiro
        for page in doc:
            full_text += page.get_text() + "\n"
        
        # Se tiver texto suficiente, ótimo!
        if len(full_text.strip()) > 100:
            doc.close()
            return {"type": "text", "data": clean_noise(full_text)}
        
        # CASO 3: SCAN (Pouco texto -> Converte para Imagens)
        images = []
        # Limitamos a 6 páginas para não estourar a API (geralmente bulas cabem nisso)
        limit_pages = min(6, len(doc))
        for i in range(limit_pages):
            page = doc[i]
            # Matrix 2.0 aumenta a qualidade (zoom) para OCR melhor
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            try:
                img_data = pix.tobytes("jpeg")
                img = Image.open(io.BytesIO(img_data))
                images.append(img)
            except: pass
        doc.close()
        
        if images:
            return {"type": "image", "data": images}
        else:
            return {"type": "error", "data": "Falha ao ler PDF."}

    except Exception as e:
        return {"type": "error", "data": str(e)}

# ----------------- RECORTE DE TEXTO (PYTHON) -----------------
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

# ----------------- RECORTE DE IMAGEM (OCR GEMINI) -----------------
def get_section_text_from_image(images, section):
    """Usa o Gemini para ler a seção específica direto das imagens"""
    
    safety = {HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, 
              HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
              HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
              HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE}
    
    model = genai.GenerativeModel('gemini-1.5-flash', safety_settings=safety)
    
    prompt = [
        f"Você é uma máquina de OCR. Sua tarefa é transcrever o texto da seção '{section}'.",
        "1. Olhe todas as imagens.",
        f"2. Encontre onde começa o título '{section}'.",
        "3. Transcreva tudo o que está abaixo desse título até encontrar o título da próxima seção.",
        "4. Se não encontrar a seção, responda apenas 'Seção não encontrada'.",
        "5. Não faça resumos. Transcrição literal."
    ]
    prompt.extend(images) # Adiciona as imagens ao prompt
    
    try:
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        return f"Erro no OCR: {str(e)}"

# ----------------- JUIZ (COMPARADOR) -----------------
def ai_judge_diff(ref_text, bel_text, secao):
    if len(ref_text) < 10 or len(bel_text) < 10: return "⚠️ Texto insuficiente."
    
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    model = genai.GenerativeModel('gemini-1.5-pro', safety_settings=safety) # Pro para julgar melhor
    
    prompt = f"""
    Atue como Auditor de Qualidade. Compare os textos da seção "{secao}".
    
    REF (Original):
    {ref_text[:15000]}
    
    GRÁFICA (Prova):
    {bel_text[:15000]}
    
    INSTRUÇÕES:
    1. Ignore formatação e quebras de linha.
    2. Se os textos dizem a mesma coisa (mesmos números, substâncias, avisos), responda "CONFORME".
    3. Se houver erro (número diferente, falta de aviso de alerta), descreva o erro.
    """
    try:
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Erro Juiz: {str(e)}"

# ----------------- UI -----------------
st.title("👁️ Validador Pro (Com Suporte a Scan)")
st.markdown("**Status:** Ativo | **Engine:** Gemini 1.5 Pro/Flash | **Modo:** Texto & Scan (OCR)")

if configure_api():
    st.success("✅ API Conectada")
else:
    st.error("❌ Erro na configuração da API Key")

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

if f1 and f2 and st.button("🚀 EXECUTAR AUDITORIA"):
    with st.spinner("Lendo documentos (Detectando se é Texto ou Scan)..."):
        # Leitura
        d1 = extract_content(f1.getvalue(), f1.name)
        d2 = extract_content(f2.getvalue(), f2.name)
        
        # Exibe modo detectado
        modo1 = "📝 TEXTO" if d1['type'] == 'text' else ("📷 SCAN (OCR)" if d1['type'] == 'image' else "❌ ERRO")
        modo2 = "📝 TEXTO" if d2['type'] == 'text' else ("📷 SCAN (OCR)" if d2['type'] == 'image' else "❌ ERRO")
        st.info(f"Modo de Leitura: Ref [{modo1}] vs Gráfica [{modo2}]")
        
        if d1['type'] == 'error' or d2['type'] == 'error':
            st.error("Erro na leitura dos arquivos.")
        else:
            prog = st.progress(0)
            
            for i, sec in enumerate(SECOES):
                # 1. Obter texto da Referência
                if d1['type'] == 'text':
                    txt_ref = get_section_text_python(d1['data'], sec, SECOES)
                else:
                    # Se for scan, usa OCR do Gemini
                    txt_ref = get_section_text_from_image(d1['data'], sec)
                
                # 2. Obter texto da Gráfica
                if d2['type'] == 'text':
                    txt_bel = get_section_text_python(d2['data'], sec, SECOES)
                else:
                    txt_bel = get_section_text_from_image(d2['data'], sec)

                # 3. Comparação (Juiz)
                # Verifica se extração falhou antes de gastar crédito de juiz
                if "não encontrada" in txt_ref and "não encontrada" in txt_bel:
                    veredito = "❌ Seção não localizada em nenhum documento"
                    color = "orange"
                else:
                    veredito_raw = ai_judge_diff(txt_ref, txt_bel, sec)
                    if "CONFORME" in veredito_raw.upper() and len(veredito_raw) < 100:
                        veredito = "✅ CONFORME"
                        color = "green"
                    else:
                        veredito = veredito_raw
                        color = "red"

                # Exibição
                with st.expander(f"{sec}", expanded=(color=="red")):
                    st.markdown(f":{color}[**{veredito}**]")
                    ca, cb = st.columns(2)
                    ca.text_area("Ref", txt_ref, height=150, key=f"r{i}")
                    cb.text_area("Gráfica", txt_bel, height=150, key=f"b{i}")
                
                prog.progress((i + 1) / len(SECOES))
