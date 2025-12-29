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
st.set_page_config(page_title="Validador Farmacêutico (Blindado)", page_icon="🛡️", layout="wide")

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
# O sistema tentará estes nomes em ordem até um funcionar.
# Isso resolve o erro 404 (nome errado) e o erro 429 (cota).
MODELOS_DISPONIVEIS = [
    "gemini-1.5-flash-latest",   # Tentativa 1: Versão mais recente
    "gemini-1.5-flash-001",      # Tentativa 2: Versão estável 001
    "gemini-1.5-flash-002",      # Tentativa 3: Versão estável 002
    "gemini-1.5-flash",          # Tentativa 4: Apelido genérico
    "gemini-1.5-flash-8b",       # Tentativa 5: Versão leve
    "gemini-1.5-pro-latest",     # Tentativa 6: Pro (se o Flash falhar tudo)
    "gemini-1.5-pro-001"         # Tentativa 7: Pro estável
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
st.title("🛡️ Validador Farmacêutico (Sistema Anti-Falha)")
st.caption("Auto-Repair ativado: Testando múltiplas versões do Gemini automaticamente.")

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
        with st.spinner(f"Iniciando varredura de modelos compatíveis..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # PROMPT RIGOROSO (FORÇA A TRANSCRIÇÃO COMPLETA)
            prompt = f"""
            ATUE COMO UM SOFTWARE DE COMPARAÇÃO FORENSE DE TEXTO.
            
            SUA TAREFA:
            1. Ler o texto dos arquivos.
            2. Comparar Arte vs Gráfica.
            
            LISTA DE TÍTULOS OBRIGATÓRIA: {SECOES_PADRAO}

            ⚠️ INSTRUÇÕES:
            - **NÃO RESUMA.** Transcreva o texto COMPLETO, caractere por caractere.
            - **TÍTULOS:** Se o título no arquivo for diferente do gabarito (ex: "Apresentação" vs "APRESENTAÇÕES"), MARQUE COMO DIVERGENTE.
            - Se o texto for longo, continue até o fim.

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "Do gabarito",
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
            modelo_conectado = ""
            sucesso = False
            
            status_placeholder = st.empty()

            # --- LOOP DUPLO: TENTA TODOS OS MODELOS X TODAS AS CHAVES ---
            for modelo_atual in MODELOS_DISPONIVEIS:
                if sucesso: break
                
                for idx_k, api_key in enumerate(keys_validas):
                    try:
                        status_placeholder.text(f"Testando conexão: {modelo_atual} (Chave {idx_k+1})...")
                        
                        genai.configure(api_key=api_key)
                        # Sem o prefixo 'models/' que às vezes causa erro em versões novas da lib
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
                        
                        # Se passou daqui, funcionou!
                        sucesso = True
                        modelo_conectado = modelo_atual
                        status_placeholder.success(f"✅ Conectado com sucesso ao modelo: {modelo_atual}")
                        break 

                    except Exception as e:
                        err = str(e)
                        # Se for 404 ou Not Found, tenta o próximo modelo (break no loop de chaves)
                        if "404" in err or "not found" in err.lower():
                            break 
                        
                        # Se for 429 (Quota), tenta a próxima chave no mesmo modelo
                        elif "429" in err or "quota" in err.lower():
                            time.sleep(1)
                            continue 
                        
                        # Outros erros, salva e tenta próximo
                        else:
                            ultimo_erro = err
                            continue
            
            if not sucesso:
                st.error("❌ Falha crítica: Nenhum modelo do Google respondeu.")
                st.write("Isso geralmente indica que a biblioteca `google-generativeai` precisa ser atualizada no servidor ou o Google está instável.")
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

                    st.markdown(f"### 📊 Resultado ({modelo_conectado})")
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
