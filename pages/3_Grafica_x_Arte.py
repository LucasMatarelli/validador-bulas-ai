import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import fitz  # PyMuPDF
import docx
import io
import json
import time

# ----------------- 1. CONFIGURAÇÃO VISUAL -----------------
st.set_page_config(page_title="Validador Farmacêutico (Multi-Model)", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
        line-height: 1.5;
        color: #212529;
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        border: 1px solid #ced4da;
        height: 100%; 
        white-space: pre-wrap;
    }

    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #dc3545 !important; }
    
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e9ecef;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. LISTA DE MODELOS (FAILOVER) -----------------
# Se o primeiro der 404, ele tenta o segundo, e assim por diante.
# Fugimos dos experimentais que estão com cota zero.
MODELOS_DISPONIVEIS = [
    "models/gemini-1.5-flash-latest",  # Nome mais atual
    "models/gemini-1.5-flash-001",     # Versão estável
    "models/gemini-1.5-flash",         # Apelido genérico
    "models/gemini-1.5-pro-latest",    # Plano B (Pro)
    "models/gemini-1.5-pro-001"        # Plano C (Pro estável)
]

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

SECOES_PADRAO = [
    "APRESENTAÇÕES", 
    "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

# ----------------- 4. UI PRINCIPAL -----------------
st.title("🛡️ Validador Farmacêutico (Auto-Repair)")
st.caption("Sistema inteligente que busca o modelo ativo automaticamente.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Referência)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Validação)", type=["pdf", "jpg", "png", "docx"])

if st.button("🔍 Validar Texto Integral"):
    
    # --- CARREGAMENTO DE CHAVES ---
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"), 
        st.secrets.get("GEMINI_API_KEY2"), 
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k and len(k) > 10]

    if not keys_validas:
        st.error("Nenhuma chave API válida encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner(f"Lendo arquivos..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO FORENSE.
            
            SUA TAREFA É MECÂNICA:
            1. Ler o texto dos arquivos.
            2. Comparar Arte vs Gráfica.
            
            LISTA DE TÍTULOS OBRIGATÓRIA: {SECOES_PADRAO}

            ⚠️ INSTRUÇÕES ANTI-ALUCINAÇÃO:
            - **PROIBIDO RESUMIR.** Transcreva o texto COMPLETO, caractere por caractere.
            - **TÍTULOS:** Se o título no arquivo for diferente do gabarito (ex: "Apresentação" vs "APRESENTAÇÕES"), MARQUE COMO DIVERGENTE.

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "Do gabarito acima",
                        "titulo_encontrado_arte": "Leitura Arte",
                        "titulo_encontrado_grafica": "Leitura Grafica",
                        "texto_arte": "Texto INTEGRAL...",
                        "texto_grafica": "Texto INTEGRAL...",
                        "status": "CONFORME" ou "DIVERGENTE",
                        "obs": "Divergência"
                    }}
                ]
            }}
            """
            
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None
            ultimo_erro = ""
            modelo_usado = ""

            # --- LOOP INTELIGENTE (MODELO + CHAVE) ---
            # Tenta encontrar uma combinação que funcione (Modelo X + Chave Y)
            sucesso = False
            
            progress_bar = st.progress(0)
            status_text = st.empty()

            for idx_m, modelo_atual in enumerate(MODELOS_DISPONIVEIS):
                if sucesso: break
                
                for idx_k, api_key in enumerate(keys_validas):
                    try:
                        status_text.text(f"Testando: {modelo_atual} | Chave {idx_k+1}...")
                        
                        genai.configure(api_key=api_key)
                        model = genai.GenerativeModel(
                            modelo_atual, 
                            generation_config={
                                "response_mime_type": "application/json", 
                                "temperature": 0.0,
                                "max_output_tokens": 8192
                            },
                            safety_settings=safety_settings
                        )
                        
                        # Tenta gerar
                        response = model.generate_content(payload=[prompt, "--- ARTE ---"] + conteudo1 + ["--- GRÁFICA ---"] + conteudo2)
                        
                        # Se não deu erro, sucesso!
                        sucesso = True
                        modelo_usado = modelo_atual
                        status_text.text(f"✅ Conectado! Modelo: {modelo_atual}")
                        progress_bar.progress(100)
                        break 

                    except Exception as e:
                        err = str(e)
                        # Se for 404 (Modelo não encontrado), tenta o próximo modelo imediatamente
                        if "404" in err or "not found" in err.lower():
                            # st.warning(f"Modelo {modelo_atual} não encontrado. Tentando próximo...")
                            break # Sai do loop de chaves e vai para o próximo modelo
                        
                        # Se for 429 (Quota), tenta a próxima chave com o mesmo modelo
                        elif "429" in err or "quota" in err.lower():
                            time.sleep(1)
                            continue 
                        
                        else:
                            ultimo_erro = err
                            continue
            
            if not sucesso:
                st.error("❌ Todos os modelos e chaves falharam.")
                st.code(ultimo_erro)
                st.stop()
            
            # --- EXIBIÇÃO ---
            if response:
                try:
                    texto = response.text
                    if "```json" in texto: texto = texto.split("```json")[1].split("```")[0]
                    elif "```" in texto: texto = texto.split("```")[1].split("```")[0]
                    
                    data = json.loads(texto.strip(), strict=False)
                    secoes = data.get("secoes", [])

                    total = len(secoes)
                    divs = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    oks = total - divs

                    st.markdown(f"### 📊 Resultado ({modelo_usado})")
                    c1, c2 = st.columns(2)
                    c1.metric("Conformes", oks)
                    c2.metric("Divergentes", divs, delta_color="inverse")

                    if divs > 0:
                        st.error(f"❌ {divs} Divergências.")
                    else:
                        st.success("✅ Tudo Conforme.")

                    st.divider()

                    for s in secoes:
                        status = s.get('status', 'CONFORME')
                        titulo_padrao = s.get('titulo_padrao', 'Seção')
                        titulo_arte = s.get('titulo_encontrado_arte', '-')
                        titulo_graf = s.get('titulo_encontrado_grafica', '-')
                        obs = s.get('obs', '')

                        if status == "CONFORME":
                            icon, css, aberto = "✅", "border-ok", False
                        else:
                            icon, css, aberto = "🚨", "border-warn", True

                        with st.expander(f"{icon} {titulo_padrao}", expanded=aberto):
                            if titulo_arte != titulo_padrao or titulo_graf != titulo_padrao:
                                st.markdown(f"""
                                <div style="background-color: #f8d7da; padding: 10px; border-radius: 5px; margin-bottom: 10px; color: #721c24;">
                                    <strong>❌ TÍTULO INCORRETO:</strong><br>
                                    Esperado: <code>{titulo_padrao}</code><br>
                                    Arte: <code>{titulo_arte}</code> | Gráfica: <code>{titulo_graf}</code>
                                </div>
                                """, unsafe_allow_html=True)
                            
                            if obs: st.caption(f"📝 {obs}")

                            ce, cd = st.columns(2)
                            with ce:
                                st.caption("Arte")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with cd:
                                st.caption("Gráfica")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("Erro ao ler JSON.")
                    st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
