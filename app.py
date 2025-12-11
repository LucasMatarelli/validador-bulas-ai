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
    page_title="Validador de Bulas",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    
    .stCard { background-color: white; padding: 25px; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; font-weight: bold; border-bottom: 2px solid #ffc107; } 
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; font-weight: bold; text-decoration: underline wavy red; } 
    mark.anvisa { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; font-weight: bold; }

    .texto-bula { font-size: 1.0rem; line-height: 1.6; color: #333; font-family: 'Segoe UI', sans-serif; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 50px; border: none; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "2. COMO ESTE MEDICAMENTO FUNCIONA?",
    "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "6. COMO DEVO USAR ESTE MEDICAMENTO?",
    "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
    "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA",
    "3. CARACTERÍSTICAS FARMACOLÓGICAS", "4. CONTRAINDICAÇÕES",
    "5. ADVERTÊNCIAS E PRECAUÇÕES", "6. INTERAÇÕES MEDICAMENTOSAS",
    "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "8. POSOLOGIA E MODO DE USAR",
    "9. REAÇÕES ADVERSAS", "10. SUPERDOSE", "DIZERES LEGAIS"
]

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO"]

# ----------------- FUNÇÕES AUXILIARES -----------------

@st.cache_resource
def get_mistral_client():
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    return Mistral(api_key=api_key) if api_key else None

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=90, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u200b', '').replace('\u00ad', '').replace('\ufeff', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """
    Processa arquivos com OCR FORÇADO se o texto nativo for insuficiente.
    """
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            
            # Tenta extrair texto nativo primeiro (rápido)
            for page in doc: 
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0: full_text += b[4] + "\n"
            
            # --- LÓGICA DE DECISÃO: TEXTO OU OCR? ---
            # Se tiver pouco texto (menos de 500 chars), provavelmente é imagem/curvas.
            # Nesse caso, ignoramos o texto extraído e partimos para OCR pesado.
            usar_ocr = len(full_text.strip()) < 500
            
            if not usar_ocr:
                # Limpeza básica de rodapés se for texto nativo
                full_text = re.sub(r'(Página|Pag\.)\s*\d+(\s*de\s*\d+)?', '', full_text, flags=re.IGNORECASE)
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            # --- MODO OCR (Alta Resolução) ---
            # Se caiu aqui, é porque o PDF é imagem. Vamos "aumentar o zoom".
            images = []
            limit_pages = min(8, len(doc)) # Lê até 8 páginas
            for i in range(limit_pages):
                page = doc[i]
                # Matrix(3.0, 3.0) aumenta a resolução em 3x (Zoom) para ler letras pequenas
                pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                try: 
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                except: 
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                
                img = Image.open(img_byte_arr)
                # Redimensiona se ficar monstrusamente grande, mas mantém qualidade alta
                if img.width > 2500:
                    img.thumbnail((2500, 2500), Image.Resampling.LANCZOS)
                images.append(img)
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro no processamento: {str(e)}")
        return {"type": "text", "data": ""}

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Barreiras
    barreiras = [s for s in todas_secoes if s != secao]
    barreiras.extend(["DIZERES LEGAIS", "Anexo B", "Histórico de Alteração"])
    stop_markers_str = "\n".join([f"- {s}" for s in barreiras])

    # Regras específicas Anti-Alucinação e Anti-Mistura
    regra_especifica = ""
    if "1. PARA QUE" in secao.upper():
        regra_especifica = """
        ATENÇÃO EXTREMA SEÇÃO 1:
        - Esta seção geralmente é CURTA.
        - Se você vir um quadro "Atenção: Contém...", "Atenção: Este medicamento...", "Não use se...", PARE. Isso pertence às Contraindicações (Seção 3).
        - NÃO inclua avisos de "Atenção" na Seção 1.
        """
    elif "4. O QUE DEVO SABER" in secao.upper():
        regra_especifica = """
        ATENÇÃO EXTREMA SEÇÃO 4:
        - Esta seção é LONGA. Ela atravessa colunas.
        - Não pare no primeiro parágrafo. Continue lendo até encontrar o título "5. ONDE, COMO..."
        """

    prompt_text = f"""
    Você é um scanner de texto OCR forense.
    
    TAREFA: Localizar e copiar o texto da seção "{secao}".
    
    ⚠️ REGRAS DE SEGURANÇA (PARA NÃO INVENTAR):
    1. **TOLERÂNCIA ZERO PARA INVENÇÃO**: Se você não encontrar o texto exato da seção, responda com string vazia "". NÃO INVENTE TEXTO DE OUTRAS BULAS (ex: não fale de "gel" se não estiver escrito).
    2. **CÓPIA LITERAL**: Copie exatamente o que vê.
       - Texto original: "deixou de tomar" -> Você escreve: "deixou de tomar". (NUNCA mude para "esqueceu").
       - Texto original: "não deve ser utilizado" -> Você escreve: "não deve ser utilizado".
    
    ⚠️ REGRAS DE ESTRUTURA:
    1. O texto original tem colunas. Siga o fluxo de leitura.
    2. **PARE** imediatamente se encontrar qualquer título da lista abaixo.
    
    {regra_especifica}
    
    ⛔ TÍTULOS DE PARADA (STOP MARKERS):
    {stop_markers_str}
    
    SAÍDA JSON:
    {{
      "titulo": "{secao}",
      "ref": "texto exato extraído do documento 1",
      "bel": "texto exato extraído do documento 2",
      "status": "CONFORME"
    }}
    """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Se for texto, manda texto. Se for imagem (OCR forçado), manda imagem.
    limit = 60000
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            if len(d['data']) < 50: # Segurança contra texto vazio
                 messages_content.append({"type": "text", "text": f"\n--- {nome}: (Arquivo vazio ou ilegível) ---\n"})
            else:
                 messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- {nome} (Imagens do PDF) ---"})
            # Manda mais páginas (até 4) para garantir que pegue seções longas
            for img in d['data'][:4]: 
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                
                if not eh_visualizacao:
                    # Limpeza para comparação
                    t_ref = re.sub(r'\s+', ' ', str(dados.get('ref', '')).strip().lower())
                    t_bel = re.sub(r'\s+', ' ', str(dados.get('bel', '')).strip().lower())
                    
                    # Remove tags HTML residuais
                    t_ref = re.sub(r'<[^>]+>', '', t_ref)
                    t_bel = re.sub(r'<[^>]+>', '', t_bel)

                    if t_ref == t_bel:
                        dados['status'] = 'CONFORME'
                        # Remove marcações se estiver tudo certo
                        dados['ref'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('ref', ''))
                        dados['bel'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('bel', ''))
                    else:
                        dados['status'] = 'DIVERGENTE'
                
                if "DIZERES LEGAIS" in secao.upper():
                    dados['status'] = "VISUALIZACAO"

                return dados
                
        except Exception as e:
            if attempt == 0: time.sleep(2)
            else: return {"titulo": secao, "ref": f"Erro: {str(e)}", "bel": "Erro", "status": "ERRO"}
    
    return {"titulo": secao, "ref": "Erro de processamento", "bel": "Erro de processamento", "status": "ERRO"}

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de bulas")
    client = get_mistral_client()
    if client: st.success("✅ Sistema Online")
    else: st.error("❌ Configuração pendente")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()
    st.caption("v4.5 - OCR + Anti-Alucinação")

if pagina == "🏠 Início":
    st.markdown("""<div style="text-align: center;"><h1>Validador de Bulas</h1></div>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.info("🎯 **OCR Avançado:** Zoom 3x automático")
    with c2: st.info("⚡ **Anti-Alucinação:** Bloqueio de invenção")
    with c3: st.info("🔍 **Colunas:** Leitura visual inteligente")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_doc1 = "REFERÊNCIA"
    nome_doc2 = "BELFAR"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Referência"
        label_box2 = "📄 BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional": lista_secoes = SECOES_PROFISSIONAL
    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 ANVISA"
        label_box2 = "📄 MKT"
        nome_doc1 = "ANVISA"
        nome_doc2 = "MKT"
    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"
        label_box2 = "📄 Gráfica"
        nome_doc1 = "ARTE VIGENTE"
        nome_doc2 = "GRÁFICA"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: f1 = st.file_uploader(label_box1, type=["pdf", "docx"], key="f1")
    with c2: f2 = st.file_uploader(label_box2, type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2 or not client:
            st.warning("⚠️ Verifique arquivos e API Key.")
        else:
            with st.status("🔄 Processando documentos (OCR pode levar alguns segundos)...", expanded=True) as status:
                d1 = process_file_content(f1.getvalue(), f1.name)
                d2 = process_file_content(f2.getvalue(), f2.name)
                
                # Feedback sobre o modo de leitura usado
                modo1 = "OCR (Imagem)" if d1['type'] == 'images' else "Texto Nativo"
                modo2 = "OCR (Imagem)" if d2['type'] == 'images' else "Texto Nativo"
                st.write(f"ℹ️ Doc 1 lido como: **{modo1}** | Doc 2 lido como: **{modo2}**")
                
                st.write("🔍 Auditando seções...")
                resultados = []
                bar = st.progress(0)
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {
                        executor.submit(auditar_secao_worker, client, sec, d1, d2, nome_doc1, nome_doc2, lista_secoes): sec 
                        for sec in lista_secoes
                    }
                    
                    for i, future in enumerate(concurrent.futures.as_completed(futures)):
                        res = future.result()
                        resultados.append(res)
                        bar.progress((i + 1) / len(lista_secoes))
                
                status.update(label="✅ Concluído!", state="complete", expanded=False)

            resultados.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)
            
            conformes = sum(1 for r in resultados if "CONFORME" in r.get('status', ''))
            divergentes = sum(1 for r in resultados if "DIVERGENTE" in r.get('status', ''))
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Total", len(lista_secoes))
            k2.metric("Conformes", conformes)
            k3.metric("Divergentes", divergentes, delta_color="inverse")
            
            st.divider()
            
            for res in resultados:
                status = res.get('status', 'ERRO')
                icon = "✅" if "CONFORME" in status else "⚠️" if "DIVERGENTE" in status else "👁️"
                cor = "#28a745" if "CONFORME" in status else "#ffc107" if "DIVERGENTE" in status else "#17a2b8"
                
                with st.expander(f"{icon} {res['titulo']} - {status}", expanded=("DIVERGENTE" in status)):
                    c_a, c_b = st.columns(2)
                    with c_a:
                        st.caption(nome_doc1)
                        st.markdown(f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-left: 5px solid {cor};'>{res.get('ref', '')}</div>", unsafe_allow_html=True)
                    with c_b:
                        st.caption(nome_doc2)
                        st.markdown(f"<div class='texto-bula' style='background:#fff; border:1px solid #ddd; padding:15px; border-left: 5px solid {cor};'>{res.get('bel', '')}</div>", unsafe_allow_html=True)
