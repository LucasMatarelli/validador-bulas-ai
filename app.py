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
import concurrent.futures
import time
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas V30 Turbo",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS PERSONALIZADOS -----------------
st.markdown("""
<style>
    /* OCULTA A BARRA SUPERIOR */
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
    
    /* Legendas */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Marcações de Texto (Destaques no Texto) */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; } /* AMARELO - DIVERGENCIA */
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; } /* VERMELHO - PORTUGUES */
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; } /* AZUL - DATA */

    /* Botões */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }
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

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_mistral_client():
    api_key = None
    try:
        api_key = st.secrets["MISTRAL_API_KEY"]
    except Exception:
        pass 
    if not api_key:
        api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None
    return Mistral(api_key=api_key)

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """Processa o arquivo e retorna o texto ou imagens. Com Cache."""
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text()
            
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": full_text}
            
            images = []
            limit_pages = min(4, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
                except TypeError:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
                pix = None
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception:
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

# --- WORKER AJUSTADO PARA RETORNAR TEXTO MARCADO E NÃO RESUMO ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2):
    
    prompt_text = f"""
    Atue como um Auditor de Bulas Farmacêuticas Extremamente Preciso.
    TAREFA: Extrair e comparar SOMENTE a seção "{secao}" entre o {nome_doc1} e o {nome_doc2}.
    
    INSTRUÇÕES DE RESPOSTA (JSON OBRIGATÓRIO):
    
    1. Não faça resumos. Eu preciso visualizar o texto lado a lado.
    2. No campo "ref", coloque o texto extraído do {nome_doc1} sem alterações.
    3. No campo "bel", coloque o texto extraído do {nome_doc2}, mas aplicando as seguintes TAGS HTML ONDE NECESSÁRIO:
       - Use <mark class="diff">TEXTO DIFERENTE</mark> para destacar QUALQUER palavra ou frase que esteja diferente do {nome_doc1} (divergência de conteúdo).
       - Use <mark class="ort">ERRO</mark> para destacar erros ortográficos ou gramaticais no {nome_doc2}.
       - Use <mark class="anvisa">DATA</mark> para destacar APENAS datas de aprovação da ANVISA (formato DD/MM/AAAA).
    
    4. STATUS:
       - "CONFORME": Se o sentido for idêntico.
       - "DIVERGENTE": Se houver mudança de sentido ou informação técnica diferente.
       - "FALTANTE": Se a seção não existir.

    FORMATO JSON:
    {{
        "titulo": "{secao}",
        "ref": "Texto completo do doc 1 aqui...",
        "bel": "Texto completo do doc 2 com as tags <mark class='diff'>...</mark> aqui...",
        "status": "STATUS"
    }}
    """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            texto_limpo = d['data'][:60000] 
            messages_content.append({"type": "text", "text": f"\n--- CONTEÚDO {nome} ---\n{texto_limpo}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGENS {nome} (OCR) ---"})
            for img in d['data'][:2]:
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    try:
        chat_response = client.chat.complete(
            model="pixtral-large-latest", 
            messages=[{"role": "user", "content": messages_content}],
            response_format={"type": "json_object"}
        )
        raw_content = chat_response.choices[0].message.content
        dados = extract_json(raw_content)
        
        if dados:
            dados['titulo'] = secao
            return dados
        else:
            return {
                "titulo": secao, 
                "ref": "Erro Formato JSON", 
                "bel": raw_content, 
                "status": "ERRO"
            }
            
    except Exception as e:
        return {"titulo": secao, "ref": "Erro API", "bel": str(e), "status": "ERRO"}

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador V30 Turbo")
    
    client = get_mistral_client()
    
    if client:
        st.success(f"✅ Mistral Conectado")
    else:
        st.error("❌ Erro de Conexão")
        st.caption("Configure MISTRAL_API_KEY.")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

# ----------------- LÓGICA DAS PÁGINAS -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e;">Validador Inteligente - Modo Turbo</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Processamento Paralelo Ativado.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">💊 Medicamento Referência x BELFAR</div>
            <div class="card-text">
                Comparação lado a lado com marcação inteligente.
                <br><ul>
                    <li>Diferenças: <span class="highlight-yellow">amarelo</span></li>
                    <li>Ortografia: <span class="highlight-pink">vermelho</span></li>
                    <li>Datas Anvisa: <span class="highlight-blue">azul</span></li>
                </ul>
            </div>
        </div>""", unsafe_allow_html=True)

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    label_box1 = "Arquivo 1"
    label_box2 = "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Referência"
        label_box2 = "📄 BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL
                nome_tipo = "Profissional"
    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 ANVISA"
        label_box2 = "📄 MKT"
    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"
        label_box2 = "📄 Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"##### {label_box1}")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2:
        st.markdown(f"##### {label_box2}")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA TURBO"):
        if not f1 or not f2:
            st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            if not client: st.stop()

            # --- LEITURA OTIMIZADA COM CACHE ---
            with st.spinner("📂 Lendo arquivos..."):
                b1 = f1.getvalue()
                b2 = f2.getvalue()
                d1 = process_file_content(b1, f1.name.lower())
                d2 = process_file_content(b2, f2.name.lower())
                gc.collect()

            if not d1 or not d2:
                st.error("Falha ao ler arquivos.")
                st.stop()

            nome_doc1 = label_box1.replace("📄 ", "").upper()
            nome_doc2 = label_box2.replace("📄 ", "").upper()

            # --- PROCESSAMENTO PARALELO ---
            resultados_secoes = []
            
            with st.status("⚡ Processando seções simultaneamente...", expanded=True) as status:
                st.write("Iniciando workers de IA...")
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_secao = {
                        executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2): secao 
                        for secao in lista_secoes
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_secao):
                        secao_nome = future_to_secao[future]
                        try:
                            data_secao = future.result()
                            if data_secao:
                                resultados_secoes.append(data_secao)
                                st.write(f"✅ {secao_nome} analisada.")
                        except Exception as exc:
                            st.error(f"Erro em {secao_nome}: {exc}")
                
                status.update(label="Análise Completa!", state="complete", expanded=False)

            # --- ORDENAÇÃO E EXIBIÇÃO ---
            
            # Ordena os resultados
            resultados_secoes.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)

            # Métricas
            total = len(resultados_secoes)
            conformes = sum(1 for x in resultados_secoes if "CONFORME" in x.get('status', ''))
            score = int((conformes / total) * 100) if total > 0 else 0

            # Data (Extração simples)
            datas_texto = "Não detectado"
            for r in resultados_secoes:
                if "DIZERES LEGAIS" in r['titulo']:
                    match = re.search(r'\d{2}/\d{2}/\d{4}', r.get('bel', ''))
                    if match: datas_texto = match.group(0)

            m1, m2, m3 = st.columns(3)
            m1.metric("Conformidade", f"{score}%")
            m2.metric("Seções Analisadas", total)
            m3.metric("Data Ref.", datas_texto)
            
            st.divider()
            
            # Exibição
            for sec in resultados_secoes:
                status = sec.get('status', 'N/A')
                titulo = sec.get('titulo', '').upper()
                
                icon = "✅"
                if "DIVERGENTE" in status: icon = "❌"
                elif "FALTANTE" in status: icon = "🚨"
                elif "ERRO" in status: icon = "⚠️"
                
                if any(x in titulo for x in SECOES_SEM_DIVERGENCIA):
                    icon = "👁️" 
                    status = "VISUALIZAÇÃO"
                
                with st.expander(f"{icon} {titulo} — {status}"):
                    cA, cB = st.columns(2)
                    with cA:
                        st.markdown(f"**{nome_doc1}**")
                        # Usa o texto cru no arquivo 1
                        st.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px; font-size:0.9rem;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                    with cB:
                        st.markdown(f"**{nome_doc2}**")
                        # O HTML renderiza as marcações coloridas aqui
                        st.markdown(f"<div style='background:#fff; border:1px solid #eee; padding:10px; border-radius:5px; font-size:0.9rem;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
