import streamlit as st
from mistralai import Mistral
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import base64
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas (Mistral)",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS PERSONALIZADOS -----------------
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
    
    /* Destaques (Legenda) */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Box de Curva */
    .curve-box { background-color: #f8f9fa; border-left: 4px solid #55a68e; padding: 10px 15px; margin-top: 15px; font-size: 0.9rem; color: #666; }

    /* Botões */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }

    /* Marcações de Texto (Destaques no Texto) */
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

# ----------------- FUNÇÕES DE BACKEND (MISTRAL) -----------------

def get_mistral_client():
    # 1. TENTA LER A CHAVE DOS SECRETS
    api_key = None
    try:
        api_key = st.secrets["MISTRAL_API_KEY"]
    except Exception:
        pass 

    if not api_key:
        api_key = os.environ.get("MISTRAL_API_KEY")

    if not api_key:
        return None
    
    # Inicializa o cliente Mistral
    return Mistral(api_key=api_key)

def image_to_base64(image):
    """Converte imagem PIL para string base64"""
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=90)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            images = []
            
            # Limite de páginas para performance e custo
            limit_pages = min(12, len(doc))
            
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except TypeError:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                        
                images.append(Image.open(img_byte_arr))
                pix = None
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro ao processar arquivo {uploaded_file.name}: {e}")
        return None
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"): text = text[4:]
    return text

