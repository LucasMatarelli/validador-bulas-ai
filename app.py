import streamlit as st
from groq import Groq
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Groq (Safe Mode)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; height: 100%;
    }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
    
    .stButton>button { width: 100%; background-color: #f25c05; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #d94e00; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]
SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]
SECOES_SEM_DIVERGENCIA = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- FUNÇÕES AUXILIARES -----------------
def get_groq_client():
    api_key = None
    try: api_key = st.secrets["GROQ_API_KEY"]
    except: pass
    
    if not api_key: api_key = os.environ.get("GROQ_API_KEY")
    if not api_key: return None
    return Groq(api_key=api_key)

def process_uploaded_file(uploaded_file):
    """Extrai TEXTO puro."""
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        full_text = ""

        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            full_text = "\n".join([p.text for p in doc.paragraphs])
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                full_text += page.get_text() + "\n"
            doc.close()
            
        return full_text
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}")
        return None

def extract_json(text):
    try:
        text = text.replace("```json", "").replace("```", "").strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(text[start:end])
        return json.loads(text)
    except: return None

# ----------------- FUNÇÃO DE GERAÇÃO (AJUSTADA PARA LIMITE 12k TPM) -----------------
def analisar_bula_groq(client, texto_ref, texto_bel, secoes):
    
    # --- CÁLCULO DE SEGURANÇA PARA PLANO FREE ---
    # Limite Groq Free: 12.000 tokens/min (TPM)
    # 1 token ~= 4 caracteres.
    # Vamos usar no máximo 6.000 tokens de ENTRADA (aprox 24.000 caracteres)
    # E reservar 2.000 tokens para SAÍDA.
    # Total da requisição: ~8.000 tokens (bem abaixo dos 12.000)
    
    LIMIT_CHARS_PER_DOC = 12000 # 12k chars por documento = ~3k tokens cada
    
    ref_safe = texto_ref[:LIMIT_CHARS_PER_DOC]
    bel_safe = texto_bel[:LIMIT_CHARS_PER_DOC]
    
    prompt_system = """
    Você é um Auditor Farmacêutico.
    REGRAS HTML:
    1. DIVERGÊNCIAS: Use <mark class='diff'>texto</mark> NOS DOIS LADOS.
    2. ERRO PORTUGUÊS: Use <mark class='ort'>texto</mark>.
    3. DATA ANVISA: Procure "Aprovado em dd/mm/aaaa" nos Dizeres Legais e use <mark class='anvisa'>data</mark>.

    SAÍDA JSON:
    { "METADADOS": { "score": 0-100, "datas": [] }, "SECOES": [ { "titulo": "...", "ref": "...", "bel": "...", "status": "..." } ] }
    """

    prompt_user = f"""
    --- TEXTO REFERÊNCIA (Parte 1) ---
    {ref_safe}

    --- TEXTO BELFAR (Parte 1) ---
    {bel_safe}

    SEÇÕES PARA ANALISAR:
    {secoes}
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=3000, # Reduzido para garantir que cabe no limite TPM
            top_p=1,
            stream=False,
        )
        return chat_completion.choices[0].message.content
    
    except Exception as e:
        error_msg = str(e)
        if "413" in error_msg or "rate_limit" in error_msg:
             st.warning("⚠️ O arquivo é muito grande para o plano gratuito da Groq. O texto foi truncado para caber.")
             return None
        else:
             st.error(f"Erro na Groq: {e}")
             return None

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador Groq")
    
    client = get_groq_client()
    if client: st.success("✅ Groq Ativo")
    else: st.error("❌ Configure o secrets.toml"); st.stop()
    
    st.divider()
    pagina = st.radio("Menu:", ["Início", "Comparar Bulas"])

if pagina == "Início":
    st.markdown("<h1 style='text-align: center; color: #f25c05;'>Validador Llama 3.3</h1>", unsafe_allow_html=True)
    st.info("Sistema otimizado para evitar bloqueios de Copyright e limites de tamanho da Groq.")

else:
    st.markdown("## Comparador de Bulas")
    
    col_tipo, _ = st.columns([1, 2])
    tipo_bula = col_tipo.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
    lista_secoes = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Referência (PDF/DOCX)", type=["pdf", "docx"])
    f2 = c2.file_uploader("Belfar (PDF/DOCX)", type=["pdf", "docx"])

    if st.button("🚀 COMPARAR AGORA") and f1 and f2:
        with st.spinner("⚡ Processando texto..."):
            
            t1 = process_uploaded_file(f1)
            t2 = process_uploaded_file(f2)
            
            if t1 and t2:
                json_res = analisar_bula_groq(client, t1, t2, lista_secoes)
                
                if json_res: # Se não deu erro 413
                    data = extract_json(json_res)
                    
                    if data:
                        meta = data.get("METADADOS", {})
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                        m2.metric("Seções", len(data.get("SECOES", [])))
                        m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                        st.divider()
                        
                        for sec in data.get("SECOES", []):
                            icon = "✅"
                            if "DIVERGENTE" in sec['status'].upper(): icon = "❌"
                            elif "FALTANTE" in sec['status'].upper(): icon = "🚨"
                            elif any(x in sec['titulo'] for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {sec['status']}"):
                                cA, cB = st.columns(2)
                                cA.markdown("**Referência**")
                                cA.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                                cB.markdown("**Belfar**")
                                cB.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
                    else:
                        st.error("Erro na leitura do JSON. Tente novamente.")
                else:
                    st.error("Falha na comunicação com a IA devido ao tamanho do texto.")
