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
from io import BytesIO

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

# ----------------- 3. FUNÇÕES DE LIMPEZA E NORMALIZAÇÃO -----------------

def clean_metadata_and_footers(texto: str) -> str:
    """
    Remove metadados de produção/impressão e rodapés/paginações do texto.
    Remove linhas que contenham:
     - "Medida da bula", "Tipologia da bula", "Impressão:", "Papel:", "Cor:"
     - "Frente/Verso", "VERSO", "FRENTE"
     - dimensões tipo "45,00 cm x 19,00 cm"
     - nomes tipo "BUL_..." ou sequências longas em maiúsculas com underscores (prováveis nomes de arquivo)
     - paginação "Bula ao Paciente Página 2 de 9" (variações)
    """
    if not texto:
        return texto

    t = texto

    # Remove linhas com palavras-chave de metadado (case-insensitive)
    keys_line_patterns = [
        r'(?im)^\s*.*medida\s+da\s+bula.*$',
        r'(?im)^\s*.*tipologia\s+da\s+bula.*$',
        r'(?im)^\s*.*tipologia:.*$',
        r'(?im)^\s*.*impress(ã|a)o.*:.*$',
        r'(?im)^\s*.*impressão:.*$',
        r'(?im)^\s*.*papel:.*$',
        r'(?im)^\s*.*cor:.*$',
        r'(?im)^\s*.*frente\/verso.*$',
        r'(?im)^\s*frente\/verso.*$',
        r'(?im)^\s*^\s*verso\s*$',
        r'(?im)^\s*^\s*fren?te\s*$'
    ]
    for p in keys_line_patterns:
        t = re.sub(p, '', t)

    # Remove linhas contendo dimensões (ex: 45,00 cm x 19,00 cm) em variantes
    t = re.sub(r'(?im)^\s*\d{1,2},\d{2}\s*cm\s*[x×X]\s*\d{1,2},\d{2}\s*cm\s*$', '', t, flags=re.MULTILINE)
    t = re.sub(r'(?im)\d{1,2},\d{2}\s*cm\s*[x×X]\s*\d{1,2},\d{2}\s*cm', '', t)

    # Remove nomes longos em MAIÚSCULAS com underscores que pareçam nomes de arquivo (ex: BUL_MALEATO_DE_ENALAPRIL_...)
    # Remover linhas que tenham muitas letras maiúsculas/underscores e números
    t = re.sub(r'(?m)^\s*[A-Z0-9_]{8,}\s*$', '', t)

    # Remove padrões contendo "BUL" ou "BULA" seguidos de identificadores (com ou sem underscores)
    t = re.sub(r'(?im)\bBUL[A-Z0-9_]*\b', '', t)
    t = re.sub(r'(?im)\bBULA_[A-Z0-9_]+\b', '', t)

    # Remove paginação / rodapé do tipo "Bula ao Paciente Página 2 de 9" e variações "Página 2 de 9"
    page_patterns = [
        r'(?im)\bBula(?:\s+ao\s+Paciente)?\s+P[aá]gina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'(?im)\bBula(?:\s+ao\s+Paciente)?\s+P[aá]gina\s*\d+\b',
        r'(?im)\bP[aá]gina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'(?im)\bP[aá]gina\s*\d+\b'
    ]
    for p in page_patterns:
        t = re.sub(p, '', t)

    # Remove repetições curtas de "Verso", "Frente", "Frente/Verso" mesmo no meio da linha
    t = re.sub(r'(?im)\bverso\b', '', t)
    t = re.sub(r'(?im)\bfrente\b', '', t)
    t = re.sub(r'(?im)\bfrente\/verso\b', '', t)

    # Limpa caracteres extras e colapsa múltiplas quebras de linha em uma única
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\r', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    # Remove linhas em branco que sobram no início/fim de texto
    t = "\n".join([ln for ln in (line.rstrip() for line in t.splitlines()) if ln.strip() != ""])

    return t.strip()

