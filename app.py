import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import re
import os
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Pro (Gemini 2.5)",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CSS PARA VISUAL LIMPO -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main { background-color: #f4f6f8; }
    .stCard { background-color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    .stButton>button { width: 100%; background-color: #007bff; color: white; font-weight: bold; border-radius: 8px; height: 50px; font-size: 16px; }
    .stButton>button:hover { background-color: #0056b3; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONFIGURAÇÃO DA API -----------------
def configure_api():
    # Tenta pegar do secrets ou usa a chave direta (Fallback)
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key:
        api_key = "AIzaSyBcPfO6nlsy1vCvKW_VNofEmG7GaSdtiLE" # Sua chave
    
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

# ----------------- FUNÇÕES DE LIMPEZA E LEITURA -----------------
def clean_noise(text):
    """Limpeza técnica básica para remover lixo de PDF"""
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
    Lê o arquivo e decide se é TEXTO (PDF Nativo) ou IMAGEM (Scan).
    Retorna: {'type': 'text', 'data': str} OU {'type': 'image', 'data': [PIL.Image]}
    """
    try:
        # 1. DOCX (Sempre Texto)
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": clean_noise(text)}
        
        # 2. PDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        
        # Tenta extrair texto
        for page in doc:
            full_text += page.get_text() + "\n"
        
        # SE TIVER TEXTO SUFICIENTE -> É PDF NATIVO
        if len(full_text.strip()) > 200:
            doc.close()
            return {"type": "text", "data": clean_noise(full_text)}
        
        # SE NÃO TIVER TEXTO -> É SCAN (IMAGEM)
        # Converte páginas para imagens para o Gemini ler
        images = []
        limit_pages = min(8, len(doc)) # Lê até 8 páginas para não estourar memória
        for i in range(limit_pages):
            page = doc[i]
            # Matrix 2.0 melhora resolução para OCR
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
            return {"type": "error", "data": "Falha ao processar arquivo (vazio ou corrompido)."}

    except Exception as e:
        return {"type": "error", "data": str(e)}

# ----------------- RECORTE (PYTHON TEXTO) -----------------
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

# ----------------- OCR (GEMINI LÊ IMAGEM) -----------------
def get_section_text_ocr(images, section):
    """
    Usa o Gemini 2.5 Flash para ler a seção direto da imagem (Scan).
    """
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    
    # MODELO ATUALIZADO: 2.5 Flash
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    
    prompt = [
        f"Você é um especialista em OCR. Transcreva APENAS o texto da seção '{section}'.",
        "1. Procure nas imagens onde esta seção começa.",
        "2. Copie todo o texto dela até encontrar o título da próxima seção.",
        "3. Se não achar, responda 'Seção não encontrada'.",
        "4. Não invente nada. Cópia literal."
    ]
    prompt.extend(images) # Envia as imagens junto
    
    try:
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        return f"Erro OCR: {str(e)}"

# ----------------- JUIZ (COMPARADOR) -----------------
def ai_judge_diff(ref_text, bel_text, secao):
    if len(ref_text) < 10 or len(bel_text) < 10: return "⚠️ Texto insuficiente para análise."
    
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    
    # MODELO ATUALIZADO: 2.5 Flash (Rápido e Eficiente)
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    
    prompt = f"""
    Atue como Auditor da ANVISA. Compare os dois textos da seção "{secao}".
    
    REF (Original):
    {ref_text[:15000]}
    
    GRÁFICA (Prova):
    {bel_text[:15000]}
    
    INSTRUÇÕES:
    1. O texto da Gráfica deve seguir o conteúdo da Referência.
    2. Ignore formatação (quebras de linha, espaços).
    3. Verifique números, unidades (mg, ml) e avisos de alerta.
    4. Se estiver tudo certo, responda APENAS: "CONFORME".
    5. Se houver erro, liste apenas o que está diferente.
    """
    try:
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Erro Juiz: {str(e)}"

# ----------------- UI PRINCIPAL -----------------
st.title("👁️ Validador Pro (Gemini 2.5)")
st.markdown("**Status:** Online | **Engine:** Gemini 2.5 Flash | **Suporte:** PDF Texto & Scan")

if configure_api():
    st.success("✅ API Conectada")
else:
    st.error("❌ Erro na API Key")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência (Word/PDF)", key="f1")
f2 = c2.file_uploader("Gráfica (Scan/PDF)", key="f2")

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
    with st.spinner("Analisando documentos..."):
        # 1. Leitura Inteligente (Detecta Texto ou Imagem)
        d1 = extract_content(f1.getvalue(), f1.name)
        d2 = extract_content(f2.getvalue(), f2.name)
        
        # Mostra o modo detectado
        m1 = "TEXTO" if d1['type'] == 'text' else "SCAN (OCR)"
        m2 = "TEXTO" if d2['type'] == 'text' else "SCAN (OCR)"
        st.info(f"Modo: Ref [{m1}] vs Gráfica [{m2}]")
        
        if d1['type'] == 'error' or d2['type'] == 'error':
            st.error("Erro ao ler arquivos. Tente novamente.")
        else:
            prog = st.progress(0)
            
            for i, sec in enumerate(SECOES):
                # Extração Ref
                if d1['type'] == 'text':
                    txt_ref = get_section_text_python(d1['data'], sec, SECOES)
                else:
                    txt_ref = get_section_text_ocr(d1['data'], sec)
                
                # Extração Gráfica
                if d2['type'] == 'text':
                    txt_bel = get_section_text_python(d2['data'], sec, SECOES)
                else:
                    txt_bel = get_section_text_ocr(d2['data'], sec)
                
                # Validação (Juiz)
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

                # Exibição
                with st.expander(f"{sec}", expanded=(color=="red")):
                    st.markdown(f":{color}[**{veredito}**]")
                    ca, cb = st.columns(2)
                    ca.text_area("Ref", txt_ref, height=150, key=f"r{i}")
                    cb.text_area("Gráfica", txt_bel, height=150, key=f"b{i}")
                
                prog.progress((i + 1) / len(SECOES))
