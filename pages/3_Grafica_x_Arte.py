import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Scanner Total de Modelos", layout="wide")

# ----------------- LISTA MASSIVA DE MODELOS (O Pente Fino) -----------------
# Vamos testar do mais novo para o mais antigo, priorizando Flash/Vision.
ALL_POSSIBLE_MODELS = [
    # --- FAMÍLIA 2.0 (Novos/Lite) ---
    "models/gemini-2.0-flash-lite-preview-02-05",
    "models/gemini-2.0-flash-exp",
    
    # --- FAMÍLIA 1.5 FLASH (Os ideais) ---
    "models/gemini-1.5-flash", 
    "models/gemini-1.5-flash-latest",
    "models/gemini-1.5-flash-001",
    "models/gemini-1.5-flash-002",
    "models/gemini-1.5-flash-8b",

    # --- FAMÍLIA 1.5 PRO (Mais potentes) ---
    "models/gemini-1.5-pro",
    "models/gemini-1.5-pro-latest",
    "models/gemini-1.5-pro-001",
    "models/gemini-1.5-pro-002",

    # --- FAMÍLIA 1.0 / LEGACY (Último recurso) ---
    "models/gemini-pro-vision",  # Antigo modelo visual
    "models/gemini-1.0-pro-vision-latest",
    "models/gemini-pro",         # Texto apenas (mas serve para testar conexão)
]

# ----------------- FUNÇÃO DE VARREDURA TOTAL -----------------
def scanner_brutal():
    keys = {
        "🔑 Chave 1": st.secrets.get("GEMINI_API_KEY"),
        "🔑 Chave 2": st.secrets.get("GEMINI_API_KEY2")
    }
    
    # Remove chaves vazias
    active_keys = {name: k for name, k in keys.items() if k}
    
    if not active_keys:
        st.error("❌ Nenhuma chave configurada no secrets.toml")
        st.stop()

    results_log = []
    winner = None

    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_steps = len(active_keys) * len(ALL_POSSIBLE_MODELS)
    current_step = 0

    st.write("--- INICIANDO VARREDURA ---")

    for key_name, api_key in active_keys.items():
        genai.configure(api_key=api_key)
        
        for model_name in ALL_POSSIBLE_MODELS:
            current_step += 1
            progress = current_step / total_steps
            progress_bar.progress(progress)
            status_text.text(f"Testando {key_name} com {model_name}...")
            
            try:
                # Tenta instanciar e gerar um token mínimo
                model = genai.GenerativeModel(model_name)
                
                # Teste rápido: "Oi"
                response = model.generate_content("Oi")
                
                # SE PASSAR DAQUI, FUNCIONA!
                st.success(f"✅ SUCESSO! {key_name} aceitou o modelo: **{model_name}**")
                
                # Verifica se aceita imagem (Opcional, mas bom saber)
                can_see = "Vision" if "vision" in model_name or "1.5" in model_name or "2.0" in model_name else "Texto"
                
                winner = (api_key, model_name)
                break # Para tudo, achamos um que funciona!
                
            except Exception as e:
                err_msg = str(e)
                short_err = "Erro desconhecido"
                if "404" in err_msg: short_err = "404 (Não existe)"
                elif "429" in err_msg: short_err = "429 (Sem Cota)"
                elif "400" in err_msg: short_err = "400 (Inválido)"
                elif "403" in err_msg: short_err = "403 (Permissão)"
                
                # Log discreto para não poluir
                # results_log.append(f"{key_name} | {model_name} -> {short_err}")
                continue
        
        if winner: break

    progress_bar.empty()
    status_text.empty()
    
    if winner:
        return winner
    else:
        st.error("❌ VARREDURA COMPLETA: Nenhum modelo funcionou.")
        with st.expander("Ver detalhes técnicos"):
            st.write("Provável causa: As chaves API não têm o serviço 'Generative Language' ativado no Google Cloud, ou a região da conta bloqueia todos os modelos Gemini.")
        return None

# ----------------- UI -----------------
st.title("🔫 Scanner de Modelos & Comparador")

# Executa scanner se ainda não tivermos um modelo definido na sessão
if "working_config" not in st.session_state:
    if st.button("🔍 INICIAR VARREDURA EM TODAS AS CHAVES"):
        found = scanner_brutal()
        if found:
            st.session_state["working_config"] = found
            st.rerun()
else:
    # --- MODULO VISUAL ATIVADO ---
    api_key, model_name = st.session_state["working_config"]
    st.success(f"🔌 Conectado e Operante: `{model_name}`")
    
    # Configura o vencedor
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    # Função de Imagens
    def pdf_to_images(uploaded_file):
        try:
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            return images
        except: return []

    st.markdown("---")
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"])
    f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"])

    if st.button("🚀 Comparar Visualmente") and f1 and f2:
        with st.spinner("Processando..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            for i in range(min(len(imgs1), len(imgs2), 5)):
                st.markdown(f"**Página {i+1}**")
                colA, colB = st.columns(2)
                colA.image(imgs1[i], use_container_width=True)
                colB.image(imgs2[i], use_container_width=True)
                
                try:
                    # Tenta enviar imagem. Se o modelo for só texto (ex: gemini-pro), vai dar erro aqui.
                    resp = model.generate_content([
                        "Atue como auditor gráfico. Compare as duas imagens. Se idêntico: '✅ OK'. Se erro: Liste.",
                        imgs1[i], imgs2[i]
                    ])
                    st.write(resp.text)
                    time.sleep(3)
                except Exception as e:
                    if "images" in str(e) or "supported" in str(e):
                        st.error(f"O modelo encontrado ({model_name}) não suporta imagens. Tente outra chave.")
                    else:
                        st.error(f"Erro: {e}")
                st.divider()
    
    if st.button("🔄 Resetar Scanner"):
        del st.session_state["working_config"]
        st.rerun()
