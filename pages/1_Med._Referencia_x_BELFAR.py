import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import difflib
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

SECOES_SEM_COMPARACAO = {"APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"}

# Palavras funcionais que sozinhas NÃO justificam marcação
PALAVRAS_FUNCIONAIS = {
    'a','o','as','os','um','uma','uns','umas','de','do','da','dos','das',
    'em','no','na','nos','nas','por','para','com','sem','sob','sobre',
    'entre','até','que','se','e','ou','mas','pelo','pela','pelos','pelas',
    'ao','à','aos','às','seu','sua','seus','suas','este','esta','estes',
    'estas','esse','essa','esses','essas','isso','isto','quando','onde',
    'como','não','mais','muito','também','já','só','ainda','é','são',
    'foi','foram','ser','estar','pode','podem','
}

# ----------------- 3. EXTRAÇÃO DE TEXTO -----------------

def extract_text_from_file(uploaded_file):
    try:
        text = ""
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n\n"
        # Une hífens de quebra de linha
        text = re.sub(r'(\w)-\s*\n(\w)', r'\1\2', text)
        # Remove rodapés de página
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        return text
    except:
        return ""

# ----------------- 4. DIFF EM DOIS NÍVEIS -----------------

def norm(t):
    """Normalização para comparação (lowercase + espaços)."""
    t = t.lower().replace('\xa0',' ').replace('\u200b','').replace('\xad','')
    return re.sub(r'\s+',' ',t).strip()

def tokenizar(texto):
    """Divide em tokens preservando espaços como tokens separados."""
    return [t for t in re.split(r'(\s+)', texto) if t]

def tem_conteudo_real(tokens):
    """Verifica se os tokens têm ao menos 1 palavra não-funcional."""
    palavras = [t for t in tokens if re.search(r'[a-záàãâéêíóôõúüçA-Z]', t)]
    nao_func = [p for p in palavras if norm(p).strip('.,;:!?()-–•') not in PALAVRAS_FUNCIONAIS]
    return len(nao_func) > 0

def diff_palavra_a_palavra(txt_ref, txt_belfar):
    """
    Compara dois textos palavra a palavra.
    Retorna lista de trechos da BELFAR que divergem.
    """
    tokens_ref    = tokenizar(txt_ref)
    tokens_belfar = tokenizar(txt_belfar)

    norm_ref    = [norm(t) for t in tokens_ref]
    norm_belfar = [norm(t) for t in tokens_belfar]

    matcher = difflib.SequenceMatcher(None, norm_ref, norm_belfar, autojunk=False)

    trechos = []
    buffer  = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'insert'):
            novos = [t for t in tokens_belfar[j1:j2] if not re.match(r'^\s+$', t)]
            if novos and tem_conteudo_real(novos):
                buffer.extend(novos)
        else:
            if buffer:
                # Fecha o buffer e salva em chunks de até 6 palavras
                for i in range(0, len(buffer), 6):
                    chunk = buffer[i:i+6]
                    frase = " ".join(chunk).strip().strip('.,;:!?()')
                    if len(frase) >= 4:
                        trechos.append(frase)
                buffer = []

    if buffer:
        for i in range(0, len(buffer), 6):
            chunk = buffer[i:i+6]
            frase = " ".join(chunk).strip().strip('.,;:!?()')
            if len(frase) >= 4:
                trechos.append(frase)

    return trechos

def dividir_paragrafos(texto):
    """Divide em parágrafos não-vazios."""
    paras = re.split(r'\n{2,}', texto)
    return [p.strip() for p in paras if p.strip()]

