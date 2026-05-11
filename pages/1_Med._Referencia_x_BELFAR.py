import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import re
import time
import difflib
import unicodedata

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

# Similaridade mínima para considerar dois parágrafos como "o mesmo conteúdo"
# (0.0 = qualquer coisa bate, 1.0 = idêntico)
SIMILARIDADE_PARAGRAFO = 0.55

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
    texto = texto.strip()
    for fence in ("```json", "```"):
        texto = texto.replace(fence, "")
    texto = texto.strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    consertado = re.sub(r',\s*$', '', texto)

    num_aspas = consertado.count('"') - consertado.count('\\"')
    if num_aspas % 2 != 0:
        consertado += '"'

    pilha = []
    dentro_string = False
    escape = False
    for ch in consertado:
        if escape:
            escape = False; continue
        if ch == '\\':
            escape = True; continue
        if ch == '"' and not escape:
            dentro_string = not dentro_string; continue
        if not dentro_string:
            if ch in ('{', '['):
                pilha.append('}' if ch == '{' else ']')
            elif ch in ('}', ']'):
                if pilha and pilha[-1] == ch:
                    pilha.pop()

    for f in reversed(pilha):
        consertado += f

    try:
        return json.loads(consertado)
    except json.JSONDecodeError as e:
        raise ValueError(f"Não foi possível reparar o JSON: {e}")

