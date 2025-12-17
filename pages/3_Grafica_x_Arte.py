import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Visual (Auto-Fix)", layout="wide")

# ----------------- LISTA DE MODELOS PARA TENTAR -----------------
# O código vai testar um por um até achar o que sua conta aceita.
MODEL_CANDIDATES = [
    "models/gemini-1.5-flash",          # Nome padrão
    "models/gemini-1.5-flash-001",      # Nome versionado (comum em contas antigas)
    "models/gemini-1.5-flash-002",      # Versão atualizada
    "models/gemini-1.5-flash-latest",   # Alias
    "models/gemini-1.5-flash-8b",       # Versão ultra-leve
    "gemini-1.5-flash"                  # Sem prefixo
]

# ----------------- FUNÇÃO MESTRA (ROTAÇÃO TOTAL) -----------------
def try_generate_vision_robust(prompt, img_objects):
    """
    Tenta:
    1. Chave 1 -> Testa todos os modelos da lista.
    2. Se der erro de cota (429), muda para Chave 2 -> Testa todos os modelos.
    """
    
    # 1. Pega as chaves
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k] # Remove vazias

    if not valid_keys:
        raise Exception("Nenhuma chave API encontrada no secrets.toml")

    last_error = None

    # LOOP 1: Rotação de Chaves
    for key_idx, api_key in enumerate(valid_keys):
        genai.configure(api_key=api_key)
        
        # LOOP 2: Rotação de Nomes de Modelo
        for model_name in MODEL_CANDIDATES:
            try:
                model = genai.GenerativeModel(model_name)
                
                # Tenta gerar
                response = model.generate_content([prompt, *img_objects])
                return response, model_name # Sucesso! Retorna resposta e qual modelo funcionou
                
            except Exception as e:
                error_str = str(e)
                last_error = e
                
                # ANÁLISE DO ERRO PARA DECIDIR O QUE FAZER
                
                # Se for 404 (Model not found) -> TENTA O PRÓXIMO NOME NA MESMA CHAVE
                if "404" in error_str or "not found" in error_str.lower():
                    continue 
                
                # Se for 429 (Quota) -> PARA DE TESTAR NOMES E VAI PARA A PRÓXIMA CHAVE
                elif "429" in error_str or "quota" in error_str.lower():
                    break # Sai do loop de modelos, cai no loop de chaves
                
                # Outros erros -> Continua tentando
                else:
                    continue

    # Se chegou aqui, nada funcionou
    raise last_error

# ----------------- UTILITÁRIOS -----------------
def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except: return []

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Auto-Fix 404)")
st.caption("Motor: Busca automática do modelo Gemini Flash compatível.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Comparar Visualmente"):
    if f1 and f2:
        with st.spinner("Processando imagens..."):
            imgs1 = pdf_to_images(f1) if f1.name.lower().endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.lower().endswith(".pdf") else [Image.open(f2)]
            
            max_p = min(len(imgs1), len(imgs2), 5)
            
            for i in range(max_p):
                st.markdown(f"### 📄 Página {i+1}")
                col_a, col_b = st.columns(2)
                col_a.image(imgs1[i], caption="Arte", use_container_width=True)
                col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                
                prompt = """
                Atue como Especialista de Pré-Impressão.
                Compare visualmente as duas imagens.
                
                VERIFIQUE:
                1. Layout (deslocamentos).
                2. Fontes (trocas ou quebras).
                3. Logotipos e Cores.
                4. Textos (blocos sumidos).
                
                Se idêntico: Responda apenas "✅ Aprovado".
                Se houver erro: Liste os erros.
                """
                
                try:
                    # Chama a função robusta
                    resp, used_model = try_generate_vision_robust(prompt, [imgs1[i], imgs2[i]])
                    
                    if i == 0:
                        st.toast(f"Conectado com sucesso em: {used_model}", icon="🔌")
                    
                    if "✅" in resp.text:
                        st.success(resp.text)
                    else:
                        st.error(resp.text)
                    
                    time.sleep(4)
                    
                except Exception as e:
                    st.error(f"Erro Fatal: {e}")
                    st.warning("Verifique se suas chaves API têm acesso ao Gemini 1.5 Flash no Google AI Studio.")
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
