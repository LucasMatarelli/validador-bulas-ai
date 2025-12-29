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
st.set_page_config(page_title="Validador Farmacêutico Rigoroso", page_icon="⚖️", layout="wide")

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
    .border-warn { border-left: 6px solid #dc3545 !important; } /* Vermelho para erro */
    
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

# ----------------- 2. MODELO (Gemini 2.0 Flash) -----------------
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
st.title("⚖️ Validador Rigoroso (Multi-Key)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Referência)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Validação)", type=["pdf", "jpg", "png", "docx"])

if st.button("🔍 Validar Texto Integral"):
    
    # CARREGAMENTO EXPLÍCITO DAS 3 CHAVES
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"), 
        st.secrets.get("GEMINI_API_KEY2"), 
        st.secrets.get("GEMINI_API_KEY3")
    ]
    # Filtra apenas as chaves que existem (não nulas)
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada nos Segredos.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando... se uma chave falhar, tentaremos a próxima automaticamente..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            Você é um Auditor de Qualidade Documental.
            
            SUA MISSÃO: 
            1. Extrair o texto EXATAMENTE como está nos arquivos (letra por letra).
            2. Comparar Arte vs Gráfica.
            3. Validar rigorosamente os TÍTULOS.

            LISTA DE TÍTULOS PADRÃO: {SECOES_PADRAO}

            ⚠️ REGRAS DE VALIDAÇÃO:
            1. **TÍTULOS:** A comparação deve ser EXATA. 
               - "Apresentação" != "APRESENTAÇÕES" -> DIVERGENTE.
               - "COMPOSICAO" != "COMPOSIÇÃO" -> DIVERGENTE.
            
            2. **TEXTO:** - Transcreva o texto CORPO ipsis litteris.
               - NÃO mude pontuação. NÃO corrija erros.
               - Diferença? Status "DIVERGENTE".

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "ESPERADO",
                        "titulo_encontrado_arte": "ENCONTRADO ARTE",
                        "titulo_encontrado_grafica": "ENCONTRADO GRAFICA",
                        "texto_arte": "Texto completo...",
                        "texto_grafica": "Texto completo...",
                        "status": "CONFORME" ou "DIVERGENTE",
                        "obs": "Explicação do erro"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- ARTE ---"] + conteudo1 + ["--- GRÁFICA ---"] + conteudo2
            
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None
            ultimo_erro = ""
            sucesso = False

            # --- LOOP DE ROTAÇÃO DE CHAVES ---
            for i, api_key in enumerate(keys_validas):
                try:
                    st.toast(f"Tentando Chave {i+1}...")
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            "max_output_tokens": 8192
                        },
                        safety_settings=safety_settings
                    )
                    
                    response = model.generate_content(payload)
                    sucesso = True
                    st.toast(f"✅ Sucesso com Chave {i+1}!")
                    break  # SE DEU CERTO, SAI DO LOOP

                except Exception as e:
                    ultimo_erro = str(e)
                    # Se for o erro de quota (429) ou qualquer outro, avisa e continua
                    st.warning(f"⚠️ Chave {i+1} falhou (Quota ou Erro). Trocando para a próxima...")
                    time.sleep(1) # Espera 1 segundo para não travar a requisição
                    continue # VAI PARA A PRÓXIMA CHAVE
            
            # SE ACABOU O LOOP E NENHUMA FUNCIONOU
            if not sucesso:
                st.error(f"❌ Todas as {len(keys_validas)} chaves falharam. Detalhe do último erro: {ultimo_erro}")
                st.stop()
            
            # --- PROCESSAMENTO DA RESPOSTA (SÓ CHEGA AQUI SE UMA CHAVE FUNCIONAR) ---
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

                    st.markdown("### 📊 Resultado")
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
                            if titulo_arte != titulo_padrao or titulo_graf != titulo_padrao:
                                st.markdown(f"""
                                <div style="background-color: #f8d7da; padding: 10px; border-radius: 5px; margin-bottom: 10px; color: #721c24;">
                                    <strong>❌ ERRO DE TÍTULO:</strong><br>
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
