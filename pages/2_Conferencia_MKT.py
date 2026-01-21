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

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Conferência MKT", page_icon="💊", layout="wide")

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

    /* DIVERGÊNCIA (Amarelo) */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }

    /* ERRO PORTUGUÊS (Vermelho) - Estilo sutil */
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
    "CABEÇALHO DA BULA",
    "APRESENTAÇÕES", 
    "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

SECOES_SEM_COMPARACAO = []
SECOES_PROFISSIONAL = [] 

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def remove_page_footers(texto):
    """Remove padrões de paginação/rodapé que causam diffs (somente para comparação)."""
    if not texto:
        return texto
    t = texto
    # Padrões comuns, com variantes
    patterns = [
        r'\bBula(?:\s+ao\s+Paciente)?\s+Página\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'\bBula(?:\s+ao\s+Paciente)?\s+Página\s*\d+\b',
        r'\bPágina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'\bPágina\s*\d+\b'
    ]
    for p in patterns:
        t = re.sub(p, '', t, flags=re.IGNORECASE)
    # Também remove repetições muito curtas de "Página X de Y" mesmo grudadas com pontuação
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip()

def extract_header(texto):
    """Extrai tudo desde o início do documento até (mas não incluindo) 'APRESENTAÇÕES'."""
    if not texto:
        return ""
    # Procura pela palavra 'APRESENTAÇÕES' ou variações mais comuns
    m = re.search(r'\bAPRESENTA\S*\b', texto, flags=re.IGNORECASE)
    if m:
        idx = m.start()
        header = texto[:idx].strip()
        # Remover algarismos romanos + traço no início de linhas do conteúdo do cabeçalho
        header = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', header)
        return header.strip()
    else:
        # fallback: pega até primeira seção conhecida (APRESENTAÇÕES maiúsculo/minúsc)
        return re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', texto).strip()

def normalizacao_nuclear(texto):
    """Remove TUDO que não seja letra ou número para comparação de conteúdo,
       e retira rodapés de paginação antes de normalizar."""
    if not texto:
        return ""
    t = remove_page_footers(texto)
    t = re.sub(r'<[^>]+>', '', t)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('ASCII')
    t = re.sub(r'[^a-zA-Z0-9]', '', t)
    return t.lower()

def verificar_ortografia_inteligente(texto):
    """Corretor Ultra-Conservador para erros de português"""
    try:
        spell = SpellChecker(language='pt')

        whitelist = {
            'mg', 'ml', 'mcg', 'ui', 'g', 'kg', 'l', 'dl', 'mmhg', 'bpm', 'kcal', 
            'crf', 'crm', 'anvisa', 'lote', 'val', 'fab', 'sac', 'cnpj', 'cep', 
            'dr', 'dra', 'vp', 'vps', 'bula', 'paciente', 'profissional', 'sac',
            'blister', 'cartucho', 'posologia', 'superdose', 'farmacocinetica',
            'biodisponibilidade', 'excipiente', 'excipientes', 'revestimento',
            'comprimido', 'capsula', 'solucao', 'suspensao', 'oral', 'intravenosa',
            'subcutanea', 'intramuscular', 'topico', 'oftalmico', 'nasal',
            'adulto', 'pediatrico', 'geriatrico', 'indicação', 'contraindicação',
            'advertencia', 'precaucao', 'interacao', 'reacao', 'adversa', 'sintoma',
            'tratamento', 'diagnostico', 'profilaxia', 'analgesico', 'antipiretico',
            'anti-inflamatorio', 'antibiotico', 'antiviral', 'antifungico',
            'cardiovascular', 'respiratorio', 'digestivo', 'nervoso', 'central',
            'periferico', 'renal', 'hepatico', 'sanguineo', 'imunologico',
            'endocrino', 'metabolico', 'musculoesqueletico', 'dermatologico',
            'predisponentes', 'sistemicos', 'sistêmicos', 'congenita', 'congênita',
            'aneurisma', 'dissecção', 'disseccao', 'valvar', 'valvula', 'regurgitação',
            'endocardite', 'marfan', 'ehlers-danlos', 'turner', 'sjogren', 'takayasu',
            'behcet', 'reumatoide', 'artrite', 'corticosteroides', 'fluorquinolonas',
            'hipersensibilidade', 'arritmia', 'protuberancia', 'abdômen', 'abdomen',
            'gonorreia', 'gonorréia', 'infeccao', 'infeção', 'trato', 'urinario',
            'uretra', 'cervix', 'tubulos', 'túbulos', 'renais', 'queimação', 'queimacao',
            'prostatite', 'prostata', 'cistite', 'ureia', 'bacteria', 'bacterias'
        }
        spell.word_frequency.load_words(whitelist)

        tokens = re.split(r'(<[^>]+>|\s+|[().,:;!?/\[\]])', texto)
        resultado = []

        for token in tokens:
            if not token.strip() or token.startswith('<') or not any(c.isalpha() for c in token):
                resultado.append(token)
                continue

            palavra_limpa = re.sub(r'[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ-]', '', token)

            if (not palavra_limpa or 
                len(palavra_limpa) < 4 or 
                any(c.isdigit() for c in token) or 
                '-' in palavra_limpa or
                palavra_limpa[0].isupper()):
                resultado.append(token)
                continue

            p_lower = palavra_limpa.lower()

            if p_lower in spell or p_lower in whitelist:
                resultado.append(token)
            else:
                resultado.append(token)

        return "".join(resultado)
    except:
        return texto

