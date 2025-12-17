import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz
import io
import time
import requests

st.set_page_config(page_title="Diagnóstico & Visual", layout="wide")

# ----------------- INFORMAÇÕES DE COTA (FREE TIER) -----------------
st.sidebar.header("📊 Cotas do Plano Gratuito")
st.sidebar.info("""
**Gemini 1.5 Flash (O que queremos usar):**
* **15 RPM** (Requisições por Minuto)
* **1.500 RPD** (Requisições por Dia)
* **1 Milhão TPM** (Tokens por Minuto)

**Gemini 2.0 Flash Lite (Preview):**
* Cota instável ou Zero dependendo da conta.
""")

# ----------------- FERRAMENTA DE DIAGNÓSTICO -----------------
def testar_chave(api_key, key_name):
    if not api_key:
        return False, "Chave não configurada."
    
    genai.configure(api_key=api_key)
    log = []
    
    # Teste 1: Listar Modelos (Verifica Permissão da Conta)
    try:
        modelos = list(genai.list_models())
        nomes = [m.name for m in modelos if 'generateContent' in m.supported_generation_methods]
        if not nomes:
            return False, "Conectou, mas nenhum modelo disponível (Bloqueio de Região?)."
        log.append(f"✅ Listagem OK ({len(nomes)} modelos encontrados).")
    except Exception as e:
        return False, f"❌ Falha de Permissão (A API 'Generative Language' está ativada?): {str(e)}"

    # Teste 2: Tentar Gerar com Gemini 1.5 Flash
    target_model = "models/gemini-1.5-flash"
    try:
        model = genai.GenerativeModel(target_model)
        model.generate_content("Teste de conexão.")
        return True, f"✅ SUCESSO TOTAL! O modelo {target_model} está funcionando."
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            return False, "⚠️ Chave Válida, mas Cota Excedida (Espere alguns minutos)."
        elif "404" in error_msg:
            return False, f"❌ Modelo {target_model} não encontrado nesta chave."
        else:
            return False, f"❌ Erro ao gerar: {error_msg}"

# ----------------- UI PRINCIPAL -----------------
st.title("🛠️ Diagnóstico de Chaves & Visual")

tab1, tab2 = st.tabs(["🔍 DIAGNÓSTICO (Rode Primeiro)", "🎨 Comparador Visual"])

with tab1:
    st.markdown("### Verificação de Saúde das Chaves")
    if st.button("🔍 VERIFICAR CHAVES AGORA"):
        keys = {
            "Chave 1 (GEMINI_API_KEY)": st.secrets.get("GEMINI_API_KEY"),
            "Chave 2 (GEMINI_API_KEY2)": st.secrets.get("GEMINI_API_KEY2")
        }
        
        valid_key_found = False
        
        for name, key in keys.items():
            st.markdown(f"#### Testando: {name}...")
            if key:
                sucesso, msg = testar_chave(key, name)
                if sucesso:
                    st.success(msg)
                    valid_key_found = True
                else:
                    st.error(msg)
            else:
                st.warning("Não configurada no secrets.toml")
            st.divider()
            
        if not valid_key_found:
            st.error("🚫 Nenhuma chave está funcionando para o Gemini 1.5 Flash.")
            st.markdown("""
            **SOLUÇÃO:**
            1. Acesse o [Google AI Studio](https://aistudio.google.com/).
            2. Crie uma **NOVA CHAVE** em um projeto novo.
            3. Verifique se a API "Generative Language API" está ativada no Google Cloud.
            """)

# ----------------- O CÓDIGO VISUAL (SÓ RODA SE TIVER CHAVE) -----------------
with tab2:
    def get_working_genai():
        # Tenta pegar a primeira chave que passar no teste básico
        keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
        for k in keys:
            if k:
                try:
                    genai.configure(api_key=k)
                    genai.GenerativeModel("models/gemini-1.5-flash").generate_content("oi")
                    return k
                except: continue
        return None

    def pdf_to_images(file):
        try:
            doc = fitz.open(stream=file.read(), filetype="pdf")
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            return images
        except: return []

    st.markdown("### Comparação Gráfica")
    
    active_key = get_working_genai()
    
    if not active_key:
        st.warning("⚠️ O sistema não detectou chaves funcionais. Rode o Diagnóstico na aba ao lado.")
    else:
        st.success("Motor Visual Pronto (Gemini 1.5 Flash)")
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel("models/gemini-1.5-flash")

        c1, c2 = st.columns(2)
        f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"])
        f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"])

        if st.button("Comparar") and f1 and f2:
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            with st.spinner("Analisando..."):
                for i in range(min(len(imgs1), len(imgs2), 5)):
                    st.markdown(f"**Página {i+1}**")
                    colA, colB = st.columns(2)
                    colA.image(imgs1[i], use_container_width=True)
                    colB.image(imgs2[i], use_container_width=True)
                    
                    try:
                        resp = model.generate_content([
                            "Atue como auditor gráfico. Compare as imagens. Se igual, diga '✅ OK'. Se erro, liste.",
                            imgs1[i], imgs2[i]
                        ])
                        st.write(resp.text)
                        time.sleep(4)
                    except Exception as e:
                        st.error(f"Erro: {e}")
