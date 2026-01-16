import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time
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
    "models/gemini-2.5-flash", 
    "models/gemini-2.0-flash", 
    "models/gemini-1.5-flash", 
    "gemini-1.5-flash"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = SECOES_PACIENTE 
SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def normalizacao_nuclear(texto):
    if not texto: return ""
    t = re.sub(r'<[^>]+>', '', texto)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('ASCII')
    t = re.sub(r'[^a-zA-Z0-9]', '', t)
    return t.lower()

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
        elif tag == 'replace':
            html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
            tem_diff = True
        elif tag == 'delete':
            html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            tem_diff = True
        elif tag == 'insert':
            html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
            tem_diff = True
            
    return " ".join(html_ref_list), " ".join(html_novo_list), tem_diff

def gerar_diff_html(texto_ref, texto_novo):
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""
    
    if normalizacao_nuclear(texto_ref) == normalizacao_nuclear(texto_novo):
        html_novo = melhorar_visual_topicos(texto_novo.replace('\n', '<br>'))
        return texto_ref.replace('\n', '<br>'), html_novo, False

    ref_limpo = re.sub(r'<[^>]+>', '', texto_ref)
    novo_limpo = re.sub(r'<[^>]+>', '', texto_novo)
    
    r_html, n_html, diff_bool = diff_palavra_a_palavra(ref_limpo, novo_limpo)
    
    n_html_final = melhorar_visual_topicos(n_html)
    r_html_final = r_html.replace('\n', '<br>')
    
    return r_html_final, n_html_final, diff_bool

# ----------------- 4. EXTRAÇÃO E OCR -----------------

