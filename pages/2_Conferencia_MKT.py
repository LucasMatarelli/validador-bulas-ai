import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json

# ----------------- 1. VISUAL & CSS (O mesmo do anterior) -----------------
st.set_page_config(page_title="MKT Lado a Lado", page_icon="📢", layout="wide")

st.markdown("""
<style>
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
        white-space: pre-wrap; /* Mantém quebras de linha */
    }

    /* Destaques */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; border: 1px solid #bee5eb; font-weight: bold; }

    /* Bordas de Status */
    .border-ok { border-left: 6px solid #28a745 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ffc107 !important; } /* Amarelo */
    .border-err { border-left: 6px solid #dc3545 !important; }  /* Vermelho */
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
# Usando o flash-latest para garantir JSON estável e cota alta
MODELO_FIXO = "models/gemini-flash-latest"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. EXTRAÇÃO DE TEXTO (SEM OCR) -----------------
def extract_text_from_pdf(uploaded_file):
    """Extrai texto puro do PDF usando PyMuPDF (Fitz)"""
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        return text
    except Exception as e:
        return ""

# ----------------- 4. UI PRINCIPAL -----------------
st.title("📢 Conferência MKT (Texto vs Texto)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Anvisa (Referência)", type=["pdf"], key="anvisa")
f2 = c2.file_uploader("🎨 Arte MKT (Para Validar)", type=["pdf"], key="mkt")

if st.button("🚀 Validar Marketing"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Erro de API Key.")
            st.stop()

        with st.spinner("Extraindo textos e validando claims..."):
            # Extração de texto direto (Rápido, leve)
            t_anvisa = extract_text_from_pdf(f1)
            t_mkt = extract_text_from_pdf(f2)
            
            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("⚠️ Um dos arquivos parece vazio ou é imagem (não contém texto selecionável).")
                st.stop()

            # PROMPT ADAPTADO PARA MKT
            prompt = f"""
            Atue como Revisor Farmacêutico (Medical Affairs).
            Compare o TEXTO DO MKT (Material Promocional) com o TEXTO DA ANVISA (Bula/Referência).
            
            OBJETIVO: Validar se as afirmações do Marketing estão embasadas na Bula.

            TEXTO ANVISA (FONTE DE VERDADE):
            {t_anvisa[:50000]} 

            TEXTO MKT (PARA VALIDAR):
            {t_mkt[:20000]}

            TAREFA:
            1. Identifique cada TÓPICO/CLAIM feito no MKT (ex: "Indicação", "Posologia", "Slogan", "Advertências").
            2. Busque o trecho correspondente na Anvisa que comprova (ou contradiz) o MKT.
            3. Gere um JSON comparativo.

            REGRAS DE DESTAQUE (apenas no campo 'texto_mkt'):
            - <span class="highlight-yellow">TEXTO</span> para informações no MKT que não constam na bula ou estão exageradas (Divergência).
            - <span class="highlight-red">TEXTO</span> para erros gramaticais/ortográficos no MKT.
            - <span class="highlight-blue">TEXTO</span> para avisos legais obrigatórios (ex: "SE PERSISTIREM OS SINTOMAS...").

            SAÍDA JSON OBRIGATÓRIA:
            [
              {{
                "titulo": "Tópico Identificado (ex: Posologia)",
                "texto_anvisa": "Trecho copiado da Bula que valida o tópico",
                "texto_mkt": "Trecho do MKT com tags HTML de destaque",
                "status": "CONFORME" (se validado) ou "DIVERGENTE" (se inventado/errado)
              }}
            ]
            """
            
            try:
                # Chamada ao modelo
                response = model.generate_content(prompt)
                dados = json.loads(response.text)

                st.write("")
                
                # Métricas
                total = len(dados)
                divergentes = sum(1 for d in dados if d['status'] != 'CONFORME')
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Tópicos no MKT", total)
                k2.metric("Validados", total - divergentes)
                k3.metric("Atenção Requerida", divergentes, delta_color="inverse")
                st.divider()

                # Renderização Lado a Lado
                for item in dados:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Tópico')
                    
                    if status == "CONFORME":
                        icon = "✅"
                        css = "border-ok"
                    else:
                        icon = "⚠️"
                        css = "border-warn"

                    with st.expander(f"{icon} {titulo}", expanded=(status != "CONFORME")):
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("Referência (Bula Anvisa)")
                            # Texto Anvisa sem highlight, apenas para prova
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_anvisa", "Não encontrado na bula.")}</div>', unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("Peça MKT (Validada)")
                            # Texto MKT com os highlights coloridos
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_mkt", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar: {e}")
                st.caption("Dica: Verifique se os PDFs possuem texto selecionável (não são imagens escaneadas).")

    else:
        st.warning("Envie a Bula Anvisa e a Arte MKT.")
