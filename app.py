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
    page_title="Validador de Bulas",
    page_icon="🔬",
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
    
    .stRadio > div[role="radiogroup"] > label {
        background-color: white; border: 1px solid #e1e4e8; padding: 12px 15px;
        border-radius: 8px; margin-bottom: 8px; transition: all 0.2s;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #f0fbf7; border-color: #55a68e; color: #55a68e; cursor: pointer;
    }

    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover {
        transform: translateY(-5px); box-shadow: 0 15px 30px rgba(0,0,0,0.1); border-color: #55a68e;
    }

    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }

    /* TAGS DE MARCAÇÃO NO TEXTO */
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

# ----------------- FUNÇÕES BACKEND -----------------
def get_mistral_client():
    api_key = None
    try:
        api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key:
        api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key: return None
    return Mistral(api_key=api_key)

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=95) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # PROCESSAMENTO DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        # PROCESSAMENTO PDF HÍBRIDO (SMART EXTRACT)
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # 1. TENTATIVA: Extração de TEXTO PURO (PDF Digital)
            # Isso evita o limite de 4 páginas e lê o documento inteiro
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            # Se encontrou uma quantidade razoável de texto (>500 caracteres), usa o modo Texto
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": full_text}
            
            # 2. TENTATIVA: Extração de IMAGENS (PDF Escaneado) - Fallback
            # Aqui mantemos o limite para não estourar a API
            images = []
            limit_pages = min(4, len(doc)) 
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
                pix = None
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro no arquivo {uploaded_file.name}: {e}")
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

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    client = get_mistral_client()
    if client: st.success(f"✅ Mistral Conectado")
    else: st.error("❌ Configure MISTRAL_API_KEY")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

