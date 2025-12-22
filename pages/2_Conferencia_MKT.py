import streamlit as st
import google.generativeai as genai
from google.api_core import retry
import fitz  # PyMuPDF
import docx  # Para ler arquivos Word
import json
import re

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }

    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #333;
        background-color: #ffffff;
        padding: 18px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        white-space: pre-wrap;
        text-align: justify;
    }
    .highlight-yellow { background-color: #fff9c4; color: #000; padding: 2px 4px; border-radius: 4px; border: 1px solid #fbc02d; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 4px; border-radius: 4px; border: 1px solid #1976d2; font-weight: bold; }
    
    .border-ok { border-left: 6px solid #4caf50 !important; }
    .border-warn { border-left: 6px solid #ff9800 !important; }
    .border-info { border-left: 6px solid #2196f3 !important; }
    
    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 3. EXTRAÇÃO DE TEXTO APURADA -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        # Verifica se é PDF e extrai mantendo a estrutura visual
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=11)["blocks"]
                for b in blocks:
                    block_text = ""
                    for l in b.get("lines", []):
                        line_text = ""
                        for s in l.get("spans", []):
                            content = s["text"]
                            font_name = s["font"].lower()
                            is_bold = (s["flags"] & 16) or "bold" in font_name or "black" in font_name
                            
                            if is_bold:
                                line_text += f"<b>{content}</b>"
                            else:
                                line_text += content
                        block_text += line_text + "\n"
                    text += block_text + "\n"
        
        # Verifica se é DOCX
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs:
                para_text = ""
                for run in para.runs:
                    if run.bold:
                        para_text += f"<b>{run.text}</b>"
                    else:
                        para_text += run.text
                text += para_text + "\n\n"
        
        return text
    except Exception as e:
        return f"Erro na leitura: {e}"

# ----------------- 4. LISTAS DE SEÇÕES -----------------
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

# ----------------- 5. INTERFACE PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

tipo_bula = st.radio("Selecione o tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
lista_secoes_ativa = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

st.divider()

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arquivo Referência", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📂 Arquivo BELFAR", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada nos Secrets.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando Inteligência Artificial..."):
            f1.seek(0); f2.seek(0)
            t_ref = extract_text_from_file(f1)
            t_belfar = extract_text_from_file(f2)

            if len(t_ref) < 20 or len(t_belfar) < 20:
                st.error("Erro: Arquivo ilegível ou vazio."); st.stop()

            prompt = f"""
            Você é um Auditor de Qualidade Farmacêutica Rígido.
            
            INPUT TEXTO REFERÊNCIA:
            {t_ref} 
            
            INPUT TEXTO BELFAR:
            {t_belfar}

            SUA TAREFA:
            1. Identifique as seções listadas abaixo.
            2. Extraia o texto MANTENDO A FORMATAÇÃO ORIGINAL (quebras de linha e tags <b>).
            3. Se houver listas (bullet points), mantenha cada item em uma linha separada.
            4. NÃO CORRIJA ERROS. Copie exatamente como está no texto extraído acima.

            LISTA DE SEÇÕES: {lista_secoes_ativa}

            REGRAS DE OUTPUT:
            - Seções "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS": Status "CONFORME". Apenas extraia.
            - Outras Seções: Compare o texto. Se houver divergência, use <span class="highlight-yellow"> no trecho diferente.
            - Destaque a Data da Anvisa nos "DIZERES LEGAIS" com <span class="highlight-blue">.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_belfar": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_ref": "Texto original com tags <b> e quebras de linha",
                        "texto_belfar": "Texto original com tags <b> e quebras de linha",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                    response = model.generate_content(prompt, request_options={'retry': None})
                    break 
                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1: continue
                    else: st.error(f"Erro Fatal: {ultimo_erro}"); st.stop()

            if response:
                try:
                    resultado = json.loads(response.text)
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_belfar = resultado.get("data_anvisa_belfar", "-")
                    dados_secoes = resultado.get("secoes", [])

                    divergentes_count = 0
                    for item in dados_secoes:
                        if 'highlight-yellow' in item.get('texto_belfar', '') or item.get('status') == 'DIVERGENTE':
                            item['status'] = 'DIVERGENTE'
                            divergentes_count += 1
                        else:
                            item['status'] = 'CONFORME'

                    st.markdown("### 📊 Resumo da Conferência")
                    c_d1, c_d2, c_d3 = st.columns(3)
                    c_d1.metric("Data Ref.", data_ref)
                    c_d2.metric("Data BELFAR", data_belfar, delta="Igual" if data_ref == data_belfar else "Diferente")
                    c_d3.metric("Seções", len(dados_secoes))

                    sub1, sub2 = st.columns(2)
                    sub1.info(f"✅ **Conformes:** {len(dados_secoes) - divergentes_count}")
                    if divergentes_count > 0: sub2.warning(f"⚠️ **Divergentes:** {divergentes_count}")
                    else: sub2.success("✨ **Divergências:** 0")

                    st.divider()

                    for item in dados_secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon = "⚖️"; css = "border-info"; aberto = True
                        elif status == "CONFORME":
                            icon = "✅"; css = "border-ok"; aberto = False
                        else:
                            icon = "⚠️"; css = "border-warn"; aberto = True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("📜 Referência")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_ref", "")}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("💊 BELFAR")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_belfar", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro ao ler resposta da IA: {e}")
    else:
        st.warning("Envie os dois arquivos.")
