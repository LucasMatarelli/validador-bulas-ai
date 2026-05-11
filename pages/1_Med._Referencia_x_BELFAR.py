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

# ----------------- 3. EXTRAÇÃO DE TEXTO COM NEGRITO MARCADO -----------------
def extract_text_with_bold(uploaded_file):
    """
    Extrai texto do PDF marcando trechos em negrito com [B]...[/B].
    Agrupa spans da mesma linha para não quebrar palavras no meio.
    """
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        todas_linhas = []

        for page in doc:
            blocos = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            for bloco in blocos:
                if bloco.get("type") != 0:
                    continue
                for linha in bloco.get("lines", []):
                    grupos = []
                    for span in linha.get("spans", []):
                        txt = span.get("text", "")
                        if not txt.strip():
                            continue
                        flags = span.get("flags", 0)
                        font_name = span.get("font", "").lower()
                        is_bold = bool(flags & 16) or "bold" in font_name or "-bd" in font_name or "heavy" in font_name
                        if grupos and grupos[-1][1] == is_bold:
                            grupos[-1][0] += txt
                        else:
                            grupos.append([txt, is_bold])

                    partes = []
                    for texto_grupo, is_bold in grupos:
                        t = texto_grupo.strip()
                        if not t:
                            continue
                        if is_bold:
                            partes.append(f"[B]{t}[/B]")
                        else:
                            partes.append(t)

                    linha_txt = " ".join(partes).strip()
                    if linha_txt:
                        todas_linhas.append(linha_txt)

        texto = "\n".join(todas_linhas)
        texto = re.sub(r'(\w)-\s*\n(\w)', r'\1\2', texto)
        return texto
    except Exception as e:
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

# ----------------- 5. TRUNCA APÓS DATA ANVISA -----------------
def truncar_ate_data_anvisa(texto):
    padroes = [
        r'(esta bula foi (?:atualizada|aprovada)[^\n]{0,300}\d{2}/\d{2}/\d{4}[^\n]*)',
        r'(bula (?:padrão\s+)?aprovada pela anvisa[^\n]{0,200}\d{2}/\d{2}/\d{4}[^\n]*)',
        r'(atualizada conforme bula padrão[^\n]{0,200}\d{2}/\d{2}/\d{4}[^\n]*)',
        r'(\d{2}/\d{2}/\d{4}[^\n]{0,100}aprovad[ao][^\n]*)',
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            return texto[:m.end()].strip()
    return texto

# ----------------- 6. PINTURA DOS PDFs (Qualidade Melhorada) -----------------
def gerar_imagens_pdf_grifado(uploaded_file, amarelo=None, vermelho=None, azul=None):
    amarelo  = amarelo  or []
    vermelho = vermelho or []
    azul     = azul     or []

    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens = []

    for page in doc:
        for frase in amarelo:
            frase = str(frase).strip()
            if len(frase) < 3: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0.85, 0))
                a.set_opacity(0.3) # Opacidade reduzida para não esconder a letra preta
                a.update()

        for frase in vermelho:
            frase = str(frase).strip()
            if len(frase) < 3: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0, 0))
                a.set_opacity(0.3)
                a.update()

        for frase in azul:
            frase = str(frase).strip()
            if len(frase) < 3: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(0, 0.5, 1))
                a.set_opacity(0.3)
                a.update()

        # Resolução altíssima para garantir que o texto fique nítido
        pix = page.get_pixmap(matrix=fitz.Matrix(6, 6))
        imagens.append(pix.tobytes("png"))

    return imagens

