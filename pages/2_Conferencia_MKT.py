import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF

st.set_page_config(page_title="Conferência MKT (Gemini)", layout="wide")

# ----------------- CONFIGURAÇÃO -----------------
try:
    api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("MISTRAL_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    else:
        st.error("Sem chave API.")
        st.stop()
except:
    st.error("Erro config API.")
    st.stop()

def get_text(file):
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        text = ""
        for page in doc: text += page.get_text("text", sort=True) + "\n"
        return text
    except: return ""

st.title("📋 Conferência MKT (Regras)")
st.markdown("Validação de Regras e Ortografia via **Gemini 2.0 Flash Lite** (Sem OCR).")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Anvisa (Regra)", type="pdf", key="mkt1")
f2 = c2.file_uploader("Arte Marketing (Análise)", type="pdf", key="mkt2")

if st.button("🚀 Validar MKT"):
    if f1 and f2:
        with st.spinner("Lendo textos..."):
            t1 = get_text(f1)
            t2 = get_text(f2)
            
        if len(t1) < 50 or len(t2) < 50:
            st.error("⚠️ Um dos arquivos não possui texto digital. OCR desativado.")
        else:
            with st.spinner("⚡ Gemini Lite validando regras..."):
                prompt = f"""
                Atue como um Revisor de Marketing Farmacêutico Sênior.
                Analise a ARTE DE MARKETING (Texto 2) com base nas regras da BULA ANVISA (Texto 1).
                
                VERIFIQUE OS SEGUINTES PONTOS CRÍTICOS:
                1. **Ortografia e Gramática:** Liste qualquer erro de português na Arte.
                2. **Informações Obrigatórias:** Verifique se as informações de Posologia, Contraindicações e Cuidados estão coerentes com a Bula.
                3. **Proibições:** Verifique se há promessas de cura milagrosas ou uso off-label não permitido na bula.
                
                TEXTO 1 (BULA ANVISA - A VERDADE):
                {t1[:20000]}
                
                TEXTO 2 (ARTE MKT - PARA ANÁLISE):
                {t2[:20000]}
                
                Gere um relatório detalhado e profissional.
                """
                
                try:
                    model = genai.GenerativeModel("models/gemini-2.0-flash-lite-preview-02-05")
                    resp = model.generate_content(prompt)
                    
                    st.info("📝 Relatório de Conformidade")
                    st.markdown(resp.text)
                    
                except Exception as e:
                    st.error(f"Erro na IA: {e}")
    else:
        st.warning("Envie os arquivos.")
