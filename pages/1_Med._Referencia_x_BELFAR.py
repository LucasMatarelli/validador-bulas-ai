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

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. EXTRAÇÃO DE TEXTO -----------------

def extract_text_from_file(uploaded_file):
    try:
        text = ""
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n\n"
        text = re.sub(r'(\w)-\s*\n(\w)', r'\1\2', text)
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        return text
    except:
        return ""

# ----------------- 4. DIFFLIB CIRÚRGICO POR SEÇÃO -----------------

def normalizar(texto):
    texto = texto.lower()
    texto = texto.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()

def extrair_trechos_divergentes_por_secao(secoes_com_textos):
    """
    Aplica difflib DENTRO de cada seção já pareada pela IA.
    Anti-falso-positivo: ignora palavras funcionais isoladas e diferenças só de caixa.
    """
    PALAVRAS_FUNCIONAIS = {
        'a', 'o', 'as', 'os', 'um', 'uma', 'uns', 'umas',
        'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na', 'nos', 'nas',
        'por', 'para', 'com', 'sem', 'sob', 'sobre', 'entre', 'até',
        'que', 'se', 'e', 'ou', 'mas', 'pelo', 'pela', 'pelos', 'pelas',
        'ao', 'à', 'aos', 'às', 'seu', 'sua', 'seus', 'suas',
        'este', 'esta', 'estes', 'estas', 'esse', 'essa', 'esses', 'essas',
        'isso', 'isto', 'quando', 'onde', 'como', 'não', 'mais', 'muito',
        'também', 'já', 'só', 'ainda', 'é', 'são', 'foi', 'foram',
        'ser', 'estar', 'pode', 'podem', 'the', 'and', 'of',
    }

    trechos_amarelos = []

    for item in secoes_com_textos:
        titulo    = item.get("titulo", "").strip().upper()
        txt_ref   = item.get("texto_ref", "").strip()
        txt_belfar = item.get("texto_belfar", "").strip()

        if any(b in titulo for b in SECOES_SEM_COMPARACAO):
            continue
        if not txt_ref or not txt_belfar:
            continue

        tokens_ref    = re.findall(r'\S+', txt_ref)
        tokens_belfar = re.findall(r'\S+', txt_belfar)

        # Normaliza só para comparação
        norm_ref    = [normalizar(t) for t in tokens_ref]
        norm_belfar = [normalizar(t) for t in tokens_belfar]

        matcher = difflib.SequenceMatcher(None, norm_ref, norm_belfar, autojunk=False)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag not in ('replace', 'insert'):
                continue

            tokens_div = tokens_belfar[j1:j2]
            palavras   = [t for t in tokens_div if re.search(r'[a-záàãâéêíóôõúüçA-Z]', t)]

            if not palavras:
                continue

            # Precisa de ao menos 1 palavra não-funcional para marcar
            nao_funcionais = [
                p for p in palavras
                if normalizar(p).strip('.,;:!?()') not in PALAVRAS_FUNCIONAIS
            ]
            if not nao_funcionais:
                continue

            # Agrupa em chunks de até 5 palavras para busca no PDF
            for i in range(0, len(palavras), 5):
                chunk = palavras[i:i+5]
                frase = " ".join(chunk).strip().strip('.,;:!?()')
                if len(frase) >= 5:
                    trechos_amarelos.append(frase)

    # Remove duplicatas
    vistos, unicos = set(), []
    for t in trechos_amarelos:
        if t not in vistos:
            vistos.add(t)
            unicos.append(t)

    return unicos

# ----------------- 5. PINTURA DOS PDFs -----------------

