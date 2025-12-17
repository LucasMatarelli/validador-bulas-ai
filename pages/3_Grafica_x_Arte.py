import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

st.set_page_config(page_title="Visual (Modo Seguro)", layout="wide")

# ----------------- LISTA DE MODELOS SEGUROS (COTA ALTA) -----------------
# Removemos qualquer 2.0 ou 2.5 para evitar o limite de 5 RPM.
SAFE_MODELS = [
    "models/gemini-1.5-flash",          # Padrão Global
    "models/gemini-1.5-flash-001",      # Versão Congelada (Mais compatível)
    "models/gemini-1.5-flash-002",      # Versão Atualizada
    "models/gemini-1.5-flash-latest"    # Alias
]

# ----------------- FUNÇÃO DE EXECUÇÃO BLINDADA -----------------
def generate_vision_content(prompt, img_objects):
    # Recupera as chaves
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        raise Exception("Nenhuma chave API configurada.")

    last_error = None

    # LÓGICA: Tenta Chave 1 (Todos os modelos) -> Falhou? -> Tenta Chave 2 (Todos os modelos)
    for api_key in valid_keys:
        genai.configure(api_key=api_key)
        
        for model_name in SAFE_MODELS:
            try:
                # Instancia o modelo atual do loop
                model = genai.GenerativeModel(model_name)
                
                # Tenta gerar o conteúdo
                response = model.generate_content([prompt, *img_objects])
                
                # Se chegou aqui, funcionou! Retorna e sai dos loops.
                return response, model_name
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Se for 404 (Modelo não existe nessa região/chave): Tenta o próximo NOME
                if "404" in error_str or "not found" in error_str:
                    continue 
                
                # Se for 429 (Cota estourada): Sai desse loop de modelos e TENTA A PRÓXIMA CHAVE
                elif "429" in error_str or "quota" in error_str:
                    break 
                
                # Outros erros: Tenta o próximo nome por garantia
                else:
                    continue

    # Se saiu de todos os loops e nada funcionou
    raise last_error

# ----------------- UTILITÁRIOS -----------------
def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom 2.0 é o ideal para leitura visual
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except: return []

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Modo Seguro)")
st.caption("Motor: Rotação automática entre modelos da família 1.5 Flash (Alta Disponibilidade).")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte Aprovada", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Arquivo Gráfica", type=["pdf", "jpg", "png"], key="f2")

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
                Atue como Auditor de Qualidade Gráfica.
                Compare visualmente as duas imagens lado a lado.
                
                VERIFIQUE COM RIGOR:
                1. Layout e Diagramação (deslocamentos, margens).
                2. Fontes (trocas, caracteres corrompidos).
                3. Logotipos e Cores (mudanças visíveis).
                4. Textos (blocos faltando ou sobrando).
                
                RESULTADO:
                - Se idêntico: Responda apenas "✅ Aprovado".
                - Se houver erro: Liste os erros encontrados.
                """
                
                try:
                    with st.spinner(f"Analisando Pág {i+1} (Buscando modelo disponível)..."):
                        # Chama a função blindada
                        resp, used_model = generate_vision_content(prompt, [imgs1[i], imgs2[i]])
                        
                        if i == 0:
                            st.toast(f"Conectado via: {used_model}", icon="🟢")
                        
                        if "✅" in resp.text:
                            st.success(resp.text)
                        else:
                            st.error(resp.text)
                        
                        # Pausa de 5 segundos para garantir que o limite de 15 RPM não estoure
                        time.sleep(5)
                        
                except Exception as e:
                    st.error(f"Erro Fatal: {e}")
                    st.warning("Todas as tentativas de conexão falharam (404 e 429).")
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
