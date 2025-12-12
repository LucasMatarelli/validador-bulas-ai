import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import re
import os
import time
import concurrent.futures
from PIL import Image

# ----------------- CONFIGURAÇÃO DA CHAVE -----------------
MINHA_API_KEY = st.secrets.get("GOOGLE_API_KEY", "AIzaSyBcPfO6nlsy1vCvKW_VNofEmG7GaSdtiLE")

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Turbo (v15)",
    page_icon="🚀",
    layout="wide"
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

# ----------------- SETUP API -----------------
if MINHA_API_KEY:
    genai.configure(api_key=MINHA_API_KEY)

# ----------------- FUNÇÕES AUXILIARES -----------------
def normalize_for_comparison(text):
    """Remove espaços, quebras de linha e deixa minúsculo para comparação rápida"""
    if not text: return ""
    # Remove tudo que não for letra ou número
    return re.sub(r'[\W_]+', '', text).lower()

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
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"text": clean_noise(text), "images": [], "is_scan": False}
        
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        for page in doc: full_text += page.get_text() + "\n"
        
        images = []
        # Gera imagens apenas se necessário (Scan)
        if len(full_text.strip()) < 200:
            limit_pages = min(6, len(doc)) 
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                except: pass
        
        doc.close()
        is_scan = len(full_text.strip()) < 200
        return {"text": clean_noise(full_text), "images": images, "is_scan": is_scan}

    except Exception as e:
        return {"error": str(e)}

# ----------------- RECORTE PYTHON -----------------
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
    if start == -1: return ""
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

# ----------------- OCR GEMINI (Fallback) -----------------
def get_section_text_ocr(images, section):
    if not images: return "Imagens não disponíveis."
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    prompt = [f"Transcreva a seção '{section}'. Copie até a próxima seção. Se não achar, responda 'Seção não encontrada'."]
    prompt.extend(images)
    
    for attempt in range(3):
        try:
            resp = model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            if "429" in str(e): 
                time.sleep(5)
                continue
            return ""
    return ""

# ----------------- JUIZ (Com Otimização de Igualdade) -----------------
def ai_judge_diff(ref_text, bel_text, secao):
    # 1. OTIMIZAÇÃO DE VELOCIDADE: Comparação Python Direta
    # Se os textos forem tecnicamente iguais (removendo formatação), não chama a IA.
    norm_ref = normalize_for_comparison(ref_text)
    norm_bel = normalize_for_comparison(bel_text)
    
    # Se ambos têm texto e são idênticos, retorna conforme direto (Zero Custo/Tempo)
    if len(norm_ref) > 10 and norm_ref == norm_bel:
        return "✅ CONFORME (Validação Automática)"

    # 2. Se forem diferentes, chama o Juiz Gemini
    safety = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
    
    prompt = f"""
    Comparação de Bula (Seção: {secao}).
    REF: {ref_text[:10000]}
    GRÁFICA: {bel_text[:10000]}
    
    Tarefa:
    1. Ignore quebras de linha e formatação.
    2. Verifique números, unidades e avisos.
    3. Responda APENAS "CONFORME" se o sentido e dados forem iguais. Se não, liste o erro.
    """
    
    for attempt in range(3): 
        try:
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            if "429" in str(e):
                time.sleep(5 + (attempt * 5))
                continue
            return f"Erro API: {str(e)}"
    return "❌ Falha API"

# ----------------- PROCESSAMENTO PARALELO -----------------
def processar_secao_unica(sec, d1, d2, secoes_lista):
    """Função isolada para rodar em paralelo"""
    
    # 1. Extração REF
    txt_ref = get_section_text_python(d1['text'], sec, secoes_lista)
    if (not txt_ref) and d1['images']: # Fallback OCR
        txt_ref = get_section_text_ocr(d1['images'], sec)
        
    # 2. Extração BEL
    txt_bel = get_section_text_python(d2['text'], sec, secoes_lista)
    if (not txt_bel) and d2['images']: # Fallback OCR
        txt_bel = get_section_text_ocr(d2['images'], sec)

    # 3. Validação
    if not txt_ref: txt_ref = "Não encontrada"
    if not txt_bel: txt_bel = "Não encontrada"
    
    if "Não encontrada" in txt_ref and "Não encontrada" in txt_bel:
        res = "❌ Seção não localizada"
        cor = "orange"
    else:
        res = ai_judge_diff(txt_ref, txt_bel, sec)
        if "CONFORME" in res.upper() and len(res) < 60:
            res = "✅ CONFORME"
            cor = "green"
        else:
            cor = "red"
            
    return {"titulo": sec, "ref": txt_ref, "bel": txt_bel, "veredito": res, "cor": cor}

# ----------------- UI -----------------
st.title("🚀 Validador Turbo (Rápido + Scan)")

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

if f1 and f2 and st.button("🚀 INICIAR TURBO"):
    with st.spinner("Processando..."):
        d1 = extract_content(f1.getvalue(), f1.name)
        d2 = extract_content(f2.getvalue(), f2.name)
        
        if "error" in d1 or "error" in d2:
            st.error("Erro leitura.")
        else:
            # BARRA DE PROGRESSO
            bar = st.progress(0)
            results = []
            
            # PARALELISMO (3 Workers = 3x mais rápido, mas seguro pro Free Tier)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(processar_secao_unica, sec, d1, d2, SECOES): sec for sec in SECOES}
                
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    results.append(future.result())
                    bar.progress((i + 1) / len(SECOES))
            
            # ORDENAR RESULTADOS
            results.sort(key=lambda x: SECOES.index(x['titulo']))
            
            # EXIBIR
            for r in results:
                with st.expander(f"{r['titulo']}", expanded=(r['cor']=="red")):
                    st.markdown(f":{r['cor']}[**{r['veredito']}**]")
                    ca, cb = st.columns(2)
                    ca.text_area("Ref", r['ref'], height=120)
                    cb.text_area("Gráfica", r['bel'], height=120)