if pagina == "🏠 Início":
    st.markdown("""<div style="text-align: center; padding: 30px 20px;"><h1 style="color: #55a68e;">Validador Inteligente</h1><p style="color: #7f8c8d;">Auditoria rigorosa de bulas com Mistral AI.</p></div>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown("""<div class="stCard"><div class="card-title">💊 Ref x BELFAR</div>Compara referência com BELFAR.<br><br><ul><li>Diferenças: <span class="highlight-yellow">amarelo</span></li><li>Ortografia: <span class="highlight-pink">rosa</span></li><li>Data Anvisa: <span class="highlight-blue">azul</span></li></ul></div>""", unsafe_allow_html=True)
    with c2: st.markdown("""<div class="stCard"><div class="card-title">📋 Conferência MKT</div>Compara ANVISA com MKT.<br><br><ul><li>Diferenças: <span class="highlight-yellow">amarelo</span></li><li>Ortografia: <span class="highlight-pink">rosa</span></li><li>Data Anvisa: <span class="highlight-blue">azul</span></li></ul></div>""", unsafe_allow_html=True)
    with c3: st.markdown("""<div class="stCard"><div class="card-title">🎨 Gráfica x Arte</div>Compara Gráfica com Arte.<br><br><ul><li>Diferenças: <span class="highlight-yellow">amarelo</span></li><li>Ortografia: <span class="highlight-pink">rosa</span></li><li>Data Anvisa: <span class="highlight-blue">azul</span></li></ul></div>""", unsafe_allow_html=True)

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
            if tipo_bula == "Profissional": lista_secoes = SECOES_PROFISSIONAL; nome_tipo = "Profissional"
    elif pagina == "📋 Conferência MKT": label_box1 = "📄 Arquivo ANVISA"; label_box2 = "📄 Arquivo MKT"
    elif pagina == "🎨 Gráfica x Arte": label_box1 = "📄 Arte Vigente"; label_box2 = "📄 PDF da Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not f1 or not f2: st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"🤖 Lendo documentos na íntegra (Mistral Pixtral)..."):
                try:
                    if not client: st.error("Sem chave API."); st.stop()
                    d1 = process_uploaded_file(f1); d2 = process_uploaded_file(f2)
                    gc.collect()
                    if not d1 or not d2: st.error("Erro na leitura."); st.stop()

                    nome_doc1 = label_box1.replace("📄 ", "").upper()
                    nome_doc2 = label_box2.replace("📄 ", "").upper()
                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])

                    # --- PROMPT REVISADO E FLEXÍVEL ---
                    prompt_text = f"""
                    Atue como Auditor Farmacêutico Especialista.
                    
                    DOCUMENTOS:
                    1. {nome_doc1} (Referência/Padrão)
                    2. {nome_doc2} (Candidato/BELFAR)

                    MISSÃO:
                    Localize e extraia o conteúdo das seções abaixo.
                    SEJA FLEXÍVEL COM TÍTULOS: Se o título variar um pouco (ex: "Cuidados de Armazenamento" vs "Onde guardar"), extraia mesmo assim.
                    
                    SEÇÕES ALVO:
                    {secoes_str}

                    === REGRAS DE EXTRAÇÃO ===
                    1. Extraia o texto COMPLETO de cada seção. Não abrevie.
                    2. Ignore apenas o cabeçalho/título da seção, pegue o conteúdo.
                    3. Se a seção não existir no documento, marque como "FALTANTE".
                    
                    === REGRAS DE MARCAÇÃO (HTML) ===
                    1. DIVERGÊNCIAS (Amarelo): "Texto igual <mark class='diff'>texto diferente</mark> texto igual."
                    2. ERROS DE PORTUGUÊS (Rosa): "Texto com <mark class='ort'>ero</mark>."
                    3. DATA DA ANVISA (Azul): "<mark class='anvisa'>dd/mm/aaaa</mark>". (Geralmente no rodapé ou final).

                    SAÍDA JSON:
                    {{
                        "METADADOS": {{ "score": 0 a 100, "datas": ["dd/mm/aaaa"] }},
                        "SECOES": [
                            {{ 
                                "titulo": "NOME DA SEÇÃO DA LISTA ACIMA", 
                                "ref": "CONTEUDO COMPLETO DOC 1...", 
                                "bel": "CONTEUDO COMPLETO DOC 2...", 
                                "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" 
                            }}
                        ]
                    }}
                    """

                    messages_content = [{"type": "text", "text": prompt_text}]

                    # Montagem Inteligente do Conteúdo
                    def add_content(doc_data, doc_name):
                        if doc_data['type'] == 'text':
                            messages_content.append({"type": "text", "text": f"\n--- TEXTO COMPLETO {doc_name} ---\n{doc_data['data']}"})
                        else:
                            messages_content.append({"type": "text", "text": f"\n--- IMAGENS {doc_name} (LEIA COM ATENÇÃO) ---"})
                            for img in doc_data['data']:
                                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_to_base64(img)}"})

                    add_content(d1, nome_doc1)
                    add_content(d2, nome_doc2)

                    chat_response = client.chat.complete(
                        model="pixtral-large-latest",
                        messages=[{"role": "user", "content": messages_content}],
                        response_format={"type": "json_object"},
                        max_tokens=9000
                    )

                    response_text = chat_response.choices[0].message.content
                    data = extract_json(response_text)
                    
                    if not data: st.error("Erro JSON da IA.")
                    else:
                        meta = data.get("METADADOS", {})
                        datas_limpas = [re.sub(r'<[^>]+>', '', d) for d in meta.get("datas", [])]
                        display_data = ", ".join(datas_limpas) if datas_limpas else "⚠️ Não possui data ANVISA"

                        m1, m2, m3 = st.columns(3)
                        m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                        m2.metric("Seções", len(data.get("SECOES", [])))
                        m3.metric("Datas", display_data)
                        st.divider()
                        
                        for sec in data.get("SECOES", []):
                            status = sec.get('status', 'N/A'); titulo = sec.get('titulo', '').upper()
                            icon = "✅"
                            if "DIVERGENTE" in status: icon = "❌"
                            elif "FALTANTE" in status: icon = "🚨"
                            if any(x in titulo for x in SECOES_SEM_DIVERGENCIA):
                                icon = "👁️"; status = "VISUALIZAÇÃO (Divergências Ignoradas)" if "DIVERGENTE" in status else "VISUALIZAÇÃO"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                cA, cB = st.columns(2)
                                with cA:
                                    st.markdown(f"**{nome_doc1}**")
                                    st.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                                with cB:
                                    st.markdown(f"**{nome_doc2}**")
                                    st.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)

                except Exception as e: st.error(f"Erro: {e}")
