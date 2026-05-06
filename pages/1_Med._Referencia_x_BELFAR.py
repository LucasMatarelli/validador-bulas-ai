import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import re
import time

# ----------------- 1. CONFIG PÁGINA -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")
st.markdown('<style>[data-testid="stHeader"]{visibility:hidden;}</style>', unsafe_allow_html=True)

# ----------------- 2. CONSTANTES -----------------
MODELOS_PARA_TENTAR = [
    "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES","COMPOSIÇÃO",
    "PARA QUE ESTE MEDICAMENTO É INDICADO","COMO ESTE MEDICAMENTO FUNCIONA?",
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?","O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?","COMO DEVO USAR ESTE MEDICAMENTO?",
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES","COMPOSIÇÃO","INDICAÇÕES","RESULTADOS DE EFICÁCIA",
    "CARACTERÍSTICAS FARMACOLÓGICAS","CONTRAINDICAÇÕES","ADVERTÊNCIAS E PRECAUÇÕES",
    "INTERAÇÕES MEDICAMENTOSAS","CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
    "POSOLOGIA E MODO DE USAR","REAÇÕES ADVERSAS","SUPERDOSE","DIZERES LEGAIS"
]

# ----------------- 3. EXTRAÇÃO DE TEXTO DO PDF -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n"
        # Une hífens de quebra de linha
        text = re.sub(r'(\w)-\s*\n(\w)', r'\1\2', text)
        return text
    except:
        return ""

# ----------------- 4. PINTURA DOS PDFs -----------------
def gerar_imagens_pdf_grifado(uploaded_file, amarelo=None, vermelho=None, azul=None):
    amarelo  = amarelo  or []
    vermelho = vermelho or []
    azul     = azul     or []

    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens = []

    for page in doc:
        # Pinta Amarelo (Divergências IA)
        for frase in amarelo:
            frase = str(frase).strip()
            if len(frase) < 5: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0.85, 0))
                a.set_opacity(0.45)
                a.update()

        # Pinta Vermelho (Erros)
        for frase in vermelho:
            frase = str(frase).strip()
            if len(frase) < 4: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0, 0))
                a.set_opacity(0.40)
                a.update()

        # Pinta Azul (Data Anvisa)
        for frase in azul:
            frase = str(frase).strip()
            if len(frase) < 4: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(0, 0.5, 1))
                a.set_opacity(0.40)
                a.update()

        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4))
        imagens.append(pix.tobytes("png"))

    return imagens

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Auditor Visual de Bulas (Com IA Semântica)")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente","Profissional"), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR",     type=["pdf"], key="f2")

