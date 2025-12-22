import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import io
import json
import re  # IMPORTANTE: Adicionado para corrigir o erro dos pontos

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

st.markdown("""
<style>
    /* --- ESCONDER MENU SUPERIOR --- */
    [data-testid="stHeader"] {
        visibility: hidden;
    }

    /* Caixas de Texto */
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
        white-space: pre-wrap; /* Mantém parágrafos */
        text-align: justify;
    }

    /* Destaques Precisos */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
    }
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; font-weight: bold; 
    }
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }    /* Verde */
    .border-warn { border-left: 6px solid #ffc107 !important; } /* Amarelo */
    .border-info { border-left: 6px solid #17a2b8 !important; } /* Azul */

    /* Métricas no Topo */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 3. PROCESSAMENTO INTELIGENTE -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()

        # --- PROCESSAMENTO DE PDF ---
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            
            # Tenta pegar texto digital primeiro
            full_text = ""
            has_digital_text = False
            
            for page in doc:
                text = page.get_text("text")
                if len(text.strip()) > 50: 
                    has_digital_text = True
                full_text += text + "\n"
            
            if has_digital_text:
                return [full_text]
            else:
                images = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
        
        # --- PROCESSAMENTO DE IMAGENS ---
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]

        # --- PROCESSAMENTO DE DOCX ---
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return ["\n".join(full_text)]
            
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
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando... Priorizando texto original para evitar alucinações..."):
            f1.seek(0)
            f2.seek(0)
            
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # --- CORREÇÃO NO PROMPT: INSTRUÇÃO ANTI-PONTILHADO ---
            prompt = f"""
            Você é um EXTRATOR FORENSE DE TEXTO.
            
            INPUT: Documentos farmacêuticos (Texto Digital ou Imagens).
            TAREFA: Extrair e comparar as seções: {SECOES_COMPLETAS}

            ⚠️ PROTOCOLO DE TOLERÂNCIA ZERO PARA ALUCINAÇÃO:
            1. **VERBATIM:** Copie as palavras EXATAMENTE como estão.
            2. **TRATAMENTO DE LAYOUT (CRUCIAL):** - Se houver linhas pontilhadas longas (ex: "Cloridrato ......... 5mg"), **NÃO REPRODUZA OS PONTOS**. 
               - Substitua por um único espaço ou "..." curto.
               - O excesso de pontos causa erro no sistema.
            
            3. **ESTRUTURA JSON SEGURA:** - Use ASPAS SIMPLES nas tags HTML (ex: class='highlight').
               - Escape aspas duplas do texto original (\").

            🚨 REGRAS DE STATUS POR GRUPO:

            >>> GRUPO BLINDADO (SEM DIVERGÊNCIAS): 
            [ "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS" ]
            - Status OBRIGATÓRIO: "CONFORME".
            - PROIBIDO usar highlight.
            - Apenas transcreva o texto original limpo.
            - Exceção: Em "DIZERES LEGAIS", se encontrar uma data, envolva em <span class='highlight-blue'>DATA</span>.

            >>> GRUPO PADRÃO (TODAS AS OUTRAS SEÇÕES):
            - Compare palavra por palavra.
            - Diferença REAL? Marque <span class='highlight-yellow'>TEXTO ERRADO</span>.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto da arte",
                        "texto_grafica": "Texto da gráfica",
                        "status": "CONFORME"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- ARTE (REFERÊNCIA) ---"] + conteudo1 + ["--- GRÁFICA (VALIDAÇÃO) ---"] + conteudo2
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    response = model.generate_content(payload)
                    break 
                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        st.warning(f"⚠️ Chave {i+1} falhou. Tentando próxima...")
                        continue
                    else:
                        st.error(f"❌ Erro fatal: {ultimo_erro}")
                        st.stop()
            
            if response:
                try:
                    texto_limpo = response.text.replace("```json", "").replace("```", "").strip()
                    
                    # --- CORREÇÃO DE SEGURANÇA NO PYTHON ---
                    # Remove excesso de pontos que a IA possa ter gerado (ex: "......")
                    # Substitui qualquer sequência de mais de 3 pontos por "..."
                    texto_limpo = re.sub(r'\.{4,}', '...', texto_limpo)

                    resultado = json.loads(texto_limpo, strict=False)
                    
                    data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                    data_graf = resultado.get("data_anvisa_grafica", "Não encontrada")
                    secoes = resultado.get("secoes", [])

                    st.markdown("### 📊 Resumo da Conferência")
                    
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Data Anvisa (Ref)", data_ref)
                    
                    cor_delta = "normal" if data_ref == data_graf and data_ref != "Não encontrada" else "inverse"
                    msg_delta = "Vigência" if data_ref == data_graf else "Diferente"
                    if data_graf == "Não encontrada": msg_delta = ""
                    
                    k2.metric("Data Anvisa (Gráfica)", data_graf, delta=msg_delta, delta_color=cor_delta)
                    k3.metric("Seções Analisadas", len(secoes))

                    div_count = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    ok_count = len(secoes) - div_count
                    
                    b1, b2 = st.columns(2)
                    b1.success(f"✅ **Conformes: {ok_count}**")
                    if div_count > 0:
                        b2.warning(f"⚠️ **Divergentes: {div_count}**")
                    else:
                        b2.success("✨ **Divergentes: 0**")
                    
                    st.divider()

                    for item in secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon, css, aberto = "📅", "border-info", True
                        elif status == "CONFORME":
                            icon, css, aberto = "✅", "border-ok", False
                        else:
                            icon, css, aberto = "⚠️", "border-warn", True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("Referência (Arte)")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("Validação (Gráfica)")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except json.JSONDecodeError as e:
                    st.error(f"Erro JSON: {e}")
                    st.warning("O documento contém caracteres complexos de layout. Tente novamente.")
                    st.code(texto_limpo[:1000]) # Mostra o começo do erro para debug
                except Exception as e:
                    st.error(f"Erro visual: {e}")

    else:
        st.warning("Adicione os arquivos.")
