import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import re
import time
import difflib

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

SECOES_SEM_COMPARACAO = {"APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"}

# ----------------- 3. EXTRAÇÃO DE TEXTO DO PDF -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n"
        text = re.sub(r'(\w)-\s*\n(\w)', r'\1\2', text)
        return text
    except:
        return ""

# ----------------- 4. REPARADOR DE JSON TRUNCADO -----------------
def reparar_json_truncado(texto):
    """
    Tenta consertar um JSON cortado no meio pelo limite de tokens.
    Fecha strings abertas, arrays e objetos na ordem correta.
    """
    texto = texto.strip()
    # Remove fences de markdown se houver
    for fence in ("```json", "```"):
        texto = texto.replace(fence, "")
    texto = texto.strip()

    # Primeiro tenta parse normal
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    # Conta profundidade de chaves/colchetes e strings abertas
    consertado = texto
    
    # Remove a última vírgula pendente antes de fechar
    consertado = re.sub(r',\s*$', '', consertado)
    
    # Detecta se terminou no meio de uma string — fecha a string
    # Conta aspas: se ímpar, tem uma string aberta
    num_aspas = consertado.count('"') - consertado.count('\\"')
    if num_aspas % 2 != 0:
        consertado += '"'

    # Fecha estruturas abertas na ordem inversa
    pilha = []
    dentro_string = False
    escape = False
    for ch in consertado:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            dentro_string = not dentro_string
            continue
        if not dentro_string:
            if ch in ('{', '['):
                pilha.append('}' if ch == '{' else ']')
            elif ch in ('}', ']'):
                if pilha and pilha[-1] == ch:
                    pilha.pop()

    # Fecha o que ficou aberto
    for fechamento in reversed(pilha):
        consertado += fechamento

    try:
        return json.loads(consertado)
    except json.JSONDecodeError as e:
        raise ValueError(f"Não foi possível reparar o JSON: {e}")

# ----------------- 5. MOTOR DE DIVERGÊNCIAS -----------------
def encontrar_divergencias_exatas(texto_ref, texto_belfar):
    t_ref_limpo = re.sub(r'\s+', ' ', texto_ref).strip()
    t_bel_limpo = re.sub(r'\s+', ' ', texto_belfar).strip()

    tok_ref = t_ref_limpo.split()
    tok_bel = t_bel_limpo.split()

    norm_ref = [t.lower() for t in tok_ref]
    norm_bel = [t.lower() for t in tok_bel]

    matcher = difflib.SequenceMatcher(None, norm_ref, norm_bel, autojunk=False)
    trechos_para_grifar = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('insert', 'replace'):
            inicio = j1
            fim = j2

            tamanho_str = sum(len(tok_bel[x]) for x in range(inicio, fim))
            if tamanho_str <= 3 and fim < len(tok_bel):
                fim = min(fim + 2, len(tok_bel))

            palavras_divergentes = tok_bel[inicio:fim]

            for k in range(0, len(palavras_divergentes), 6):
                pedaco = " ".join(palavras_divergentes[k:k+6])
                if len(pedaco.strip()) > 1:
                    trechos_para_grifar.append(pedaco)

    return trechos_para_grifar

# ----------------- 6. PINTURA DOS PDFs -----------------
def gerar_imagens_pdf_grifado(uploaded_file, amarelo=None, vermelho=None, azul=None):
    amarelo  = amarelo  or []
    vermelho = vermelho or []
    azul     = azul     or []

    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens = []

    for page in doc:
        for frase in amarelo:
            frase = str(frase).strip()
            if len(frase) < 2: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0.85, 0))
                a.set_opacity(0.45)
                a.update()

        for frase in vermelho:
            frase = str(frase).strip()
            if len(frase) < 4: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0, 0))
                a.set_opacity(0.40)
                a.update()

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

