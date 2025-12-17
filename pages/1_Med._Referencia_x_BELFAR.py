import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import re

st.set_page_config(page_title="Ref x BELFAR (Gemini Lite)", layout="wide")

# ----------------- CONFIGURAÇÃO API -----------------
try:
    api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("MISTRAL_API_KEY") # Tenta pegar qualquer uma configurada
    if api_key:
        genai.configure(api_key=api_key)
    else:
        st.error("Configure a GEMINI_API_KEY no secrets.toml")
        st.stop()
except:
    st.error("Erro na configuração da API.")
    st.stop()

# ----------------- FUNÇÕES -----------------
def get_text_from_pdf(file):
    """Extrai texto digital (sem OCR)."""
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        text = ""
        for page in doc:
            # sort=True organiza colunas (essencial para bula)
            text += page.get_text("text", sort=True) + "\n"
        return text
    except Exception as e:
        return ""

def clean_json(text_response):
    """Limpa o markdown ```json ... ``` para evitar erros."""
    text = re.sub(r"```json", "", text_response)
    text = re.sub(r"```", "", text)
    return text.strip()

# ----------------- UI -----------------
st.title("💊 Ref x BELFAR (Gemini Lite)")
st.markdown("Comparação de Texto via **Gemini 2.0 Flash Lite** (Sem OCR).")

# Estilos CSS para os cards
st.markdown("""
<style>
    .box-ref { background-color: #f8f9fa; padding: 15px; border-left: 5px solid #6c757d; border-radius: 5px; }
    .box-bel { background-color: #f1f8e9; padding: 15px; border-left: 5px solid #55a68e; border-radius: 5px; }
    mark.diff { background-color: #fff176; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
    mark.ort { background-color: #ffcdd2; padding: 2px 4px; border-radius: 3px; font-weight: bold; text-decoration: underline; }
    mark.anvisa { background-color: #b3e5fc; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência (PDF Texto)", type="pdf", key="f1")
f2 = c2.file_uploader("Belfar (PDF Texto)", type="pdf", key="f2")

if st.button("🚀 Iniciar Auditoria"):
    if f1 and f2:
        with st.spinner("Lendo arquivos (Modo Texto Digital)..."):
            t1 = get_text_from_pdf(f1)
            t2 = get_text_from_pdf(f2)
        
        if len(t1) < 50 or len(t2) < 50:
            st.error("⚠️ Atenção: Um dos arquivos parece ser imagem ou está vazio. Este módulo não usa OCR.")
        else:
            with st.spinner("⚡ Gemini Lite analisando..."):
                prompt = f"""
                ATUE COMO UM AUDITOR FARMACÊUTICO.
                
                TAREFA:
                Compare o texto REF (Referência) com o texto BEL (Candidato) seção por seção.
                
                REGRAS OBRIGATÓRIAS:
                1. Extraia o texto COMPLETO de cada seção. NÃO RESUMA.
                2. No campo 'bel', use tags HTML para destacar problemas:
                   - <mark class='diff'>texto</mark> para divergências de conteúdo (números, palavras trocadas).
                   - <mark class='ort'>texto</mark> para erros de português.
                   - <mark class='anvisa'>data</mark> para datas nos Dizeres Legais.
                3. Se o texto for igual, apenas copie ele sem tags.
                
                FORMATO JSON DE RESPOSTA:
                {{
                    "METADADOS": {{"datas": ["DD/MM/AAAA"]}},
                    "SECOES": [
                        {{"titulo": "NOME DA SEÇÃO", "ref": "Texto completo ref...", "bel": "Texto completo bel...", "status": "OK ou DIVERGENTE"}}
                    ]
                }}

                === TEXTO REF ===
                {t1}

                === TEXTO BEL ===
                {t2}
                """
                
                try:
                    # Usando o modelo Lite Rápido
                    model = genai.GenerativeModel("models/gemini-2.0-flash-lite-preview-02-05")
                    
                    # Força resposta JSON
                    resp = model.generate_content(
                        prompt, 
                        generation_config={"response_mime_type": "application/json"}
                    )
                    
                    data = json.loads(clean_json(resp.text))
                    
                    # Renderização
                    secs = data.get("SECOES", [])
                    dates = data.get("METADADOS", {}).get("datas", [])
                    
                    st.success("✅ Análise Finalizada")
                    
                    # Métricas
                    col_m1, col_m2 = st.columns(2)
                    errs = sum(1 for s in secs if "DIVERGENTE" in s['status'])
                    col_m1.metric("Seções Analisadas", len(secs))
                    col_m2.metric("Seções com Divergência", errs)
                    
                    if dates:
                        st.caption(f"📅 Data Detectada: {dates[0]}")
                    
                    st.divider()

                    for s in secs:
                        icon = "❌" if "DIVERGENTE" in s['status'] else "✅"
                        with st.expander(f"{icon} {s.get('titulo', 'Seção')} - {s.get('status')}"):
                            cR, cB = st.columns(2)
                            cR.markdown(f"**Referência**<div class='box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**Candidato**<div class='box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                            
                except Exception as e:
                    st.error(f"Erro na IA: {e}")
    else:
        st.warning("Envie os dois arquivos.")
