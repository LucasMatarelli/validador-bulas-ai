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
    """Lê o PDF e CORTA A LEITURA após a data da Anvisa."""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                text += page.get_text("text") + "\n\n"
        
        # Limpeza cirúrgica
        text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text) # Remove quebra de hifen
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        
        # Faca de corte: IGNORA DIZERES LEGAIS
        padrao_data = r'aprovada\s+pela\s+Anvisa\s+em\s*\d{2}/\d{2}/\d{4}'
        matches = list(re.finditer(padrao_data, text, re.IGNORECASE))
        
        if matches:
            ultimo_match = matches[-1]
            text = text[:ultimo_match.end()] 
            
        return text
    except: 
        return ""

def achar_frases_divergentes(texto_ref, texto_novo):
    """Compara e devolve frases com CONTEXTO (para o PDF não pintar a mesma palavra em todo lugar)."""
    def limpar_espacos(t):
        t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
        return re.sub(r'[ \t\n\r]+', ' ', t).strip()
        
    texto_ref = limpar_espacos(texto_ref)
    texto_novo = limpar_espacos(texto_novo)

    tokens_ref = texto_ref.split()
    tokens_novo = texto_novo.split()

    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_novo, autojunk=False)
    
    divergencias_ref = []
    divergencias_mkt = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ['replace', 'delete']:
            # Pega 2 palavras antes e 2 depois para ter certeza que é um lugar único no PDF
            start = max(0, i1 - 2)
            end = min(len(tokens_ref), i2 + 2)
            frase = " ".join(tokens_ref[start:end]).strip()
            if len(frase) > 5: divergencias_ref.append(frase)
            
        if tag in ['replace', 'insert']:
            start = max(0, j1 - 2)
            end = min(len(tokens_novo), j2 + 2)
            frase = " ".join(tokens_novo[start:end]).strip()
            if len(frase) > 5: divergencias_mkt.append(frase)
                
    return divergencias_ref, divergencias_mkt

def achar_datas_anvisa(texto):
    """Caça a data da anvisa."""
    padrao = r'aprovada\s+pela\s+Anvisa\s+em\s*\d{2}/\d{2}/\d{4}'
    return re.findall(padrao, texto, re.IGNORECASE)

# ----------------- 4. A MÁGICA: PDFS PINTADOS -----------------

def gerar_imagens_pdf_grifado(uploaded_file, amarelo, vermelho, azul):
    """Aplica marca-texto translúcido (pastel) para não esconder a letra."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        # PINTA AS DIVERGÊNCIAS (AMARELO PASTEL)
        for frase in amarelo:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0.9, 0.2)) # Amarelo mais suave
                annot.set_opacity(0.4) # Deixa transparente (consegue ler por baixo)
                annot.update()

        # PINTA ERROS DE PORTUGUÊS (VERMELHO PASTEL)
        for frase in vermelho:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0.4, 0.4)) # Vermelho suave/rosado
                annot.set_opacity(0.4)
                annot.update()

        # PINTA DATA DA ANVISA (AZUL PASTEL)
        for frase in azul:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(0.4, 0.7, 1)) # Azul claro
                annot.set_opacity(0.4)
                annot.update()

        # Zoom 2x para qualidade de leitura
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
        st.error("Erro Crítico: Nenhuma API Key encontrada.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo arquivos e cortando Dizeres Legais..."):
            f1.seek(0); f2.seek(0)
            
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio, ilegível ou Data da Anvisa não encontrada."); st.stop()

            # IA caça erros de português COM CONTEXTO
            prompt = f"""
            Você é um Revisor Ortográfico Farmacêutico Rigoroso.
            INPUT TEXTO DA BELFAR: {t_mkt[:150000]}
            
            SUA MISSÃO:
            Liste trechos deste texto que contenham ERROS CLAROS DE GRAMÁTICA ou ORTOGRAFIA do Português.
            REGRA CRÍTICA: Retorne a FRASE INTEIRA onde o erro está (coloque cerca de 3 palavras antes e 3 depois do erro para dar contexto). 
            Se retornar apenas a palavra solta, o sistema vai bugar.
            Não liste termos médicos corretos. Se não houver erros, retorne uma lista vazia.

            SAÍDA JSON:
            {{
                "erros_ortograficos": ["texto de contexto antes PALAVRA_ERRADA texto de contexto depois"]
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
                st.error("❌ Falha Total da IA ao buscar erros.")
                st.stop()
            
            try:
                # Blindagem contra o bug de crases do GitHub
                tag_inicio = chr(96) * 3 + "json"
                tag_fim = chr(96) * 3
                
                texto_resposta = response.text.replace(tag_inicio, "").replace(tag_fim, "").strip()
                resultado = json.loads(texto_resposta)
                
                erros_vermelhos = resultado.get("erros_ortograficos", [])
                
                # Compara textos para achar diferenças
                divergencias_ref, divergencias_mkt = achar_frases_divergentes(t_anvisa, t_mkt)
                
                # Acha as datas azuis
                datas_azuis_ref = achar_datas_anvisa(t_anvisa)
                datas_azuis_mkt = achar_datas_anvisa(t_mkt)

                with st.spinner("Pintando PDFs e gerando a visão Lado a Lado (Pode levar alguns segundos)..."):
                    f1.seek(0)
                    f2.seek(0)
                    
                    fotos_ref = gerar_imagens_pdf_grifado(f1, divergencias_ref, [], datas_azuis_ref)
                    fotos_mkt = gerar_imagens_pdf_grifado(f2, divergencias_mkt, erros_vermelhos, datas_azuis_mkt)

                    st.markdown("""
                    ### 🎨 Legenda da Auditoria:
                    * 🟡 **Amarelo (Opacidade 40%):** Divergência de texto (adicionado, removido ou alterado).
                    * 🔴 **Vermelho (Opacidade 40%):** Erro de ortografia ou gramática (BELFAR).
                    * 🔵 **Azul (Opacidade 40%):** Assinatura/Data da Anvisa.
                    * 🛑 **Atenção:** Tudo o que está após a data da Anvisa foi sumariamente ignorado.
                    """)
                    st.divider()

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
