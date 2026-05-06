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
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA",
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES",
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]

# Seções que não precisam de comparação de conteúdo (empresa, códigos, etc.)
SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. EXTRAÇÃO DE TEXTO -----------------

def extract_text_from_file(uploaded_file):
    """Extrai texto limpo do PDF para análise pela IA e pelo difflib."""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc:
                text += page.get_text("text") + "\n\n"

        # Remove hifens de quebra de linha e rodapés inúteis
        text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        return text
    except:
        return ""

# ----------------- 4. LÓGICA DIFFLIB (CORAÇÃO DO CÓDIGO 2) -----------------

def extrair_trechos_divergentes(texto_ref, texto_belfar):
    """
    Usa difflib (igual ao Código 2) para detectar divergências reais palavra a palavra.
    Retorna lista de trechos da BELFAR que divergem, prontos para o highlight no PDF.
    """
    if not texto_ref or not texto_belfar:
        return []

    def limpar(t):
        t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
        t = re.sub(r'[ \t]+', ' ', t)
        t = re.sub(r' ([.,;:?!])', r'\1', t)
        return t

    texto_ref   = limpar(texto_ref)
    texto_belfar = limpar(texto_belfar)

    tokens_ref    = [t for t in re.split(r'(\s+)', texto_ref)   if t]
    tokens_belfar = [t for t in re.split(r'(\s+)', texto_belfar) if t]

    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_belfar, autojunk=False)

    trechos_divergentes = []
    buffer_tokens = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'insert'):
            novos = tokens_belfar[j1:j2]
            palavras = [t for t in novos if not re.match(r'^\s+$', t)]
            if palavras:
                buffer_tokens.extend(palavras)
        else:
            # Fecha o buffer atual e salva o trecho
            if buffer_tokens:
                # Agrupa tokens em frases de até 6 palavras para melhor localização no PDF
                for i in range(0, len(buffer_tokens), 6):
                    chunk = buffer_tokens[i:i+6]
                    frase = " ".join(chunk).strip()
                    if len(frase) >= 4:
                        trechos_divergentes.append(frase)
                buffer_tokens = []

    # Fecha qualquer buffer restante
    if buffer_tokens:
        for i in range(0, len(buffer_tokens), 6):
            chunk = buffer_tokens[i:i+6]
            frase = " ".join(chunk).strip()
            if len(frase) >= 4:
                trechos_divergentes.append(frase)

    return trechos_divergentes

# ----------------- 5. PINTURA DOS PDFs (BASE DO CÓDIGO 1) -----------------

def gerar_imagens_pdf_grifado(uploaded_file, amarelo=None, vermelho=None, azul=None):
    """
    Abre o PDF e aplica marca-texto translúcido em alta resolução.
    - Amarelo: divergências detectadas pelo difflib
    - Vermelho: erros ortográficos detectados pela IA
    - Azul:    data de aprovação da Anvisa
    """
    amarelo = amarelo or []
    vermelho = vermelho or []
    azul    = azul    or []

    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        # AMARELO — Divergências do difflib
        for frase in amarelo:
            if not frase or len(str(frase).strip()) < 4:
                continue
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 1, 0))
                annot.set_opacity(0.35)
                annot.update()

        # VERMELHO — Erros ortográficos da IA
        for frase in vermelho:
            if not frase or len(str(frase).strip()) < 4:
                continue
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0, 0))
                annot.set_opacity(0.35)
                annot.update()

        # AZUL — Data da Anvisa
        for frase in azul:
            if not frase or len(str(frase).strip()) < 4:
                continue
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(0, 0.5, 1))
                annot.set_opacity(0.35)
                annot.update()

        # Alta resolução (4x zoom)
        zoom   = 4
        matriz = fitz.Matrix(zoom, zoom)
        pix    = page.get_pixmap(matrix=matriz)
        imagens_geradas.append(pix.tobytes("png"))

    return imagens_geradas

# ----------------- 6. UI PRINCIPAL -----------------

st.title("💊 Auditor Visual de Bulas (Lado a Lado)")

tipo_bula = st.radio(
    "Escolha o Tipo de Bula:",
    ("Paciente", "Profissional"),
    horizontal=True
)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR",     type=["pdf"], key="f2")