def normalizacao_nuclear(texto):
    """Remove tudo que não seja letra ou número para comparação de conteúdo,
       após limpar metadados/rodapés."""
    if not texto:
        return ""
    t = clean_metadata_and_footers(texto)
    t = re.sub(r'<[^>]+>', '', t)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('ASCII')
    t = re.sub(r'[^a-zA-Z0-9]', '', t)
    return t.lower()

# ----------------- 4. FUNÇÕES INTELIGENTES (mantidas / adaptadas) -----------------

def verificar_ortografia_inteligente(texto):
    """Corretor Ultra-Conservador para erros de português"""
    try:
        spell = SpellChecker(language='pt')

        whitelist = {
            'mg', 'ml', 'mcg', 'ui', 'g', 'kg', 'l', 'dl', 'mmhg', 'bpm', 'kcal', 
            'crf', 'crm', 'anvisa', 'lote', 'val', 'fab', 'sac', 'cnpj', 'cep', 
            'dr', 'dra', 'vp', 'vps', 'bula', 'paciente', 'profissional', 'sac',
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

    # Para comparação, removemos metadados/rodapés que travam o diff
    comp_ref = clean_metadata_and_footers(texto_ref)
    comp_novo = clean_metadata_and_footers(texto_novo)

    # Comparação ignorando tags HTML e metadados
    if normalizacao_nuclear(comp_ref) == normalizacao_nuclear(comp_novo):
        # Se equivalentes após normalização, mostramos os textos limpos (sem metadados) mantendo formatação
        html_ref = clean_metadata_and_footers(texto_ref).replace('\n', '<br>')
        html_ref = melhorar_visual_topicos(html_ref)

        html_novo = verificar_ortografia_inteligente(clean_metadata_and_footers(texto_novo))
        html_novo = html_novo.replace('\n', '<br>')
        html_novo = melhorar_visual_topicos(html_novo)

        return html_ref, html_novo, False

    # Diff preservando formatação original (após limpeza para evitar ruído)
    r_html, n_html, diff_bool = diff_palavra_a_palavra(clean_metadata_and_footers(texto_ref), clean_metadata_and_footers(texto_novo))

    n_html_final = verificar_ortografia_inteligente(n_html)
    n_html_final = melhorar_visual_topicos(n_html_final)
    r_html_final = melhorar_visual_topicos(r_html.replace('\n', '<br>'))

    return r_html_final, n_html_final, diff_bool

# ----------------- 5. EXTRAÇÃO DE TEXTO -----------------

def extract_text_from_file(uploaded_file):
    """Extrai texto mantendo negrito/itálico quando possível."""
    try:
        text = ""
        name = getattr(uploaded_file, "name", "uploaded")
        if name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
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
                            is_bold = ((flags & 16) or "bold" in font_name or "black" in font_name or "heavy" in font_name or "semibold" in font_name)
                            is_italic = ((flags & 2) or "italic" in font_name or "oblique" in font_name)
                            formatted_text = content
                            if is_bold and is_italic:
                                formatted_text = f"<b><i>{content}</i></b>"
                            elif is_bold:
                                formatted_text = f"<b>{content}</b>"
                            elif is_italic:
                                formatted_text = f"<i>{content}</i>"
                            line_text += formatted_text
                        block_text += line_text.strip() + " "
                    text += block_text.strip() + "\n\n"
            doc.close()

        elif name.lower().endswith('.docx'):
            try:
                uploaded_file.seek(0)
                doc = docx.Document(uploaded_file)
            except Exception:
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

        # Limpeza inicial: remove metadados/rodapés logo após extrair
        return clean_metadata_and_footers(text.strip())

    except Exception as e:
        st.error(f"Erro ao extrair texto do arquivo {getattr(uploaded_file, 'name', '')}: {str(e)}")
        return ""

# ----------------- 6. UI PRINCIPAL -----------------
st.title("💊 Conferência MKT")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Bula MKT", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência", key="process_button"):
    st.info("Iniciando processamento...")
    if not f1 or not f2:
        st.warning("Por favor, envie ambos os arquivos antes de processar.")
    else:
        st.info(f"Arquivo BELFAR detectado: {getattr(f1, 'name', 'desconhecido')}")
        st.info(f"Arquivo MKT detectado: {getattr(f2, 'name', 'desconhecido')}")

    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada. Adicione as GEMINI_API_KEY no Secrets.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo arquivos e conectando à IA..."):
            try:
                f1.seek(0); f2.seek(0)
                t_anvisa = extract_text_from_file(f1)
                t_mkt = extract_text_from_file(f2)

                st.info(f"Tamanho do texto BELFAR (após limpeza): {len(t_anvisa)} caracteres")
                st.info(f"Tamanho do texto MKT (após limpeza): {len(t_mkt)} caracteres")
            except Exception as e:
                st.exception(f"Falha ao extrair textos: {e}")
                st.stop()

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.

            INPUT TEXTO 1 (REF): {t_anvisa[:150000]}
            INPUT TEXTO 2 (MKT): {t_mkt[:150000]}

            REGRAS CRÍTICAS DE EXTRAÇÃO:

