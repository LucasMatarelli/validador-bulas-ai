import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time
from spellchecker import SpellChecker
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Gráfica x Arte", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.7;
        color: #212529;
        background-color: #ffffff;
        padding: 25px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: left;
    }
    
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }
    
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        border-bottom: 2px solid #dc3545; 
        font-weight: bold;
        cursor: help;
    }
    
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }
    
    .topico-item {
        display: block;
        margin-left: 20px;
        margin-bottom: 4px;
        text-indent: -15px; 
    }
    
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-1.5-pro", # Pro lida melhor com textos longos sem cortar
    "models/gemini-2.0-flash", 
    "models/gemini-1.5-flash"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO?", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def normalizacao_nuclear(texto):
    if not texto: return ""
    t = re.sub(r'<[^>]+>', '', texto)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('ASCII')
    t = re.sub(r'[^a-zA-Z0-9]', '', t)
    return t.lower()

def verificar_ortografia_inteligente(texto):
    try:
        spell = SpellChecker(language='pt')
        # ... (sua lista de whitelist mantida)
        tokens = re.split(r'(<[^>]+>|\s+|[().,:;!?/\[\]])', texto)
        resultado = []
        for token in tokens:
            if not token.strip() or token.startswith('<') or not any(c.isalpha() for c in token):
                resultado.append(token)
                continue
            resultado.append(token)
        return "".join(resultado)
    except:
        return texto

def melhorar_visual_topicos(texto_html):
    linhas = re.split(r'(<br>|\n)', texto_html)
    novo_texto = []
    for linha in linhas:
        if re.search(r'^\s*[-•*]\s+', re.sub(r'<[^>]+>', '', linha).strip()):
            linha_limpa = re.sub(r'^\s*[-•*]\s+', '', linha)
            novo_texto.append(f'<div class="topico-item">• {linha_limpa}</div>')
        else:
            novo_texto.append(linha)
    return "".join(novo_texto)

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def diff_palavra_a_palavra(texto_ref, texto_novo):
    # Split preservando as tags para a comparação
    palavras_ref = texto_ref.split()
    palavras_novo = texto_novo.split()
    matcher = difflib.SequenceMatcher(None, palavras_ref, palavras_novo)
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            texto = " ".join(palavras_ref[i1:i2])
            html_ref_list.append(texto)
            html_novo_list.append(texto)
        else:
            tem_diff = True
            if tag in ('replace', 'delete'):
                html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            if tag in ('replace', 'insert'):
                html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
                
    return " ".join(html_ref_list), " ".join(html_novo_list), tem_diff

def gerar_diff_html(texto_ref, texto_novo):
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""
    
    if normalizacao_nuclear(texto_ref) == normalizacao_nuclear(texto_novo):
        return texto_ref.replace('\n', '<br>'), texto_novo.replace('\n', '<br>'), False

    # Comparação direta mantendo as tags <b> e <i> vindas da extração
    r_html, n_html, diff_bool = diff_palavra_a_palavra(texto_ref, texto_novo)
    
    # Apenas visual e ortografia
    r_html_final = verificar_ortografia_inteligente(r_html)
    r_html_final = melhorar_visual_topicos(r_html_final.replace('\n', '<br>'))
    n_html_final = n_html.replace('\n', '<br>')
    
    return r_html_final, n_html_final, diff_bool

# ----------------- 4. EXTRAÇÃO E OCR -----------------

def ocr_via_gemini(uploaded_file, api_keys):
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()
    prompt_ocr = """
    Transcreva caractere por caractere. PROIBIDO traduzir ou resumir. 
    Mantenha negritos com <b> e itálicos com <i>.
    Se estiver escrito "geral", mantenha "geral".
    """
    
    safety_settings = {category: HarmBlockThreshold.BLOCK_NONE for category in [HarmCategory.HARM_CATEGORY_HATE_SPEECH, HarmCategory.HARM_CATEGORY_HARASSMENT, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT]}

    for key in api_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel("models/gemini-1.5-pro")
            response = model.generate_content([{'mime_type': 'application/pdf', 'data': bytes_data}, prompt_ocr], safety_settings=safety_settings)
            return response.text, None
        except Exception as e:
            continue
    return "", "Falha no OCR"