def gerar_imagens_pdf_grifado(uploaded_file, amarelo=None, vermelho=None, azul=None):
    amarelo  = amarelo  or []
    vermelho = vermelho or []
    azul     = azul     or []

    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        for frase in amarelo:
            if not frase or len(str(frase).strip()) < 4:
                continue
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0.85, 0))
                annot.set_opacity(0.40)
                annot.update()

        for frase in vermelho:
            if not frase or len(str(frase).strip()) < 4:
                continue
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(1, 0, 0))
                annot.set_opacity(0.35)
                annot.update()

        for frase in azul:
            if not frase or len(str(frase).strip()) < 4:
                continue
            for area in page.search_for(str(frase)):
                annot = page.add_highlight_annot(area)
                annot.set_colors(stroke=(0, 0.5, 1))
                annot.set_opacity(0.35)
                annot.update()

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

        texto_resposta_ia = ""
        sucesso_ia = False

        with st.spinner("🧠 Extraindo seções com IA (1-2 minutos)..."):
            f1.seek(0); f2.seek(0)
            t_ref    = extract_text_from_file(f1)
            t_belfar = extract_text_from_file(f2)

            if len(t_ref) < 20 or len(t_belfar) < 20:
                st.error("Arquivo vazio ou ilegível.")
                st.stop()

            prompt = f"""
Você é um Extrator de Dados Farmacêuticos extremamente rigoroso.

BULA REFERÊNCIA:
{t_ref[:150000]}

BULA BELFAR:
{t_belfar[:150000]}

SUA MISSÃO — extrair o texto LITERAL e COMPLETO de cada seção das duas bulas.
REGRAS ABSOLUTAS:
- NÃO resuma, NÃO parafraseie, NÃO altere nenhuma palavra.
- PRESERVE pontuação e quebras de parágrafo (\\n\\n) exatamente como estão.
- Para "erros_ortograficos": apenas erros GRAVES de digitação na BELFAR. NUNCA aponte termos médicos, doenças ou compostos. Se tiver dúvida, deixe [].
- Para "data_anvisa_frase": a frase exata da BELFAR com a data de aprovação.

SEÇÕES: {secoes_alvo}

JSON puro sem markdown:
{{
    "data_anvisa_ref": "dd/mm/aaaa ou -",
    "data_anvisa_mkt": "dd/mm/aaaa ou -",
    "erros_ortograficos": [],
    "data_anvisa_frase": [],
    "secoes": [
        {{
            "titulo": "NOME DA SEÇÃO",
            "texto_ref": "texto literal completo da Referência",
            "texto_belfar": "texto literal completo da BELFAR"
        }}
    ]
}}
"""

            for key in keys_validas:
                if sucesso_ia: break
                genai.configure(api_key=key)
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model_inst = genai.GenerativeModel(
                            modelo,
                            generation_config={
                                "response_mime_type": "application/json",
                                "temperature": 0.0
                            }
                        )
                        response          = model_inst.generate_content(prompt)
                        texto_resposta_ia = response.text
                        sucesso_ia        = True
                        break
                    except Exception:
                        time.sleep(0.5)
                        continue

        if not sucesso_ia:
            st.error("❌ Falha Total da IA. Verifique as chaves / cota.")
            st.stop()

        with st.spinner("🔬 Calculando divergências e pintando PDFs..."):
            try:
                texto_limpo = texto_resposta_ia.strip()
                for fence in ("```json", "```"):
                    texto_limpo = texto_limpo.replace(fence, "")
                texto_limpo = texto_limpo.strip()
                if texto_limpo.startswith("json"):
                    texto_limpo = texto_limpo[4:].strip()

                resultado = json.loads(texto_limpo)

                data_ref        = resultado.get("data_anvisa_ref", "-")
                data_mkt        = resultado.get("data_anvisa_mkt", "-")
                erros_vermelhos = resultado.get("erros_ortograficos") or []
                datas_azuis     = resultado.get("data_anvisa_frase")  or []
                dados_secoes    = resultado.get("secoes", [])

                amarelo_final = extrair_trechos_divergentes_por_secao(dados_secoes)

                f1.seek(0); f2.seek(0)
                fotos_ref    = gerar_imagens_pdf_grifado(f1)
                fotos_belfar = gerar_imagens_pdf_grifado(
                    f2,
                    amarelo  = amarelo_final,
                    vermelho = erros_vermelhos,
                    azul     = datas_azuis
                )

            except Exception as e:
                st.error(f"Erro interno: {e}")
                st.code(texto_resposta_ia)
                st.stop()

        st.markdown("### 📊 Resumo da Auditoria")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Data Referência", data_ref)
        col_b.metric("Data BELFAR", data_mkt,
                     delta="Igual" if data_ref == data_mkt else "⚠️ Diferente")
        col_c.metric("Trechos grifados", len(amarelo_final))

        st.markdown("""
        ### 🎨 Legenda:
        * 🟡 **Amarelo** — Divergência de conteúdo (difflib por seção)
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
