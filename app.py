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
import unicodedata
import time
import concurrent.futures

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas", page_icon="💊", layout="wide")

# Listas de seções para busca
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

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO"]

# ----------------- FUNÇÕES AUXILIARES -----------------

def get_mistral_client():
    """Obtém o cliente da API Mistral."""
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    return Mistral(api_key=api_key) if api_key else None

def image_to_base64(image):
    """Converte imagem para base64."""
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    """Limpa o texto removendo caracteres invisíveis e normalizando espaços."""
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    # Remove caracteres invisíveis e espaços não quebráveis
    text = text.replace('\xa0', ' ').replace('\u0000', '').replace('\u200b', '')
    # Transforma múltiplos espaços em um único espaço
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def remove_numbering(text):
    """Remove numeração automática de seções (ex: '5. Onde...')."""
    if not text: return ""
    return re.sub(r'^\s*\d+[\.\)]\s*', '', text)

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """Processa o conteúdo do arquivo (PDF ou DOCX)."""
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 100:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            # OCR se for imagem (fallback)
            images = []
            limit_pages = min(5, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except: return None
    return None

def extract_json(text):
    """Extrai JSON válido de uma string, lidando com erros comuns."""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text).strip()
    try:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        return json.loads(text)
    except: return None

# --- WORKER DE AUDITORIA ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, proxima_secao):
    
    eh_dizeres = "DIZERES LEGAIS" in secao.upper()
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Instrução de limite para evitar pegar texto da próxima seção
    limite_instrucao = ""
    if proxima_secao:
        limite_instrucao = f"O texto termina ANTES do título '{proxima_secao}'. NÃO leia além disso."
    else:
        limite_instrucao = "Leia até o fim do documento."

    prompt_text = ""
    
    if eh_dizeres:
        prompt_text = f"""
        Atue como Auditor. Extraia "DIZERES LEGAIS".
        ONDE: Rodapé (CNPJ, Farm. Resp).
        REGRAS: 
        1. Copie o texto completo encontrado. 
        2. Destaque datas (DD/MM/AAAA) com <mark class='anvisa'>DATA</mark> EM AMBOS OS TEXTOS (Ref e Bel).
        3. NÃO use amarelo.
        JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    elif eh_visualizacao:
        prompt_text = f"""
        Atue como Formatador. Transcreva "{secao}".
        REGRAS: Apenas texto puro. Sem marcações.
        JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    else:
        # PROMPT DE COMPARAÇÃO REFINADO
        prompt_text = f"""
        Atue como Auditor Rigoroso. Compare "{secao}" entre Doc 1 e Doc 2.
        
        LIMITES: O texto começa após o título "{secao}". {limite_instrucao}
        
        REGRAS PARA IGNORAR (NÃO MARQUE ERRO):
        1. "Candida" == "Candida:" == "Candida)". (Ignore pontuação colada).
        2. "150mg" == "150 mg". (Ignore espaços).
        3. Maiúsculas/minúsculas se o sentido for igual.
        
        MARQUE AMARELO (<mark class='diff'>) APENAS SE:
        - Palavra trocada (ex: "paranoide" vs "paranóide").
        - Texto adicionado ou removido.
        
        JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "CONFORME ou DIVERGENTE" }}
        """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Limite seguro para não cortar JSON
    limit = 35000 
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGEM {nome} ---"})
            for img in d['data'][:2]: 
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"}
            )
            dados = extract_json(chat_response.choices[0].message.content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                dados['ref'] = remove_numbering(dados.get('ref', ''))
                dados['bel'] = remove_numbering(dados.get('bel', ''))

                # Auto-Correção de Status
                if not eh_visualizacao and not eh_dizeres:
                    txt = (str(dados.get('bel', '')) + str(dados.get('ref', ''))).lower()
                    tem_marca = 'class="diff"' in txt or "class='diff'" in txt or "class='ort'" in txt
                    if not tem_marca: dados['status'] = 'CONFORME'
                
                if eh_dizeres: dados['status'] = 'VISUALIZACAO'
                return dados
                
        except Exception:
            time.sleep(1)
            continue
    
    # FALLBACK SE JSON FALHAR (Mostra texto cru)
    texto1 = d1['data'] if d1['type']=='text' else ""
    texto2 = d2['data'] if d2['type']=='text' else ""
    
    # Busca simples para tentar mostrar algo relevante
    idx1 = texto1.find(secao)
    idx2 = texto2.find(secao)
    
    res1 = texto1[idx1:idx1+2000] if idx1 != -1 else "Texto não encontrado ou erro JSON."
    res2 = texto2[idx2:idx2+2000] if idx2 != -1 else "Texto não encontrado ou erro JSON."

    return {
        "titulo": secao,
        "ref": res1,
        "bel": res2,
        "status": "ERRO LEITURA (Texto Bruto)"
    }

# ----------------- UI PRINCIPAL -----------------

st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; } 
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; } 
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
    .texto-bula { font-size: 1.1rem !important; line-height: 1.6; color: #333; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 12px; height: 60px; border: none; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    client = get_mistral_client()
    if client: st.success("✅ Conectado")
    else: st.error("❌ Desconectado (API Key)")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador de Bulas</h1>", unsafe_allow_html=True)
    st.info("Selecione o tipo de auditoria no menu lateral.")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_doc1 = "REFERÊNCIA"
    nome_doc2 = "BELFAR"
    
    if pagina == "💊 Ref x BELFAR":
        label1, label2 = "Ref", "Belfar"
        nome_doc1, nome_doc2 = "REFERÊNCIA", "BELFAR"
        tipo = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
        if tipo == "Profissional": lista_secoes = SECOES_PROFISSIONAL
    elif pagina == "📋 Conferência MKT":
        label1, label2 = "ANVISA", "MKT"
        nome_doc1, nome_doc2 = "ANVISA", "MKT"
    elif pagina == "🎨 Gráfica x Arte":
        label1, label2 = "Arte", "Gráfica"
        nome_doc1, nome_doc2 = "ARTE", "GRÁFICA"
    
    c1, c2 = st.columns(2)
    # CORREÇÃO CRÍTICA: Labels definidos para evitar erro do Streamlit
    f1 = c1.file_uploader(f"Arquivo {label1}", type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(f"Arquivo {label2}", type=["pdf", "docx"], key="f2")
    
    if st.button("INICIAR AUDITORIA"):
        if not client or not f1 or not f2:
            st.warning("Verifique conexão e arquivos.")
            st.stop()

        with st.spinner("🚀 Lendo arquivos..."):
            d1 = process_file_content(f1.getvalue(), f1.name.lower())
            d2 = process_file_content(f2.getvalue(), f2.name.lower())
        
        resultados = []
        progress = st.progress(0)
        status = st.empty()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_secao = {}
            for i, secao in enumerate(lista_secoes):
                # Define a próxima seção para usar como âncora de fim
                proxima = lista_secoes[i+1] if i + 1 < len(lista_secoes) else None
                future = executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2, proxima)
                future_to_secao[future] = secao
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_secao):
                try:
                    data = future.result()
                    if data: resultados.append(data)
                except: pass
                completed += 1
                progress.progress(completed / len(lista_secoes))
                status.text(f"Analisando: {completed}/{len(lista_secoes)}")

        status.empty()
        progress.empty()
        # Ordena os resultados para seguir a ordem correta da bula
        resultados.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)

        total = len(resultados)
        conformes = sum(1 for x in resultados if "CONFORME" in x.get('status', ''))
        visuais = sum(1 for x in resultados if "VISUALIZACAO" in x.get('status', ''))
        score = int(((conformes + visuais) / total) * 100) if total > 0 else 0
        
        st.metric("Conformidade Geral", f"{score}%")
        st.divider()

        for sec in resultados:
            stt = sec.get('status', 'N/A')
            icon = "✅"
            if "DIVERGENTE" in stt: icon = "❌"
            elif "ERRO" in stt: icon = "⚠️"
            elif "VISUALIZACAO" in stt: icon = "👁️"
            
            with st.expander(f"{icon} {sec['titulo']} — {stt}"):
                cA, cB = st.columns(2)
                with cA:
                    st.markdown(f"**{nome_doc1}**")
                    st.markdown(f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-radius:5px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                with cB:
                    st.markdown(f"**{nome_doc2}**")
                    st.markdown(f"<div class='texto-bula' style='background:#fff; border:1px solid #eee; padding:15px; border-radius:5px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
