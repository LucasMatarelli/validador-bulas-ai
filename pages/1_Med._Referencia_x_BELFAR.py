import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import difflib
import re
import time

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE"
]

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def extract_text_from_file(uploaded_file):
    """Lê o PDF de forma bruta e PARA A LEITURA após a data da Anvisa."""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                text += page.get_text("text") + "\n\n"
        
        # Limpeza cirúrgica
        text = re.sub(r'(\w)-\s+(\w)', r'\1-\2', text)
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        
        # REGRA DE OURO: Cortar tudo que vem DEPOIS da data da Anvisa
        padrao_data = r'aprovada\s+pela\s+Anvisa\s+em\s*\d{2}/\d{2}/\d{4}'
        matches = list(re.finditer(padrao_data, text, re.IGNORECASE))
        
        if matches:
            ultimo_match = matches[-1] # Pega a data da Anvisa
            text = text[:ultimo_match.end()] # Faca de corte: descarta todo o resto
            
        return text
    except: 
        return ""

def achar_frases_divergentes(texto_ref, texto_novo):
    """Retorna duas listas: o que mudou na Referência e o que mudou na Belfar."""
    def limpar_espacos(t):
        t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
        return re.sub(r'[ \t]+', ' ', t) 
        
    texto_ref = limpar_espacos(texto_ref)
    texto_novo = limpar_espacos(texto_novo)

    tokens_ref = [t for t in re.split(r'(\s+)', texto_ref) if t]
    tokens_novo = [t for t in re.split(r'(\s+)', texto_novo) if t]

    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_novo, autojunk=False)
    matcher.set_seqs(tokens_ref, tokens_novo)
    
    divergencias_ref = []
    divergencias_mkt = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ['replace', 'delete']:
            frase = " ".join(tokens_ref[i1:i2]).strip()
            if len(frase) > 3: divergencias_ref.append(frase)
        if tag in ['replace', 'insert']:
            frase = " ".join(tokens_novo[j1:j2]).strip()
            if len(frase) > 3: divergencias_mkt.append(frase)
                
    return divergencias_ref, divergencias_mkt

def achar_datas_anvisa(texto):
    """Caça a frase da data da anvisa para pintar de azul."""
    padrao = r'aprovada\s+pela\s+Anvisa\s+em\s*\d{2}/\d{2}/\d{4}'
    return re.findall(padrao, texto, re.IGNORECASE)

# ----------------- 4. A MÁGICA: PINTAR OS PDFS LADO A LADO -----------------

def gerar_imagens_pdf_grifado(uploaded_file, amarelo, vermelho, azul):
    """Abre o PDF e aplica o marca-texto digital com cores específicas."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        # PINTA AS DIVERGÊNCIAS DE AMARELO
        for frase in amarelo:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 1, 0)) # RGB para Amarelo
                annot.update()

        # PINTA OS ERROS DE PORTUGUÊS DE VERMELHO
        for frase in vermelho:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0, 0)) # RGB para Vermelho
                annot.update()

        # PINTA A DATA DA ANVISA DE AZUL
        for frase in azul:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(0, 0.5, 1)) # RGB para Azul
                annot.update()

        # Tira a foto em alta resolução
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        imagens_geradas.append(pix.tobytes("png"))
        
    return imagens_geradas

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Auditor Visual de Bulas (Lado a Lado)")

tipo_bula = st.radio(
    "Escolha o Tipo de Bula:",
    ("Paciente", "Profissional"),
    horizontal=True
)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"], key="f2")

if st.button("🚀 Iniciar Auditoria Visual e Grifar PDFs"):
    
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada nos Secrets.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo arquivos até a Data da Anvisa..."):
            f1.seek(0); f2.seek(0)
            
            # Aqui ele lê e JÁ CORTA TUDO DEPOIS DA DATA DA ANVISA
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio, ilegível ou Data da Anvisa não encontrada."); st.stop()

            # IA caça os erros de português na Bula Belfar
            prompt = f"""
            Você é um Revisor Ortográfico Farmacêutico Rigoroso.
            INPUT TEXTO DA BELFAR: {t_mkt[:150000]}
            
            SUA MISSÃO:
            Me liste APENAS palavras ou frases curtas exatas deste texto que contenham ERROS DE GRAMÁTICA ou ORTOGRAFIA do Português. 
            Não liste termos médicos corretos.

            SAÍDA JSON:
            {{
                "erros_ortograficos": ["palavra errada 1", "frase com erro 2"]
            }}
            """
            
            response = None
            sucesso = False

            for key in keys_validas:
                if sucesso: break
                genai.configure(api_key=key)
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model_instance = genai.GenerativeModel(
                            modelo, 
                            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                        )
                        response = model_instance.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total da IA ao buscar erros de gramática.")
                st.stop()
            
            try:
                # Blindagem contra o bug do GitHub (multiplicação de crases)
                tag_inicio = chr(96) * 3 + "json"
                tag_fim = chr(96) * 3
                
                texto_resposta = response.text.replace(tag_inicio, "").replace(tag_fim, "").strip()
                resultado = json.loads(texto_resposta)
                
                # Pega a lista de erros de português (Vai ser pintada de VERMELHO)
                erros_vermelhos = resultado.get("erros_ortograficos", [])
                
                # Compara as diferenças (Vai ser pintado de AMARELO)
                divergencias_ref, divergencias_mkt = achar_frases_divergentes(t_anvisa, t_mkt)
                
                # Busca as datas (Vai ser pintado de AZUL)
                datas_azuis_ref = achar_datas_anvisa(t_anvisa)
                datas_azuis_mkt = achar_datas_anvisa(t_mkt)

                with st.spinner("Pintando os PDFs e gerando a visão Lado a Lado..."):
                    f1.seek(0)
                    f2.seek(0)
                    
                    # Gera as fotos com as marcações de cor nas coordenadas corretas
                    fotos_ref = gerar_imagens_pdf_grifado(f1, divergencias_ref, [], datas_azuis_ref)
                    fotos_mkt = gerar_imagens_pdf_grifado(f2, divergencias_mkt, erros_vermelhos, datas_azuis_mkt)

                    # LEGENDA DE CORES
                    st.markdown("""
                    ### 🎨 Legenda da Auditoria:
                    * 🟡 **Amarelo:** Divergência de texto (adicionado, removido ou alterado).
                    * 🔴 **Vermelho:** Erro de ortografia ou gramática (Apenas na BELFAR).
                    * 🔵 **Azul:** Assinatura/Data da Anvisa (A comparação para aqui).
                    """)
                    st.divider()

                    # Renderiza os PDFs Lado a Lado
                    max_pages = max(len(fotos_ref), len(fotos_mkt))
                    
                    for i in range(max_pages):
                        st.markdown(f"#### Página {i+1}")
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("📜 Bula Referência")
                            if i < len(fotos_ref):
                                st.image(fotos_ref[i], use_container_width=True)
                                
                        with col_dir:
                            st.caption("📜 Bula BELFAR")
                            if i < len(fotos_mkt):
                                st.image(fotos_mkt[i], use_container_width=True)
                        st.divider()

            except Exception as e:
                st.error(f"Erro ao processar e pintar o PDF: {e}")
    else:
        st.warning("Adicione os arquivos PDF.")