def melhorar_visual_topicos(texto_html):
    """Transforma marcadores txt em visual HTML bonito"""
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
    """Destaca datas em AZUL nos Dizeres Legais"""
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def diff_palavra_a_palavra(texto_ref, texto_novo):
    """Compara textos palavra por palavra mantendo formatação"""
    # Remove tags HTML para comparação pura
    ref_sem_tags = re.sub(r'<[^>]+>', '', texto_ref)
    novo_sem_tags = re.sub(r'<[^>]+>', '', texto_novo)

    palavras_ref = ref_sem_tags.split()
    palavras_novo = novo_sem_tags.split()

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
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""

    # Para comparação, removemos rodapés/paginações que travam o diff
    comp_ref = remove_page_footers(texto_ref)
    comp_novo = remove_page_footers(texto_novo)

    # Comparação ignorando tags HTML e rodapés
    if normalizacao_nuclear(comp_ref) == normalizacao_nuclear(comp_novo):
        # Se equivalentes após normalização, mostramos os textos originais (com formatação)
        html_ref = texto_ref.replace('\n', '<br>')
        html_ref = melhorar_visual_topicos(html_ref)

        html_novo = verificar_ortografia_inteligente(texto_novo)
        html_novo = html_novo.replace('\n', '<br>')
        html_novo = melhorar_visual_topicos(html_novo)

        return html_ref, html_novo, False

    # Diff preservando formatação original
    r_html, n_html, diff_bool = diff_palavra_a_palavra(texto_ref, texto_novo)

    n_html_final = verificar_ortografia_inteligente(n_html)
    n_html_final = melhorar_visual_topicos(n_html_final)
    r_html_final = melhorar_visual_topicos(r_html.replace('\n', '<br>'))

    return r_html_final, n_html_final, diff_bool

