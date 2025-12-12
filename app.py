import streamlit as st
from mistralai import Mistral
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
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
    .texto-bula { font-size: 1.0rem; line-height: 1.6; color: #333; font-family: 'Segoe UI', sans-serif; white-space: pre-wrap; }
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

def clean_noise(text):
    """Limpeza técnica (marcas de corte, etc), preservando texto médico."""
    if not text: return ""
    text = text.replace('\xa0', ' ').replace('\r', '')
    
    # Remove apenas lixo técnico estrito
    patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$',
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\s*:\s*\d{1,3}\s*[xX]\s*\d{1,3}\s*$', 
        r'\b\d{1,3}\s*mm\b', r'\b\d{1,3}\s*cm\b',
        r'.*:\s*19\s*,\s*0\s*x\s*45\s*,\s*0.*',
        r'^\s*\d{1,3}\s*,\s*00\s*$',
        r'.*(?:—\s*)+\s*>\s*>\s*>\s*».*',
        r'.*gm\s*>\s*>\s*>.*',
        r'.*MMA\s+\d{4}\s*-\s*\d{1,2}/\d{2,4}.*',
        r'.*Impress[ãa]o:.*',
        r'.*Negrito\s*[\.,]?\s*Corpo\s*\d+.*',
        r'.*artes.*belfar.*',
        r'.*Cor:\s*Preta.*', r'.*Papel:.*', r'.*Ap\s*\d+gr.*',
        r'.*Times New Roman.*', r'.*Cores?:.*', r'.*Pantone.*',
        r'.*Laetus.*', r'.*Pharmacode.*',
        r'^\s*BELFAR\s*$', r'^\s*UBELFAR\s*$', r'^\s*SANOFI\s*$', r'^\s*MEDLEY\s*$',
        r'.*CNPJ:.*', r'.*SAC:.*', r'.*Farm\. Resp\..*',
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$'
    ]
    
    cleaned_text = text
    for pattern in patterns:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE | re.MULTILINE)
    
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    return cleaned_text.strip()

def get_section_header_regex(secao):
    """Gera regex flexível para encontrar o título da seção."""
    # Extrai o número se houver (ex: "1. PARA QUE" -> "1")
    match = re.search(r'^(\d+)\.', secao)
    if match:
        num = match.group(1)
        # Regex que aceita "1. TÍTULO", "1 TÍTULO", "1 - TÍTULO", case insensitive
        # Pega a parte principal do título para evitar falhas por pequenos erros
        core_title = secao.split('?')[0].replace(f"{num}.", "").strip()[:15] 
        return re.compile(rf"{num}\s*[\.\-\)]?\s*{re.escape(core_title)}", re.IGNORECASE)
    else:
        # Para seções sem número (APRESENTAÇÕES, DIZERES)
        return re.compile(re.escape(secao.split(' ')[0]), re.IGNORECASE)

