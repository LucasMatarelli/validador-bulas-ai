import streamlit as st
import google.generativeai as genai
import fitz

st.set_page_config(page_title="MKT (Dual Key)", layout="wide")

# ----------------- FUNÇÃO DE ROTAÇÃO -----------------
def try_generate_content(model_name, prompt):
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    if not valid_keys: raise Exception("Sem chaves API configuradas.")
    
    last_err = None
    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)
            return model.generate_content(prompt)
        except Exception as e:
            last_err = e
            continue
    raise last_err

def get_text(file):
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        text = ""
        for page in doc: text += page.get_text("text", sort=True) + "\n"
        return text
    except: return ""

st.title("📋 Conferência MKT")
st.caption("Modelo: gemini-2.0-flash-lite-preview-02-05 | Backup Key: ON")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Anvisa", type="pdf", key="mkt1")
f2 = c2.file_uploader("Arte MKT", type="pdf", key="mkt2")

if st.button("🚀 Validar MKT"):
    if f1 and f2:
        with st.spinner("Lendo textos..."):
            t1 = get_text(f1)
            t2 = get_text(f2)
            
        if len(t1) < 50 or len(t2) < 50:
            st.error("⚠️ Texto insuficiente. OCR desligado.")
        else:
            with st.spinner("⚡ Gemini Lite validando (Alternando chaves se necessário)..."):
                prompt = f"""
                Atue como Revisor Farmacêutico.
                Compare ARTE MKT (Texto 2) com BULA ANVISA (Texto 1).
                
                VERIFIQUE:
                1. Ortografia/Gramática.
                2. Omissão de Contraindicações.
                3. Erros de Posologia.
                
                TEXTO 1 (ANVISA):
                {t1[:30000]}
                
                TEXTO 2 (MKT):
                {t2[:30000]}
                
                Gere relatório detalhado.
                """
                
                try:
                    resp = try_generate_content(
                        "models/gemini-2.0-flash-lite-preview-02-05",
                        prompt
                    )
                    st.info("📝 Relatório")
                    st.markdown(resp.text)
                except Exception as e:
                    st.error(f"Erro Fatal (Todas as chaves falharam): {e}")
    else:
        st.warning("Envie os arquivos.")
