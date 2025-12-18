import streamlit as st
import re
import difflib

# Configuração da página
st.set_page_config(page_title="Validador de Bulas", layout="wide")

def extrair_conteudo_entre_secoes(texto_completo, titulo_atual, titulo_proximo):
    """
    Extrai o texto estritamente entre o fim do titulo_atual e o inicio do titulo_proximo.
    """
    if not texto_completo:
        return ""

    # Escapa os títulos para evitar erros de regex com caracteres especiais
    t_atual = re.escape(titulo_atual)
    
    # Se houver uma próxima seção definida, busca até ela. 
    # Se não (for a última), busca até o fim do arquivo ($).
    if titulo_proximo:
        t_prox = re.escape(titulo_proximo)
        pattern = f"{t_atual}(.*?){t_prox}"
    else:
        pattern = f"{t_atual}(.*)$"

    # re.DOTALL faz o ponto (.) pegar quebras de linha também
    # re.IGNORECASE permite que o título seja detectado mesmo com maiúsculas/minúsculas diferentes
    match = re.search(pattern, texto_completo, re.DOTALL | re.IGNORECASE)

    if match:
        # Retorna o grupo 1 (conteúdo do meio) sem espaços nas pontas
        return match.group(1).strip()
    else:
        return "Seção não encontrada ou ordem dos títulos incorreta."

def processar_comparacao_visual(texto_original, texto_novo):
    """
    Compara dois textos e retorna HTML:
    - Amarelo: Diferenças (o que existe no novo e não no original).
    - Azul: Datas no formato dd/mm/aaaa.
    """
    
    # 1. COMPARAÇÃO (AMARELO)
    matcher = difflib.SequenceMatcher(None, texto_original, texto_novo)
    resultado_html = []

    # Itera sobre os blocos de diferença
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = texto_novo[j1:j2]
        
        if opcode == 'equal':
            # Texto igual: mantém normal
            resultado_html.append(trecho)
        elif opcode in ('replace', 'insert'):
            # Texto diferente (alterado ou inserido): marca de amarelo
            # Usamos background-color yellow
            resultado_html.append(f'<span style="background-color: #FFEB3B; color: black;">{trecho}</span>')
        elif opcode == 'delete':
            # Se algo foi deletado do original, não mostramos no texto final (ou poderíamos usar strike)
            pass

    texto_final = "".join(resultado_html)

    # 2. DATA DA ANVISA (AZUL)
    # Procura padrões de data (dd/mm/aaaa ou dd/mm/aa)
    # A regex \b garante que pegue a data inteira
    padrao_data = r"\b(\d{2}/\d{2}/\d{2,4})\b"
    
    # Substitui a data encontrada por ela mesma envolvida em azul
    # Isso funciona mesmo se a data estiver dentro de um span amarelo (o azul terá prioridade na fonte)
    texto_final = re.sub(
        padrao_data, 
        r'<span style="color: blue; font-weight: bold;">\1</span>', 
        texto_final
    )

    # Converte quebras de linha do texto (\n) para HTML (<br>) para exibir corretamente
    return texto_final.replace("\n", "<br>")

# --- INTERFACE DO STREAMLIT ---

st.title("💊 Validador de Bulas - Comparação de Seções")

st.info("Cole os textos completos dos arquivos abaixo para testar a extração e validação.")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Arquivo Original (Referência)")
    texto_arq1 = st.text_area("Cole o texto do PDF 1 aqui:", height=300, placeholder="Ex: DIZERES LEGAIS\nFarm. Resp.: Dr. João...\n...")

with col2:
    st.subheader("Arquivo Novo (Para Validar)")
    texto_arq2 = st.text_area("Cole o texto do PDF 2 aqui:", height=300, placeholder="Ex: DIZERES LEGAIS\nFarm. Resp.: Dr. João...\nData: 15/10/2025...")

st.markdown("---")
st.subheader("Configuração da Seção")

# Inputs para definir quais títulos delimitam o texto que queremos analisar
c_input1, c_input2 = st.columns(2)
titulo_secao_atual = c_input1.text_input("Título da Seção para extrair:", value="DIZERES LEGAIS")
titulo_proxima_secao = c_input2.text_input("Título da Próxima Seção (Pare ao encontrar):", value="HISTÓRICO DE ALTERAÇÃO", help="Deixe em branco se for a última seção do arquivo.")

if st.button("Validar Seção"):
    if texto_arq1 and texto_arq2 and titulo_secao_atual:
        
        # 1. Extração
        conteudo_1 = extrair_conteudo_entre_secoes(texto_arq1, titulo_secao_atual, titulo_proxima_secao)
        conteudo_2 = extrair_conteudo_entre_secoes(texto_arq2, titulo_secao_atual, titulo_proxima_secao)
        
        # Mostra o texto cru extraído (para debug, se quiser pode remover depois)
        with st.expander("Ver texto extraído (Sem formatação)"):
            st.text(f"Texto 1 extraído:\n{conteudo_1}")
            st.markdown("---")
            st.text(f"Texto 2 extraído:\n{conteudo_2}")

        # 2. Processamento Visual (Amarelo e Azul)
        html_final = processar_comparacao_visual(conteudo_1, conteudo_2)

        # 3. Exibição do Resultado
        st.markdown("### Resultado da Validação:")
        st.markdown(
            f"""
            <div style="border:1px solid #ccc; padding: 20px; border-radius: 5px; background-color: #f9f9f9; font-family: sans-serif; line-height: 1.6;">
                {html_final}
            </div>
            """, 
            unsafe_allow_html=True
        )
        
        st.caption("Legenda: Fundo Amarelo = Divergência de texto | Texto Azul = Data encontrada")
        
    else:
        st.warning("Por favor, preencha os textos e o título da seção.")