# ----------------- 5. NORMALIZAÇÃO -----------------
def normalizar(texto):
    """Remove acentos, lowercase, pontuação, espaços extras — para comparação semântica."""
    t = unicodedata.normalize('NFD', texto)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = t.lower()
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def similaridade(a, b):
    """Retorna razão de similaridade entre dois textos normalizados (0.0 a 1.0)."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()

# ----------------- 6. TOKENIZAÇÃO PARA DIFF FINO -----------------
def tokenizar(texto):
    """Retorna lista de (token_original, token_normalizado)."""
    tokens_raw = re.split(r'(\s+)', re.sub(r'\s+', ' ', texto).strip())
    resultado = []
    for t in tokens_raw:
        if t.strip():
            norm = normalizar(t)
            resultado.append((t, norm if norm else '__punct__'))
    return resultado

# ----------------- 7. DIFF FINO ENTRE DOIS PARÁGRAFOS SIMILARES -----------------
def diff_fino(para_ref, para_bel):
    """
    Dado que dois parágrafos são semanticamente similares,
    faz diff token a token e retorna só os trechos da BELFAR que diferem.
    """
    tok_ref = tokenizar(para_ref)
    tok_bel = tokenizar(para_bel)
    norm_ref = [t[1] for t in tok_ref]
    norm_bel = [t[1] for t in tok_bel]

    matcher = difflib.SequenceMatcher(None, norm_ref, norm_bel, autojunk=False)
    trechos = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag not in ('insert', 'replace'):
            continue

        # Se replace com mesma quantidade de tokens e normalizados iguais → não é divergência real
        if tag == 'replace' and (i2 - i1) == (j2 - j1):
            if all(norm_ref[i1+k] == norm_bel[j1+k] for k in range(i2 - i1)):
                continue

        palavras = [tok_bel[x][0] for x in range(j1, j2)]

        # Adiciona contexto para tokens muito curtos
        tamanho = sum(len(tok_bel[x][0]) for x in range(j1, j2))
        if tamanho <= 3 and j2 < len(tok_bel):
            palavras = [tok_bel[x][0] for x in range(j1, min(j2 + 2, len(tok_bel)))]

        # Quebra em pedaços de 6 palavras
        for k in range(0, len(palavras), 6):
            pedaco = " ".join(palavras[k:k+6]).strip()
            if len(pedaco) > 1:
                trechos.append(pedaco)

    return trechos

# ----------------- 8. MOTOR PRINCIPAL DE DIVERGÊNCIAS -----------------
def encontrar_divergencias_exatas(texto_ref, texto_belfar):
    """
    Estratégia em dois níveis:
    1. Divide ambos os textos em parágrafos.
    2. Para cada parágrafo da BELFAR, tenta achar o parágrafo mais similar da REF.
       - Se similaridade >= limiar: faz diff fino (só marca palavras que mudaram).
       - Se similaridade < limiar: o parágrafo inteiro é novo/ausente na REF → marca tudo.
    Isso evita falsos positivos quando os textos têm a mesma info mas reorganizada.
    """
    # Divide em parágrafos não-vazios
    def em_paragrafos(texto):
        return [p.strip() for p in re.split(r'\n{1,}', texto) if len(p.strip()) > 15]

    paras_ref = em_paragrafos(texto_ref)
    paras_bel = em_paragrafos(texto_belfar)

    if not paras_ref or not paras_bel:
        # Fallback: texto simples sem parágrafos, faz diff direto
        return diff_fino(texto_ref, texto_belfar)

    trechos_para_grifar = []

    # Para cada parágrafo da BELFAR, acha o mais similar na REF
    for para_bel in paras_bel:
        melhor_sim = 0.0
        melhor_ref = ""

        for para_ref in paras_ref:
            sim = similaridade(para_ref, para_bel)
            if sim > melhor_sim:
                melhor_sim = sim
                melhor_ref = para_ref

        if melhor_sim >= SIMILARIDADE_PARAGRAFO:
            # Parágrafos correspondem → diff fino para achar só o que mudou
            diffs = diff_fino(melhor_ref, para_bel)
            trechos_para_grifar.extend(diffs)
        else:
            # Parágrafo completamente novo na BELFAR → grifa tudo
            tokens = tokenizar(para_bel)
            palavras = [t[0] for t in tokens]
            for k in range(0, len(palavras), 6):
                pedaco = " ".join(palavras[k:k+6]).strip()
                if len(pedaco) > 1:
                    trechos_para_grifar.append(pedaco)

    return trechos_para_grifar

# ----------------- 9. PINTURA DOS PDFs -----------------
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

# ----------------- 10. UI PRINCIPAL -----------------
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
2. Copie os textos completos exatamente como estão nas bulas, preservando quebras de parágrafo com \\n.
3. Se uma seção não existir em uma delas, coloque string vazia "".
4. CRÍTICO: Retorne um JSON COMPLETO e válido. Se o texto for muito longo, prefira truncar
   o conteúdo de uma seção a entregar um JSON incompleto.
5. Para "data_anvisa_frase": copie a frase EXATA e COMPLETA como aparece na bula BELFAR
   contendo a data de aprovação da Anvisa (ex: "Esta bula foi aprovada pela Anvisa em 31/07/2025.").
   Deve ser uma lista com essa frase literal.

Responda SOMENTE em JSON válido e completo:
{{
    "data_anvisa_ref": "dd/mm/aaaa ou -",
    "data_anvisa_mkt": "dd/mm/aaaa ou -",
    "erros_ortograficos": ["palavra ou frase com erro de português na BELFAR"],
    "data_anvisa_frase": ["frase literal completa da belfar com a data de aprovação"],
    "secoes": [
        {{
            "titulo": "NOME DA SEÇÃO",
            "texto_ref": "texto literal completo da Referência com \\n entre parágrafos",
            "texto_belfar": "texto literal completo da BELFAR com \\n entre parágrafos"
        }}
    ]
}}
"""

        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=65536,
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
            resultado = reparar_json_truncado(texto_resposta_ia)

            data_ref        = resultado.get("data_anvisa_ref", "-")
            data_mkt        = resultado.get("data_anvisa_mkt", "-")
            erros_vermelhos = resultado.get("erros_ortograficos") or []
            dados_secoes    = resultado.get("secoes", [])

            # ── Correção da data azul: garante que é lista de strings não-vazias ──
            raw_azul = resultado.get("data_anvisa_frase") or []
            if isinstance(raw_azul, str):
                raw_azul = [raw_azul]
            datas_azuis = [str(x).strip() for x in raw_azul if str(x).strip()]

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

    if datas_azuis:
        st.info(f"🔵 Frase de aprovação Anvisa localizada: *{datas_azuis[0]}*")

    st.markdown("""
### 🎨 Legenda:
* 🟡 **Amarelo** — Palavras/trechos diferentes ou ausentes na Referência
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