# ----------------- 7. CHUNKS PARA BUSCA NO PDF -----------------
def chunks_de_frase(frase, tamanho=7):
    palavras = frase.split()
    if len(palavras) <= tamanho:
        return [frase] if frase.strip() else []
    resultado = []
    passo = max(1, tamanho // 2)
    for i in range(0, len(palavras) - tamanho + 1, passo):
        resultado.append(" ".join(palavras[i:i+tamanho]))
    return resultado

def expandir_para_chunks(lista_frases, tamanho=7):
    resultado = []
    for frase in lista_frases:
        f = str(frase).strip()
        if f:
            resultado.extend(chunks_de_frase(f, tamanho))
    return resultado

# ----------------- 8. UI PRINCIPAL -----------------
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
    secoes_comparar = [s for s in secoes_alvo if s not in ("APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS")]

    texto_resposta_ia = ""
    sucesso_ia = False

    with st.spinner("🧠 IA comparando as bulas com precisão extrema..."):
        f1.seek(0); f2.seek(0)
        t_ref_bruto    = extract_text_with_bold(f1)
        t_belfar_bruto = extract_text_with_bold(f2)

        if len(t_ref_bruto) < 20 or len(t_belfar_bruto) < 20:
            st.error("Arquivo vazio ou ilegível."); st.stop()

        t_ref    = truncar_ate_data_anvisa(t_ref_bruto)
        t_belfar = truncar_ate_data_anvisa(t_belfar_bruto)

        prompt = f"""
Você é um auditor rigoroso comparando dois textos LITERALMENTE.

NOTAÇÃO USADA:
- Trechos entre [B]...[/B] estão em NEGRITO no PDF original.
- Trechos sem marcação estão em texto normal.
- BULA REFERÊNCIA = texto base.
- BULA BELFAR = texto a ser auditado.

════════════════════════════════════════════════════
REGRA DE OURO: COMPARAÇÃO LITERAL E ESTRITA
A regra é simples e inegociável: O QUE NÃO FOR EXATAMENTE IGUAL, É DIVERGÊNCIA.

1. SÍMBOLOS E PONTUAÇÃO: Se uma bula tem um traço (-), ponto, vírgula, ou qualquer símbolo e a outra não tem (ou tem um símbolo diferente), MARQUE COMO DIVERGÊNCIA.
2. NEGRITO (A TAG [B]): Se uma palavra está com [B] em uma bula e sem [B] na outra, MARQUE COMO DIVERGÊNCIA. (Exceção: Se estiver com [B] nas DUAS, é igual, não marque).
3. PALAVRAS E LETRAS: Qualquer diferença de grafia, maiúsculas/minúsculas, ou troca de palavras DEVE ser marcada.
4. EXCEÇÃO: Apenas os nomes próprios do medicamento (FLAGYL vs Flagimax) NÃO são divergências. Todo o resto é.
════════════════════════════════════════════════════

REGRAS PARA divergencias_amarelo (AMARELO):
Marque TUDO na BULA BELFAR que não for uma cópia idêntica (caractere por caractere, símbolo por símbolo, negrito por negrito) da BULA REFERÊNCIA, seguindo a Regra de Ouro acima.

REGRAS PARA erros_ortograficos (VERMELHO):
Marque SOMENTE palavras com erro claro de português na BULA BELFAR (ex: "mediamento" em vez de medicamento). Se a diferença for apenas de pontuação ou negrito, vai para o AMARELO.

REGRAS PARA data_anvisa_frase (AZUL):
- Copie a frase LITERAL E COMPLETA da BULA BELFAR com a data de aprovação Anvisa (sem tags).
- Copie a frase LITERAL E COMPLETA da BULA REFERÊNCIA com a data de aprovação Anvisa (sem tags).

FORMATO DOS ITENS DE SAÍDA:
Cada item de divergencias_amarelo e erros_ortograficos deve ser:
- Trecho LITERAL de 6 a 10 palavras da BULA BELFAR, SEM tags [B] ou [/B].
- Específico o suficiente para ser localizado no PDF.

SEÇÕES A COMPARAR (ignore APRESENTAÇÕES, COMPOSIÇÃO, DIZERES LEGAIS):
{secoes_comparar}

════════════════════════════════════════════════════
BULA REFERÊNCIA ([B]...[/B] = negrito no PDF):
{t_ref[:80000]}

════════════════════════════════════════════════════
BULA BELFAR ([B]...[/B] = negrito no PDF):
{t_belfar[:80000]}

════════════════════════════════════════════════════
RESPONDA APENAS EM JSON VÁLIDO E COMPLETO:
{{
  "data_anvisa_ref": "dd/mm/aaaa ou -",
  "data_anvisa_mkt": "dd/mm/aaaa ou -",
  "data_anvisa_frase": ["frase literal completa da BELFAR com data Anvisa, sem tags"],
  "data_anvisa_frase_ref": ["frase literal completa da REFERÊNCIA com data Anvisa, sem tags"],
  "erros_ortograficos": ["trecho literal 6-10 palavras com erro real na BELFAR, sem tags"],
  "divergencias_amarelo": [
    "trecho literal 6-10 palavras da BELFAR que é divergência literal real, sem tags"
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

    with st.spinner("🎨 Pintando PDFs com Alta Resolução..."):
        try:
            resultado = reparar_json_truncado(texto_resposta_ia)

            data_ref        = resultado.get("data_anvisa_ref", "-")
            data_mkt        = resultado.get("data_anvisa_mkt", "-")
            erros_vermelhos = resultado.get("erros_ortograficos") or []
            divergencias    = resultado.get("divergencias_amarelo") or []

            raw_azul_belfar = resultado.get("data_anvisa_frase") or []
            raw_azul_ref    = resultado.get("data_anvisa_frase_ref") or []
            if isinstance(raw_azul_belfar, str): raw_azul_belfar = [raw_azul_belfar]
            if isinstance(raw_azul_ref, str):    raw_azul_ref    = [raw_azul_ref]
            datas_azuis_belfar = [str(x).strip() for x in raw_azul_belfar if str(x).strip()]
            datas_azuis_ref    = [str(x).strip() for x in raw_azul_ref    if str(x).strip()]

            amarelo_chunks     = expandir_para_chunks(divergencias, tamanho=7)
            vermelho_chunks    = expandir_para_chunks(erros_vermelhos, tamanho=7)
            azul_chunks_belfar = expandir_para_chunks(datas_azuis_belfar, tamanho=7)
            azul_chunks_ref    = expandir_para_chunks(datas_azuis_ref, tamanho=7)

            f1.seek(0); f2.seek(0)
            fotos_ref    = gerar_imagens_pdf_grifado(f1, azul=azul_chunks_ref)
            fotos_belfar = gerar_imagens_pdf_grifado(
                f2,
                amarelo  = amarelo_chunks,
                vermelho = vermelho_chunks,
                azul     = azul_chunks_belfar,
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
    cc.metric("Divergências Identificadas", len(divergencias))

    if datas_azuis_belfar:
        st.info(f"🔵 Frase Anvisa (BELFAR): *{datas_azuis_belfar[0]}*")
    if datas_azuis_ref:
        st.info(f"🔵 Frase Anvisa (Referência): *{datas_azuis_ref[0]}*")

    st.markdown("""
### 🎨 Legenda:
* 🟡 **Amarelo** — Qualquer diferença literal: traços, pontuação, formatação, palavras ausentes/extras
* 🔴 **Vermelho** — Erro ortográfico / gramatical real
* 🔵 **Azul** — Frase de aprovação da Anvisa (em ambas as bulas)
""")
    st.divider()

    max_pages = max(len(fotos_ref), len(fotos_belfar))
    for i in range(max_pages):
        st.markdown(f"#### Página {i+1}")
        cl, cr = st.columns(2)
        with cl:
            st.caption("📜 Bula Referência (data Anvisa em azul)")
            if i < len(fotos_ref):
                st.image(fotos_ref[i], use_container_width=True)
        with cr:
            st.caption("📜 Bula BELFAR (Auditoria Detalhada)")
            if i < len(fotos_belfar):
                st.image(fotos_belfar[i], use_container_width=True)
        st.divider()
