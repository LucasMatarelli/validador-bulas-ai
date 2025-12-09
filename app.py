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
import time
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (MENU BONITO & UI) -----------------
st.markdown("""
<style>
    /* Oculta o Header Padrão */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    /* Fundo geral */
    .stApp { background-color: #f8f9fa; }

    /* --- MENU LATERAL ESTILIZADO (SEM BOLINHAS) --- */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e0e0e0;
    }
    
    /* Esconde a bolinha do radio button */
    div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }
    
    /* Estilo do Botão do Menu */
    div[role="radiogroup"] label {
        background-color: white;
        padding: 15px 20px;
        border-radius: 12px;
        margin-bottom: 10px;
        border: 1px solid #eef0f3;
        box-shadow: 0 2px 5px rgba(0,0,0,0.03);
        transition: all 0.3s ease;
        cursor: pointer;
        font-weight: 500;
        color: #4a5568;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    /* Hover no botão */
    div[role="radiogroup"] label:hover {
        border-color: #55a68e;
        color: #55a68e;
        background-color: #f0fbf7;
        transform: translateX(5px);
    }
    
    /* Botão Selecionado (Ativo) */
    div[role="radiogroup"] label[data-checked="true"] {
        background: linear-gradient(135deg, #55a68e 0%, #3d8b74 100%);
        color: white !important;
        border: none;
        box-shadow: 0 4px 10px rgba(85, 166, 142, 0.3);
    }

    /* --- CARDS E CONTEÚDO --- */
    .stCard {
        background-color: white; padding: 25px; border-radius: 16px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05); margin-bottom: 20px;
        border: 1px solid #f0f2f5;
    }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 10px; border-bottom: 2px solid #f0f2f5; padding-bottom: 5px; }
    
    /* Botão de Ação Principal */
    .stButton>button { 
        width: 100%; 
        background: linear-gradient(90deg, #55a68e, #448c75); 
        color: white; 
        font-weight: bold; 
        border-radius: 10px; 
        height: 55px; 
        border: none; 
        font-size: 18px; 
        box-shadow: 0 4px 12px rgba(85, 166, 142, 0.3);
        transition: all 0.2s;
    }
    .stButton>button:hover { 
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(85, 166, 142, 0.4);
    }

    /* --- MARCAÇÕES NO TEXTO --- */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 6px; border-radius: 4px; border: 1px solid #ffeeba; font-weight: 500; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 6px; border-radius: 4px; border-bottom: 2px solid #dc3545; font-weight: 500; }
    mark.anvisa { background-color: #e0f7fa; color: #006064; padding: 3px 8px; border-radius: 20px; border: 1px solid #b2ebf2; font-weight: bold; font-size: 0.9em; }
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

# ----------------- BACKEND VELOZ -----------------
def get_mistral_client():
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key: return None
    return Mistral(api_key=api_key)

def image_to_base64(image):
    # OTIMIZAÇÃO: Redimensiona se for maior que 1024px
    if image.width > 1024 or image.height > 1024:
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    
    buffered = io.BytesIO()
    # JPEG 70: Qualidade "WhatsApp", rápida e leve
    image.save(buffered, format="JPEG", quality=70) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def process_uploaded_file(uploaded_file):
    """
    MODO TURBO:
    1. Tenta extrair texto puro (instantâneo).
    2. Se não der, converte PDF em imagem baixa resolução (rápido).
    """
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # 1. DOCX (Rápido)
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        # 2. PDF (Híbrido)
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # Checagem de Texto Digital (Instantâneo)
            has_text = False
            for i in range(min(2, len(doc))):
                if len(doc[i].get_text().strip()) > 50:
                    has_text = True
                    break
            
            if has_text:
                full_text = ""
                for page in doc:
                    full_text += page.get_text() + "\n"
                doc.close()
                return {"type": "text", "data": full_text}
            
            else:
                # Fallback Imagem (Otimizado)
                images = []
                limit_pages = min(8, len(doc)) 
                for i in range(limit_pages):
                    page = doc[i]
                    # Matrix 1.5: Resolução média. 
                    # 1.0 = 72dpi (Rápido) / 1.5 = ~108dpi (Bom) / 2.0 = 144dpi (Lento)
                    # Usando 1.5 para equilíbrio
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=75))
                    except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                    images.append(Image.open(img_byte_arr))
                    pix = None
                doc.close()
                gc.collect()
                return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro: {e}")
        return None
    return None

def repair_json(json_str):
    try:
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        start = json_str.find('{')
        end = json_str.rfind('}') + 1
        if start != -1 and end != -1: json_str = json_str[start:end]
        return json.loads(json_str)
    except: return None

def call_mistral_with_retry(client, messages, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.chat.complete(
                model="pixtral-large-latest",
                messages=[{"role": "user", "content": messages}],
                response_format={"type": "json_object"},
                max_tokens=14000 # Permite respostas longas
            )
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise e

# ----------------- UI SIDEBAR -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.title("Bula Validator")
    st.caption("v2.5 Turbo • Mistral AI")
    
    st.markdown("---")
    
    # O CSS esconde as bolinhas, transformando em botões
    pagina = st.radio(
        "MENU PRINCIPAL",
        ["🏠 Dashboard", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    client = get_mistral_client()
    if client: 
        st.markdown("<div style='text-align:center; color:#55a68e; padding:10px; background:#e8f5e9; border-radius:8px;'><b>● Sistema Online</b></div>", unsafe_allow_html=True)
    else: 
        st.error("Configure a API Key")

# ----------------- PÁGINAS -----------------

if "Dashboard" in pagina:
    st.markdown("""
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #2c3e50; font-size: 2.5rem; margin-bottom: 10px;">Central de Auditoria</h1>
        <p style="color: #7f8c8d; font-size: 1.1rem;">Selecione uma ferramenta no menu lateral para começar.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1: st.info("**💊 Ref x BELFAR**\n\nAuditoria completa de texto e conteúdo regulatório."); 
    with c2: st.warning("**📋 Conferência MKT**\n\nValidação de material de marketing contra aprovação."); 
    with c3: st.success("**🎨 Gráfica x Arte**\n\nConferência final de pré-impressão."); 

else:
    # Cabeçalho da ferramenta
    st.markdown(f"<h2 style='color:#55a68e; border-left:5px solid #55a68e; padding-left:15px;'>{pagina}</h2>", unsafe_allow_html=True)
    
    lista_secoes = SECOES_PACIENTE
    label_box1 = "Arquivo 1"; label_box2 = "Arquivo 2"
    
    if "Ref x BELFAR" in pagina:
        label_box1 = "📄 Documento de Referência"; label_box2 = "📄 Documento BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional": lista_secoes = SECOES_PROFISSIONAL
    elif "Conferência MKT" in pagina: label_box1 = "📄 Arquivo ANVISA"; label_box2 = "📄 Arquivo MKT"
    elif "Gráfica x Arte" in pagina: label_box1 = "📄 Arte Vigente"; label_box2 = "📄 PDF da Gráfica"
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1: 
        st.markdown(f"**{label_box1}**")
        f1 = st.file_uploader("f1", type=["pdf", "docx"], key="f1", label_visibility="collapsed")
    with c2: 
        st.markdown(f"**{label_box2}**")
        f2 = st.file_uploader("f2", type=["pdf", "docx"], key="f2", label_visibility="collapsed")
        
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("🚀 INICIAR AUDITORIA RÁPIDA"):
        if not f1 or not f2: 
            st.toast("Por favor, anexe os dois arquivos!", icon="⚠️")
        else:
            # STATUS CONTAINER (Melhor UX que Spinner)
            status = st.status("🚀 Iniciando motor de IA...", expanded=True)
            
            try:
                if not client: st.error("Sem chave API."); st.stop()
                
                status.write("📄 Lendo documentos e extraindo texto...")
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

                if not d1 or not d2: status.update(label="Erro na leitura!", state="error"); st.stop()

                secoes_str = ", ".join(lista_secoes)
                
                status.write("🧠 Analisando divergências e completude...")
                
                prompt_text = f"""
                Atue como Auditor Farmacêutico Especialista.
                Tarefa: Comparar 1. REFERÊNCIA vs 2. BELFAR.
                Seções Alvo: {secoes_str}

                === REGRA DE OURO: INTEGRIDADE DO TEXTO ===
                1. Extraia o texto COMPLETO de cada seção. NÃO RESUMA.
                2. Se a seção for longa, transcreva-a até o final.
                3. Ignore apenas os títulos das seções.
                4. Se não encontrar a seção, marque como "FALTANTE".

                === MARCAÇÃO HTML (OBRIGATÓRIO) ===
                No campo 'bel', você DEVE usar estas tags:
                - <mark class='diff'>texto diferente ou divergente</mark>
                - <mark class='ort'>erro de português ou digitação</mark>
                - <mark class='anvisa'>dd/mm/aaaa</mark> (Data de aprovação, procure no final)

                SAÍDA JSON:
                {{
                    "METADADOS": {{ "score": 0 a 100, "datas": ["dd/mm/aaaa"] }},
                    "SECOES": [
                        {{ "titulo": "NOME SEÇÃO", "ref": "TEXTO INTEGRAL DOC 1", "bel": "TEXTO INTEGRAL DOC 2 COM TAGS", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" }}
                    ]
                }}
                """

                messages_content = [{"type": "text", "text": prompt_text}]

                def add_content(doc_data, label):
                    if doc_data['type'] == 'text':
                        messages_content.append({"type": "text", "text": f"\n--- TEXTO {label} ---\n{doc_data['data'][:60000]}"})
                    else:
                        messages_content.append({"type": "text", "text": f"\n--- IMAGENS {label} ---"})
                        for img in doc_data['data']:
                            messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_to_base64(img)}"})

                add_content(d1, "REFERÊNCIA")
                add_content(d2, "BELFAR")

                chat_response = call_mistral_with_retry(client, messages_content)
                
                status.write("📊 Gerando relatório final...")
                data = repair_json(chat_response.choices[0].message.content)
                
                status.update(label="Concluído com Sucesso!", state="complete", expanded=False)
                
                if not data: 
                    st.error("Erro no processamento da IA.")
                else:
                    meta = data.get("METADADOS", {})
                    datas_limpas = [re.sub(r'<[^>]+>', '', d) for d in meta.get("datas", [])]
                    display_data = ", ".join(datas_limpas) if datas_limpas else "⚠️ Não possui data ANVISA"

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Score de Conformidade", f"{meta.get('score', 0)}%")
                    m2.metric("Seções Auditadas", len(data.get("SECOES", [])))
                    m3.metric("Data Anvisa", display_data)
                    st.divider()
                    
                    for sec in data.get("SECOES", []):
                        stt = sec.get('status', 'N/A'); tit = sec.get('titulo', '').upper()
                        icon = "✅"
                        if "DIVERGENTE" in stt: icon = "❌"
                        elif "FALTANTE" in stt: icon = "🚨"
                        if any(x in tit for x in SECOES_SEM_DIVERGENCIA):
                            icon = "👁️"; stt = "VISUALIZAÇÃO"
                        
                        with st.expander(f"{icon} {sec['titulo']} — {stt}"):
                            cA, cB = st.columns(2)
                            with cA:
                                st.caption(f"📄 {label_box1}")
                                st.markdown(f"<div style='background:#f8f9fa; padding:15px; border-radius:8px; border:1px solid #e9ecef; font-size:0.9rem;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                            with cB:
                                st.caption(f"📄 {label_box2}")
                                st.markdown(f"<div style='background:#f0fff4; padding:15px; border-radius:8px; border:1px solid #c3e6cb; font-size:0.9rem;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)

            except Exception as e: 
                status.update(label="Erro Fatal", state="error")
                st.error(f"Detalhes do erro: {e}")
