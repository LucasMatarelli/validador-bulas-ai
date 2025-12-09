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
    page_title="Validador de Bulas",
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
        box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px;
        border: 1px solid #e1e4e8;
    }
    .card-title { color: #55a68e; font-size: 1.1rem; font-weight: bold; margin-bottom: 10px; border-bottom: 2px solid #f0f2f5; padding-bottom: 5px; }
    
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 50px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }

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
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key: return None
    return Mistral(api_key=api_key)

def image_to_base64(image):
    # REDIMENSIONAMENTO DE SEGURANÇA: Se a imagem for gigante, reduz para max 1024px
    max_size = (1024, 1024)
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    
    buffered = io.BytesIO()
    # Otimização: Qualidade 70 é o suficiente para OCR e muito mais leve
    image.save(buffered, format="JPEG", quality=70) 
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
            
            # Tenta texto primeiro (muito mais rápido)
            first_page_text = doc[0].get_text() if len(doc) > 0 else ""
            if len(first_page_text.strip()) > 50:
                full_text = ""
                for page in doc:
                    full_text += page.get_text() + "\n"
                doc.close()
                return {"type": "text", "data": full_text}
            
            else:
                # PDF Imagem: Otimização Matrix 1.5 (Mais rápido e evita erro 502)
                images = []
                limit_pages = min(5, len(doc)) 
                for i in range(limit_pages):
                    page = doc[i]
                    # Matrix 1.5 é o equilíbrio perfeito entre velocidade e leitura
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=70))
                    except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                    images.append(Image.open(img_byte_arr))
                    pix = None
                doc.close()
                gc.collect()
                return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro no arquivo {uploaded_file.name}: {e}")
        return None
    return None

def repair_json(json_str):
    try:
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        start = json_str.find('{')
        end = json_str.rfind('}') + 1
        if start != -1 and end != -1:
            json_str = json_str[start:end]
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None

def call_mistral_with_retry(client, messages, max_retries=3):
    """Função de resiliência: Tenta chamar a API 3x se der erro de servidor"""
    for attempt in range(max_retries):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest",
                messages=[{"role": "user", "content": messages}],
                response_format={"type": "json_object"},
                max_tokens=8000
            )
            return chat_response
        except Exception as e:
            error_msg = str(e)
            # Se for erro de servidor (500, 502, 503) ou limite de taxa (429), espera e tenta de novo
            if "500" in error_msg or "502" in error_msg or "503" in error_msg or "429" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    st.toast(f"Servidor ocupado (Erro 502). Tentando novamente em {wait_time}s...", icon="⏳")
                    time.sleep(wait_time)
                    continue
            raise e # Se for outro erro ou acabou as tentativas, estoura o erro

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador Rápido")
    client = get_mistral_client()
    if client: st.success(f"✅ Mistral Conectado")
    else: st.error("❌ Configure MISTRAL_API_KEY")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])

if pagina == "🏠 Início":
    st.markdown("""<div style="text-align: center; padding: 30px 20px;"><h1 style="color: #55a68e;">Validador Inteligente</h1><p>Auditoria de bulas com <b>retry automático</b> e otimização de velocidade.</p></div>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown("""<div class="stCard"><div class="card-title">💊 Ref x BELFAR</div>Compara referência com BELFAR.<br><br>Legenda:<br>🟡 Divergência<br>🔴 Erro PT<br>🔵 Data Anvisa</div>""", unsafe_allow_html=True)
    with c2: st.markdown("""<div class="stCard"><div class="card-title">📋 Conferência MKT</div>Compara ANVISA com MKT.<br><br>Legenda:<br>🟡 Divergência<br>🔴 Erro PT<br>🔵 Data Anvisa</div>""", unsafe_allow_html=True)
    with c3: st.markdown("""<div class="stCard"><div class="card-title">🎨 Gráfica x Arte</div>Compara Gráfica com Arte.<br><br>Legenda:<br>🟡 Divergência<br>🔴 Erro PT<br>🔵 Data Anvisa</div>""", unsafe_allow_html=True)

else:
    st.markdown(f"## {pagina}")
    lista_secoes = SECOES_PACIENTE
    nome_doc1 = "REFERÊNCIA"
    nome_doc2 = "BELFAR"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Documento de Referência"
        label_box2 = "📄 Documento BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional": lista_secoes = SECOES_PROFISSIONAL
    elif pagina == "📋 Conferência MKT": label_box1 = "📄 Arquivo ANVISA"; label_box2 = "📄 Arquivo MKT"
    elif pagina == "🎨 Gráfica x Arte": label_box1 = "📄 Arte Vigente"; label_box2 = "📄 PDF da Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("Upload 1", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("Upload 2", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2: st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"⚡ Processando (com sistema anti-falha 502)..."):
                try:
                    if not client: st.error("Sem chave API."); st.stop()
                    
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect() 

                    if not d1 or not d2: st.error("Erro na leitura dos arquivos."); st.stop()

                    secoes_str = ", ".join(lista_secoes) 

                    prompt_text = f"""
                    Atue como Auditor Farmacêutico.
                    Compare: 1. REFERÊNCIA vs 2. BELFAR.
                    SEÇÕES ALVO: {secoes_str}

                    INSTRUÇÕES:
                    1. Extraia o texto COMPLETO das seções (ignore apenas o título).
                    2. Se não encontrar, marque "FALTANTE".
                    
                    MARCAÇÃO HTML OBRIGATÓRIA (Use <mark>):
                    - Divergência: <mark class='diff'>texto diferente</mark>
                    - Erro PT: <mark class='ort'>texto errado</mark>
                    - Data Anvisa: <mark class='anvisa'>dd/mm/aaaa</mark>

                    JSON APENAS:
                    {{
                        "METADADOS": {{ "score": 0 a 100, "datas": ["dd/mm/aaaa"] }},
                        "SECOES": [
                            {{ "titulo": "NOME SEÇÃO", "ref": "texto 1...", "bel": "texto 2...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" }}
                        ]
                    }}
                    """

                    messages_content = [{"type": "text", "text": prompt_text}]

                    def add_content(doc_data, label):
                        if doc_data['type'] == 'text':
                            messages_content.append({"type": "text", "text": f"\n--- TEXTO {label} ---\n{doc_data['data'][:50000]}"})
                        else:
                            messages_content.append({"type": "text", "text": f"\n--- IMAGENS {label} ---"})
                            for img in doc_data['data']:
                                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_to_base64(img)}"})

                    add_content(d1, "REFERÊNCIA")
                    add_content(d2, "BELFAR")

                    # Chamada com Retry Automático
                    chat_response = call_mistral_with_retry(client, messages_content)

                    data = repair_json(chat_response.choices[0].message.content)
                    
                    if not data: 
                        st.error("A IA respondeu, mas o JSON veio quebrado.")
                        st.code(chat_response.choices[0].message.content)
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
                                icon = "👁️"; status = "VISUALIZAÇÃO"
                            
                            with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                cA, cB = st.columns(2)
                                with cA:
                                    st.markdown(f"**{label_box1}**")
                                    st.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                                with cB:
                                    st.markdown(f"**{label_box2}**")
                                    st.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)

                except Exception as e: st.error(f"Erro Fatal: {e}")