if st.button("🚀 Iniciar Auditoria Visual e Grifar PDFs"):

    keys_raw    = [
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

        # ── ETAPA 1: IA extrai seções estruturadas + erros ortográficos + data ──
        texto_resposta_ia = ""
        sucesso_ia = False

        with st.spinner("🧠 Lendo arquivos e analisando com IA (1-2 minutos)..."):
            f1.seek(0); f2.seek(0)
            t_ref   = extract_text_from_file(f1)
            t_belfar = extract_text_from_file(f2)

            if len(t_ref) < 20 or len(t_belfar) < 20:
                st.error("Arquivo vazio ou ilegível.")
                st.stop()

            prompt = f"""
Você é um Auditor Farmacêutico e Extrator de Dados Rigoroso.

REFERÊNCIA: {t_ref[:150000]}
BELFAR: {t_belfar[:150000]}

MISSÃO:
1. Extrair o conteúdo COMPLETO de cada seção das duas bulas (sem resumir nenhuma frase).
2. Detectar erros GRAVES de digitação ou gramática na BELFAR (NÃO aponte nomes de doenças, compostos ou termos médicos).
3. Extrair a frase exata contendo a data de aprovação da Anvisa na BELFAR.

REGRAS CRÍTICAS:
- Para erros ortográficos: devolva o trecho exato da BELFAR (2 a 5 palavras). Se tiver dúvida, NÃO aponte.
- Para data_anvisa: devolva a frase exata como aparece na BELFAR (ex: "aprovada pela Anvisa em 05/02/2025").
- IGNORE completamente diferenças de empresa, CNPJ, endereço, SAC e farmacêutico responsável.
- PRESERVE todas as quebras de parágrafo (\\n\\n) no conteúdo das seções.

LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}

SAÍDA — apenas JSON puro, sem markdown:
{{
    "data_anvisa_ref": "dd/mm/aaaa",
    "data_anvisa_mkt": "dd/mm/aaaa",
    "erros_ortograficos": ["trecho com erro 1", "trecho com erro 2"],
    "data_anvisa_frase": ["frase exata contendo a data na BELFAR"],
    "secoes": [
        {{
            "titulo": "NOME DA SEÇÃO",
            "texto_ref": "conteúdo completo da Referência...",
            "texto_belfar": "conteúdo completo da BELFAR..."
        }}
    ]
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
                        response       = model_instance.generate_content(prompt)
                        texto_resposta_ia = response.text
                        sucesso_ia     = True
                        break
                    except Exception:
                        time.sleep(0.5)
                        continue

        if not sucesso_ia:
            st.error("❌ Falha Total da IA. Verifique as chaves / cota.")
            st.stop()

        # ── ETAPA 2: difflib por seção + pintura dos PDFs ──
        with st.spinner("🖌️ Calculando divergências (difflib) e pintando PDFs em Alta Resolução..."):
            try:
                # Limpa possíveis cercas de markdown
                texto_limpo = texto_resposta_ia.strip()
                for fence in ("```json", "```"):
                    texto_limpo = texto_limpo.replace(fence, "")
                texto_limpo = texto_limpo.strip()
                if texto_limpo.startswith("json"):
                    texto_limpo = texto_limpo[4:].strip()

                resultado = json.loads(texto_limpo)

                data_ref   = resultado.get("data_anvisa_ref", "-")
                data_mkt   = resultado.get("data_anvisa_mkt", "-")
                erros_vermelhos = resultado.get("erros_ortograficos") or []
                datas_azuis     = resultado.get("data_anvisa_frase") or []
                dados_secoes    = resultado.get("secoes", [])

                # ── Aplica difflib em cada seção para montar lista amarela ──
                trechos_amarelos = []

                for item in dados_secoes:
                    titulo      = item.get("titulo", "").strip().upper()
                    txt_ref     = item.get("texto_ref", "").strip()
                    txt_belfar  = item.get("texto_belfar", "").strip()

                    # Seções blindadas: não compara conteúdo
                    eh_blindada = any(b in titulo for b in SECOES_SEM_COMPARACAO)
                    if eh_blindada:
                        continue

                    novos_trechos = extrair_trechos_divergentes(txt_ref, txt_belfar)
                    trechos_amarelos.extend(novos_trechos)

                # Remove duplicatas preservando ordem
                vistos = set()
                amarelo_final = []
                for t in trechos_amarelos:
                    if t not in vistos:
                        vistos.add(t)
                        amarelo_final.append(t)

                # ── Gera imagens dos PDFs ──
                f1.seek(0); f2.seek(0)

                fotos_ref    = gerar_imagens_pdf_grifado(f1)  # Referência: sem marca
                fotos_belfar = gerar_imagens_pdf_grifado(
                    f2,
                    amarelo=amarelo_final,
                    vermelho=erros_vermelhos,
                    azul=datas_azuis
                )

            except Exception as e:
                st.error("Erro interno ao processar a pintura do PDF.")
                st.code(texto_resposta_ia)
                st.stop()

        # ── ETAPA 3: Exibição ──
        st.markdown("### 📊 Resumo da Auditoria")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Data Referência", data_ref)
        col_b.metric("Data BELFAR",     data_mkt,
                     delta="Igual" if data_ref == data_mkt else "⚠️ Diferente")
        col_c.metric("Trechos grifados", len(amarelo_final))

        st.markdown("""
        ### 🎨 Legenda:
        * 🟡 **Amarelo** — Divergência de conteúdo detectada pelo difflib (palavra a palavra)
        * 🔴 **Vermelho** — Erro ortográfico / gramática
        * 🔵 **Azul** — Data de aprovação da Anvisa
        """)
        st.divider()

        max_pages = max(len(fotos_ref), len(fotos_belfar))

        for i in range(max_pages):
            st.markdown(f"#### Página {i + 1}")
            col_esq, col_dir = st.columns(2)

            with col_esq:
                st.caption("📜 Bula Referência (Visão Limpa)")
                if i < len(fotos_ref):
                    st.image(fotos_ref[i], use_container_width=True)

            with col_dir:
                st.caption("📜 Bula BELFAR (Auditoria Inteligente)")
                if i < len(fotos_belfar):
                    st.image(fotos_belfar[i], use_container_width=True)

            st.divider()

    else:
        st.warning("Adicione os dois arquivos PDF para iniciar.")