def extract_text_from_file(uploaded_file):
    """Extrai texto mantendo formatação (negrito e itálico)"""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")

            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

                for block in blocks:
                    if block.get("type") != 0:
                        continue

                    block_text = ""

                    for line in block.get("lines", []):
                        line_text = ""

                        for span in line.get("spans", []):
                            content = span.get("text", "")
                            if not content.strip():
                                line_text += content
                                continue

                            flags = span.get("flags", 0)
                            font_name = span.get("font", "").lower()

                            is_bold = (
                                (flags & 16) or 
                                "bold" in font_name or 
                                "black" in font_name or 
                                "heavy" in font_name or
                                "semibold" in font_name
                            )

                            is_italic = (
                                (flags & 2) or 
                                "italic" in font_name or 
                                "oblique" in font_name
                            )

                            formatted_text = content
                            if is_bold and is_italic:
                                formatted_text = f"<b><i>{content}</i></b>"
                            elif is_bold:
                                formatted_text = f"<b>{content}</b>"
                            elif is_italic:
                                formatted_text = f"<i>{content}</i>"

                            line_text += formatted_text

                        # CORRIGE PALAVRAS GRUDADAS: Adiciona espaço entre palavras
                        block_text += line_text.strip() + " "

                    text += block_text.strip() + "\n\n"

            doc.close()

        elif uploaded_file.name.lower().endswith('.docx'):
            # python-docx aceita file-like? em geral aceita caminho; mas aceita também objetos com .read() se for bytesIO,
            # como estamos usando o objeto enviado pelo streamlit, tentamos passar diretamente.
            try:
                doc = docx.Document(uploaded_file)
            except Exception:
                # fallback: ler bytes e passar via BytesIO
                from io import BytesIO
                uploaded_file.seek(0)
                doc = docx.Document(BytesIO(uploaded_file.read()))

            for para in doc.paragraphs:
                para_text = ""

                for run in para.runs:
                    content = run.text
                    if not content:
                        continue

                    is_bold = run.bold is True
                    is_italic = run.italic is True

                    formatted_text = content
                    if is_bold and is_italic:
                        formatted_text = f"<b><i>{content}</i></b>"
                    elif is_bold:
                        formatted_text = f"<b>{content}</b>"
                    elif is_italic:
                        formatted_text = f"<i>{content}</i>"

                    para_text += formatted_text

                text += para_text + "\n\n"

        return text.strip()

    except Exception as e:
        st.error(f"Erro ao extrair texto: {str(e)}")
        return ""

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Conferência MKT")

tipo_bula = st.radio(
    "Escolha o Tipo de Bula:",
    ("Paciente",),
    horizontal=True
)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Bula MKT", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):

    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo arquivos e conectando à IA..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.

            INPUT TEXTO 1 (REF): {t_anvisa[:150000]}
            INPUT TEXTO 2 (MKT): {t_mkt[:150000]}

            REGRAS CRÍTICAS DE EXTRAÇÃO:

**CABE��ALHO DA BULA**: Extrair TODO o conteúdo desde o início do documento ATÉ (mas NÃO incluindo) o título "APRESENTAÇÕES". 
Inclui: nome do produto, código de barras, nomenclaturas, etc.
Inclui frases como "I – IDENTIFICAÇÃO DO PRODUTO TRADICIONAL FITOTERÁPICO"
Inclui "II – INFORMAÇÕES QUANTO ÀS APRESENTAÇÕES E COMPOSIÇÃO"
Inclui "III – INFORMAÇÕES AO PACIENTE"
IMPORTANTE: Remover APENAS os algarismos romanos (I, II, III) e o hífen/traço, mantendo o texto.
PARAR antes de encontrar "APRESENTAÇÕES" ou qualquer variação.

**SEÇÕES NORMAIS**: A partir de "APRESENTAÇÕES" até "DIZERES LEGAIS", extrair cada seção completa.

**FORMATAÇÃO**: 
Manter <b> e <i> EXATAMENTE como está
NÃO corrigir português
NÃO resumir
Ignorar linhas horizontais/elementos gráficos

**DATA DE APROVAÇÃO**: Extrair frase "aprovada pela Anvisa em..."

Se uma seção não existir, NÃO inclua no JSON.

LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}

