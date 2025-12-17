import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import re
import os

st.set_page_config(page_title="Ref x BELFAR (Dual Key)", layout="wide")

# ----------------- FUNÇÃO DE ROTAÇÃO DE CHAVES -----------------
def try_generate_content(model_name, prompt, config=None):
    """
    Tenta usar a Chave 1. Se der erro (cota excedida), usa a Chave 2.
    """
    # Lista de chaves disponíveis
    keys = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2")
    ]
    # Remove chaves vazias/nulas
    valid_keys = [k for k in keys if k is not None]

    if not valid_keys:
        raise Exception("Nenhuma chave API configurada (GEMINI_API_KEY ou GEMINI_API_KEY2).")

    last_error = None

    for index, key in enumerate(valid_keys):
        try:
            # Configura a chave atual
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)
            
            # Tenta gerar
            response = model.generate_content(prompt, generation_config=config)
            return response
        except Exception as e:
            last_error = e
            # Se falhou, o loop continua para a próxima chave
            continue
    
    # Se todas falharem, levanta o erro da última
    raise last_error

# ----------------- FUNÇÕES AUXILIARES -----------------
def get_text_from_pdf(file):
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text", sort=True) + "\n"
        return text
    except: return ""

def clean_json(text):
    text = re.sub(r"```json|```", "", text).strip()
    return text

# ----------------- UI -----------------
st.title("💊 Ref x BELFAR (Gemini Lite - Dual Key)")
st.caption("Modelo: gemini-2.0-flash-lite-preview-02-05 | Sistema de Backup de Chave Ativo")

st.markdown("""
<style>
    .box-ref { background-color: #f8f9fa; padding: 15px; border-left: 5px solid #6c757d; }
    .box-bel { background-color: #f1f8e9; padding: 15px; border-left: 5px solid #55a68e; }
    mark.diff { background-color: #fff176; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência (PDF)", type="pdf", key="f1")
f2 = c2.file_uploader("Belfar (PDF)", type="pdf", key="f2")

if st.button("🚀 Iniciar Auditoria"):
    if f1 and f2:
        with st.spinner("Lendo textos (Sem OCR)..."):
            t1 = get_text_from_pdf(f1)
            t2 = get_text_from_pdf(f2)
        
        if len(t1) < 50 or len(t2) < 50:
            st.error("⚠️ Texto insuficiente. Este módulo não lê imagens (OCR desligado).")
        else:
            with st.spinner("⚡ Gemini Lite analisando (Tentando Chave 1... Se falhar, Chave 2)..."):
                prompt = f"""
                Você é um Auditor Farmacêutico.
                Compare o texto REF com o BELFAR.
                
                REGRAS:
                1. Extraia o texto COMPLETO de cada seção. NÃO RESUMA.
                2. Use <mark class='diff'>texto</mark> para divergências.
                3. Use <mark class='ort'>texto</mark> para erros de português.
                
                JSON:
                {{ "SECOES": [ {{"titulo": "X", "ref": "...", "bel": "...", "status": "OK/DIVERGENTE"}} ] }}

                === REF ===
                {t1}

                === BELFAR ===
                {t2}
                """
                
                try:
                    # CHAMADA COM ROTAÇÃO DE CHAVES
                    resp = try_generate_content(
                        "models/gemini-2.0-flash-lite-preview-02-05",
                        prompt,
                        config={"response_mime_type": "application/json"}
                    )
                    
                    data = json.loads(clean_json(resp.text))
                    st.success("✅ Análise Finalizada")
                    
                    for s in data.get("SECOES", []):
                        icon = "❌" if "DIVERGENTE" in s['status'] else "✅"
                        with st.expander(f"{icon} {s.get('titulo','Seção')}"):
                            cR, cB = st.columns(2)
                            cR.markdown(f"<div class='box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"<div class='box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                            
                except Exception as e:
                    st.error(f"Todas as chaves falharam. Erro: {e}")
    else:
        st.warning("Envie os arquivos.")
