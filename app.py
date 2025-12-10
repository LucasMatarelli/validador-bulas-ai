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
import unicodedata
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas V30 Turbo",
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
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; height: 100%;
    }

    /* Cores das Marcações */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; } 
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; } 
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }

    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; }
    .stButton>button:hover { background-color: #448c75; }
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

# Seções onde a IA não deve apontar divergências (apenas datas)
SECOES_SEM_DIVERGENCIA = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- FUNÇÕES AUXILIARES -----------------

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

# --- SANITIZAÇÃO AGRESSIVA PARA CORRIGIR FALSOS POSITIVOS ---
def sanitize_text(text):
    if not text: return ""
    # 1. Normaliza Unicode (Ajusta cedilhas, acentos e caracteres especiais)
    text = unicodedata.normalize('NFKC', text)
    # 2. Remove caracteres de controle invisíveis
    text = text.replace('\xa0', ' ').replace('\u0000', '').replace('\u200b', '')
    # 3. TRANSFORMA TUDO EM UMA LINHA SÓ COM ESPAÇAMENTO PADRÃO
    # Isso evita que quebras de linha no PDF gerem erro de "divergência"
    return re.sub(r'\s+', ' ', text).strip()

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text()
            
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
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

# --- CÉREBRO DA IA: PROMPT CORRIGIDO PARA MARCAÇÃO DUPLA ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2):
    
    ignorar_divergencia = any(s in secao.upper() for s in SECOES_SEM_DIVERGENCIA)
    
    # Define se deve buscar datas ANVISA (Dizeres Legais)
    regra_data = ""
    if "DIZERES LEGAIS" in secao.upper():
        regra_data = "- Use <mark class='anvisa'>DATA</mark> para destacar datas (DD/MM/AAAA) tanto no 'ref' quanto no 'bel'."

    if ignorar_divergencia:
        # MODO VISUALIZAÇÃO (Sem Divergência Amarela, só Data Azul)
        prompt_text = f"""
        Atue como Formatador de Texto.
        TAREFA: Extrair o texto da seção "{secao}" de dois documentos.
        
        REGRAS:
        1. NÃO MARQUE DIVERGÊNCIAS (Proibido usar amarelo).
        2. Apenas transcreva o texto limpo.
        3. {regra_data}
        
        SAÍDA JSON:
        {{
            "titulo": "{secao}",
            "ref": "Texto do documento 1 (com data azul se houver)...",
            "bel": "Texto do documento 2 (com data azul se houver)...",
            "status": "VISUALIZACAO"
        }}
        """
    else:
        # MODO AUDITORIA (Com Divergência Amarela nos DOIS lados)
        prompt_text = f"""
        Atue como Auditor Comparativo.
        TAREFA: Comparar "{secao}" entre Docs 1 e 2.
        
        REGRAS CRÍTICAS DE IGNORAR (EVITAR FALSO POSITIVO):
        1. IGNORE ABSOLUTAMENTE ESPAÇOS E FORMATAÇÃO. "A B" é igual a "A  B".
        2. SÓ MARQUE DIFERENÇA SE A LETRA OU PALAVRA MUDAR.
        
        REGRAS DE MARCAÇÃO (ESPELHADA):
        1. Se houver divergência, marque a palavra no Doc 1 E a palavra correspondente no Doc 2.
           - Exemplo: Doc 1 tem "Casa", Doc 2 tem "Caza".
           - Resultado Ref: "<mark class='diff'>Casa</mark>"
           - Resultado Bel: "<mark class='diff'>Caza</mark>"
        2. Use <mark class='ort'>ERRO</mark> para erros de português.
        3. {regra_data} (NÃO use data azul fora de Dizeres Legais).

        SAÍDA JSON:
        {{
            "titulo": "{secao}",
            "ref": "Texto Doc 1 com tags nas palavras divergentes...",
            "bel": "Texto Doc 2 com tags nas palavras divergentes...",
            "status": "CONFORME ou DIVERGENTE"
        }}
        """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Prepara envio (limita caracteres para evitar estouro de token)
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            texto_limpo = d['data'][:50000] 
            messages_content.append({"type": "text", "text": f"\n--- TEXTO {nome} ---\n{texto_limpo}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGEM {nome} ---"})
            for img in d['data'][:2]:
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    # Retry Logic para Erro JSON
    max_retries = 3
    for attempt in range(max_retries):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"}
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados and 'bel' in dados:
                dados['titulo'] = secao
                return dados
            else:
                raise ValueError("JSON Inválido")
                
        except Exception as e:
            time.sleep(1)
            if attempt == max_retries - 1:
                # Se falhar tudo, tenta retornar o texto cru sem marcação para não dar erro na tela
                return {
                    "titulo": secao,
                    "ref": "Texto muito longo para processamento automático.", 
                    "bel": "Por favor, confira manualmente esta seção.", 
                    "status": "ERRO JSON"
                }
            continue

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

if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e;">Validador Inteligente - Simétrico</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Marcação Espelhada e Zero Falsos Positivos.</p>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">💊 Novidades</div>
            <div class="card-text">
                <ul>
                    <li><b>Marcação Dupla:</b> Erros marcados em AMBOS os textos.</li>
                    <li><b>Sanitização Total:</b> Ignora completamente espaços duplos/enter.</li>
                    <li><b>Datas:</b> Azul nos dois lados.</li>
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
    if st.button("🚀 INICIAR AUDITORIA SIMÉTRICA"):
        if not f1 or not f2:
            st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            if not client: st.stop()

            with st.spinner("📂 Sanitizando e Analisando..."):
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

            resultados_secoes = []
            
            with st.status("⚡ Comparando textos lado a lado...", expanded=True) as status:
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_secao = {
                        executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2): secao 
                        for secao in lista_secoes
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_secao):
                        try:
                            data_secao = future.result()
                            if data_secao:
                                resultados_secoes.append(data_secao)
                        except Exception:
                            pass
                status.update(label="Concluído!", state="complete", expanded=False)

            # Ordenação
            resultados_secoes.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)

            # Métricas
            total = len(resultados_secoes)
            conformes = sum(1 for x in resultados_secoes if "CONFORME" in x.get('status', ''))
            score = int((conformes / total) * 100) if total > 0 else 0

            datas_texto = "N/D"
            for r in resultados_secoes:
                if "DIZERES LEGAIS" in r['titulo']:
                    match = re.search(r'\d{2}/\d{2}/\d{4}', r.get('bel', ''))
                    if match: datas_texto = match.group(0)

            m1, m2, m3 = st.columns(3)
            m1.metric("Conformidade", f"{score}%")
            m2.metric("Seções", total)
            m3.metric("Data Ref.", datas_texto)
            
            st.divider()
            
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
                        # Agora exibe HTML renderizado na esquerda também!
                        st.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px; font-size:0.9rem;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                    with cB:
                        st.markdown(f"**{nome_doc2}**")
                        st.markdown(f"<div style='background:#fff; border:1px solid #eee; padding:10px; border-radius:5px; font-size:0.9rem;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
