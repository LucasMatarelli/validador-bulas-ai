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
    """Abre o PDF e aplica o marca-texto translúcido (Pastel) com Altíssima Resolução."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        # AMARELO PASTEL (Divergências Inteligentes) - Opacidade 25%
        for frase in amarelo:
            if not frase or len(str(frase).strip()) < 4: continue
            
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 1, 0))
                annot.set_opacity(0.25)
                annot.update()

        # VERMELHO PASTEL (Erros Reais de Português) - Opacidade 25%
        for frase in vermelho:
            if not frase or len(str(frase).strip()) < 4: continue
            
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0, 0)) 
                annot.set_opacity(0.25)
                annot.update()

        # AZUL PASTEL (Data da Anvisa) - Opacidade 25%
        for frase in azul:
            if not frase or len(str(frase).strip()) < 4: continue
            
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(0, 0.5, 1)) 
                annot.set_opacity(0.25)
                annot.update()

        # AQUI ESTÁ A CORREÇÃO DE QUALIDADE:
        # Aumentamos o Zoom de 2x para 4x. Isso garante nitidez de monitores 4K/Retina.
        zoom = 4
        matriz_alta_resolucao = fitz.Matrix(zoom, zoom)
        
        pix = page.get_pixmap(matrix=matriz_alta_resolucao)
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
        texto_resposta_ia = ""
        sucesso_ia = False
        
        # SPINNER 1: APENAS A INTELIGÊNCIA ARTIFICIAL
        with st.spinner("🧠 Lendo arquivos e analisando com IA (Isso pode levar de 1 a 2 minutos)..."):
            f1.seek(0); f2.seek(0)
            
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível.")
                st.stop()

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

            SAÍDA JSON OBRIGATÓRIA (sem formatação markdown, apenas o json):
            {{
                "divergencias_belfar": ["trecho exato divergente 1", "trecho exato divergente 2"],
                "erros_ortograficos": ["trecho com erro de gramatica"],
                "data_anvisa": ["aprovada pela Anvisa em..."]
            }}
            """

            for key in keys_validas:
                if sucesso_ia: break
                genai.configure(api_key=key)
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model_instance = genai.GenerativeModel(
                            modelo, 
                            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                        )
                        response = model_instance.generate_content(prompt)
                        texto_resposta_ia = response.text
                        sucesso_ia = True
                        break 
                    except Exception as e:
                        time.sleep(0.5)
                        continue

        if not sucesso_ia:
            st.error("❌ Falha Total da IA na Auditoria. (Pode ser excesso de cota ou erro de API).")
            st.stop()
            
        # SPINNER 2: PINTURA DOS PDFS (Separado e isolado para não dar o bug do infinito)
        with st.spinner("🖌️ Auditoria concluída! Pintando os PDFs em Alta Resolução e montando a tela..."):
            try:
                tag_inicio = chr(96) * 3 + "json"
                tag_fim = chr(96) * 3
                texto_limpo = texto_resposta_ia.replace(tag_inicio, "").replace(tag_fim, "").strip()
                
                # Caso a IA retorne "json" solto no começo
                if texto_limpo.startswith("json"):
                    texto_limpo = texto_limpo[4:].strip()

                resultado = json.loads(texto_limpo)
                
                # Proteção extra contra nulos na API
                divergencias_mkt = resultado.get("divergencias_belfar") or []
                erros_vermelhos = resultado.get("erros_ortograficos") or []
                datas_azuis_mkt = resultado.get("data_anvisa") or []

                f1.seek(0); f2.seek(0)
                
                fotos_ref = gerar_imagens_pdf_grifado(f1, [], [], [])
                fotos_mkt = gerar_imagens_pdf_grifado(f2, divergencias_mkt, erros_vermelhos, datas_azuis_mkt)

            except Exception as e:
                st.error("Erro interno ao processar a pintura do PDF.")
                st.code(texto_resposta_ia)
                st.stop()

        # RENDERIZAÇÃO FINAL NA TELA (Só executa se tudo der certo)
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

    else:
        st.warning("Adicione os arquivos PDF para iniciar.")
