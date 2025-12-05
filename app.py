import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
from PIL import Image
import pytesseract  # ← nova dependência

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS PERSONALIZADOS (MANTIDOS) -----------------
st.markdown("""
<style>
    /* OCULTA A BARRA SUPERIOR (TOOLBAR) */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }

    /* Ajuste de Fundo e Fontes */
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* ESTILO DO MENU DE NAVEGAÇÃO */
    .stRadio > div[role="radiogroup"] > label {
        background-color: white;
        border: 1px solid #e1e4e8;
        padding: 12px 15px;
        border-radius: 8px;
        margin-bottom: 8px;
        transition: all 0.2s;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #f0fbf7;
        border-color: #55a68e;
        color: #55a68e;
        cursor: pointer;
    }

    /* Card Estilizado */
    .stCard {
        background-color: white;
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05);
        margin-bottom: 25px;
        border: 1px solid #e1e4e8;
        transition: transform 0.2s;
        height: 100%;
    }
    .stCard:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 30px rgba(0,0,0,0.1);
        border-color: #55a68e;
    }

    /* Títulos dos Cards */
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    
    /* Destaques */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Box de Curva */
    .curve-box { background-color: #f8f9fa; border-left: 4px solid #55a68e; padding: 10px 15px; margin-top: 15px; font-size: 0.9rem; color: #666; }

    /* Botões */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }

    /* Marcações de Texto */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
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

# ----------------- FUNÇÕES DE LEITURA/EXTRAÇÃO -----------------

def extract_text_from_file(uploaded_file):
    """
    Extrai texto de DOCX ou PDF. Se for PDF, realiza OCR nas páginas (máx. 12 páginas).
    """
    file_bytes = uploaded_file.read()
    filename = uploaded_file.name.lower()

    if filename.endswith('.docx'):
        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join([p.text for p in doc.paragraphs])
        return text

    elif filename.endswith('.pdf'):
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        texts = []
        limit_pages = min(12, len(doc))
        for i in range(limit_pages):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            txt = pytesseract.image_to_string(img, lang="por")
            texts.append(txt)
            pix = None
            img = None
            gc.collect()
        doc.close()
        return "\n".join(texts)

    else:
        return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"):
        text = text[4:]
    return text

def extract_json(text):
    try:
        clean = clean_json_response(text)
        start = clean.find('{')
        end = clean.rfind('}') + 1
        if start != -1 and end != -1:
            return json.loads(clean[start:end])
        return json.loads(clean)
    except Exception:
        return None

# ----------------- FUNÇÃO DE CONFIGURAÇÃO DO MODELO -----------------

def get_gemini_model():
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "Chave API não configurada nos Secrets!"
    genai.configure(api_key=api_key)
    modelos_para_testar = [
        'models/gemini-2.5-flash',
        'models/gemini-1.5-pro',
        'models/gemini-2.0-flash-exp',
        'models/gemini-1.5-flash'
    ]
    for model_name in modelos_para_testar:
        try:
            model = genai.GenerativeModel(model_name)
            return model, model_name
        except Exception:
            continue
    return genai.GenerativeModel('models/gemini-1.5-flash'), "models/gemini-1.5-flash (Fallback)"

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    model_instance, model_name_used = get_gemini_model()
    if model_instance:
        st.success(f"✅ Conectado: {model_name_used.replace('models/', '')}")
    else:
        st.error("❌ Erro de Conexão")
        st.caption("Verifique se a chave está correta em Secrets.")
    st.divider()
    pagina = st.radio(
        "Navegação:",
        ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"]
    )
    st.divider()

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e; font-size: 3rem; margin-bottom: 10px;">Validador Inteligente</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Central de auditoria e conformidade de bulas farmacêuticas com IA.</p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">💊 Medicamento Referência x BELFAR</div>
            <div class="card-text">
                Compara a bula de referência com a bula BELFAR.<br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">📋 Conferência MKT</div>
            <div class="card-text">
                Compara arquivo ANVISA com PDF MKT.<br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">🎨 Gráfica x Arte Vigente</div>
            <div class="card-text">
                Compara PDF Gráfica com Arte Vigente (Lê curvas).<br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ----------------- FERRAMENTA (Auditoria) -----------------
else:
    st.markdown(f"## {pagina}")

    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"

    label_box1 = "Arquivo 1"
    label_box2 = "Arquivo 2"

    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Documento de Referência"
        label_box2 = "📄 Documento BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL
                nome_tipo = "Profissional"

    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 Arquivo ANVISA"
        label_box2 = "📄 Arquivo MKT"

    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"
        label_box2 = "📄 PDF da Gráfica"

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"##### {label_box1}")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2:
        st.markdown(f"##### {label_box2}")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")

    st.write("")
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not f1 or not f2:
            st.warning("⚠️ Por favor, faça o upload dos dois arquivos para continuar.")
        else:
            with st.spinner(f"🤖 Analisando com {model_name_used.split('/')[-1]}..."):
                try:
                    model = model_instance
                    if not model:
                        st.error("Erro crítico: Chave API não detectada.")
                        st.stop()

                    text1 = extract_text_from_file(f1)
                    text2 = extract_text_from_file(f2)
                    gc.collect()

                    if not text1 or not text2:
                        st.error("Falha ao extrair texto dos arquivos.")
                        st.stop()

                    # monta payload apenas com texto — sem imagem
                    payload = [
                        "CONTEXTO: Auditoria Interna Confidencial. Uso proprietário da empresa.",
                        f"--- {label_box1.upper()} ---\n{text1}",
                        f"--- {label_box2.upper()} ---\n{text2}"
                    ]

                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])

                    prompt = f"""
Atue como Auditor Farmacêutico RÍGIDO. Analise o texto dos dois documentos fornecidos:

1. {label_box1}
2. {label_box2}

LISTA DE SEÇÕES A ANALISAR ({nome_tipo}):
{secoes_str}

=== REGRAS DE EXTRAÇÃO E COMPARAÇÃO ===
1. Ao extrair o conteúdo de cada seção, copie APENAS o parágrafo de texto (sem título da seção).  
2. Não repita títulos.  
3. Pare a cópia quando o título da próxima seção aparecer.  
4. Para seções normais: utilize <mark class='diff'> para divergências de sentido, <mark class='ort'> para erros de ortografia.  
5. Para seções informativas (Apresentações, Composição, Dizeres Legais): apenas transcreva o texto limpo (sem títulos).  
6. Para a data da ANVISA: procure no rodapé da seção 'DIZERES LEGAIS'. Se houver data no formato dd/mm/aaaa, marque com <mark class='anvisa'>dd/mm/aaaa</mark>.  
Retorne um JSON com a estrutura especificada no README.
"""

                    response = model.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"},
                        safety_settings={
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }
                    )

                    data = extract_json(response.text)
                    if not data:
                        st.error("A IA não retornou um JSON válido. Tente novamente.")
                    else:
                        meta = data.get("METADADOS", {})
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                        m2.metric("Seções Analisadas", len(data.get("SECOES", [])))
                        m3.metric("Datas Encontradas", ", ".join(meta.get("datas", [])) or "Nenhuma data")

                        st.divider()

                        for sec in data.get("SECOES", []):
                            status = sec.get('status', 'N/A')
                            titulo = sec.get('titulo', '').upper()
                            icon = "✅"
                            if "DIVERGENTE" in status: icon = "❌"
                            elif "FALTANTE" in status: icon = "🚨"
                            if any(x in titulo for x in SECOES_SEM_DIVERGENCIA):
                                icon = "👁️"
                                if "DIVERGENTE" in status:
                                    status = "VISUALIZAÇÃO (Divergências Ignoradas)"
                                else:
                                    status = "VISUALIZAÇÃO"

                            with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                cA, cB = st.columns(2)
                                with cA:
                                    st.markdown(f"**{label_box1.upper()}**")
                                    st.markdown(
                                        f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref','')}</div>",
                                        unsafe_allow_html=True
                                    )
                                with cB:
                                    st.markdown(f"**{label_box2.upper()}**")
                                    st.markdown(
                                        f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel','')}</div>",
                                        unsafe_allow_html=True
                                    )

                except Exception as e:
                    st.error(f"Erro durante a análise: {e}")
