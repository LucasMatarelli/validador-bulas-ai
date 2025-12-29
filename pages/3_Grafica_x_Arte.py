import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import fitz  # PyMuPDF
import docx
import io
import json

# ----------------- 1. CONFIGURAÇÃO VISUAL -----------------
st.set_page_config(page_title="Validador Farmacêutico Rigoroso", page_icon="⚖️", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Courier New', monospace; /* Fonte monoespaçada para ver cada caractere */
        font-size: 0.9rem;
        line-height: 1.5;
        color: #212529;
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        border: 1px solid #ced4da;
        height: 100%; 
        white-space: pre-wrap; /* Mantém quebras de linha originais */
    }

    /* Cores de Status */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #dc3545 !important; } /* Vermelho para erro */
    .border-info { border-left: 6px solid #17a2b8 !important; }

    /* Highlight de Erros */
    .diff-highlight { background-color: #ffcccc; text-decoration: underline; font-weight: bold; }

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

# ----------------- 3. PROCESSAMENTO DE ARQUIVOS -----------------
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

# Lista exata esperada (Case Sensitive)
SECOES_PADRAO = [
    "APRESENTAÇÕES", 
    "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", # Note que às vezes aparece com "?" ou sem
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
st.title("⚖️ Validador de Texto Rigoroso (Gemini 2.0)")
st.markdown("**Regra:** Transcrição exata e validação rígida de títulos (Ex: *Apresentação* ≠ *APRESENTAÇÕES*).")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Referência)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Validação)", type=["pdf", "jpg", "png", "docx"])

if st.button("🔍 Validar Texto Integral"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Extraindo e comparando texto integralmente..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # --- PROMPT PARA EXTRAÇÃO LITERAL E RIGOROSA ---
            prompt = f"""
            Você é um Auditor de Qualidade Documental.
            
            SUA MISSÃO: 
            1. Extrair o texto das bulas EXATAMENTE como está nos arquivos.
            2. Comparar Arte vs Gráfica.
            3. Validar rigorosamente os TÍTULOS das seções.

            LISTA DE TÍTULOS ESPERADOS (PADRÃO):
            {SECOES_PADRAO}

            ⚠️ REGRAS DE VALIDAÇÃO (CRÍTICO):
            
            1. **TÍTULOS:** - Compare o título encontrado no arquivo com a lista padrão acima.
               - A comparação deve ser EXATA (caractere por caractere).
               - Exemplo: Se no arquivo está "Apresentação" e o padrão é "APRESENTAÇÕES", ISSO É UMA DIVERGÊNCIA DE TÍTULO.
               - Exemplo: Se no arquivo está "COMPOSICAO" (sem til) e o padrão é "COMPOSIÇÃO", ISSO É UMA DIVERGÊNCIA.
               - Se o título estiver errado, marque status: "DIVERGENTE".

            2. **CONTEÚDO DO TEXTO:**
               - Transcreva o texto CORPO da seção ipsis litteris (letra por letra).
               - NÃO mude pontuação. NÃO corrija erros de português.
               - Se houver diferença entre Arte e Gráfica, status: "DIVERGENTE".

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "TÍTULO ESPERADO DA LISTA",
                        "titulo_encontrado_arte": "Título exato lido na Arte",
                        "titulo_encontrado_grafica": "Título exato lido na Gráfica",
                        "texto_arte": "Texto completo exato...",
                        "texto_grafica": "Texto completo exato...",
                        "status": "CONFORME" ou "DIVERGENTE",
                        "obs": "Explique o erro se houver (ex: Título incorreto)"
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

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            "max_output_tokens": 8192 # Máximo permitido
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
                        st.error(f"❌ Erro fatal: {ultimo_erro}")
                        st.stop()
            
            if response:
                try:
                    texto = response.text
                    if "```json" in texto: texto = texto.split("```json")[1].split("```")[0]
                    elif "```" in texto: texto = texto.split("```")[1].split("```")[0]
                    
                    data = json.loads(texto.strip(), strict=False)
                    secoes = data.get("secoes", [])

                    # Métricas
                    total = len(secoes)
                    divs = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    oks = total - divs

                    st.markdown("### 📊 Resultado da Auditoria")
                    c1, c2 = st.columns(2)
                    c1.metric("Conformes", oks)
                    c2.metric("Divergentes", divs, delta_color="inverse")

                    if divs > 0:
                        st.error(f"❌ Foram encontradas {divs} divergências (Texto ou Título).")
                    else:
                        st.success("✅ Documento 100% Conforme (Títulos e Conteúdo).")

                    st.divider()

                    for s in secoes:
                        status = s.get('status', 'CONFORME')
                        titulo_padrao = s.get('titulo_padrao', 'Seção Desconhecida')
                        titulo_arte = s.get('titulo_encontrado_arte', '-')
                        titulo_graf = s.get('titulo_encontrado_grafica', '-')
                        obs = s.get('obs', '')

                        # Lógica de Ícone e Borda
                        if status == "CONFORME":
                            icon = "✅"
                            css = "border-ok"
                            aberto = False
                        else:
                            icon = "🚨"
                            css = "border-warn"
                            aberto = True

                        with st.expander(f"{icon} {titulo_padrao}", expanded=aberto):
                            
                            # Validação Específica de Título
                            if titulo_arte != titulo_padrao or titulo_graf != titulo_padrao:
                                st.markdown(f"""
                                <div style="background-color: #f8d7da; padding: 10px; border-radius: 5px; margin-bottom: 10px; color: #721c24;">
                                    <strong>❌ ERRO DE TÍTULO DETECTADO:</strong><br>
                                    Esperado: <code>{titulo_padrao}</code><br>
                                    Encontrado Arte: <code>{titulo_arte}</code><br>
                                    Encontrado Gráfica: <code>{titulo_graf}</code>
                                </div>
                                """, unsafe_allow_html=True)
                            
                            if obs:
                                st.caption(f"📝 Nota do Auditor: {obs}")

                            c_esq, c_dir = st.columns(2)
                            with c_esq:
                                st.caption("📄 Texto Arte (Original)")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with c_dir:
                                st.caption("📄 Texto Gráfica (Validação)")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("Erro ao processar o texto completo.")
                    st.warning("O arquivo pode ser muito grande para exibição integral em uma única passagem.")
                    st.text(f"Erro técnico: {e}")
                    if response.candidates:
                         st.write(f"Motivo parada: {response.candidates[0].finish_reason}")
    else:
        st.warning("Por favor, faça o upload dos arquivos.")