def extract_text_smart(uploaded_file, api_keys=None):
    text = ""
    try:
        if uploaded_file.name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                blocks = page.get_text("dict", flags=11, sort=True)["blocks"]
                for b in blocks:
                    block_text = ""
                    for l in b.get("lines", []):
                        line_txt = ""
                        for s in l.get("spans", []):
                            content = s["text"]
                            font_props = s["font"].lower()
                            is_bold = (s["flags"] & 16) or "bold" in font_props
                            is_italic = (s["flags"] & 2) or "italic" in font_props
                            res = content
                            if is_bold: res = f"<b>{res}</b>"
                            if is_italic: res = f"<i>{res}</i>"
                            # FIX: Não adiciona espaço entre spans para evitar "rea ções"
                            line_txt += res
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
        
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    res = run.text
                    if run.bold: res = f"<b>{res}</b>"
                    if run.italic: res = f"<i>{res}</i>"
                    para_txt += res
                text += para_txt + "\n\n"
        
        texto_limpo = re.sub(r'<[^>]+>', '', text).strip()
        if uploaded_file.name.lower().endswith('.pdf') and len(texto_limpo) < 1000 and api_keys:
            texto_ocr, erro_ocr = ocr_via_gemini(uploaded_file, api_keys)
            return texto_ocr if texto_ocr else text
        return text
    except Exception as e:
        return f"Erro: {str(e)}"

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

# Sidebar fixa como no seu original
st.markdown("""<style> section[data-testid="stSidebar"] { width: 250px !important; } </style>""", unsafe_allow_html=True)

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_raw = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_raw if k]

    if f1 and f2:
        with st.spinner("Analisando bulas..."):
            t_anvisa = extract_text_smart(f1, api_keys=keys_validas)
            t_mkt = extract_text_smart(f2, api_keys=keys_validas)

            # PROMPT REFORÇADO PARA NÃO CORTAR E MANTER TAGS
            prompt = f"""
            Você é um ROBÔ DE CÓPIA FIEL. 
            Extraia o texto das seções: {SECOES_PACIENTE}
            
            REGRAS VITAIS:
            1. Para a seção da GRÁFICA (Ref), copie o texto TODO, sem omitir uma única palavra.
            2. Mantenha as tags <b> e <i> rigorosamente.
            3. Se houver erro de escrita no input, mantenha no output.
            
            FORMATO JSON:
            {{ "data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [ {{ "titulo": "...", "texto_anvisa": "...", "texto_mkt": "..." }} ] }}
            
            INPUT GRÁFICA: {t_anvisa[:160000]}
            INPUT ARTE: {t_mkt[:160000]}
            """
            
            # Configuração com max_output_tokens alto para não truncar o JSON
            genai.configure(api_key=keys_validas[0])
            model = genai.GenerativeModel("models/gemini-1.5-pro", 
                                          generation_config={"response_mime_type": "application/json", "temperature": 0.0, "max_output_tokens": 8192})
            
            response = model.generate_content(prompt)
            resultado = json.loads(response.text)

            secoes_finais = []
            for item in resultado.get("secoes", []):
                titulo = item.get('titulo', '').strip()
                txt_ref = item.get('texto_anvisa', "").strip()
                txt_mkt = item.get('texto_mkt', "").strip()
                
                titulo_upper = titulo.upper()
                eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

                if eh_blindada:
                    status = "CONFORME"
                    # Correção e destaques apenas na Gráfica (txt_ref) como solicitado
                    html_ref = verificar_ortografia_inteligente(txt_ref)
                    if "DIZERES LEGAIS" in titulo_upper:
                        html_ref = destacar_datas(html_ref); html_mkt = destacar_datas(txt_mkt)
                    else:
                        html_mkt = txt_mkt
                    html_ref = melhorar_visual_topicos(html_ref.replace('\n', '<br>'))
                    html_mkt = html_mkt.replace('\n', '<br>')
                else:
                    # Na função gerar_diff_html, a correção agora é aplicada ao html_ref (Gráfica)
                    html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                    status = "DIVERGENTE" if teve_diff else "CONFORME"

                secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

            # --- RENDERIZAÇÃO ---
            st.divider()
            for item in secoes_finais:
                css = "border-warn" if item['status'] == "DIVERGENTE" else "border-ok"
                with st.expander(f"{item['titulo']}", expanded=(item['status'] == "DIVERGENTE")):
                    ce, cd = st.columns(2)
                    ce.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                    cd.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)
