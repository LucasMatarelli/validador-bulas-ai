import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

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
        white-space: pre-wrap; /* MANTÉM AS QUEBRAS DE LINHA E PARÁGRAFOS ORIGINAIS */
    }
    
    /* DIVERGÊNCIA (Amarelo) */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }
    
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
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
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemma-3-27b-it"
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

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def diff_palavra_a_palavra(texto_ref, texto_novo):
    # O uso do regex mantem espaços e quebras de linha preservados como tokens isolados
    tokens_ref = re.split(r'(\s+)', texto_ref)
    tokens_novo = re.split(r'(\s+)', texto_novo)
    
    tokens_ref = [t for t in tokens_ref if t]
    tokens_novo = [t for t in tokens_novo if t]

    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_novo)
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            html_ref_list.append("".join(tokens_ref[i1:i2]))
            html_novo_list.append("".join(tokens_novo[j1:j2]))
        elif tag in ['replace', 'delete', 'insert']:
            # Trata Texto Referência
            if tag in ['replace', 'delete']:
                chunk_ref = "".join(tokens_ref[i1:i2])
                if chunk_ref.strip(): # Só marca como divergência visual se não for apenas uma quebra de linha perdida
                    html_ref_list.append(f'<span class="highlight-yellow">{chunk_ref}</span>')
                    tem_diff = True
                else:
                    html_ref_list.append(chunk_ref)
            
            # Trata Texto Novo
            if tag in ['replace', 'insert']:
                chunk_novo = "".join(tokens_novo[j1:j2])
                if chunk_novo.strip():
                    html_novo_list.append(f'<span class="highlight-yellow">{chunk_novo}</span>')
                    tem_diff = True
                else:
                    html_novo_list.append(chunk_novo)
                
    return "".join(html_ref_list), "".join(html_novo_list), tem_diff

def extract_text_from_file(uploaded_file):
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
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
                            flags = s.get("flags", 0)
                            
                            is_bold = (
                                (flags & 16) or 
                                "bold" in font_props or 
                                "black" in font_props or
                                "heavy" in font_props or
                                "semibold" in font_props or
                                font_props.endswith("-b") or
                                font_props.endswith("-bold")
                            )
                            
                            is_italic = (
                                (flags & 2) or 
                                "italic" in font_props or
                                "oblique" in font_props or
                                font_props.endswith("-i") or
                                font_props.endswith("-italic")
                            )
                            
                            res = content
                            if is_italic: 
                                res = f"<i>{res}</i>"
                            if is_bold: 
                                res = f"<b>{res}</b>"
                            
                            line_txt += res + " "
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    res = run.text
                    if run.italic: 
                        res = f"<i>{res}</i>"
                    if run.bold: 
                        res = f"<b>{res}</b>"
                    para_txt += res
                text += para_txt + "\n\n"
        
        # ---------------------------------------------------------
        # LIMPEZA AVANÇADA DE FORMATAÇÃO E RODAPÉS
        # ---------------------------------------------------------
        # 1. Junta palavras divididas por hífen entre quebras/spans (Ex: Henoch- Schoenlein)
        text = re.sub(r'(\w)-\s+(\w)', r'\1-\2', text)
        
        # 2. Remove paginação padrão
        text = re.sub(r'(?i)bula[^\n]*?p[áa]gina[^\n]*?\d+\s*de\s*\d+', '', text)
        text = re.sub(r'(?i)p[áa]gina[^\n]*?\d+\s*de\s*\d+', '', text)
        
        # 3. Remove rodapés de controle de versão da indústria (Ex: 1 VP14 = Voltaren_Bula_Paciente 5)
        text = re.sub(r'(?i)\b\d*\s*VP\d+\s*=\s*[^\n]+', '', text)
        
        # 4. Remove nomes de arquivo perdidos como rodapé (Ex: Medicamento_Bula_Paciente 03)
        text = re.sub(r'(?i)\b[a-z0-9_]+_bula_(?:paciente|profissional)[^\n]*', '', text)
        
        # 5. Limpa excesso de quebras de linha duplas extras geradas pela remoção
        text = re.sub(r'\n\s*\n', '\n\n', text)
        # ---------------------------------------------------------
        
        return text
    except: 
        return ""

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
</style>
""", unsafe_allow_html=True)

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

tipo_bula = st.radio(
    "Escolha o Tipo de Bula:",
    ("Paciente", "Profissional"),
    horizontal=True
)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"], key="f2")

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

            SUA MISSÃO:
            1. Extrair DATA DE APROVAÇÃO (frase exata "aprovada pela Anvisa em...").
            2. Extrair TODO o conteúdo de cada seção. NÃO RESUMA.
            3. PRESERVAR RIGOROSAMENTE formatação <b> e <i>. NÃO corrigir português.
            4. MANTER todas as tags <b></b> e <i></i> EXATAMENTE como aparecem no texto.

            LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "...",
                        "texto_mkt": "..."
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
                resultado = json.loads(response.text)
                data_ref = resultado.get("data_anvisa_ref", "-")
                data_mkt = resultado.get("data_anvisa_mkt", "-")
                dados_secoes = resultado.get("secoes", [])
                
                secoes_finais = []
                divs_count = 0

                for item in dados_secoes:
                    titulo = item.get('titulo', '').strip()
                    txt_ref = item.get('texto_anvisa', '').strip()
                    txt_mkt = item.get('texto_mkt', '').strip()
                    
                    titulo_upper = titulo.upper()
                    eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

                    if eh_blindada:
                        status = "CONFORME"
                        if "DIZERES LEGAIS" in titulo_upper:
                            html_mkt = destacar_datas(txt_mkt)
                            html_ref = destacar_datas(txt_ref)
                        else:
                            html_mkt = txt_mkt
                            html_ref = txt_ref
                    else:
                        html_ref, html_mkt, teve_diff = diff_palavra_a_palavra(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({
                        "titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status
                    })

                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Referência", data_ref)
                c2.metric("Data BELFAR", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
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
                        with ce:
                            st.caption("Referência")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd:
                            st.caption("BELFAR")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}")
                st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
