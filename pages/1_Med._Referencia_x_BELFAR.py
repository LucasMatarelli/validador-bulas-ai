import streamlit as st
from google import genai
from google.genai import types
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
    "gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"
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

# ----------------- 4. MOTOR DE DIVERGÊNCIAS -----------------
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

# ----------------- 6. UI PRINCIPAL -----------------
st.title("💊 Auditor Visual de Bulas")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente","Profissional"), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR",     type=["pdf"], key="f2")

if st.button("🚀 Iniciar Auditoria"):

    # Busca as chaves de API nos Secrets do Streamlit
    keys_validas = []
    for k_name in ["GEMINI_API_KEY", "GEMINI_API_KEY2", "GEMINI_API_KEY3"]:
        val = st.secrets.get(k_name)
        if val:
            keys_validas.append((k_name, val))

    if not keys_validas:
        st.error("Erro: Nenhuma chave API configurada nos Secrets.")
        st.stop()

    if not (f1 and f2):
        st.warning("Envie os dois arquivos PDF.")
        st.stop()

    secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

    texto_resposta_ia = ""
    sucesso_ia = False
    erros_detalhados = []

    with st.spinner("🧠 IA Analisando..."):
        f1.seek(0); f2.seek(0)
        t_ref = extract_text_from_file(f1)
        t_bel = extract_text_from_file(f2)

        prompt = f"""
        Compare as bulas e extraia as seções {secoes_alvo} literalmente.
        BULA REF: {t_ref[:100000]}
        BULA BELFAR: {t_bel[:100000]}
        Responda apenas com JSON estruturado contendo 'data_anvisa_ref', 'data_anvisa_mkt', 'erros_ortograficos', 'data_anvisa_frase' e 'secoes'.
        """

        for nome_chave, key in keys_validas:
            if sucesso_ia: break
            try:
                client = genai.Client(api_key=key)
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        resp = client.models.generate_content(
                            model=modelo,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.0
                            )
                        )
                        texto_resposta_ia = resp.text
                        sucesso_ia = True
                        break
                    except Exception as e_mod:
                        erros_detalhados.append(f"{nome_chave} + {modelo}: {str(e_mod)}")
            except Exception as e_key:
                erros_detalhados.append(f"Erro na chave {nome_chave}: {str(e_key)}")

    if not sucesso_ia:
        st.error("Falha na conexão com a IA.")
        for err in erros_detalhados:
            st.warning(err)
        st.stop()

    with st.spinner("🔬 Processando Divergências..."):
        try:
            # Limpeza básica do JSON
            texto_limpo = texto_resposta_ia.strip().replace("```json", "").replace("```", "")
            resultado = json.loads(texto_limpo)

            data_ref = resultado.get("data_anvisa_ref", "-")
            data_mkt = resultado.get("data_anvisa_mkt", "-")
            erros_v = resultado.get("erros_ortograficos") or []
            datas_a = resultado.get("data_anvisa_frase") or []
            dados_s = resultado.get("secoes") or []

            amarelo_final = []
            for s in dados_s:
                if any(b in s.get("titulo", "").upper() for b in SECOES_SEM_COMPARACAO):
                    continue
                divs = encontrar_divergencias_exatas(s.get("texto_ref", ""), s.get("texto_belfar", ""))
                amarelo_final.extend(divs)

            f1.seek(0); f2.seek(0)
            fotos_ref = gerar_imagens_pdf_grifado(f1)
            fotos_bel = gerar_imagens_pdf_grifado(f2, amarelo=amarelo_final, vermelho=erros_v, azul=datas_a)

            st.metric("Trechos Divergentes", len(amarelo_final))
            
            for i in range(max(len(fotos_ref), len(fotos_bel))):
                st.subheader(f"Página {i+1}")
                col_a, col_b = st.columns(2)
                with col_a:
                    if i < len(fotos_ref): st.image(fotos_ref[i])
                with col_b:
                    if i < len(fotos_bel): st.image(fotos_bel[i])

        except Exception as e_final:
            st.error(f"Erro ao processar dados: {str(e_final)}")
            st.code(texto_resposta_ia)
