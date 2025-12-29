import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import json
import difflib
import re
import unicodedata

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Conferência MKT", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        white-space: pre-wrap; 
        text-align: left;
    }
    
    /* Highlight Amarelo (Apenas divergências reais de texto) */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; font-weight: bold;
    }
    
    /* Highlight Azul (Datas da Anvisa) */
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }
    
    /* Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 3. FUNÇÕES AUXILIARES -----------------

def limpar_ruido_visual(texto):
    if not texto: return ""
    texto = texto.replace(u'\xa0', u' ')
    texto = texto.replace(u'\xad', u'')
    texto = texto.replace(u'‐', u'-').replace(u'‑', u'-')
    texto = re.sub(r'[\._]{3,}', ' ', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()

def normalizar_rigorosa(texto):
    """
    Remove TUDO que não for letra ou número para comparação.
    Ignora: Espaços, Enters, Pontos soltos, Tags HTML, Quebras de token.
    """
    if not texto: return ""
    # Remove tags HTML
    txt = re.sub(r'<[^>]+>', '', texto)
    # Remove o token interno de quebra se houver
    txt = txt.replace('[[BREAK]]', '')
    # Remove TODOS os espaços em branco (espaço, tab, enter)
    txt = re.sub(r'\s+', '', txt)
    return unicodedata.normalize('NFKD', txt).lower().strip()

def eh_conteudo_visivel(texto):
    """
    Verifica se o texto contém conteúdo real visível (não é só formatação/espaço).
    Necessário para o novo gerar_diff_html funcionar.
    """
    if not texto: return False
    # Se a normalização rigorosa retornar algo, é visível.
    return normalizar_rigorosa(texto) != ""

def destacar_datas(texto):
    """
    REGEX NUCLEAR: Encontra a data independente do que estiver no meio da frase.
    """
    if not texto: return ""
    padrao = r'(aprovada.*?pela.*?Anvisa.*?em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def gerar_diff_html(texto_ref, texto_novo):
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    TOKEN_QUEBRA = " [[BREAK]] "
    
    ref_limpo = limpar_ruido_visual(texto_ref).replace('\n', TOKEN_QUEBRA)
    novo_limpo = limpar_ruido_visual(texto_novo).replace('\n', TOKEN_QUEBRA)
    
    a = ref_limpo.split()
    b = novo_limpo.split()
    
    # AQUI É O MOTOR DE COMPARAÇÃO
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    html_output = []
    eh_divergente = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = b[j1:j2]
        texto_trecho = " ".join(trecho).replace("[[BREAK]]", "\n")
        
        if tag == 'equal':
            html_output.append(texto_trecho)
        
        elif tag == 'replace':
            # Se substituiu texto, checa se é visível para marcar divergência
            if eh_conteudo_visivel(texto_trecho):
                html_output.append(f'<span class="highlight-yellow">{texto_trecho}</span>')
                eh_divergente = True
            else:
                html_output.append(texto_trecho)

        elif tag == 'insert':
            # Se inseriu texto novo
            if eh_conteudo_visivel(texto_trecho):
                html_output.append(f'<span class="highlight-yellow">{texto_trecho}</span>')
                eh_divergente = True
            else:
                html_output.append(texto_trecho)
        
        elif tag == 'delete':
            # Se apagou algo do original
            trecho_deletado = a[i1:i2]
            texto_deletado = " ".join(trecho_deletado).replace("[[BREAK]]", "")
            
            if eh_conteudo_visivel(texto_deletado):
                eh_divergente = True 
            
    resultado_final = " ".join(html_output)
    resultado_final = resultado_final.replace(" \n ", "\n").replace("\n ", "\n").replace(" \n", "\n")
    return resultado_final, eh_divergente

# ----------------- 4. EXTRAÇÃO DE TEXTO -----------------
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
                            is_bold = (s["flags"] & 16) or "bold" in font_props or "black" in font_props
                            if is_bold:
                                line_txt += f"<b>{content}</b>"
                            else:
                                line_txt += content
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
                    
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    if run.bold:
                        para_txt += f"<b>{run.text}</b>"
                    else:
                        para_txt += run.text
                text += para_txt + "\n\n"
        return text
    except Exception as e:
        return ""

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

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Conferência MKT")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Arquivo Anvisa", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("🎨 Arquivo MKT", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Analisando estrutura..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Erro: Arquivo vazio ou ilegível."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.
            
            INPUT TEXTO 1 (REF): 
            {t_anvisa[:150000]}
            
            INPUT TEXTO 2 (MKT): 
            {t_mkt[:150000]}

            SUA MISSÃO:
            1. **DATA DE APROVAÇÃO:** Procure EXATAMENTE pela frase "Esta bula foi atualizada conforme Bula Padrão aprovada pela Anvisa em (DATA)". Extraia APENAS essa data específica.
            
            2. **CONTEÚDO COMPLETO:** - Extraia TODO o texto entre um título e outro.
               - NÃO PARE no meio. NÃO RESUMA.
            
            3. **FORMATAÇÃO:**
               - MANTENHA as tags <b> e </b> originais. NÃO REMOVA O NEGRITO.
               - NÃO INVENTE negrito onde não tem.
               - NÃO CORRIJA O PORTUGUÊS. Copie ipsis litteris.

            LISTA DE SEÇÕES ESPERADAS: {SECOES_PACIENTE}

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto completo com <b> e \\n",
                        "texto_mkt": "Texto completo com <b> e \\n"
                    }}
                ]
            }}
            """
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                    response = model.generate_content(prompt, request_options={'retry': None})
                    break 
                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1: continue
                    else: st.error(f"Erro Fatal: {ultimo_erro}"); st.stop()

            if response:
                try:
                    resultado = json.loads(response.text)
                    data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                    data_mkt = resultado.get("data_anvisa_mkt", "Não encontrada")
                    dados_secoes = resultado.get("secoes", [])
                    secoes_finais = []
                    divergentes_count = 0

                    for item in dados_secoes:
                        titulo = item.get('titulo', '').strip()
                        txt_ref = item.get('texto_anvisa', '').strip()
                        txt_mkt = item.get('texto_mkt', '').strip()
                        
                        titulo_upper = titulo.upper()
                        eh_secao_blindada = any(blindada in titulo_upper for blindada in SECOES_SEM_COMPARACAO)

                        if eh_secao_blindada:
                            status = "CONFORME"
                            
                            if "DIZERES LEGAIS" in titulo_upper:
                                html_ref = destacar_datas(txt_ref) 
                                html_mkt = destacar_datas(txt_mkt) 
                            else:
                                html_ref = txt_ref
                                html_mkt = txt_mkt 
                            
                        else:
                            # Chama a nova função (agora atualizada)
                            html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                            status = "DIVERGENTE" if teve_diff else "CONFORME"
                            if teve_diff: divergentes_count += 1
                            html_ref = txt_ref

                        secoes_finais.append({
                            "titulo": titulo,
                            "texto_anvisa": html_ref.replace('\n', '<br>'),
                            "texto_mkt": html_mkt.replace('\n', '<br>'),
                            "status": status
                        })

                    st.markdown("### 📊 Resumo da Conferência")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Data Anvisa (Ref)", data_ref)
                    c2.metric("Data Anvisa (MKT)", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                    c3.metric("Seções", len(secoes_finais))

                    sub1, sub2 = st.columns(2)
                    sub1.info(f"✅ **Conformes:** {len(secoes_finais) - divergentes_count}")
                    if divergentes_count > 0: sub2.warning(f"⚠️ **Divergentes:** {divergentes_count}")
                    else: sub2.success("✨ **Divergências:** 0")

                    st.divider()

                    for item in secoes_finais:
                        status = item['status']
                        titulo = item['titulo']
                        
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon = "⚖️"; css = "border-info"; aberto = True
                        elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO):
                            icon = "🔒"; css = "border-ok"; aberto = False
                        elif status == "CONFORME":
                            icon = "✅"; css = "border-ok"; aberto = False
                        else:
                            icon = "⚠️"; css = "border-warn"; aberto = True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("📜 Referência")
                                st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("🎨 Validado")
                                st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro ao processar JSON: {e}")
    else:
        st.warning("Adicione os arquivos.")