if st.button("🚀 Iniciar Auditoria Visual e Grifar PDFs"):

    keys_validas = [k for k in [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ] if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada nos Secrets.")
        st.stop()

    if not (f1 and f2):
        st.warning("Adicione os dois arquivos PDF para iniciar.")
        st.stop()

    secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

    texto_resposta_ia = ""
    sucesso_ia = False

    with st.spinner("🧠 IA Analisando conteúdo semântico (Isso será bem mais rápido agora)..."):
        f1.seek(0); f2.seek(0)
        t_ref    = extract_text_from_file(f1)
        t_belfar = extract_text_from_file(f2)

        if len(t_ref) < 20 or len(t_belfar) < 20:
            st.error("Arquivo vazio ou ilegível."); st.stop()

        prompt = f"""
        Você é um Auditor Farmacêutico Sênior com olhar clínico.

        BULA REFERÊNCIA:
        {t_ref[:150000]}

        BULA BELFAR:
        {t_belfar[:150000]}

        Sua missão é focar APENAS nestas seções: {secoes_alvo}.

        INSTRUÇÕES DE ANÁLISE (MUITO IMPORTANTE):
        1. Compare as seções equivalentes nas duas bulas.
        2. Identifique DIVERGÊNCIAS REAIS de conteúdo (informações médicas adicionadas na BELFAR, informações removidas ou significados alterados).
        3. IGNORE TOTALMENTE mudanças estéticas: troca de '•' por '-', números, parágrafos quebrados em lugares diferentes, ou pontuação diferente. Se o sentido da frase é o mesmo, NÃO é divergência.
        4. "trechos_divergentes_belfar": Forneça trechos exatos (entre 5 a 15 palavras) LITERALMENTE copiados da bula BELFAR onde a divergência ocorre. Como é para grifar no PDF, a cópia deve ser idêntica (copiar e colar do texto da BELFAR).

        Responda SOMENTE em formato JSON válido:
        {{
            "raciocinio_auditor": "Explique brevemente em 1 linha o que você encontrou de diferente",
            "data_anvisa_ref": "dd/mm/aaaa ou -",
            "data_anvisa_mkt": "dd/mm/aaaa ou -",
            "erros_ortograficos": ["palavra ou frase com erro de português na BELFAR"],
            "data_anvisa_frase": ["frase literal da belfar que contem a data"],
            "trechos_divergentes_belfar": [
                "frase exata copiada da belfar da mudanca 1",
                "frase exata copiada da belfar da mudanca 2"
            ]
        }}
        """

        for key in keys_validas:
            if sucesso_ia: break
            genai.configure(api_key=key)
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    inst = genai.GenerativeModel(
                        modelo,
                        generation_config={"response_mime_type":"application/json","temperature":0.1}
                    )
                    resp = inst.generate_content(prompt)
                    texto_resposta_ia = resp.text
                    sucesso_ia = True
                    break
                except Exception as e:
                    time.sleep(0.5)

    if not sucesso_ia:
        st.error("❌ Falha Total da IA. Verifique as chaves / cota.")
        st.stop()

    with st.spinner("🖌️ Grifando PDFs com base no laudo da IA..."):
        try:
            texto_limpo = texto_resposta_ia.strip()
            for fence in ("```json","```"):
                texto_limpo = texto_limpo.replace(fence,"")
            
            resultado = json.loads(texto_limpo.strip())

            data_ref        = resultado.get("data_anvisa_ref","-")
            data_mkt        = resultado.get("data_anvisa_mkt","-")
            erros_vermelhos = resultado.get("erros_ortograficos") or []
            datas_azuis     = resultado.get("data_anvisa_frase")  or []
            amarelo_final   = resultado.get("trechos_divergentes_belfar") or []

            f1.seek(0); f2.seek(0)
            fotos_ref    = gerar_imagens_pdf_grifado(f1)
            fotos_belfar = gerar_imagens_pdf_grifado(
                f2,
                amarelo  = amarelo_final,
                vermelho = erros_vermelhos,
                azul     = datas_azuis
            )

        except Exception as e:
            st.error(f"Erro ao processar resposta: {e}")
            st.code(texto_resposta_ia)
            st.stop()

    # ── ETAPA 3: Exibição ──
    st.markdown("### 📊 Resumo da Auditoria")
    ca, cb, cc = st.columns(3)
    ca.metric("Data Referência", data_ref)
    cb.metric("Data BELFAR", data_mkt,
              delta="Igual" if data_ref == data_mkt else "⚠️ Diferente")
    cc.metric("Divergências Encontradas (IA)", len(amarelo_final))

    st.markdown(f"> **Parecer da IA:** *{resultado.get('raciocinio_auditor', 'Nenhuma observação')}*")

    st.markdown("""
    ### 🎨 Legenda:
    * 🟡 **Amarelo** — Divergência real de conteúdo (ignorado marcadores e layout)
    * 🔴 **Vermelho** — Erro ortográfico / gramática
    * 🔵 **Azul** — Data de aprovação da Anvisa
    """)
    st.divider()

    max_pages = max(len(fotos_ref), len(fotos_belfar))
    for i in range(max_pages):
        st.markdown(f"#### Página {i+1}")
        cl, cr = st.columns(2)
        with cl:
            st.caption("📜 Bula Referência (Visão Limpa)")
            if i < len(fotos_ref):
                st.image(fotos_ref[i], use_container_width=True)
        with cr:
            st.caption("📜 Bula BELFAR (Auditoria IA)")
            if i < len(fotos_belfar):
                st.image(fotos_belfar[i], use_container_width=True)
        st.divider()