SAÍDA JSON:
{{
 "data_anvisa_ref": "dd/mm/aaaa",
 "data_anvisa_mkt": "dd/mm/aaaa",
 "secoes": [
     {{
         "titulo": "NOME EXATO DA SEÇÃO",
         "texto_anvisa": "conteúdo completo",
         "texto_mkt": "conteúdo completo"
     }}
 ]
}}
"""

        response = None
        sucesso = False
        log_erros = []

        for idx_key, key in enumerate(keys_validas):
            if sucesso:
                break
            genai.configure(api_key=key)
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    model = genai.GenerativeModel(
                        modelo, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    response = model.generate_content(prompt)
                    sucesso = True
                    break 
                except Exception as e:
                    log_erros.append(f"Key {idx_key+1} | {modelo}: {str(e)}")
                    time.sleep(0.5)
                    continue

        if not sucesso:
            st.error("❌ Falha Total. Detalhes:")
            st.code("\n".join(log_erros))
            st.stop()

        try:
            resultado = json.loads(response.text)
            data_ref = resultado.get("data_anvisa_ref", "-")
            data_mkt = resultado.get("data_anvisa_mkt", "-")
            dados_secoes = resultado.get("secoes", [])

            # Fallback / correções locais:
            secoes_finais = []
            divs_count = 0

            for item in dados_secoes:
                titulo = item.get('titulo', '').strip()
                txt_ref = item.get('texto_anvisa', '').strip()
                txt_mkt = item.get('texto_mkt', '').strip()

                # Se for CABEÇALHO DA BULA: garantir que pegou tudo até APRESENTAÇÕES
                if "CABEÇALHO" in titulo.upper():
                    # Se o texto extraído estiver muito curto ou não corresponder ao trecho inicial,
                    # extraímos do texto bruto original até 'APRESENTAÇÕES'
                    if not txt_ref or len(txt_ref) < 50 or re.search(r'APRESENTA', txt_ref, flags=re.IGNORECASE) is None:
                        txt_ref = extract_header(t_anvisa)
                    if not txt_mkt or len(txt_mkt) < 50 or re.search(r'APRESENTA', txt_mkt, flags=re.IGNORECASE) is None:
                        txt_mkt = extract_header(t_mkt)

                    # Remove algarismos romanos + traço do conteúdo (por linha), preservando o título
                    txt_ref = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_ref)
                    txt_mkt = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_mkt)

                # Processa seção com diff ou destaque de datas
                if "DIZERES LEGAIS" in titulo.upper():
                    html_ref = destacar_datas(txt_ref).replace('\n', '<br>')
                    html_novo = destacar_datas(txt_mkt)
                    html_novo = verificar_ortografia_inteligente(html_novo).replace('\n', '<br>')
                    html_ref = melhorar_visual_topicos(html_ref)
                    html_novo = melhorar_visual_topicos(html_novo)
                    status = "CONFORME"
                else:
                    html_ref, html_novo, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                    status = "DIVERGENTE" if teve_diff else "CONFORME"
                    if teve_diff:
                        divs_count += 1

                secoes_finais.append({
                    "titulo": titulo, 
                    "texto_anvisa": html_ref, 
                    "texto_mkt": html_novo, 
                    "status": status
                })

            st.markdown("### 📊 Resumo")
            c1, c2, c3 = st.columns(3)
            c1.metric("Data BELFAR", data_ref)
            c2.metric("Data MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
            c3.metric("Seções", len(secoes_finais))

            sub1, sub2 = st.columns(2)
            sub1.info(f"✅ Conformes: {len(secoes_finais) - divs_count}")
            if divs_count > 0:
                sub2.warning(f"⚠️ Divergentes: {divs_count}")
            else:
                sub2.success("✨ Divergências: 0")

            st.divider()

            for item in secoes_finais:
                status = item['status']
                titulo = item['titulo']

                if "DIZERES LEGAIS" in titulo.upper(): 
                    icon, css, aberto = "⚖️", "border-info", False
                elif status == "CONFORME": 
                    icon, css, aberto = "✅", "border-ok", False
                else: 
                    icon, css, aberto = "⚠️", "border-warn", True

                with st.expander(f"{icon} {titulo}", expanded=aberto):
                    ce, cd = st.columns(2)
                    with ce:
                        st.caption("BELFAR")
                        st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                    with cd:
                        st.caption("MKT")
                        st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Erro ao processar JSON: {e}")
            try:
                st.code(response.text)
            except:
                pass
    else:
        st.warning("Adicione os arquivos.")