def extract_json(text):
    try:
        clean = clean_json_response(text)
        start = clean.find('{')
        end = clean.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(clean[start:end])
        return json.loads(clean)
    except: return None

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    # Inicializa cliente Mistral
    client = get_mistral_client()
    
    if client:
        st.success(f"✅ Mistral Conectado")
        st.caption("Modelo: pixtral-large-latest")
    else:
        st.error("❌ Erro de Conexão")
        st.caption("Configure MISTRAL_API_KEY nos Secrets.")
    
    st.divider()
    
    # Menu de Navegação
    pagina = st.radio(
        "Navegação:",
        ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"]
    )
    
    st.divider()

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e; font-size: 3rem; margin-bottom: 10px;">Validador (Mistral AI)</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Central de auditoria e conformidade de bulas farmacêuticas com IA.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">💊 Medicamento Referência x BELFAR</div>
            <div class="card-text">
                Compara a bula de referência com a bula BELFAR.
                <br><br>
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
                Compara arquivo ANVISA com PDF MKT.
                <br><br>
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
                Compara PDF Gráfica com Arte Vigente (Lê curvas).
                <br><br>
                <ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">rosa</span></li>
                    <li>Data Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ----------------- FERRAMENTA -----------------
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
    if st.button("🚀 INICIAR AUDITORIA (MISTRAL)"):
        if not f1 or not f2:
            st.warning("⚠️ Por favor, faça o upload dos dois arquivos para continuar.")
        else:
            with st.spinner(f"🤖 Analisando com Pixtral (Mistral AI)..."):
                try:
                    if not client:
                        st.error("Erro crítico: Chave API não detectada.")
                        st.stop()

                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if not d1 or not d2:
                        st.error("Falha ao ler os arquivos.")
                        st.stop()

                    # Montagem do Payload para o Mistral (Pixtral)
                    nome_doc1 = label_box1.replace("📄 ", "").upper()
                    nome_doc2 = label_box2.replace("📄 ", "").upper()
                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])

                    # 1. Criação do Texto do Prompt
                    prompt_text = f"""
                    Atue como Auditor Farmacêutico RÍGIDO. Analise TODAS as imagens anexadas para encontrar o texto.
                    CONTEXTO: Auditoria Interna Confidencial.

                    DOCUMENTOS ENVIADOS:
                    1. {nome_doc1} (Referência/Padrão)
                    2. {nome_doc2} (Candidato/BELFAR)

                    LISTA DE SEÇÕES A ANALISAR ({nome_tipo}):
                    {secoes_str}

                    === REGRA ZERO: LIMPEZA ABSOLUTA DE TEXTO ===
                    1. EXTRAÇÃO PURA: Ao extrair o conteúdo de uma seção, copie APENAS O PARÁGRAFO DE TEXTO.
                    2. PROIBIDO TÍTULOS: NÃO inclua o título da seção (ex: NÃO escreva "4. O QUE DEVO SABER..." no início do texto extraído).
                    3. SEM REPETIÇÕES: Se houver quebra de página e o título da seção aparecer de novo, DELETE-O. Mantenha o texto fluido.
                    4. LIMITES: Pare de copiar assim que o título da PRÓXIMA seção aparecer.

                    === REGRA 1: COMPARAÇÃO ===
                    - Seções normais: Use <mark class='diff'> para divergências de sentido e <mark class='ort'> para erros de português.
                    - Seções informativas (Apresentações, Composição, Dizeres Legais): Apenas transcreva o texto limpo (sem títulos).

                    === REGRA 2: DATA DA ANVISA ===
                    - Busque no rodapé de "DIZERES LEGAIS". Se achar "Aprovado em dd/mm/aaaa", use <mark class='anvisa'>dd/mm/aaaa</mark> NO TEXTO DA SEÇÃO.
                    
                    SAÍDA JSON OBRIGATÓRIA:
                    {{
                        "METADADOS": {{ "score": 0 a 100, "datas": ["apenas a data dd/mm/aaaa sem html"] }},
                        "SECOES": [
                            {{ "titulo": "NOME SEÇÃO", "ref": "texto limpo...", "bel": "texto limpo...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" }}
                        ]
                    }}
                    
                    Abaixo seguem os textos (caso existam arquivos DOCX) e as imagens (caso existam arquivos PDF):
                    """

                    # 2. Montagem da lista de conteúdo (Multimodal)
                    messages_content = [{"type": "text", "text": prompt_text}]

                    # Adiciona Texto do Doc 1 (se for texto)
                    if d1['type'] == 'text':
                        messages_content.append({"type": "text", "text": f"\n--- CONTEÚDO TEXTO {nome_doc1} ---\n{d1['data']}"})
                    # Adiciona Imagens do Doc 1 (se for imagem)
                    else:
                        messages_content.append({"type": "text", "text": f"\n--- IMAGENS {nome_doc1} ---"})
                        for img in d1['data']:
                            b64 = image_to_base64(img)
                            messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

                    # Adiciona Texto do Doc 2 (se for texto)
                    if d2['type'] == 'text':
                        messages_content.append({"type": "text", "text": f"\n--- CONTEÚDO TEXTO {nome_doc2} ---\n{d2['data']}"})
                    # Adiciona Imagens do Doc 2 (se for imagem)
                    else:
                        messages_content.append({"type": "text", "text": f"\n--- IMAGENS {nome_doc2} ---"})
                        for img in d2['data']:
                            b64 = image_to_base64(img)
                            messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

                    # CHAMADA API MISTRAL
                    chat_response = client.chat.complete(
                        model="pixtral-large-latest", # Modelo Vision da Mistral
                        messages=[
                            {
                                "role": "user",
                                "content": messages_content
                            }
                        ],
                        response_format={"type": "json_object"}
                    )

                    response_text = chat_response.choices[0].message.content
                    
                    data = extract_json(response_text)
                    if not data:
                        st.error("O Mistral não retornou um JSON válido. Tente novamente.")
                        st.write(response_text) # Debug caso falhe
                    else:
                        meta = data.get("METADADOS", {})
                        
                        # --- CORREÇÃO DA DATA (REMOÇÃO DE TAGS HTML) ---
                        datas_brutas = meta.get("datas", [])
                        datas_limpas = [re.sub(r'<[^>]+>', '', d) for d in datas_brutas]
                        
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                        m2.metric("Seções Analisadas", len(data.get("SECOES", [])))
                        m3.metric("Datas Encontradas", ", ".join(datas_limpas) or "Nenhuma data")
                        
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
                                    st.markdown(f"**{nome_doc1}**")
                                    st.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                                with cB:
                                    st.markdown(f"**{nome_doc2}**")
                                    st.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro durante a análise Mistral: {e}")
