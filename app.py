import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import re
import os
import time
import unicodedata
import concurrent.futures
from PIL import Image

# ----------------- CONFIGURAÇÃO API -----------------
# Tenta pegar dos secrets ou usa a variável direta
API_KEY = st.secrets.get("GOOGLE_API_KEY")

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Farmacêutico AI",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS PREMIUM -----------------
st.markdown("""
<style>
    /* Reset e Fontes */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    
    /* Remove barra superior padrão */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 2rem !important; }
    
    /* Cards de Resultado */
    .result-card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 16px;
        transition: all 0.3s ease;
    }
    .result-card:hover { box-shadow: 0 6px 16px rgba(0,0,0,0.08); }
    
    /* Status Badges */
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    .badge-success { background-color: #d1fae5; color: #065f46; border: 1px solid #a7f3d0; }
    .badge-error { background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
    .badge-warning { background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    
    /* Botão Principal */
    .stButton>button {
        width: 100%;
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
        font-weight: 700;
        border: none;
        border-radius: 10px;
        height: 56px;
        font-size: 16px;
        box-shadow: 0 4px 6px rgba(16, 185, 129, 0.2);
        transition: transform 0.1s;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(16, 185, 129, 0.3);
    }
    
    /* Text Areas */
    .stTextArea textarea {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        font-family: 'Menlo', 'Monaco', monospace;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES DE SEÇÃO -----------------
SECOES_PACIENTE = [
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

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA",
    "3. CARACTERÍSTICAS FARMACOLÓGICAS", "4. CONTRAINDICAÇÕES",
    "5. ADVERTÊNCIAS E PRECAUÇÕES", "6. INTERAÇÕES MEDICAMENTOSAS",
    "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "8. POSOLOGIA E MODO DE USAR",
    "9. REAÇÕES ADVERSAS", "10. SUPERDOSE", "DIZERES LEGAIS"
]

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- CONFIGURAÇÃO GEMINI -----------------
if API_KEY:
    genai.configure(api_key=API_KEY)

def get_gemini_model():
    # Tenta o modelo mais novo primeiro
    modelos = ['gemini-2.0-flash-exp', 'gemini-1.5-flash']
    for m in modelos:
        try:
            test_model = genai.GenerativeModel(m)
            return test_model
        except: continue
    return genai.GenerativeModel('gemini-1.5-flash')

# ----------------- EXTRAÇÃO INTELIGENTE (SEM COPYRIGHT) -----------------
def clean_noise(text):
    """Remove sujeira técnica de gráfica"""
    if not text: return ""
    text = text.replace('\xa0', ' ').replace('\r', '')
    patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$',
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\s*:\s*\d{1,3}\s*[xX]\s*\d{1,3}\s*$', r'\b\d{1,3}\s*mm\b',
        r'.*Impess[ãa]o:.*', r'.*Negrito\s*[\.,]?\s*Corpo\s*\d+.*',
        r'.*artes.*belfar.*', r'.*Cor:\s*Preta.*', r'.*Papel:.*',
        r'.*Times New Roman.*', r'.*Cores?:.*', r'.*Pharmacode.*', 
        r'^\s*BELFAR\s*$', r'.*CNPJ:.*', r'.*SAC:.*'
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE | re.MULTILINE)
    return text.strip()

def extract_content(file_bytes, filename):
    """Lê PDF/DOCX e retorna Texto + Imagens (para fallback)"""
    try:
        # DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"text": clean_noise(text), "images": [], "is_scan": False}
        
        # PDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text = ""
        for page in doc: full_text += page.get_text() + "\n"
        
        # Gera imagens para fallback OCR
        images = []
        limit = min(8, len(doc))
        for i in range(limit):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            try: images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            except: pass
        doc.close()
        
        return {"text": clean_noise(full_text), "images": images, "is_scan": len(full_text) < 200}
    except Exception as e:
        return {"error": str(e)}

# ----------------- RECORTE DE SEÇÃO (Regex Flexível) -----------------
def normalize_text(text):
    if not text: return ""
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII').lower()

def find_section_start(text, section_name):
    text_norm = normalize_text(text)
    
    # 1. Busca Título Exato Normalizado
    core_name = section_name.lower().split('?')[0]
    core_norm = normalize_text(core_name)
    match = re.search(re.escape(core_norm), text_norm)
    if match: return match.start()
    
    # 2. Busca por Número (ex: "1. ")
    if section_name[0].isdigit():
        num = section_name.split('.')[0]
        match = re.search(rf"\n\s*{num}\.?\s", text_norm)
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

# ----------------- AI WORKERS (JUIZ & OCR) -----------------
def get_section_text_ocr(images, section):
    """Usa IA apenas se o Python falhar (Fallback)"""
    if not images: return ""
    
    model = get_gemini_model()
    # Prompt de extração técnica para evitar copyright
    prompt = [f"Extraia tecnicamente o texto da seção '{section}' para análise de conformidade regulatória. Copie até o próximo título. Se não achar, retorne vazio."]
    prompt.extend(images)
    
    try: return model.generate_content(prompt).text.strip()
    except: return ""

def ai_judge_diff(ref, bel, secao):
    """
    IA atua como JUIZ. 
    Ela NÃO gera o texto (evita copyright), ela apenas ANALISA a diferença.
    """
    # Comparação rápida Python (Custo Zero)
    if normalize_text(ref) == normalize_text(bel):
        return "✅ CONFORME (Auto)"

    model = get_gemini_model()
    prompt = f"""
    Atue como Auditor de Qualidade Farmacêutica.
    
    TAREFA: Comparar o conteúdo das duas bulas abaixo (Seção: {secao}).
    
    TEXTO REFERÊNCIA:
    {ref[:15000]}
    
    TEXTO GRÁFICA:
    {bel[:15000]}
    
    INSTRUÇÕES:
    1. Ignore formatação, quebras de linha e maiúsculas/minúsculas.
    2. Foque em: Números (mg, ml), nomes de substâncias e AVISOS DE SEGURANÇA.
    3. Se o sentido e os dados técnicos forem iguais, responda APENAS: "CONFORME".
    4. Se houver diferença crítica, liste-a resumidamente.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Erro IA: {str(e)}"

# ----------------- LÓGICA PRINCIPAL -----------------
def processar_secao(sec, d1, d2, lista):
    # 1. Tenta Python
    txt_ref = get_section_text_python(d1['text'], sec, lista)
    # 2. Se falhar, tenta OCR (Fallback)
    if (not txt_ref or len(txt_ref) < 10) and d1['images']: 
        txt_ref = get_section_text_ocr(d1['images'], sec)
    
    txt_bel = get_section_text_python(d2['text'], sec, lista)
    if (not txt_bel or len(txt_bel) < 10) and d2['images']: 
        txt_bel = get_section_text_ocr(d2['images'], sec)
    
    # 3. Validação
    if not txt_ref: txt_ref = "Não encontrada"
    if not txt_bel: txt_bel = "Não encontrada"
    
    if "Não encontrada" in txt_ref and "Não encontrada" in txt_bel:
        res = "❌ Seção não localizada"
        cor = "badge-warning"
    else:
        res = ai_judge_diff(txt_ref, txt_bel, sec)
        if "CONFORME" in res.upper() and len(res) < 50:
            res = "CONFORME"
            cor = "badge-success"
        else:
            cor = "badge-error"
            
    return {"titulo": sec, "ref": txt_ref, "bel": txt_bel, "veredito": res, "cor": cor}

# ----------------- UI FRON-END -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.title("Validador")
    st.caption("v18.0 | Engine: Gemini 2.0 Flash")
    
    if not API_KEY:
        st.error("⚠️ Chave API não configurada!")
    else:
        st.success("✅ Sistema Online")
        
    st.divider()
    tipo_bula = st.radio("Tipo de Bula", ["Paciente", "Profissional"])
    modo_scan = st.toggle("Forçar Modo OCR (Lento)", value=False, help="Ative se o PDF for imagem e não estiver lendo.")

st.markdown("### 🚀 Nova Auditoria")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Documento de Referência (Word/PDF)", key="f1")
f2 = c2.file_uploader("Documento da Gráfica (PDF/Scan)", key="f2")

if f1 and f2 and st.button("INICIAR VALIDAÇÃO INTELIGENTE"):
    secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL
    
    with st.spinner("🔍 Analisando documentos e comparando textos..."):
        d1 = extract_content(f1.getvalue(), f1.name)
        d2 = extract_content(f2.getvalue(), f2.name)
        
        if "error" in d1 or "error" in d2:
            st.error("Erro ao ler arquivos. Verifique se estão corrompidos.")
        else:
            # Se usuário forçou OCR, apaga o texto extraído para obrigar o uso de imagem
            if modo_scan: 
                d1['text'] = ""
                d2['text'] = ""

            results = []
            bar = st.progress(0)
            
            # Execução Paralela (3 workers é o ideal para não dar rate limit)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(processar_secao, s, d1, d2, secoes_alvo): s for s in secoes_alvo}
                
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    results.append(future.result())
                    bar.progress((i + 1) / len(secoes_alvo))
            
            # Ordenação
            results.sort(key=lambda x: secoes_alvo.index(x['titulo']))
            
            st.divider()
            
            # Exibição dos Resultados
            for i, r in enumerate(results):
                expand = True if "error" in r['cor'] else False
                cor_css = "#d1fae5" if "success" in r['cor'] else ("#fee2e2" if "error" in r['cor'] else "#fef3c7")
                
                with st.expander(f"{r['titulo']}", expanded=expand):
                    st.markdown(f"""
                    <div style="background-color: {cor_css}; padding: 10px; border-radius: 8px; margin-bottom: 10px; color: #333;">
                        <strong>VEREDITO:</strong> {r['veredito']}
                    </div>
                    """, unsafe_allow_html=True)
                    
                    cA, cB = st.columns(2)
                    cA.text_area("Referência (Extração)", r['ref'], height=150, key=f"r_{i}", disabled=True)
                    cB.text_area("Gráfica (Extração)", r['bel'], height=150, key=f"b_{i}", disabled=True)