def extrair_trechos_divergentes(secoes):
    """
    Estratégia em 2 níveis:
    
    NÍVEL 1 — Parágrafo a parágrafo:
      - Parágrafos que existem só na BELFAR → marca o parágrafo inteiro (primeiras 8 palavras)
      - Parágrafos que existem só na Referência → não marca nada na BELFAR
      - Símbolos de tópico diferentes (•, –, -, *, números) → marca o início do parágrafo
    
    NÍVEL 2 — Dentro de parágrafos pareados:
      - Diff palavra a palavra para pegar alterações pontuais
    """
    trechos_amarelos = []

    for item in secoes:
        titulo    = item.get("titulo","").strip().upper()
        txt_ref   = item.get("texto_ref","").strip()
        txt_belfar = item.get("texto_belfar","").strip()

        if any(b in titulo for b in SECOES_SEM_COMPARACAO):
            continue
        if not txt_ref or not txt_belfar:
            continue

        paras_ref    = dividir_paragrafos(txt_ref)
        paras_belfar = dividir_paragrafos(txt_belfar)

        norm_paras_ref    = [norm(p) for p in paras_ref]
        norm_paras_belfar = [norm(p) for p in paras_belfar]

        # ── NÍVEL 1: diff de parágrafos ──
        matcher_para = difflib.SequenceMatcher(
            None, norm_paras_ref, norm_paras_belfar, autojunk=False
        )

        for tag, i1, i2, j1, j2 in matcher_para.get_opcodes():

            if tag == 'equal':
                # Parágrafos iguais em conteúdo — verifica só símbolo de tópico
                for idx_r, idx_b in zip(range(i1, i2), range(j1, j2)):
                    p_ref_raw  = paras_ref[idx_r]
                    p_bel_raw  = paras_belfar[idx_b]

                    simbolo_ref = re.match(r'^([•\-–—*]|\d+\.)\s*', p_ref_raw)
                    simbolo_bel = re.match(r'^([•\-–—*]|\d+\.)\s*', p_bel_raw)

                    sym_r = simbolo_ref.group(1) if simbolo_ref else ""
                    sym_b = simbolo_bel.group(1) if simbolo_bel else ""

                    if sym_r != sym_b:
                        # Símbolo diferente → marca as primeiras palavras do parágrafo na BELFAR
                        primeiras = " ".join(p_bel_raw.split()[:5]).strip('.,;:!?()')
                        if len(primeiras) >= 4:
                            trechos_amarelos.append(primeiras)

            elif tag == 'insert':
                # Parágrafos que existem SÓ na BELFAR → marca cada um
                for idx_b in range(j1, j2):
                    p_bel = paras_belfar[idx_b]
                    palavras = p_bel.split()
                    # Marca em chunks de até 7 palavras para cobrir o parágrafo inteiro
                    for i in range(0, len(palavras), 7):
                        chunk = palavras[i:i+7]
                        frase = " ".join(chunk).strip().strip('.,;:!?()')
                        if len(frase) >= 4 and tem_conteudo_real(frase.split()):
                            trechos_amarelos.append(frase)

            elif tag == 'replace':
                # Parágrafos modificados → diff palavra a palavra dentro de cada par
                # Pareamos os parágrafos com SequenceMatcher interno
                sub_ref  = paras_ref[i1:i2]
                sub_bel  = paras_belfar[j1:j2]

                # Parágrafos extras na BELFAR (sem par na ref) → marca inteiro
                if len(sub_bel) > len(sub_ref):
                    for p_extra in sub_bel[len(sub_ref):]:
                        palavras = p_extra.split()
                        for i in range(0, len(palavras), 7):
                            chunk = palavras[i:i+7]
                            frase = " ".join(chunk).strip().strip('.,;:!?()')
                            if len(frase) >= 4 and tem_conteudo_real(frase.split()):
                                trechos_amarelos.append(frase)

                # Para os parágrafos que têm par → diff palavra a palavra
                for p_r, p_b in zip(sub_ref, sub_bel):
                    novos = diff_palavra_a_palavra(p_r, p_b)
                    trechos_amarelos.extend(novos)

            # tag == 'delete': parágrafo só na REF → não marca nada na BELFAR

    # Remove duplicatas preservando ordem
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
    imagens = []

    for page in doc:
        for frase in amarelo:
            frase = str(frase).strip()
            if len(frase) < 4: continue
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

