import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
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

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def extract_text_from_file(uploaded_file):
    """Lê o PDF bruto para dar contexto à IA."""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                text += page.get_text("text") + "\n\n"
        
        # Remove hifens de quebra de página e rodapés inúteis
        text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        return text
    except: 
        return ""

# ----------------- 4. A MÁGICA: PINTAR OS PDFS LADO A LADO -----------------

def gerar_imagens_pdf_grifado(uploaded_file, amarelo, vermelho, azul):
    """Abre o PDF e aplica o marca-texto translúcido (Pastel) para leitura fácil."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        # AMARELO PASTEL (Divergências Inteligentes) - Opacidade 25%
        for frase in amarelo:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 1, 0))
                annot.set_opacity(0.25)
                annot.update()

        # VERMELHO PASTEL (Erros Reais de Português) - Opacidade 25%
        for frase in vermelho:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0, 0)) 
                annot.set_opacity(0.25)
                annot.update()

        # AZUL PASTEL (Data da Anvisa) - Opacidade 25%
        for frase in azul:
            for area in page.search_for(frase):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(0, 0.5, 1)) 
                annot.set_opacity(0.25)
                annot.update()

        # Print em alta resolução (Zoom 2x)
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
        with st.spinner("Lendo arquivos..."):
            f1.seek(0); f2.seek(0)
            
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível."); st.stop()

            # IA FAZ A AUDITORIA INTELIGENTE AGORA (Substitui o difflib)
            prompt = f"""
            Você é um Auditor Farmacêutico Sênior. 
            Audite a bula BELFAR usando a bula REFERÊNCIA como base.
            
            REFERÊNCIA: {t_anvisa[:150000]}
            BELFAR: {t_mkt[:150000]}
            
            REGRAS DE OURO CRÍTICAS:
            1. DIVERGÊNCIAS (Amarelo): Liste trechos da BELFAR onde a informação farmacêutica, indicação, efeito colateral ou dosagem foi ALTERADA, ADICIONADA ou OMITIDA incorretamente.
               - IGNORE mudanças de maiúsculas/minúsculas, layout, quebras de linha ou sinônimos óbvios.
               - IGNORE COMPLETAMENTE as informações de Empresa (Nomes da empresa, CNPJ, Farmacêutico responsável, Endereços, SAC, Códigos de barras). Isso é naturalmente diferente e NÃO DEVE ser apontado.
               - Para cada erro real achado, retorne exatamente o trecho da bula BELFAR (entre 3 a 8 palavras contínuas) para que eu possa grifar na tela.

            2. ERROS DE PORTUGUÊS (Vermelho): Liste erros graves de digitação ou gramática na BELFAR.
               - NUNCA aponte nomes de doenças (ex: Sjögren, Alzheimer), compostos (ex: norfloxacino) ou termos médicos.
               - Se tiver dúvida, NÃO aponte. Devolva o trecho exato (de 2 a 5 palavras).

            3. DATA DA ANVISA (Azul): Devolva a frase exata contendo a data de aprovação na bula BELFAR (ex: "aprovada pela Anvisa em 05/02/2025").

            Se não achar divergências ou erros ortográficos, retorne listas vazias [].

            SAÍDA JSON OBRIGATÓRIA:
            {{
                "divergencias_belfar": ["trecho exato divergente 1", "trecho exato divergente 2"],
                "erros_ortograficos": ["trecho com erro de gramatica"],
                "data_anvisa": ["aprovada pela Anvisa em..."]
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
                st.error("❌ Falha Total da IA na Auditoria.")
                st.stop()
            
            try:
                # Blindagem contra o bug de crases do GitHub
                tag_inicio = chr(96) * 3 + "json"
                tag_fim = chr(96) * 3
                
                texto_resposta = response.text.replace(tag_inicio, "").replace(tag_fim, "").strip()
                resultado = json.loads(texto_resposta)
                
                divergencias_mkt = resultado.get("divergencias_belfar", [])
                erros_vermelhos = resultado.get("erros_ortograficos", [])
                datas_azuis_mkt = resultado.get("data_anvisa", [])

                with st.spinner("Pintando os PDFs e montando a tela Lado a Lado..."):
                    f1.seek(0)
                    f2.seek(0)
                    
                    # Gera as fotos com as marcações translúcidas (A Referência fica limpa ou só com Azul da data)
                    fotos_ref = gerar_imagens_pdf_grifado(f1, [], [], []) # Referência não leva amarelo/vermelho aqui pra ficar limpa visualmente
                    fotos_mkt = gerar_imagens_pdf_grifado(f2, divergencias_mkt, erros_vermelhos, datas_azuis_mkt)

                    st.markdown("""
                    ### 🎨 Legenda da Auditoria Inteligente:
                    * 🟡 **Amarelo (Suave):** Divergência real de conteúdo (ignora layout e cabeçalhos).
                    * 🔴 **Vermelho (Suave):** Erro de ortografia (ignora termos médicos e nomes de doenças).
                    * 🔵 **Azul (Suave):** Data da Anvisa.
                    """)
                    st.divider()

                    max_pages = max(len(fotos_ref), len(fotos_mkt))
                    
                    for i in range(max_pages):
                        st.markdown(f"#### Página {i+1}")
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("📜 Bula Referência (Visão Limpa)")
                            if i < len(fotos_ref):
                                st.image(fotos_ref[i], use_container_width=True)
                                
                        with col_dir:
                            st.caption("📜 Bula BELFAR (Auditoria IA)")
                            if i < len(fotos_mkt):
                                st.image(fotos_mkt[i], use_container_width=True)
                        st.divider()

            except Exception as e:
                st.error(f"Erro ao desenhar o PDF: {e}")
                st.code(response.text)
    else:
        st.warning("Adicione os arquivos PDF para iniciar.")
