import streamlit as st
import cohere
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Cohere (Sem Limites)",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8;
    }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; font-weight: bold; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; font-weight: bold; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; font-weight: bold; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; height: 55px; font-size: 16px; }
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
def get_cohere_client():
    try: api_key = st.secrets["COHERE_API_KEY"]
    except: api_key = os.environ.get("COHERE_API_KEY")
    return cohere.Client(api_key) if api_key else None

def process_uploaded_file(uploaded_file):
    """Extrai TEXTO puro (Cohere processa texto muito bem)"""
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
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match: return json.loads(match.group())
        return json.loads(text)
    except: return None

# ----------------- LÓGICA COHERE (MODELO COMMAND R+) -----------------
def analisar_bula_cohere(client, texto_ref, texto_bel, secoes):
    
    lista_secoes_str = "\n".join([f"- {s}" for s in secoes])
    
    mensagem = f"""
    Você é um Auditor Farmacêutico Especialista (ANVISA).
    
    TAREFA:
    Compare os dois textos de bula abaixo (Referência vs Belfar).
    
    INSTRUÇÕES DE EXTRAÇÃO:
    1. Para cada seção listada, extraia TODO o texto contido nela. NÃO RESUMA.
    2. Copie o texto até encontrar o título da próxima seção.
    
    INSTRUÇÕES DE COMPARAÇÃO (HTML):
    - DIVERGÊNCIAS: Use <mark class='diff'>texto diferente</mark> NOS DOIS LADOS (Ref e Bel).
    - ERROS DE PORTUGUÊS: Use <mark class='ort'>erro</mark>.
    - DATA DE APROVAÇÃO: Procure "Aprovado em dd/mm/aaaa" nos Dizeres Legais e marque com <mark class='anvisa'>data</mark>.
    
    FORMATO JSON OBRIGATÓRIO:
    {{
        "METADADOS": {{ "score": 0 a 100, "datas": ["lista de datas"] }},
        "SECOES": [
            {{ "titulo": "NOME DA SEÇÃO", "ref": "texto da referência...", "bel": "texto da belfar...", "status": "CONFORME" ou "DIVERGENTE" }}
        ]
    }}
    
    LISTA DE SEÇÕES A BUSCAR:
    {lista_secoes_str}
    
    --- DOCUMENTO REFERÊNCIA ---
    {texto_ref}
    
    --- DOCUMENTO BELFAR ---
    {texto_bel}
    """

    try:
        # Usa o modelo Command R+ (Suporta 128k tokens = Bula Gigante sem erro)
        response = client.chat(
            model="command-r-plus",
            message=mensagem,
            temperature=0.1,
            preamble="Você é um assistente JSON estrito. Retorne apenas JSON válido."
        )
        return response.text
    except Exception as e:
        st.error(f"Erro na API Cohere: {e}")
        return None

# ----------------- INTERFACE -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador Cohere")
    
    client = get_cohere_client()
    if client: st.success("✅ Cohere Ativo")
    else: st.error("❌ Configure o secrets.toml"); st.stop()
    
    st.divider()
    pagina = st.radio("Menu:", ["Início", "Comparar Bulas"])

if pagina == "Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador Enterprise (Command R+)</h1>", unsafe_allow_html=True)
    st.info("Este validador usa a tecnologia da Cohere, projetada para ler documentos longos sem cortes e sem falsos positivos de Copyright.")

else:
    st.markdown("## Comparador de Bulas")
    
    col_tipo, _ = st.columns([1, 2])
    tipo_bula = col_tipo.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
    lista_secoes = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Referência (PDF/DOCX)", type=["pdf", "docx"])
    f2 = c2.file_uploader("Belfar (PDF/DOCX)", type=["pdf", "docx"])

    if st.button("🚀 INICIAR AUDITORIA") and f1 and f2:
        with st.spinner("🤖 Lendo bula inteira (128k context)..."):
            
            t1 = process_uploaded_file(f1)
            t2 = process_uploaded_file(f2)
            
            if t1 and t2:
                json_res = analisar_bula_cohere(client, t1, t2, lista_secoes)
                
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
                            status_upper = str(sec.get('status', '')).upper()
                            
                            if "DIVERGENTE" in status_upper: icon = "❌"
                            elif "FALTANTE" in status_upper: icon = "🚨"
                            elif any(x in sec['titulo'] for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {status_upper}"):
                                cA, cB = st.columns(2)
                                cA.markdown("**Referência**")
                                cA.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                                cB.markdown("**Belfar**")
                                cB.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
                    else:
                        st.error("Erro na leitura do JSON. Tente novamente.")
                        # st.code(json_res) # Debug
