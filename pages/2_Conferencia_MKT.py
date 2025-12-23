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
        white-space: pre-wrap; /* ESSENCIAL PARA MANTER QUEBRA DE LINHA */
        text-align: left;
    }
    
    /* Cores de Destaque */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; font-weight: bold;
    }
    
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }
    
    /* Bordas de Status */
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
    texto = re.sub(r'[\._]{3,}', ' ', texto) # Remove pontilhados longos
    texto = re.sub(r'[ \t]+', ' ', texto)     # Remove excesso de espaços
    return texto.strip()

def normalizar_para_comparacao(texto):
    if not texto: return ""
    return unicodedata.normalize('NFKD', texto)

def destacar_datas(texto):
    """
    Procura padrões de data (dd/mm/aaaa, mm/aaaa, etc) e aplica highlight azul.
    Não altera o texto, apenas envolve em HTML.
    """
    # Regex simples para datas comuns em bulas
    padrao_data = r'(\d{2}/\d{2}/\d{4}|\d{2}/\d{4}|\d{2}\sde\s[a-zA-Zç]+\sde\s\d{4})'
    
    def replacer(match):
        return f'<span class="highlight-blue">{match.group(0)}</span>'
    
    return re.sub(padrao_data, replacer, texto)

def gerar_diff_html(texto_ref, texto_novo):
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    TOKEN_QUEBRA = " [[BREAK]] "
    ref_limpo = limpar_ruido_visual(texto_ref).replace('\n', TOKEN_QUEBRA)
    novo_limpo = limpar_ruido_visual(texto_novo).replace('\n', TOKEN_QUEBRA)
    
    ref_norm = normalizar_para_comparacao(ref_limpo)
    novo_norm = normalizar_para_comparacao(novo_limpo)

    a = ref_norm.split()
    b = novo_norm.split()
    
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    html_output = []
    eh_divergente = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = b[j1:j2]
        texto_trecho = " ".join(trecho).replace("[[BREAK]]", "\n")
        
        if tag == 'equal':
            html_output.append(texto_trecho)
        elif tag == 'replace' or tag == 'insert':
            if texto_trecho.strip():
                html_output.append(f'<span class="highlight-yellow">{texto_trecho}</span>')
                eh_divergente = True
            else:
                html_output.append(texto_trecho)
        elif tag == 'delete':
            eh_divergente = True 
            
    resultado_final = " ".join(html_output)
    resultado_final = resultado_final.replace(" \n ", "\n").replace("\n ", "\n").replace(" \n", "\n")
    return resultado_final, eh_divergente

# ----------------- 4. EXTRAÇÃO DE TEXTO AJUSTADA -----------------
def extract_text_from_file(uploaded_file):
    """Extrai texto com sort=True e melhor separação de blocos."""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                # sort=True para ler colunas corretamente
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
                        block_text += line_txt + " " # Espaço ao fim da linha para não colar palavras
                    
                    # Adiciona o bloco com quebra dupla para separar parágrafos visualmente
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

# Lista de seções que NÃO devem ser comparadas (apenas exibidas)
SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Conferência MKT")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Anvisa (Referência)", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("🎨 Arte MKT (Para Validar)", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Analisando estrutura e extraindo conteúdo..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Erro: Arquivo vazio ou ilegível."); st.stop()

            # PROMPT REFORÇADO PARA FIDELIDADE TOTAL
            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos.
            
            INPUT TEXTO 1 (REF): 
            {t_anvisa[:120000]}
            
            INPUT TEXTO 2 (MKT): 
            {t_mkt[:120000]}

            SUA MISSÃO:
            1. Localize as seções nos dois textos.
            2. Extraia o conteúdo IPSIS LITTERIS (exatamente como está).
            3. NÃO CORRIJA O PORTUGUÊS. NÃO INVENTE PALAVRAS. Mantenha erros de digitação.
            4. Respeite as quebras de linha.

            LISTA DE SEÇÕES: {SECOES_PACIENTE}

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto exato da anvisa",
                        "texto_mkt": "Texto exato da arte mkt"
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
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_mkt = resultado.get("data_anvisa_mkt", "-")
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
                            # LÓGICA ESPECIAL PARA SEÇÕES BLINDADAS (SEM DIFF)
                            status = "CONFORME"
                            
                            # Se for DIZERES LEGAIS, aplica highlight azul nas datas
                            if "DIZERES LEGAIS" in titulo_upper:
                                html_mkt = destacar_datas(txt_mkt)
                            else:
                                html_mkt = txt_mkt # Texto puro, original
                            
                            # Referência também fica pura
                            html_ref = txt_ref 

                        else:
                            # LÓGICA PADRÃO (COM DIFF) PARA AS DEMAIS
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
                    c1.metric("Ref.", data_ref)
                    c2.metric("MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                    c3.metric("Seções", len(secoes_finais))

                    sub1, sub2 = st.columns(2)
                    sub1.info(f"✅ **Conformes:** {len(secoes_finais) - divergentes_count}")
                    if divergentes_count > 0: sub2.warning(f"⚠️ **Divergentes:** {divergentes_count}")
                    else: sub2.success("✨ **Divergências:** 0")

                    st.divider()

                    for item in secoes_finais:
                        status = item['status']
                        titulo = item['titulo']
                        
                        # Ícones e cores
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon = "⚖️"; css = "border-info"; aberto = True
                        elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO):
                            # Outras seções blindadas ficam com ícone de info e borda azul também, ou verde
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
