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
st.set_page_config(page_title="Validador Estável (1.5 Flash)", page_icon="🛡️", layout="wide")

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

# ----------------- 2. MODELO (O ÚNICO DISPONÍVEL AGORA) -----------------
# O Flash 1.5 é o único que não está com limit: 0 no momento
MODELO_FIXO = "models/gemini-1.5-flash"

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
st.title("🛡️ Validador de Texto (Modo Estável)")
st.info("Usando Gemini 1.5 Flash com Prompt Rigoroso (Único modelo com cota disponível pelo Google no momento).")

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
        with st.spinner(f"Processando..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # PROMPT OTIMIZADO PARA O 1.5 NÃO SER "PREGUIÇOSO"
            prompt = f"""
            ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO FORENSE.
            
            SUA TAREFA É MECÂNICA:
            1. Ler o texto dos arquivos.
            2. Comparar Arte vs Gráfica.
            
            LISTA DE TÍTULOS OBRIGATÓRIA: {SECOES_PADRAO}

            ⚠️ INSTRUÇÕES ANTI-ALUCINAÇÃO PARA O MODELO:
            - **PROIBIDO RESUMIR.** Você deve transcrever o texto COMPLETO, caractere por caractere.
            - **PROIBIDO IGNORAR TÍTULOS.** Verifique a lista acima. Se o título no arquivo for "Apresentação" (singular) e na lista for "APRESENTAÇÕES" (plural), MARQUE COMO DIVERGENTE.
            - Se o texto for muito longo, NÃO PARE. Continue até o fim da seção.

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "Do gabarito acima",
                        "titulo_encontrado_arte": "O que você leu no arq 1",
                        "titulo_encontrado_grafica": "O que você leu no arq 2",
                        "texto_arte": "Texto INTEGRAL da seção...",
                        "texto_grafica": "Texto INTEGRAL da seção...",
                        "status": "CONFORME" ou "DIVERGENTE",
                        "obs": "Detalhe da divergência se houver"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- ARTE ---"] + conteudo1 + ["--- GRÁFICA ---"] + conteudo2
            
            # DESATIVAR TODOS OS FILTROS DE SEGURANÇA (Para evitar bloqueio falso em bulas)
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None
            ultimo_erro = ""
            sucesso = False

            # --- LOOP DE TENTATIVAS ---
            for i, api_key in enumerate(keys_validas):
                try:
                    # st.toast(f"Conectando via Chave {i+1}...") # Comentei para limpar a tela
                    
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            "max_output_tokens": 8192 # Forçando o máximo
                        },
                        safety_settings=safety_settings
                    )
                    
                    response = model.generate_content(payload)
                    sucesso = True
                    break 

                except Exception as e:
                    ultimo_erro = str(e)
                    # Se falhar o 1.5, espera um pouco e tenta a próxima chave
                    time.sleep(2) 
                    continue 
            
            if not sucesso:
                st.error("❌ Erro de Conexão.")
                st.write("Até o modelo 1.5 está instável ou suas chaves expiraram.")
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

                    st.markdown("### 📊 Resultado da Análise")
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
                    st.error("Erro ao ler JSON. O modelo pode ter cortado a resposta.")
                    st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