# ----------------- 7. UI PRINCIPAL -----------------
st.title("💊 Auditor Visual de Bulas (Detecção Nível Palavra/Símbolo)")

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

    with st.spinner("🧠 IA mapeando a estrutura literal das bulas..."):
        f1.seek(0); f2.seek(0)
        t_ref    = extract_text_from_file(f1)
        t_belfar = extract_text_from_file(f2)

        if len(t_ref) < 20 or len(t_belfar) < 20:
            st.error("Arquivo vazio ou ilegível."); st.stop()

        prompt = f"""
        Você é um Extrator de Dados Farmacêuticos de extrema precisão.

        BULA REFERÊNCIA:
        {t_ref[:120000]}

        BULA BELFAR:
        {t_belfar[:120000]}

        SEÇÕES ALVO: {secoes_alvo}

        MISSÃO: Extrair as seções LITERAIS para o comparador algorítmico do Python.

        REGRAS ABSOLUTAS:
        1. NÃO resuma. NÃO altere nenhuma palavra, pontuação ou marcador (mantenha •, -, números idênticos).
        2. Copie os textos completos exatamente como estão nas bulas.
        3. Se uma seção não existir em uma delas, coloque string vazia "".
        4. CRÍTICO: Retorne um JSON COMPLETO e válido. Não corte o JSON no meio.
           Se o texto for muito longo, prefira truncar o conteúdo de uma seção
           a entregar um JSON incompleto.

        Responda SOMENTE em JSON válido e completo:
        {{
            "data_anvisa_ref": "dd/mm/aaaa ou -",
            "data_anvisa_mkt": "dd/mm/aaaa ou -",
            "erros_ortograficos": ["palavra ou frase com erro de português na BELFAR"],
            "data_anvisa_frase": ["frase literal da belfar com a data de aprovação"],
            "secoes": [
                {{
                    "titulo": "NOME DA SEÇÃO",
                    "texto_ref": "texto literal completo da Referência",
                    "texto_belfar": "texto literal completo da BELFAR"
                }}
            ]
        }}
        """

        # ── Configuração com max_output_tokens alto para não cortar o JSON ──
        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=65536,  # ← CORREÇÃO PRINCIPAL: aumenta o limite de saída
        )

        for key in keys_validas:
            if sucesso_ia: break
            genai.configure(api_key=key)
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    inst = genai.GenerativeModel(
                        modelo,
                        generation_config=generation_config,
                    )
                    resp = inst.generate_content(prompt)
                    texto_resposta_ia = resp.text
                    sucesso_ia = True
                    break
                except Exception:
                    time.sleep(0.5)

    if not sucesso_ia:
        st.error("❌ Falha Total da IA.")
        st.stop()

    with st.spinner("🔬 Cruzando palavras e símbolos detalhadamente e pintando PDFs..."):
        try:
            # ── CORREÇÃO: usa reparador de JSON em vez de json.loads direto ──
            resultado = reparar_json_truncado(texto_resposta_ia)

            data_ref        = resultado.get("data_anvisa_ref", "-")
            data_mkt        = resultado.get("data_anvisa_mkt", "-")
            erros_vermelhos = resultado.get("erros_ortograficos") or []
            datas_azuis     = resultado.get("data_anvisa_frase")  or []
            dados_secoes    = resultado.get("secoes", [])

            amarelo_final = []
            for secao in dados_secoes:
                titulo = secao.get("titulo", "").strip().upper()

                if any(b in titulo for b in SECOES_SEM_COMPARACAO):
                    continue

                t_r = secao.get("texto_ref", "")
                t_b = secao.get("texto_belfar", "")

                if t_r or t_b:
                    divergencias = encontrar_divergencias_exatas(t_r, t_b)
                    amarelo_final.extend(divergencias)

            f1.seek(0); f2.seek(0)
            fotos_ref    = gerar_imagens_pdf_grifado(f1)
            fotos_belfar = gerar_imagens_pdf_grifado(
                f2,
                amarelo  = amarelo_final,
                vermelho = erros_vermelhos,
                azul     = datas_azuis
            )

        except Exception as e:
            st.error(f"Erro ao processar: {e}")
            st.code(texto_resposta_ia)
            st.stop()

    # ── Exibição ──
    st.markdown("### 📊 Resumo da Auditoria")
    ca, cb, cc = st.columns(3)
    ca.metric("Data Referência", data_ref)
    cb.metric("Data BELFAR", data_mkt,
              delta="Igual" if data_ref == data_mkt else "⚠️ Diferente")
    cc.metric("Segmentos Divergentes Identificados", len(amarelo_final))

    st.markdown("""
    ### 🎨 Legenda:
    * 🟡 **Amarelo** — Inserções, alterações, tópicos/símbolos diferentes e parágrafos completos ausentes.
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
            st.caption("📜 Bula BELFAR (Auditoria Detalhada)")
            if i < len(fotos_belfar):
                st.image(fotos_belfar[i], use_container_width=True)
        st.divider()
