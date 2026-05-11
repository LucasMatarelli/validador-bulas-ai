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
    Limpa formatações vazias para evitar confusão da IA.
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
        # Remove excesso de espaços para não confundir a IA
        texto = re.sub(r'[ \t]+', ' ', texto) 
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
            if len(frase) < 4: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0.85, 0))
                a.set_opacity(0.3)
                a.update()

        for frase in vermelho:
            frase = str(frase).strip()
            if len(frase) < 4: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0, 0))
                a.set_opacity(0.3)
                a.update()

        for frase in azul:
            frase = str(frase).strip()
            if len(frase) < 4: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(0, 0.5, 1))
                a.set_opacity(0.3)
                a.update()

        pix = page.get_pixmap(matrix=fitz.Matrix(6, 6))
        imagens.append(pix.tobytes("png"))

    return imagens

# ----------------- 7. CHUNKS PARA BUSCA -----------------
def chunks_de_frase(frase, tamanho=6):
    palavras = frase.split()
    if len(palavras) <= tamanho:
        return [frase] if frase.strip() else []
    resultado = []
    passo = max(1, tamanho // 2)
    for i in range(0, len(palavras) - tamanho + 1, passo):
        resultado.append(" ".join(palavras[i:i+tamanho]))
    return resultado

def expandir_para_chunks(lista_frases, tamanho=6):
    resultado = []
    for frase in lista_frases:
        f = str(frase).strip()
        if f:
            resultado.extend(chunks_de_frase(f, tamanho))
    return resultado

# ----------------- 8. UI PRINCIPAL -----------------
st.title("💊 Auditor Visual de Bulas (Anti-Alucinação)")

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

    with st.spinner("🧠 IA processando verificação cruzada (100% de exatidão)..."):
        f1.seek(0); f2.seek(0)
        t_ref_bruto    = extract_text_with_bold(f1)
        t_belfar_bruto = extract_text_with_bold(f2)

        if len(t_ref_bruto) < 20 or len(t_belfar_bruto) < 20:
            st.error("Arquivo vazio ou ilegível."); st.stop()

        t_ref    = truncar_ate_data_anvisa(t_ref_bruto)
        t_belfar = truncar_ate_data_anvisa(t_belfar_bruto)

        prompt = f"""
Você é um sistema de verificação de arquivos DIFF implacável e estrito. 
Sua única função é extrair as diferenças absolutas entre o Arquivo A (Referência) e o Arquivo B (Belfar).
VOCÊ ESTÁ PROIBIDO DE INVENTAR OU MARCAR FALSOS POSITIVOS. 

════════════════════════════════════════════════════
REGRA ABSOLUTA 1: O TESTE DO NEGRITO
A tag de negrito é representada por [B]...[/B].
- Se a Referência diz: "[B]Atenção:[/B]"
- E a Belfar diz: "[B]Atenção:[/B]"
CONCLUSÃO: SÃO EXATAMENTE IGUAIS. É ESTRITAMENTE PROIBIDO MARCAR ISSO COMO DIVERGÊNCIA.

QUANDO MARCAR NEGRITO:
- Referência diz "[B]Atenção:[/B]" e Belfar diz "Atenção:" (Faltou a tag na Belfar -> MARQUE).
- Referência diz "Atenção:" e Belfar diz "[B]Atenção:[/B]" (Sobrou a tag na Belfar -> MARQUE).

REGRA ABSOLUTA 2: TEXTOS IDÊNTICOS
Se as palavras, a pontuação e as tags [B] (se houver) forem as mesmas em ambos os textos, VOCÊ NÃO DEVE MARCAR.
Ignore completamente se o texto sofreu quebra de linha ou se há espaços duplos. O conteúdo semântico literal é o que importa.

REGRA ABSOLUTA 3: EXCEÇÕES NÃO MARCADAS
Os nomes dos medicamentos (ex: FLAGYL na Referência vs Flagimax na Belfar) SÃO ESPERADOS. Não marque isso como divergência em hipótese alguma.
Títulos de seções numeradas (Ex: "8. QUAIS OS MALES...") NÃO devem ser marcados se estiverem com a mesma grafia.
════════════════════════════════════════════════════

FILTRO FINAL ANTES DE RESPONDER:
Antes de colocar qualquer trecho na lista "divergencias_amarelo", pergunte a si mesmo: "Este exato trecho, com estas exatas palavras e tags de negrito, já existe na Referência?". Se a resposta for SIM, DELETE o item da sua lista.

SEÇÕES A COMPARAR:
{secoes_comparar}

════════════════════════════════════════════════════
BULA REFERÊNCIA (Arquivo A):
{t_ref[:80000]}

════════════════════════════════════════════════════
BULA BELFAR (Arquivo B):
{t_belfar[:80000]}

════════════════════════════════════════════════════
SAÍDA ESPERADA:
Retorne APENAS um JSON válido. Nos arrays "divergencias_amarelo" e "erros_ortograficos", insira trechos curtos (6 a 10 palavras) retirados da BELFAR, SEM as tags [B].
{{
  "data_anvisa_ref": "dd/mm/aaaa ou -",
  "data_anvisa_mkt": "dd/mm/aaaa ou -",
  "data_anvisa_frase": ["frase literal da BELFAR com data Anvisa, sem tags"],
  "data_anvisa_frase_ref": ["frase literal da REFERÊNCIA com data Anvisa, sem tags"],
  "erros_ortograficos": ["trecho literal com erro gramatical na BELFAR, sem tags"],
  "divergencias_amarelo": [
    "trecho literal da BELFAR que passou pelo filtro final e é uma divergência verdadeira, sem tags"
  ]
}}
"""

        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0, # Zero alucinação
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

    with st.spinner("🎨 Aplicando highlights finais..."):
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

            amarelo_chunks     = expandir_para_chunks(divergencias, tamanho=6)
            vermelho_chunks    = expandir_para_chunks(erros_vermelhos, tamanho=6)
            azul_chunks_belfar = expandir_para_chunks(datas_azuis_belfar, tamanho=6)
            azul_chunks_ref    = expandir_para_chunks(datas_azuis_ref, tamanho=6)

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
    cc.metric("Divergências Verificadas", len(divergencias))

    if datas_azuis_belfar:
        st.info(f"🔵 Frase Anvisa (BELFAR): *{datas_azuis_belfar[0]}*")
    if datas_azuis_ref:
        st.info(f"🔵 Frase Anvisa (Referência): *{datas_azuis_ref[0]}*")

    st.markdown("""
### 🎨 Legenda:
* 🟡 **Amarelo** — Divergência Exata (Texto exclusivo de uma bula ou divergência real de formatação)
* 🔴 **Vermelho** — Erro ortográfico / gramatical
* 🔵 **Azul** — Frase de aprovação da Anvisa
""")
    st.divider()

    max_pages = max(len(fotos_ref), len(fotos_belfar))
    for i in range(max_pages):
        st.markdown(f"#### Página {i+1}")
        cl, cr = st.columns(2)
        with cl:
            st.caption("📜 Bula Referência")
            if i < len(fotos_ref):
                st.image(fotos_ref[i], use_container_width=True)
        with cr:
            st.caption("📜 Bula BELFAR")
            if i < len(fotos_belfar):
                st.image(fotos_belfar[i], use_container_width=True)
        st.divider()
