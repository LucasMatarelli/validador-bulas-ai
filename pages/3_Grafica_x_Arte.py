import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import fitz  # PyMuPDF
import docx
import io
import json

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        height: 100%; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        white-space: pre-wrap;
        text-align: justify;
    }

    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO (MANTIDO O FLASH) -----------------
MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 3. PROCESSAMENTO -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            has_digital_text = False
            for page in doc:
                text = page.get_text("text", sort=True)
                if len(text.strip()) > 50: has_digital_text = True
                full_text += text + "\n"
            
            if has_digital_text: return [full_text]
            else:
                images = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            return ["\n".join([p.text for p in doc.paragraphs])]
    except: return []

SECOES_COMPLETAS = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte Vigente", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Arquivo Gráfica", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Analisando bulas..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # --- PROMPT COM INSTRUÇÃO DE ECONOMIA (RESUMO) ---
            prompt = f"""
            Você é um Comparador de Textos Farmacêuticos.
            Compare as seções: {SECOES_COMPLETAS}

            ⚠️ INSTRUÇÃO DE LIMITE DE TOKENS (CRÍTICO):
            O modelo tem um limite de saída. Para não cortar o JSON:
            1. **SE ESTIVER "CONFORME":** NÃO transcreva o texto inteiro se for longo. Escreva apenas as primeiras 10 palavras, use "(...texto conforme...)" e as últimas 10 palavras.
            2. **SE ESTIVER "DIVERGENTE":** Transcreva o trecho completo onde está o erro para podermos ver.
            3. **SEM PONTILHADOS:** Nunca use "..........".

            SAÍDA JSON OBRIGATÓRIA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Inicio... (...texto conforme...) ...fim",
                        "texto_grafica": "Inicio... (...texto conforme...) ...fim",
                        "status": "CONFORME" or "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- DOC 1 ---"] + conteudo1 + ["--- DOC 2 ---"] + conteudo2
            
            # Configuração de segurança para liberar tudo
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            "max_output_tokens": 8192 # Limite máximo
                        },
                        safety_settings=safety_settings
                    )
                    
                    response = model.generate_content(payload)
                    break 

                except Exception as e:
                    if i == len(keys_validas) - 1:
                        st.error(f"Erro fatal na API: {e}")
                        st.stop()
                    continue
            
            if response:
                try:
                    # Tenta limpar o JSON
                    texto = response.text
                    if "```json" in texto: texto = texto.split("```json")[1].split("```")[0]
                    elif "```" in texto: texto = texto.split("```")[1].split("```")[0]
                    
                    # Tenta corrigir JSON cortado (gambiarra simples)
                    if not texto.strip().endswith("}"):
                        texto += "]}"
                        
                    data = json.loads(texto.strip(), strict=False)
                    
                    # --- EXIBIÇÃO ---
                    secoes = data.get("secoes", [])
                    data_ref = data.get("data_anvisa_ref", "-")
                    data_graf = data.get("data_anvisa_grafica", "-")

                    st.markdown("### 📊 Resultado")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Data Ref", data_ref)
                    c2.metric("Data Gráfica", data_graf, delta="Igual" if data_ref == data_graf else "Diferente")
                    c3.metric("Seções", len(secoes))

                    # Contador de divergências
                    divs = [s for s in secoes if s['status'] != 'CONFORME']
                    if divs: st.warning(f"⚠️ {len(divs)} Divergências encontradas!")
                    else: st.success("✅ Tudo Conforme!")

                    st.divider()

                    for s in secoes:
                        status = s.get('status', 'CONFORME')
                        titulo = s.get('titulo', 'Seção')
                        
                        icon = "✅" if status == "CONFORME" else "⚠️"
                        css = "border-ok" if status == "CONFORME" else "border-warn"
                        aberto = status != "CONFORME"

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            c_esq, c_dir = st.columns(2)
                            # Se for conforme, avisa que está resumido
                            aviso = " *(Texto resumido para economia)*" if status == "CONFORME" else ""
                            
                            with c_esq:
                                st.caption(f"Referência{aviso}")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with c_dir:
                                st.caption(f"Gráfica{aviso}")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"O JSON foi cortado pelo limite do modelo. Tente validar menos seções ou arquivos menores.")
                    st.text(f"Erro técnico: {e}")
                    if response.candidates:
                         st.write(f"Motivo da parada: {response.candidates[0].finish_reason}")
    else:
        st.warning("Adicione os arquivos.")
