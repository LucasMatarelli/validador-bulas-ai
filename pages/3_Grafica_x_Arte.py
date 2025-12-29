import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import fitz  # PyMuPDF
import docx
import io
import json

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico 2.0", page_icon="💊", layout="wide")

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
    
    .status-box {
        padding: 15px;
        border-radius: 8px;
        text-align: center;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .status-ok { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .status-warn { background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }

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

# ----------------- 2. CONFIGURAÇÃO MODELO (ATUALIZADO PARA 2.0) -----------------
# Este é o modelo mais moderno disponível atualmente fora da série 1.5
MODELO_FIXO = "models/gemini-2.0-flash-exp"

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
st.title("💊 Gráfica x Arte (Gemini 2.0)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte Vigente", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Arquivo Gráfica", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar com Gemini 2.0"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Analisando com Gemini 2.0 (Alta Performance)..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # --- PROMPT OTIMIZADO PARA 2.0 ---
            prompt = f"""
            Você é um Auditor Farmacêutico Sênior.
            Analise as seções: {SECOES_COMPLETAS}

            ⚠️ INSTRUÇÃO DE SAÍDA OBRIGATÓRIA (Token Economy):
            
            1. **SE O TEXTO ESTIVER IDÊNTICO ("CONFORME"):**
               - Retorne APENAS a string "IGUAL" nos campos de texto.
               - NÃO copie o texto original. Isso economiza memória.
            
            2. **SE O TEXTO ESTIVER DIFERENTE ("DIVERGENTE"):**
               - Copie o trecho da divergência para análise.

            3. **DIZERES LEGAIS:**
               - Tente extrair apenas as datas de aprovação se houver.
            
            SAÍDA JSON EXATA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME SEÇÃO",
                        "texto_arte": "IGUAL" (ou o texto do erro),
                        "texto_grafica": "IGUAL" (ou o texto do erro),
                        "status": "CONFORME" or "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- DOC ORIGINAL ---"] + conteudo1 + ["--- DOC GRÁFICA ---"] + conteudo2
            
            # Liberação de Segurança
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            # Gemini 2.0 suporta outputs maiores, mas mantemos 8k por segurança da API padrão
                            "max_output_tokens": 8192 
                        },
                        safety_settings=safety_settings
                    )
                    
                    response = model.generate_content(payload)
                    break 

                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        st.warning(f"⚠️ Chave {i+1} instável. Trocando...")
                        continue
                    else:
                        st.error(f"❌ Erro fatal na API (Gemini 2.0): {ultimo_erro}")
                        st.stop()
            
            if response:
                try:
                    texto = response.text
                    if "```json" in texto: texto = texto.split("```json")[1].split("```")[0]
                    elif "```" in texto: texto = texto.split("```")[1].split("```")[0]
                    
                    data = json.loads(texto.strip(), strict=False)
                    
                    secoes = data.get("secoes", [])
                    data_ref = data.get("data_anvisa_ref", "-")
                    data_graf = data.get("data_anvisa_grafica", "-")

                    st.markdown("### 📊 Resultado (Gemini 2.0)")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Data Ref", data_ref)
                    c2.metric("Data Gráfica", data_graf, delta="Igual" if data_ref == data_graf else "Diferente")
                    c3.metric("Seções", len(secoes))

                    divs = [s for s in secoes if s['status'] != 'CONFORME']
                    if divs: st.warning(f"⚠️ {len(divs)} Divergências encontradas!")
                    else: st.success("✅ Documento 100% Conforme!")

                    st.divider()

                    for s in secoes:
                        status = s.get('status', 'CONFORME')
                        titulo = s.get('titulo', 'Seção')
                        
                        t_arte = s.get("texto_arte", "")
                        t_graf = s.get("texto_grafica", "")
                        
                        # Verifica se o Gemini 2.0 usou o código de economia
                        eh_igual = (t_arte.strip().upper() == "IGUAL") or (t_graf.strip().upper() == "IGUAL")
                        
                        if status == "CONFORME" or eh_igual:
                            icon = "✅"
                            css = "border-ok"
                            aberto = False
                            conteudo_visual = """
                            <div class="status-box status-ok">
                                ✨ TEXTO VERIFICADO E APROVADO
                                <br><small>O Gemini 2.0 confirmou que o conteúdo é idêntico.</small>
                            </div>
                            """
                        else:
                            icon = "⚠️"
                            css = "border-warn"
                            aberto = True
                            conteudo_visual = None 

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            if conteudo_visual:
                                st.markdown(conteudo_visual, unsafe_allow_html=True)
                            else:
                                c_esq, c_dir = st.columns(2)
                                with c_esq:
                                    st.caption("Trecho Original")
                                    st.markdown(f'<div class="texto-box {css}">{t_arte}</div>', unsafe_allow_html=True)
                                with c_dir:
                                    st.caption("Trecho Gráfica")
                                    st.markdown(f'<div class="texto-box {css}">{t_graf}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("Erro ao ler JSON.")
                    st.text(f"Detalhe: {e}")
                    if response.candidates:
                         st.write(f"Motivo parada: {response.candidates[0].finish_reason}")
    else:
        st.warning("Adicione os arquivos.")
