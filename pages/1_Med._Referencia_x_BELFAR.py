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
            if len(frase) < 3: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0.85, 0))
                a.set_opacity(0.5)
                a.update()

        for frase in vermelho:
            frase = str(frase).strip()
            if len(frase) < 3: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0, 0))
                a.set_opacity(0.45)
                a.update()

        for frase in azul:
            frase = str(frase).strip()
            if len(frase) < 3: continue
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(0, 0.5, 1))
                a.set_opacity(0.45)
                a.update()

        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4))
        imagens.append(pix.tobytes("png"))

    return imagens

# ----------------- 6. QUEBRA EM CHUNKS PARA BUSCA NO PDF -----------------
def chunks_de_frase(frase, tamanho=8):
    """
    Quebra uma frase longa em pedaços sobrepostos de N palavras
    para que o PyMuPDF consiga encontrar no PDF mesmo com quebras de linha.
    """
    palavras = frase.split()
    if len(palavras) <= tamanho:
        return [frase]
    resultado = []
    for i in range(0, len(palavras) - tamanho + 1, max(1, tamanho // 2)):
        chunk = " ".join(palavras[i:i+tamanho])
        resultado.append(chunk)
    return resultado

def expandir_para_chunks(lista_frases, tamanho=8):
    resultado = []
    for frase in lista_frases:
        resultado.extend(chunks_de_frase(frase, tamanho))
    return resultado

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

    with st.spinner("🧠 IA comparando as bulas e identificando divergências..."):
        f1.seek(0); f2.seek(0)
        t_ref    = extract_text_from_file(f1)
        t_belfar = extract_text_from_file(f2)

        if len(t_ref) < 20 or len(t_belfar) < 20:
            st.error("Arquivo vazio ou ilegível."); st.stop()

        prompt = f"""
Você é um auditor farmacêutico especialista em comparação de bulas de medicamentos.

Você receberá duas bulas:
- BULA REFERÊNCIA: o texto oficial aprovado pela Anvisa
- BULA BELFAR: a versão do fabricante que deve ser comparada

Sua tarefa é analisar com extrema precisão e retornar um JSON com:

1. **divergencias_amarelo**: Lista de trechos de texto que existem na BELFAR mas que
   são DIFERENTES do correspondente na Referência (palavras trocadas, frases alteradas,
   informações extras que não estão na Referência, parágrafos reorganizados com conteúdo diferente).
   - NÃO inclua trechos que têm o mesmo conteúdo semântico mesmo que escritos de forma levemente diferente.
   - NÃO inclua o nome do medicamento (Flagimax, FLAGYL etc.) — esses são diferentes por natureza.
   - NÃO inclua trechos da seção APRESENTAÇÕES, COMPOSIÇÃO ou DIZERES LEGAIS.
   - Cada item deve ser um trecho LITERAL de 5 a 10 palavras consecutivas como aparecem na BULA BELFAR,
     para que possam ser encontradas e grifadas no PDF.

2. **erros_ortograficos**: Lista de palavras ou trechos curtos com erro ortográfico/gramatical
   na BULA BELFAR. Cada item deve ser o trecho LITERAL como aparece na bula BELFAR.

3. **data_anvisa_ref**: Data de aprovação da Anvisa encontrada na Bula Referência (formato dd/mm/aaaa).

4. **data_anvisa_mkt**: Data de aprovação da Anvisa encontrada na Bula BELFAR (formato dd/mm/aaaa).

5. **data_anvisa_frase**: A frase LITERAL E COMPLETA como aparece na BULA BELFAR contendo
   a data de aprovação da Anvisa. Exemplo: "Esta bula foi atualizada conforme Bula Padrão aprovada pela Anvisa em 31/07/2025."
   Deve ser uma lista com essa frase exata.

SEÇÕES PARA COMPARAR (ignore APRESENTAÇÕES, COMPOSIÇÃO, DIZERES LEGAIS):
{[s for s in secoes_alvo if s not in ("APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS")]}

---

BULA REFERÊNCIA:
{t_ref[:100000]}

---

BULA BELFAR:
{t_belfar[:100000]}

---

RESPONDA APENAS EM JSON VÁLIDO E COMPLETO:
{{
  "data_anvisa_ref": "dd/mm/aaaa ou -",
  "data_anvisa_mkt": "dd/mm/aaaa ou -",
  "data_anvisa_frase": ["frase literal completa da BELFAR com a data"],
  "erros_ortograficos": ["trecho literal com erro na BELFAR"],
  "divergencias_amarelo": [
    "trecho literal de 5-10 palavras da BELFAR que difere da Referência"
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

    with st.spinner("🎨 Pintando PDFs com as divergências identificadas..."):
        try:
            resultado = reparar_json_truncado(texto_resposta_ia)

            data_ref        = resultado.get("data_anvisa_ref", "-")
            data_mkt        = resultado.get("data_anvisa_mkt", "-")
            erros_vermelhos = resultado.get("erros_ortograficos") or []
            divergencias    = resultado.get("divergencias_amarelo") or []

            # Garante que data_anvisa_frase é lista de strings
            raw_azul = resultado.get("data_anvisa_frase") or []
            if isinstance(raw_azul, str):
                raw_azul = [raw_azul]
            datas_azuis = [str(x).strip() for x in raw_azul if str(x).strip()]

            # Expande frases longas em chunks para o PyMuPDF encontrar no PDF
            amarelo_chunks  = expandir_para_chunks(divergencias, tamanho=7)
            vermelho_chunks = expandir_para_chunks(erros_vermelhos, tamanho=7)
            azul_chunks     = expandir_para_chunks(datas_azuis, tamanho=7)

            f1.seek(0); f2.seek(0)
            fotos_ref    = gerar_imagens_pdf_grifado(f1)
            fotos_belfar = gerar_imagens_pdf_grifado(
                f2,
                amarelo  = amarelo_chunks,
                vermelho = vermelho_chunks,
                azul     = azul_chunks,
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

    if datas_azuis:
        st.info(f"🔵 Frase Anvisa localizada: *{datas_azuis[0]}*")

    st.markdown("""
### 🎨 Legenda:
* 🟡 **Amarelo** — Trechos diferentes ou ausentes na Referência
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