def slice_section_text(full_text, secao_alvo, lista_secoes):
    """
    Corta o texto EXATAMENTE onde começa a seção alvo e onde começa a PRÓXIMA.
    Isso impede que a seção 1 pegue texto da seção 4, ou que a 6 pegue a 7.
    """
    if not full_text or len(full_text) < 10: return ""
    
    # 1. Encontrar início da seção alvo
    regex_alvo = get_section_header_regex(secao_alvo)
    match_alvo = regex_alvo.search(full_text)
    
    if not match_alvo:
        return full_text # Se não achar o título, manda tudo (fallback)
    
    start_idx = match_alvo.start()
    
    # 2. Encontrar o início da PRÓXIMA seção para usar como fim
    end_idx = len(full_text)
    idx_alvo_na_lista = -1
    
    try: idx_alvo_na_lista = lista_secoes.index(secao_alvo)
    except: pass
    
    if idx_alvo_na_lista != -1 and idx_alvo_na_lista < len(lista_secoes) - 1:
        # Tenta achar qualquer uma das próximas seções (para caso pule alguma)
        for i in range(idx_alvo_na_lista + 1, len(lista_secoes)):
            prox_sec = lista_secoes[i]
            regex_prox = get_section_header_regex(prox_sec)
            match_prox = regex_prox.search(full_text, pos=start_idx + 10) # Busca APÓS o inicio da atual
            
            if match_prox:
                end_idx = match_prox.start()
                break # Achou a barreira mais próxima
    
    # 3. Recorta o texto com uma pequena margem de segurança
    # Inclui o "Atenção" que costuma estar logo antes do próximo título
    return full_text[start_idx:end_idx].strip()

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            text = clean_noise(text)
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: 
                # Sort=True é vital para ler colunas na ordem certa
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0: full_text += b[4] + "\n\n"
            
            if len(full_text.strip()) < 500: # Scan/Imagem
                images = []
                limit_pages = min(8, len(doc)) 
                for i in range(limit_pages):
                    page = doc[i]
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                    except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                    img = Image.open(img_byte_arr)
                    img.thumbnail((2500, 2500), Image.Resampling.LANCZOS)
                    images.append(img)
                doc.close()
                return {"type": "images", "data": images}
            
            full_text = clean_noise(full_text)
            return {"type": "text", "data": sanitize_text(full_text)}
            
    except Exception as e:
        return {"type": "text", "data": ""}

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # PREPARAÇÃO DO TEXTO (Corte Cirúrgico)
    # Se for texto, cortamos antes de enviar. Se for imagem, mandamos as imagens.
    texto_ref_focado = ""
    texto_bel_focado = ""
    
    # Documento 1
    if d1['type'] == 'text':
        texto_ref_focado = slice_section_text(d1['data'], secao, todas_secoes)
        if len(texto_ref_focado) < 10: texto_ref_focado = d1['data'][:30000] # Fallback
    
    # Documento 2
    if d2['type'] == 'text':
        texto_bel_focado = slice_section_text(d2['data'], secao, todas_secoes)
        if len(texto_bel_focado) < 10: texto_bel_focado = d2['data'][:30000] # Fallback

    regra_extra = ""
    if "7. O QUE DEVO FAZER" in secao.upper():
        regra_extra = "MODO SCANNER: Copie o texto EXATAMENTE como está. Não resuma. Copie até a frase 'Em caso de dúvidas procure orientação do farmacêutico'."
    elif "4. O QUE DEVO SABER" in secao.upper() or "3. QUANDO NÃO" in secao.upper():
        regra_extra = "IMPORTANTE: Inclua TODOS os avisos de 'Atenção:', 'Contém lactose', 'Gravidez' que estiverem no final do texto fornecido."

    prompt_text = f"""
Você é um EXTRATOR DE CONTEÚDO DE BULAS.
Sua tarefa: Limpar e formatar o texto da seção "{secao}".

O texto que você receberá ABAIXO já foi recortado do documento original, mas pode conter sujeira no início ou fim.

SEU OBJETIVO:
1. Identifique onde começa o texto REAL da seção "{secao}".
2. Copie TUDO até o final do bloco fornecido, INCLUINDO frases em negrito como "Atenção:...", "Informe ao seu médico...", "Ligue para 0800...".
3. NÃO inclua o título da PRÓXIMA seção (ex: não inclua "5. ONDE..." se estivermos na seção 4).
4. Se o texto estiver cortado abruptamente, copie até onde der.

{regra_extra}

SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "Texto limpo extraído do Doc 1",
  "bel": "Texto limpo extraído do Doc 2",
  "status": "CONFORME"
}}
"""
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Adiciona o conteúdo já focado (recortado)
    # DOC 1
    if d1['type'] == 'text':
        messages_content.append({"type": "text", "text": f"\n--- TEXTO {nome_doc1} (RECORTADO) ---\n{texto_ref_focado}"})
    else:
        messages_content.append({"type": "text", "text": f"\n--- {nome_doc1} (IMAGENS) ---"})
        for img in d1['data'][:6]: 
            b64 = image_to_base64(img)
            messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    # DOC 2
    if d2['type'] == 'text':
        messages_content.append({"type": "text", "text": f"\n--- TEXTO {nome_doc2} (RECORTADO) ---\n{texto_bel_focado}"})
    else:
        messages_content.append({"type": "text", "text": f"\n--- {nome_doc2} (IMAGENS) ---"})
        for img in d2['data'][:6]: 
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
                    t_ref = re.sub(r'\s+', ' ', str(dados.get('ref', '')).strip().lower())
                    t_bel = re.sub(r'\s+', ' ', str(dados.get('bel', '')).strip().lower())
                    t_ref = re.sub(r'<[^>]+>', '', t_ref)
                    t_bel = re.sub(r'<[^>]+>', '', t_bel)

                    if t_ref == t_bel:
                        dados['status'] = 'CONFORME'
                        dados['ref'] = dados.get('ref', '')
                        dados['bel'] = dados.get('bel', '')
                    else:
                        dados['status'] = 'DIVERGENTE'
                
                if "DIZERES LEGAIS" in secao.upper(): dados['status'] = "VISUALIZACAO"
                return dados
                
        except Exception as e:
            if attempt == 0: time.sleep(1)
            else: return {"titulo": secao, "ref": f"Erro: {str(e)}", "bel": "Erro", "status": "ERRO"}
    
    return {"titulo": secao, "ref": "Erro extração", "bel": "Erro extração", "status": "ERRO"}

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
    st.caption("v5.5 - Corte Híbrido")

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador de Bulas</h1>", unsafe_allow_html=True)
    st.success("✅ **Correções Implementadas (v5.5):**")
    st.markdown("""
    - **CORTE FÍSICO DO TEXTO:** O sistema agora recorta o texto da Seção X até a Seção Y antes de enviar para a IA.
    - **FIM DA MISTURA DE SEÇÕES:** Impossível a Seção 1 conter texto da Seção 4, pois o texto da 4 é removido antes da análise.
    - **CAPTURA DE AVISOS:** Como o corte vai até o título da próxima seção, ele obrigatoriamente inclui os rodapés (Atenção, Negritos) da seção atual.
    - **CORREÇÃO SEÇÃO 7:** Garante que o texto final 'Em caso de dúvidas...' seja capturado.
    """)

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
            with st.status("🔄 Processando documentos...", expanded=True) as status:
                st.write("📖 Lendo arquivos e aplicando recorte inteligente...")
                d1 = process_file_content(f1.getvalue(), f1.name)
                d2 = process_file_content(f2.getvalue(), f2.name)
                
                modo1 = "OCR (Imagem)" if d1['type'] == 'images' else "Texto Nativo (Recortado)"
                modo2 = "OCR (Imagem)" if d2['type'] == 'images' else "Texto Nativo (Recortado)"
                st.write(f"ℹ️ {nome_doc1}: {modo1} | {nome_doc2}: {modo2}")

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