# ----------------- 6. UI -----------------

st.title("💊 Auditor Visual de Bulas (Lado a Lado)")

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

    # ── ETAPA 1: IA extrai seções pareadas ──
    texto_resposta_ia = ""
    sucesso_ia = False

    with st.spinner("🧠 Extraindo seções com IA (1-2 minutos)..."):
        f1.seek(0); f2.seek(0)
        t_ref    = extract_text_from_file(f1)
        t_belfar = extract_text_from_file(f2)

        if len(t_ref) < 20 or len(t_belfar) < 20:
            st.error("Arquivo vazio ou ilegível."); st.stop()

        prompt = f"""
Você é um Extrator de Dados Farmacêuticos rigoroso.

BULA REFERÊNCIA:
{t_ref[:150000]}

BULA BELFAR:
{t_belfar[:150000]}

MISSÃO: Extrair o texto LITERAL e COMPLETO de cada seção das duas bulas.

REGRAS ABSOLUTAS:
1. NÃO resuma, NÃO parafraseie, NÃO altere nenhuma palavra ou símbolo.
2. PRESERVE todos os símbolos de tópico exatamente como estão (•, –, -, *, números).
3. PRESERVE todas as quebras de parágrafo como \\n\\n entre parágrafos distintos.
4. Se uma seção não existir em uma das bulas, coloque string vazia "".
5. "erros_ortograficos": apenas erros GRAVES de digitação na BELFAR. NUNCA termos médicos. Se dúvida, [].
6. "data_anvisa_frase": frase exata da BELFAR com a data de aprovação da Anvisa.

SEÇÕES: {secoes_alvo}

Responda SOMENTE com JSON puro (sem markdown, sem cercas):
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
                    inst = genai.GenerativeModel(
                        modelo,
                        generation_config={"response_mime_type":"application/json","temperature":0.0}
                    )
                    resp = inst.generate_content(prompt)
                    texto_resposta_ia = resp.text
                    sucesso_ia = True
                    break
                except Exception:
                    time.sleep(0.5)

    if not sucesso_ia:
        st.error("❌ Falha Total da IA. Verifique as chaves / cota.")
        st.stop()

    # ── ETAPA 2: diff em 2 níveis + pintura ──
    with st.spinner("🔬 Calculando divergências (parágrafo + palavra) e pintando PDFs..."):
        try:
            texto_limpo = texto_resposta_ia.strip()
            for fence in ("```json","```"):
                texto_limpo = texto_limpo.replace(fence,"")
            texto_limpo = texto_limpo.strip()
            if texto_limpo.startswith("json"):
                texto_limpo = texto_limpo[4:].strip()

            resultado = json.loads(texto_limpo)

            data_ref        = resultado.get("data_anvisa_ref","-")
            data_mkt        = resultado.get("data_anvisa_mkt","-")
            erros_vermelhos = resultado.get("erros_ortograficos") or []
            datas_azuis     = resultado.get("data_anvisa_frase")  or []
            dados_secoes    = resultado.get("secoes",[])

            amarelo_final = extrair_trechos_divergentes(dados_secoes)

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

    # ── ETAPA 3: Exibição ──
    st.markdown("### 📊 Resumo da Auditoria")
    ca, cb, cc = st.columns(3)
    ca.metric("Data Referência", data_ref)
    cb.metric("Data BELFAR", data_mkt,
              delta="Igual" if data_ref == data_mkt else "⚠️ Diferente")
    cc.metric("Trechos grifados", len(amarelo_final))

    st.markdown("""
    ### 🎨 Legenda:
    * 🟡 **Amarelo** — Divergência (parágrafo extra, parágrafo alterado, símbolo de tópico diferente)
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
            st.caption("📜 Bula BELFAR (Auditoria Inteligente)")
            if i < len(fotos_belfar):
                st.image(fotos_belfar[i], use_container_width=True)
        st.divider()
