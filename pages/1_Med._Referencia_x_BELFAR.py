import streamlit as st
import pdfplumber
import re
import difflib

st.set_page_config(page_title="Validador Belfar", layout="wide")

# --- FUNÇÕES ---

def ler_pdf(arquivo):
    """Lê o arquivo PDF carregado e retorna todo o texto."""
    texto_completo = ""
    with pdfplumber.open(arquivo) as pdf:
        for page in pdf.pages:
            texto_completo += page.extract_text() + "\n"
    return texto_completo

def extrair_secao(texto, titulo_inicio, titulo_fim):
    """Recorta o texto entre o título de início e o título de fim."""
    if not texto: return ""
    
    t_inicio = re.escape(titulo_inicio)
    t_fim = re.escape(titulo_fim)
    
    # Procura algo que começa com o titulo_inicio e vai até o titulo_fim
    # re.DOTALL faz pegar quebras de linha
    padrao = f"{t_inicio}(.*?){t_fim}"
    
    # Tenta encontrar com o título de fim definido
    match = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    
    # Se não achar o título de fim (ex: é a última seção), tenta pegar até o final do arquivo
    if not match:
        padrao_fim = f"{t_inicio}(.*)$"
        match = re.search(padrao_fim, texto, re.DOTALL | re.IGNORECASE)

    if match:
        return match.group(1).strip()
    return "" # Retorna vazio se não achar o título de início

def gerar_html_comparacao(texto_ref, texto_novo):
    """Gera o HTML com o amarelo (diferenças) e azul (datas)."""
    matcher = difflib.SequenceMatcher(None, texto_ref, texto_novo)
    html_output = []

    # 1. DIFERENÇAS (AMARELO)
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = texto_novo[j1:j2]
        if opcode == 'equal':
            html_output.append(trecho)
        elif opcode in ('replace', 'insert'):
            html_output.append(f'<span style="background-color: #FFEB3B; color: black;">{trecho}</span>')
    
    texto_processado = "".join(html_output)

    # 2. DATAS (AZUL)
    # Regex para datas dd/mm/aaaa ou dd/mm/aa
    padrao_data = r"\b(\d{2}/\d{2}/\d{2,4})\b"
    texto_processado = re.sub(
        padrao_data, 
        r'<span style="color: blue; font-weight: bold;">\1</span>', 
        texto_processado
    )

    return texto_processado.replace("\n", "<br>")

# --- INTERFACE ---

st.title("💊 Validador de Bulas Automático")

# 1. Seleção do Tipo de Bula
tipo_bula = st.radio("Qual o tipo da bula?", ["Paciente", "Profissional"], horizontal=True)

# Define os títulos de corte automaticamente baseados na escolha
# (Você pode ajustar esses títulos fixos se na Belfar for diferente)
if tipo_bula == "Paciente":
    titulo_corte_inicio = "DIZERES LEGAIS"
    titulo_corte_fim = "HISTÓRICO DE ALTERAÇÃO" # Ou outro título que venha depois
else: # Profissional
    titulo_corte_inicio = "DIZERES LEGAIS"
    titulo_corte_fim = "HISTÓRICO DE ALTERAÇÃO"

st.markdown("---")

# 2. Upload dos Arquivos
col1, col2 = st.columns(2)
with col1:
    arq_ref = st.file_uploader("📂 Arquivo Original (Referência)", type="pdf")
with col2:
    arq_novo = st.file_uploader("📂 Arquivo Novo (Para Validar)", type="pdf")

# 3. Processamento Automático
if arq_ref and arq_novo:
    with st.spinner("Lendo PDFs e extraindo seção..."):
        # Ler textos
        texto_ref_full = ler_pdf(arq_ref)
        texto_novo_full = ler_pdf(arq_novo)

        # Recortar apenas a seção desejada
        secao_ref = extrair_secao(texto_ref_full, titulo_corte_inicio, titulo_corte_fim)
        secao_novo = extrair_secao(texto_novo_full, titulo_corte_inicio, titulo_corte_fim)

        if not secao_ref or not secao_novo:
            st.error(f"Não consegui encontrar a seção '{titulo_corte_inicio}' em um dos arquivos. Verifique se o PDF é pesquisável (texto selecionável).")
        else:
            # Gerar visualização
            html_final = gerar_html_comparacao(secao_ref, secao_novo)

            st.success("Comparação realizada!")
            st.markdown("### Resultado (Dizeres Legais):")
            st.markdown(
                f"""
                <div style="border:1px solid #ccc; padding: 20px; border-radius: 5px; background-color: #f9f9f9; line-height: 1.6;">
                    {html_final}
                </div>
                """, 
                unsafe_allow_html=True
            )
else:
    st.info("👆 Solta os arquivos ali em cima pra começar.")
