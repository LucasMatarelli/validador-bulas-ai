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
st.set_page_config(page_title="Validador Farmacêutico (Auto-Pilot)", page_icon="🛡️", layout="wide")

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

# ----------------- 2. LISTA DE MODELOS (PRIORIDADE) -----------------
# O código tentará nesta ordem até um funcionar.
MODELOS_PARA_TENTAR = [
    "gemini-1.5-flash",          # Prioridade 1: Estável
    "gemini-1.5-flash-latest",   # Prioridade 2: Atualização
    "gemini-1.5-flash-8b",       # Prioridade 3: Leve/Rápido
    "gemini-2.0-flash-exp",      # Prioridade 4: Experimental (se voltar a cota)
    "gemini-1.5-pro"             # Prioridade 5: Último recurso
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
st.title("🛡️ Validador Farmacêutico (Modo Auto-Pilot)")
st.caption("O sistema testará automaticamente Modelos e Chaves até encontrar uma conexão aberta.")

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
        with st.spinner(f"Iniciando busca de rota disponível..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # PROMPT EXTREMAMENTE RIGOROSO (PARA FORÇAR O 1.5 A AGIR COMO O 2.0)
            prompt = f"""
            ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO FORENSE DE TEXTO.
            
            SUA TAREFA:
            1. Extrair o texto dos arquivos.
            2. Comparar Arte vs Gráfica.
            
            LISTA DE TÍTULOS OBRIGATÓRIA: {SECOES_PADRAO}

            ⚠️ INSTRUÇÕES DE TOLERÂNCIA ZERO:
            - **PROIBIDO RESUMIR.** Você deve transcrever o texto COMPLETO, caractere por caractere, linha por linha.
            - **TÍTULOS:** A validação é CASE SENSITIVE. Ex: "Apresentação" é diferente de "APRESENTAÇÕES". Marque como divergente.
            - Se o texto for longo, processe até o final. Não pare no meio.

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
            
            # Configuração de segurança para evitar bloqueio falso em bulas
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
            
            status_container = st.empty()
            
            # Monta o conteúdo final APENAS UMA VEZ
            conteudo_final = [prompt, "--- ARTE ---"] + conteudo1 + ["--- GRÁFICA ---"] + conteudo2

            # --- LOOP DUPLO: MODELOS X CHAVES ---
            for modelo_atual in MODELOS_PARA_TENTAR:
                if sucesso: break
                
                for idx_k, api_key in enumerate(keys_validas):
                    try:
                        status_container.info(f"⏳ Testando: **{modelo_atual}** com **Chave {idx_k+1}**...")
                        
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
                        
                        # CHAMADA CORRIGIDA (SEM 'PAYLOAD=')
                        response = model.generate_content(conteudo_final)
                        
                        # Se não deu erro, sucesso!
                        sucesso = True
                        modelo_conectado = modelo_atual
                        status_container.success(f"✅ Conectado! Usando: **{modelo_atual}** (Chave {idx_k+1})")
                        time.sleep(1) # Pausa dramática para ler o sucesso
                        status_container.empty() # Limpa a mensagem
                        break 

                    except Exception as e:
                        err = str(e)
                        # Se for 404 (Modelo não existe), pula pro próximo modelo
                        if "404" in err or "not found" in err.lower():
                            break 
                        
                        # Se for 429 (Cota), tenta próxima chave
                        elif "429" in err or "quota" in err.lower():
                            # Se for o último modelo e última chave, salva o erro
                            ultimo_erro = f"Quota excedida em {modelo_atual}"
                            time.sleep(0.5)
                            continue 
                        
                        else:
                            ultimo_erro = err
                            continue
            
            if not sucesso:
                st.error("❌ Falha Total: Todas as combinações de Chaves e Modelos falharam.")
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
                        st.error(f"❌ {divs} Divergências encontradas.")
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
                            # Validação visual de título
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
                    st.error("Erro ao ler JSON da resposta.")
                    st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
