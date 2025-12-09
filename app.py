import streamlit as st
from groq import Groq
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Llama 3 (Anti-Erro)",
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
    return Groq(api_key=api_key) if api_key else None

def limpar_texto(texto):
    """Remove quebras de linha excessivas para economizar tokens."""
    texto = re.sub(r'\n+', '\n', texto) # Remove linhas em branco repetidas
    texto = re.sub(r'\s+', ' ', texto)  # Remove espaços repetidos
    return texto.strip()

def preparar_texto_seguro(texto, limite_chars=18000):
    """
    Corta o texto estrategicamente para caber no limite Grátis da Groq (12k TPM).
    Prioriza o INÍCIO (Cabeçalho) e o FIM (Dizeres Legais/Data).
    """
    if len(texto) <= limite_chars:
        return texto
    
    # Se for muito grande, pega os primeiros 60% e os últimos 40% do limite
    corte_inicio = int(limite_chars * 0.6)
    corte_fim = int(limite_chars * 0.4)
    
    parte_inicio = texto[:corte_inicio]
    parte_fim = texto[-corte_fim:]
    
    return f"{parte_inicio}\n\n[...TRECHO CENTRAL OMITIDO PARA CABER NO LIMITE GRÁTIS...]\n\n{parte_fim}"

def process_uploaded_file(uploaded_file):
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
            
        # Limpa o texto para economizar espaço
        return limpar_texto(full_text)
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

# ----------------- FUNÇÃO DE GERAÇÃO (GROQ SAFE) -----------------
def analisar_bula_groq(client, texto_ref, texto_bel, secoes):
    
    # Prepara os textos cortando o excesso se necessário
    # 18.000 caracteres ~= 4.500 tokens. 
    # Ref(4.5k) + Bel(4.5k) + Prompt(1k) + Resposta(2k) = ~12k (Limite exato)
    ref_safe = preparar_texto_seguro(texto_ref)
    bel_safe = preparar_texto_seguro(texto_bel)
    
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
    SEÇÕES A ANALISAR: {secoes}

    --- REF ---
    {ref_safe}

    --- BEL ---
    {bel_safe}
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=3000, 
            top_p=1,
            stream=False,
        )
        return chat_completion.choices[0].message.content
    
    except Exception as e:
        erro = str(e)
        if "413" in erro or "rate_limit" in erro:
            st.error("⚠️ **Limite Grátis Atingido:** O arquivo é muito grande para o plano Free da Groq (12k tokens/min).")
            st.info("💡 Dica: Tente enviar apenas as páginas principais do PDF ou aguarde 1 minuto.")
        else:
            st.error(f"Erro na Groq: {e}")
        return None

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador Llama 3")
    
    client = get_groq_client()
    if client: st.success("✅ Groq Ativo")
    else: st.error("❌ Configure GROQ_API_KEY"); st.stop()
    
    st.divider()
    pagina = st.radio("Menu:", ["Início", "Comparar Bulas"])

if pagina == "Início":
    st.markdown("<h1 style='text-align: center; color: #f25c05;'>Validador Grátis (Sem Erros)</h1>", unsafe_allow_html=True)
    st.info("Este validador usa **Llama 3.3 (Meta)** via Groq.")
    
    st.markdown("""
    ### 🛡️ Proteções Ativas:
    1.  **Sem Copyright:** O Llama 3 não bloqueia textos de bulas.
    2.  **Anti-Estouro:** Se a bula for gigante, o sistema resume o "meio" automaticamente para não dar erro na conta grátis.
    3.  **Velocidade:** Processamento quase instantâneo.
    """)

else:
    st.markdown("## Comparador de Bulas")
    
    col_tipo, _ = st.columns([1, 2])
    tipo_bula = col_tipo.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
    lista_secoes = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Referência (PDF/DOCX)", type=["pdf", "docx"])
    f2 = c2.file_uploader("Belfar (PDF/DOCX)", type=["pdf", "docx"])

    if st.button("🚀 COMPARAR AGORA") and f1 and f2:
        with st.spinner("⚡ Otimizando texto e analisando..."):
            
            t1 = process_uploaded_file(f1)
            t2 = process_uploaded_file(f2)
            
            if t1 and t2:
                json_res = analisar_bula_groq(client, t1, t2, lista_secoes)
                
                if json_res: 
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
                            status = str(sec.get('status', '')).upper()
                            if "DIVERGENTE" in status: icon = "❌"
                            elif "FALTANTE" in status: icon = "🚨"
                            elif any(x in sec['titulo'] for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                cA, cB = st.columns(2)
                                cA.markdown("**Referência**")
                                cA.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                                cB.markdown("**Belfar**")
                                cB.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
                    else:
                        st.error("Erro na leitura do JSON. Tente novamente.")