def remover_rodapes_bula(texto):
    """Remove rodapés típicos de bulas farmacêuticas"""
    if not texto:
        return texto
    
    # Padrões comuns de rodapé em bulas
    padroes_rodape = [
        r'\d+ª\s*PROVA\s*-\s*\d{2}/\d{2}/\d{4}',  # Remove "1ª PROVA - 11/11/2025"
        r'Medida\s+do\s+bula.*?Papel.*?Cor.*',
        r'Medida\s+\d+,\d+\s*x\s*\d+,\d+\s*mm',
        r'Tipologia\s+de\s+bula:.*?Negro:.*?Corpo:.*',
        r'Papel:.*?Cor:.*',
        r'FRENTE.*?Medida.*?Papel.*?Cor.*',
        r'Balcomplex.*?_comprimido_.*',
        r'conteúdo:.*?atendimento@belfar\.com\.br',
        r'www\.[^\s]+',  # URLs
        r'[A-Z]{2,}\s+\d{8,}',  # Códigos alfanuméricos
    ]
    
    texto_limpo = texto
    for padrao in padroes_rodape:
        texto_limpo = re.sub(padrao, '', texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove linhas com apenas números, dimensões ou códigos
    linhas = texto_limpo.split('\n')
    linhas_filtradas = []
    for linha in linhas:
        linha_strip = linha.strip()
        # Pula linhas que são apenas números, dimensões ou muito curtas sem conteúdo relevante
        if linha_strip and not re.match(r'^[\d\s,\.]+

def ocr_via_gemini(uploaded_file, api_keys):
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()
    
    prompt_ocr = """
    ATENÇÃO: Você é um robô de OCR ULTRA-PRECISO para documentos farmacêuticos brasileiros.
    IDIOMA: Português do Brasil.
    
    REGRAS ABSOLUTAS - VIOLAÇÃO = FALHA TOTAL:
    1. COPIE caractere por caractere EXATAMENTE como está escrito no documento.
    2. PROIBIDO inventar, corrigir ou "melhorar" palavras.
    3. PROIBIDO traduzir QUALQUER palavra.
    4. Se está escrito "general" no documento, escreva "general". Se está "geral", escreva "geral".
    5. Se está escrito "cirurgião-dentista", escreva EXATAMENTE "cirurgião-dentista" (com hífen e acento).
    6. Mantenha TODOS os hífens, acentos, pontuação e espaçamentos EXATAMENTE como aparecem.
    7. CRÍTICO: Extraia TODO o texto do documento, não pare no meio, não omita nenhuma palavra.
    8. Preserve formatação: use <b> para negrito e <i> para itálico conforme aparece no original.
    9. NÃO extraia rodapés (medidas, códigos, tipologia, informações técnicas de impressão).
    10. IGNORE completamente textos como "1ª PROVA - 11/11/2025" que aparecem nas bordas.
    11. Foque APENAS no conteúdo principal da bula.
    
    ATENÇÃO ESPECIAL: 
    - Não "corrija" palavras que você acha que estão erradas
    - Não traduza termos médicos do inglês para português ou vice-versa
    - Copie palavra por palavra, incluindo termos técnicos, médicos e farmacêuticos
    """
    
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    log_erros_ocr = []

    for i, key in enumerate(api_keys):
        try:
            genai.configure(api_key=key)
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    model = genai.GenerativeModel(modelo)
                    response = model.generate_content(
                        [{'mime_type': 'application/pdf', 'data': bytes_data}, prompt_ocr],
                        safety_settings=safety_settings
                    )
                    
                    texto_extraido = response.text
                    
                    if texto_extraido:
                         texto_extraido = remover_rodapes_bula(texto_extraido)
                         return texto_extraido, None
                         
                except Exception as e_model:
                    err_msg = str(e_model)
                    log_erros_ocr.append(f"Key {i+1} | {modelo}: {err_msg}")
                    if "429" in err_msg or "quota" in err_msg.lower():
                        time.sleep(2)
                    continue
        except Exception as e_key:
            log_erros_ocr.append(f"Key {i+1} Falha Config: {str(e_key)}")
            continue
            
    return "", " | ".join(log_erros_ocr)

def extract_text_smart(uploaded_file, api_keys=None):
    text = ""
    try:
        # 1. Tentativa Nativa com FORMATAÇÃO PRESERVADA
        if uploaded_file.name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                blocks = page.get_text("dict", flags=11)["blocks"]
                for b in blocks:
                    if b.get("type") != 0:
                        continue
                    block_text = ""
                    for l in b.get("lines", []):
                        line_txt = ""
                        for s in l.get("spans", []):
                            content = s.get("text", "")
                            font_props = s.get("font", "").lower()
                            flags = s.get("flags", 0)
                            is_bold = (flags & 16) or "bold" in font_props
                            is_italic = (flags & 2) or "italic" in font_props or "oblique" in font_props
                            
                            res = content
                            if is_bold and is_italic:
                                res = f"<b><i>{res}</i></b>"
                            elif is_bold:
                                res = f"<b>{res}</b>"
                            elif is_italic:
                                res = f"<i>{res}</i>"
                            line_txt += res
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
        
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    res = run.text
                    if run.bold and run.italic:
                        res = f"<b><i>{res}</i></b>"
                    elif run.bold:
                        res = f"<b>{res}</b>"
                    elif run.italic:
                        res = f"<i>{res}</i>"
                    para_txt += res
                text += para_txt + "\n\n"
        
        # Remove rodapés do texto extraído
        text = remover_rodapes_bula(text)
        
        # 2. Análise da Necessidade de OCR
        texto_limpo = re.sub(r'<[^>]+>', '', text).strip()
        
        eh_pdf = uploaded_file.name.lower().endswith('.pdf')
        
        if eh_pdf and len(texto_limpo) < 1000 and api_keys:
            st.warning(f"👁️ Arquivo '{uploaded_file.name}' detectado com pouco texto ({len(texto_limpo)} chars < 1000). Ativando OCR...")
            texto_ocr, erro_ocr = ocr_via_gemini(uploaded_file, api_keys)
            
            if texto_ocr:
                st.success(f"✅ OCR bem-sucedido para '{uploaded_file.name}'!")
                return texto_ocr
            else:
                st.error(f"❌ Falha no OCR de '{uploaded_file.name}'. Detalhes: {erro_ocr}")
                return "" 
        else:
            if len(texto_limpo) >= 1000:
                st.info(f"📄 Arquivo '{uploaded_file.name}' lido como texto padrão (OCR não necessário).")
            
        return text
        
    except Exception as e:
        return f"Erro leitura: {str(e)}"

# ============= CRIA O MENU LATERAL =============
st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    /* SIDEBAR SEMPRE ABERTA E TRAVADA */
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        width: 250px !important;
        min-width: 250px !important;
        max-width: 250px !important;
        margin-left: 0 !important;
        transform: translateX(0) !important;
        transition: none !important;
        position: relative !important;
        background-color: #f0f2f6 !important;
        z-index: 999 !important;
    }
    
    section[data-testid="stSidebar"] > div:first-child {
        width: 250px !important;
        min-width: 250px !important;
    }
    
    section[data-testid="stSidebar"][aria-expanded="false"],
    section[data-testid="stSidebar"][aria-expanded="true"] {
        margin-left: 0 !important;
        transform: translateX(0) !important;
    }
    
    /* Remove todos os botões de colapsar */
    button[kind="header"],
    [data-testid="collapsedControl"],
    button[data-testid="baseButton-header"] {
        display: none !important;
    }
    
    /* Resto do seu CSS */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        /* ... resto do CSS ... */
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"), 
        st.secrets.get("GEMINI_API_KEY2"), 
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada no secrets."); st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE

        with st.spinner("Analisando arquivos individualmente (Texto ou OCR)..."):
            t_anvisa = extract_text_smart(f1, api_keys=keys_validas)
            t_mkt = extract_text_smart(f2, api_keys=keys_validas)

            if not t_anvisa or len(t_anvisa) < 20:
                st.error(f"ERRO: Conteúdo do arquivo BELFAR insuficiente para análise."); st.stop()
            if not t_mkt or len(t_mkt) < 20:
                st.error(f"ERRO: Conteúdo do arquivo MKT insuficiente para análise."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos ULTRA-RIGOROSO (ROBÔ DE CÓPIA PERFEITA).
            
            INPUT TEXTO 1 (REF - GRÁFICA): {t_anvisa[:180000]}
            INPUT TEXTO 2 (MKT - ARTE): {t_mkt[:180000]}
            
            REGRAS ABSOLUTAS - NÃO NEGOCIÁVEIS:
            1. COPIE o texto PALAVRA POR PALAVRA, CARACTERE POR CARACTERE exatamente como está nos inputs.
            2. PROIBIDO inventar, corrigir, "melhorar" ou alterar QUALQUER palavra.
            3. PROIBIDO traduzir termos (se está "general", mantenha "general"; se está "geral", mantenha "geral").
            4. PRESERVE TODA a formatação <b> e <i> dos textos originais.
            5. MANTENHA todos os hífens, acentos e pontuação EXATAMENTE como aparecem (ex: "cirurgião-dentista").
            6. EXTRAIA TODO o conteúdo de cada seção - NÃO CORTE o texto no meio, NÃO omita palavras.
            7. Se uma palavra parece "estranha" ou "incorreta", COPIE MESMO ASSIM - não corrija.
            8. Mantenha erros de digitação originais se houver.
            9. Se não encontrar a data de aprovação da Anvisa (geralmente nos Dizeres Legais), retorne "N/A" nos campos de data.
            
            LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}
            
            SAÍDA JSON:
            {{ "data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [ {{ "titulo": "...", "texto_anvisa": "...", "texto_mkt": "..." }} ] }}
            """
            
            response = None
            sucesso = False
            log_erros = []

            for idx_key, key in enumerate(keys_validas):
                if sucesso: break
                
                genai.configure(api_key=key)
                
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model = genai.GenerativeModel(modelo, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                        response = model.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        erro_msg = str(e)
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {erro_msg}")
                        if "429" in erro_msg or "quota" in erro_msg.lower():
                            time.sleep(3)
                        else:
                            time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total na Análise."); st.code("\n".join(log_erros)); st.stop()
            
            try:
                resultado = json.loads(response.text)
                
                data_ref = resultado.get("data_anvisa_ref") or "N/A"
                data_mkt = resultado.get("data_anvisa_mkt") or "N/A"
                
                dados_secoes = resultado.get("secoes") or []
                
                secoes_finais = []
                divs_count = 0

                for item in dados_secoes:
                    titulo = (item.get('titulo') or '').strip()
                    txt_ref = (item.get('texto_anvisa') or "").strip()
                    txt_mkt = (item.get('texto_mkt') or "").strip()
                    
                    titulo_upper = titulo.upper()
                    eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

                    if eh_blindada:
                        status = "CONFORME"
                        if "DIZERES LEGAIS" in titulo_upper:
                            html_mkt = destacar_datas(txt_mkt); html_ref = destacar_datas(txt_ref)
                        else:
                            html_mkt = txt_mkt; html_ref = txt_ref
                        html_mkt = melhorar_visual_topicos(html_mkt.replace('\n', '<br>'))
                        html_ref = html_ref.replace('\n', '<br>')
                    else:
                        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Ref", data_ref)
                c2.metric("Data MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                c3.metric("Seções", len(secoes_finais))

                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ Conformes: {len(secoes_finais) - divs_count}")
                if divs_count > 0: sub2.warning(f"⚠️ Divergentes: {divs_count}")
                else: sub2.success("✨ Divergências: 0")

                st.divider()

                for item in secoes_finais:
                    status = item['status']
                    titulo = item['titulo']
                    if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️", "border-info", True
                    elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO): icon, css, aberto = "🔒", "border-ok", False
                    elif status == "CONFORME": icon, css, aberto = "✅", "border-ok", False
                    else: icon, css, aberto = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        ce, cd = st.columns(2)
                        with ce: st.caption("Gráfica"); st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd: st.caption("Arte"); st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}"); st.code(response.text)
    else:
        st.warning("Adicione os arquivos."), linha_strip):
            linhas_filtradas.append(linha)
    
    return '\n'.join(linhas_filtradas)

def ocr_via_gemini(uploaded_file, api_keys):
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()
    
    prompt_ocr = """
    ATENÇÃO: Você é um robô de OCR ULTRA-PRECISO para documentos farmacêuticos brasileiros.
    IDIOMA: Português do Brasil.
    
    REGRAS ABSOLUTAS - VIOLAÇÃO = FALHA TOTAL:
    1. COPIE caractere por caractere EXATAMENTE como está escrito no documento.
    2. PROIBIDO inventar, corrigir ou "melhorar" palavras.
    3. PROIBIDO traduzir QUALQUER palavra.
    4. Se está escrito "general" no documento, escreva "general". Se está "geral", escreva "geral".
    5. Se está escrito "cirurgião-dentista", escreva EXATAMENTE "cirurgião-dentista" (com hífen e acento).
    6. Mantenha TODOS os hífens, acentos, pontuação e espaçamentos EXATAMENTE como aparecem.
    7. CRÍTICO: Extraia TODO o texto do documento, não pare no meio, não omita nenhuma palavra.
    8. Preserve formatação: use <b> para negrito e <i> para itálico conforme aparece no original.
    9. NÃO extraia rodapés (medidas, códigos, tipologia, informações técnicas de impressão).
    10. IGNORE completamente textos como "1ª PROVA - 11/11/2025" que aparecem nas bordas.
    11. Foque APENAS no conteúdo principal da bula.
    
    ATENÇÃO ESPECIAL: 
    - Não "corrija" palavras que você acha que estão erradas
    - Não traduza termos médicos do inglês para português ou vice-versa
    - Copie palavra por palavra, incluindo termos técnicos, médicos e farmacêuticos
    """
    
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    log_erros_ocr = []

    for i, key in enumerate(api_keys):
        try:
            genai.configure(api_key=key)
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    model = genai.GenerativeModel(modelo)
                    response = model.generate_content(
                        [{'mime_type': 'application/pdf', 'data': bytes_data}, prompt_ocr],
                        safety_settings=safety_settings
                    )
                    
                    texto_extraido = response.text
                    
                    if texto_extraido:
                         texto_extraido = remover_rodapes_bula(texto_extraido)
                         return texto_extraido, None
                         
                except Exception as e_model:
                    err_msg = str(e_model)
                    log_erros_ocr.append(f"Key {i+1} | {modelo}: {err_msg}")
                    if "429" in err_msg or "quota" in err_msg.lower():
                        time.sleep(2)
                    continue
        except Exception as e_key:
            log_erros_ocr.append(f"Key {i+1} Falha Config: {str(e_key)}")
            continue
            
    return "", " | ".join(log_erros_ocr)

def extract_text_smart(uploaded_file, api_keys=None):
    text = ""
    try:
        # 1. Tentativa Nativa com FORMATAÇÃO PRESERVADA
        if uploaded_file.name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                blocks = page.get_text("dict", flags=11)["blocks"]
                for b in blocks:
                    if b.get("type") != 0:
                        continue
                    block_text = ""
                    for l in b.get("lines", []):
                        line_txt = ""
                        for s in l.get("spans", []):
                            content = s.get("text", "")
                            font_props = s.get("font", "").lower()
                            flags = s.get("flags", 0)
                            is_bold = (flags & 16) or "bold" in font_props
                            is_italic = (flags & 2) or "italic" in font_props or "oblique" in font_props
                            
                            res = content
                            if is_bold and is_italic:
                                res = f"<b><i>{res}</i></b>"
                            elif is_bold:
                                res = f"<b>{res}</b>"
                            elif is_italic:
                                res = f"<i>{res}</i>"
                            line_txt += res
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
        
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    res = run.text
                    if run.bold and run.italic:
                        res = f"<b><i>{res}</i></b>"
                    elif run.bold:
                        res = f"<b>{res}</b>"
                    elif run.italic:
                        res = f"<i>{res}</i>"
                    para_txt += res
                text += para_txt + "\n\n"
        
        # Remove rodapés do texto extraído
        text = remover_rodapes_bula(text)
        
        # 2. Análise da Necessidade de OCR
        texto_limpo = re.sub(r'<[^>]+>', '', text).strip()
        
        eh_pdf = uploaded_file.name.lower().endswith('.pdf')
        
        if eh_pdf and len(texto_limpo) < 1000 and api_keys:
            st.warning(f"👁️ Arquivo '{uploaded_file.name}' detectado com pouco texto ({len(texto_limpo)} chars < 1000). Ativando OCR...")
            texto_ocr, erro_ocr = ocr_via_gemini(uploaded_file, api_keys)
            
            if texto_ocr:
                st.success(f"✅ OCR bem-sucedido para '{uploaded_file.name}'!")
                return texto_ocr
            else:
                st.error(f"❌ Falha no OCR de '{uploaded_file.name}'. Detalhes: {erro_ocr}")
                return "" 
        else:
            if len(texto_limpo) >= 1000:
                st.info(f"📄 Arquivo '{uploaded_file.name}' lido como texto padrão (OCR não necessário).")
            
        return text
        
    except Exception as e:
        return f"Erro leitura: {str(e)}"

# ============= CRIA O MENU LATERAL =============
st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    /* SIDEBAR SEMPRE ABERTA E TRAVADA */
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        width: 250px !important;
        min-width: 250px !important;
        max-width: 250px !important;
        margin-left: 0 !important;
        transform: translateX(0) !important;
        transition: none !important;
        position: relative !important;
        background-color: #f0f2f6 !important;
        z-index: 999 !important;
    }
    
    section[data-testid="stSidebar"] > div:first-child {
        width: 250px !important;
        min-width: 250px !important;
    }
    
    section[data-testid="stSidebar"][aria-expanded="false"],
    section[data-testid="stSidebar"][aria-expanded="true"] {
        margin-left: 0 !important;
        transform: translateX(0) !important;
    }
    
    /* Remove todos os botões de colapsar */
    button[kind="header"],
    [data-testid="collapsedControl"],
    button[data-testid="baseButton-header"] {
        display: none !important;
    }
    
    /* Resto do seu CSS */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        /* ... resto do CSS ... */
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"), 
        st.secrets.get("GEMINI_API_KEY2"), 
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada no secrets."); st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE

        with st.spinner("Analisando arquivos individualmente (Texto ou OCR)..."):
            t_anvisa = extract_text_smart(f1, api_keys=keys_validas)
            t_mkt = extract_text_smart(f2, api_keys=keys_validas)

            if not t_anvisa or len(t_anvisa) < 20:
                st.error(f"ERRO: Conteúdo do arquivo BELFAR insuficiente para análise."); st.stop()
            if not t_mkt or len(t_mkt) < 20:
                st.error(f"ERRO: Conteúdo do arquivo MKT insuficiente para análise."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso (ROBÔ DE CÓPIA).
            
            INPUT TEXTO 1 (REF - GRÁFICA): {t_anvisa[:180000]}
            INPUT TEXTO 2 (MKT - ARTE): {t_mkt[:180000]}
            
            SUA MISSÃO CRÍTICA:
            1. COPIAR o texto EXATAMENTE como está nos inputs para dentro do JSON.
            2. PRESERVAR TODA a formatação <b> e <i> dos textos originais.
            3. EXTRAIR TODO o conteúdo de cada seção - NÃO CORTE o texto no meio.
            4. PROIBIDO corrigir português. 
            5. ATENÇÃO: Se no texto de entrada estiver "geral", MANTENHA "geral". Não mude para "general".
            6. Se não encontrar a data de aprovação da Anvisa (geralmente nos Dizeres Legais), retorne "N/A" nos campos de data.
            
            LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}
            
            SAÍDA JSON:
            {{ "data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [ {{ "titulo": "...", "texto_anvisa": "...", "texto_mkt": "..." }} ] }}
            """
            
            response = None
            sucesso = False
            log_erros = []

            for idx_key, key in enumerate(keys_validas):
                if sucesso: break
                
                genai.configure(api_key=key)
                
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model = genai.GenerativeModel(modelo, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                        response = model.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        erro_msg = str(e)
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {erro_msg}")
                        if "429" in erro_msg or "quota" in erro_msg.lower():
                            time.sleep(3)
                        else:
                            time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total na Análise."); st.code("\n".join(log_erros)); st.stop()
            
            try:
                resultado = json.loads(response.text)
                
                data_ref = resultado.get("data_anvisa_ref") or "N/A"
                data_mkt = resultado.get("data_anvisa_mkt") or "N/A"
                
                dados_secoes = resultado.get("secoes") or []
                
                secoes_finais = []
                divs_count = 0

                for item in dados_secoes:
                    titulo = (item.get('titulo') or '').strip()
                    txt_ref = (item.get('texto_anvisa') or "").strip()
                    txt_mkt = (item.get('texto_mkt') or "").strip()
                    
                    titulo_upper = titulo.upper()
                    eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

                    if eh_blindada:
                        status = "CONFORME"
                        if "DIZERES LEGAIS" in titulo_upper:
                            html_mkt = destacar_datas(txt_mkt); html_ref = destacar_datas(txt_ref)
                        else:
                            html_mkt = txt_mkt; html_ref = txt_ref
                        html_mkt = melhorar_visual_topicos(html_mkt.replace('\n', '<br>'))
                        html_ref = html_ref.replace('\n', '<br>')
                    else:
                        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Ref", data_ref)
                c2.metric("Data MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                c3.metric("Seções", len(secoes_finais))

                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ Conformes: {len(secoes_finais) - divs_count}")
                if divs_count > 0: sub2.warning(f"⚠️ Divergentes: {divs_count}")
                else: sub2.success("✨ Divergências: 0")

                st.divider()

                for item in secoes_finais:
                    status = item['status']
                    titulo = item['titulo']
                    if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️", "border-info", True
                    elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO): icon, css, aberto = "🔒", "border-ok", False
                    elif status == "CONFORME": icon, css, aberto = "✅", "border-ok", False
                    else: icon, css, aberto = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        ce, cd = st.columns(2)
                        with ce: st.caption("Gráfica"); st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd: st.caption("Arte"); st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}"); st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