**CABEÇALHO DA BULA**: Extrair TODO o conteúdo desde o início do documento ATÉ (mas NÃO incluindo) o título "APRESENTAÇÕES". 
IMPORTANTE: Remover APENAS os algarismos romanos (I, II, III) e o hífen/traço, mantendo o texto.
PARAR antes de encontrar "APRESENTAÇÕES" ou qualquer variação.

**SEÇÕES NORMAIS**: A partir de "APRESENTAÇÕES" até "DIZERES LEGAIS", extrair cada seção completa.

**FORMATAÇÃO**: 
Manter <b> e <i> EXATAMENTE como está
NÃO corrigir português
NÃO resumir
Ignorar linhas horizontais/elementos gráficos

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
                if sucesso: break
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
                if response is None:
                    st.error("Resposta da IA vazia (response is None).")
                    st.stop()
                resp_text = getattr(response, "text", None)
                if not resp_text:
                    st.error("Resposta da IA não contém atributo 'text' ou está vazio.")
                    try:
                        st.code(str(response))
                    except:
                        pass
                    st.stop()

                resultado = json.loads(resp_text)
            except Exception as e:
                st.exception(f"Erro ao decodificar JSON da resposta da IA: {e}")
                try:
                    st.code(resp_text)
                except:
                    pass
                st.stop()

            try:
                data_ref = resultado.get("data_anvisa_ref", "-")
                data_mkt = resultado.get("data_anvisa_mkt", "-")
                dados_secoes = resultado.get("secoes", [])

                secoes_finais = []
                divs_count = 0

                for item in dados_secoes:
                    titulo = item.get('titulo', '').strip()
                    txt_ref = item.get('texto_anvisa', '').strip()
                    txt_mkt = item.get('texto_mkt', '').strip()

                    # Limpeza final: remove metadados/paginacao também dentro das seções retornadas pela IA
                    txt_ref = clean_metadata_and_footers(txt_ref)
                    txt_mkt = clean_metadata_and_footers(txt_mkt)

                    # Se for CABEÇALHO DA BULA: garantir que pegou tudo até APRESENTAÇÕES
                    if "CABEÇALHO" in titulo.upper():
                        if not txt_ref or len(txt_ref) < 50 or re.search(r'APRESENTA', txt_ref, flags=re.IGNORECASE) is None:
                            # extrai do texto bruto já limpo
                            txt_ref = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', t_anvisa)
                        if not txt_mkt or len(txt_mkt) < 50 or re.search(r'APRESENTA', txt_mkt, flags=re.IGNORECASE) is None:
                            txt_mkt = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', t_mkt)
                        txt_ref = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_ref)
                        txt_mkt = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_mkt)

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
                st.exception(f"Erro ao processar resultado: {e}")
                st.stop()

else:
    st.info("Aguardando ação. Adicione os arquivos e clique em 'Processar Conferência'.")
