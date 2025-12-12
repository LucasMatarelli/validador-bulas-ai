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
    # Normalização leve, mantendo quebras de linha essenciais para detecção de títulos
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u200b', '').replace('\ufeff', '').replace('\t', ' ')
    return text

def clean_noise(text):
    """Limpeza técnica que remove lixo de gráfica sem apagar conteúdo médico."""
    if not text: return ""
    
    # 1. Padrões de lixo técnico (Gráfica/Impressão)
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
        r'^\s*BELFAR\s*$', r'^\s*UBELFAR\s*$', r'^\s*SANOFI\s*$',
        r'.*CNPJ:.*', r'.*SAC:.*', r'.*Farm\. Resp\..*',
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$'
    ]
    
    cleaned_text = text
    for pattern in patterns:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Reduz quebras de linha excessivas
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    return cleaned_text.strip()

def find_section_start(text, section_name):
    """
    Localiza o índice de início de uma seção no texto, tolerando quebras de linha no título.
    Retorna o índice ou -1 se não encontrar.
    """
    # Normaliza para busca (remove espaços extras e lowercase)
    text_norm = re.sub(r'\s+', ' ', text).lower()
    
    # Prepara o título para busca (ex: "1. para que..." -> "1. para que")
    match_num = re.search(r'^(\d+)\.', section_name)
    if match_num:
        num = match_num.group(1)
        # Pega as primeiras 4 palavras do título para busca robusta
        core_title = " ".join(section_name.replace(f"{num}.", "").split()[:4]).lower()
        search_pattern = rf"{num}\s*[\.\-\)]?\s*{re.escape(core_title)}"
    else:
        # Títulos sem número (APRESENTAÇÃO, DIZERES)
        search_pattern = re.escape(section_name.split()[0].lower())

    match = re.search(search_pattern, text_norm)
    if match:
        # Se achou no texto normalizado, precisamos achar a posição no texto original.
        # Aproximação: conta caracteres até o match.
        # (Método simplificado: busca o regex direto no texto original com flag DOTALL)
        
        # Recria regex para texto original, permitindo \s+ (inclui \n) entre palavras
        words = section_name.split()
        if match_num: # Remove número para fazer regex palavra por palavra
             words = words[1:]
             regex_orig = rf"{num}\s*[\.\-\)]?\s*" + r"\s+".join([re.escape(w) for w in words[:4]])
        else:
             regex_orig = r"\s+".join([re.escape(w) for w in words[:1]])
             
        match_orig = re.search(regex_orig, text, re.IGNORECASE)
        if match_orig:
            return match_orig.start()
            
    return -1

def smart_slice(full_text, current_section, all_sections):
    """
    Corta o texto da seção atual até o início da PRÓXIMA seção encontrada.
    Se a próxima imediata não for achada, procura a seguinte, e assim por diante.
    """
    start_idx = find_section_start(full_text, current_section)
    if start_idx == -1:
        return "" # Seção não encontrada neste doc

    # Encontrar onde parar (início da próxima seção válida)
    end_idx = len(full_text)
    curr_idx_list = -1
    try: curr_idx_list = all_sections.index(current_section)
    except: pass
    
    if curr_idx_list != -1:
        # Procura a barreira mais próxima dentre as seções subsequentes
        for i in range(curr_idx_list + 1, len(all_sections)):
            next_sec = all_sections[i]
            next_start = find_section_start(full_text, next_sec)
            
            # A próxima seção deve estar DEPOIS da atual
            if next_start > start_idx:
                end_idx = next_start
                break # Achou a barreira mais próxima, para aqui.
    
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
                # Sort=True mantém a ordem lógica de leitura (colunas)
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0: full_text += b[4] + "\n\n"
            
            # Se for imagem/scan
            if len(full_text.strip()) < 200:
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
            
            # Limpeza
            full_text = clean_noise(full_text)
            return {"type": "text", "data": sanitize_text(full_text)}
            
    except Exception as e:
        return {"type": "text", "data": ""}

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # 1. RECORTE INTELIGENTE
    # Cortamos o texto antes de enviar para a IA. Isso impede "vazamento" de seções.
    texto_ref = ""
    texto_bel = ""
    
    if d1['type'] == 'text':
        texto_ref = smart_slice(d1['data'], secao, todas_secoes)
        # Se falhou o slice (vazio), usamos um fallback seguro (pequeno pedaço)
        if not texto_ref: texto_ref = "(Seção não encontrada ou texto ilegível no documento original)"
    
    if d2['type'] == 'text':
        texto_bel = smart_slice(d2['data'], secao, todas_secoes)
        if not texto_bel: texto_bel = "(Seção não encontrada ou texto ilegível no documento original)"

    # REGRAS DE PROMPT
    regra_extra = ""
    if "3. QUANDO NÃO" in secao.upper() or "4. O QUE DEVO SABER" in secao.upper():
        regra_extra = """
        ⚠️ CRÍTICO:
        - O texto fornecido termina com AVISOS em negrito (Lactose, Açúcar, Gravidez).
        - VOCÊ DEVE COPIAR ESSES AVISOS. Eles pertencem a esta seção.
        - Não pare no primeiro ponto final. Copie até o fim do texto fornecido.
        """
    elif "7. O QUE DEVO FAZER" in secao.upper():
        regra_extra = """
        - Copie TODO o texto fornecido.
        - Inclua a frase "Em caso de dúvidas procure orientação...".
        """
    elif "9. O QUE FAZER" in secao.upper():
        regra_extra = """
        - Copie o texto de superdose E o texto do "0800" / "Ligue para".
        - Ambos são obrigatórios.
        """

    prompt_text = f"""
Você é um COPIADOR DE TEXTO DE BULAS.
Sua única função é limpar a formatação e devolver o texto da seção "{secao}".

ENTRADA:
Você receberá abaixo um recorte de texto que COMEÇA na seção correta e VAI ATÉ o início da próxima seção.

TAREFA:
1. Ignore o título da seção no início (se aparecer).
2. Copie TODO o restante do conteúdo.
3. INCLUA todos os parágrafos de alerta no final (Atenção, Negritos, Rodapés da seção).
4. NÃO invente texto. Se o texto estiver vazio, retorne string vazia.

{regra_extra}

SAÍDA (JSON):
{{
  "titulo": "{secao}",
  "ref": "Texto limpo Doc 1",
  "bel": "Texto limpo Doc 2",
  "status": "CONFORME"
}}
"""
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Adiciona o conteúdo JÁ RECORTADO
    if d1['type'] == 'text':
        messages_content.append({"type": "text", "text": f"\n--- {nome_doc1} (RECORTADO) ---\n{texto_ref}"})
    else:
        messages_content.append({"type": "text", "text": f"\n--- {nome_doc1} (IMAGENS) ---"})
        for img in d1['data'][:6]: 
            b64 = image_to_base64(img)
            messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    if d2['type'] == 'text':
        messages_content.append({"type": "text", "text": f"\n--- {nome_doc2} (RECORTADO) ---\n{texto_bel}"})
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
                temperature=0.0 # Zero criatividade
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                if not eh_visualizacao:
                    # Normalização para comparação
                    t_ref = re.sub(r'\s+', ' ', str(dados.get('ref', '')).strip().lower())
                    t_bel = re.sub(r'\s+', ' ', str(dados.get('bel', '')).strip().lower())
                    t_ref = re.sub(r'<[^>]+>', '', t_ref)
                    t_bel = re.sub(r'<[^>]+>', '', t_bel)

                    # Comparação simples + Verificação de erro
                    if "(seção não encontrada" in t_ref or "(seção não encontrada" in t_bel:
                         dados['status'] = 'ERRO LEITURA'
                    elif t_ref == t_bel:
                        dados['status'] = 'CONFORME'
                    else:
                        dados['status'] = 'DIVERGENTE'
                
                if "DIZERES LEGAIS" in secao.upper(): dados['status'] = "VISUALIZACAO"
                return dados
                
        except Exception as e:
            if attempt == 0: time.sleep(1)
            else: return {"titulo": secao, "ref": f"Erro: {str(e)}", "bel": "Erro", "status": "ERRO"}
    
    return {"titulo": secao, "ref": "Erro API", "bel": "Erro API", "status": "ERRO"}

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
    st.caption("v5.6 - Smart Slice & Regex")

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador de Bulas</h1>", unsafe_allow_html=True)
    st.success("✅ **Correções Definitivas (v5.6):**")
    st.markdown("""
    - **SMART SLICE:** Recorta o texto EXATAMENTE entre o título atual e o próximo.
    - **FIM DAS ALUCINAÇÕES:** Se não achar a seção, avisa erro em vez de inventar texto.
    - **Atenção/Lactose:** Como o corte vai até o *início* da próxima seção, ele obrigatoriamente pega o rodapé da seção atual.
    - **Tolerância a Quebras:** Encontra títulos mesmo se quebrados (ex: "1. PARA QUE ESTE MEDICAMENTO É \\n INDICADO?").
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
                st.write("📖 Lendo arquivos e mapeando seções...")
                d1 = process_file_content(f1.getvalue(), f1.name)
                d2 = process_file_content(f2.getvalue(), f2.name)
                
                modo1 = "OCR (Imagem)" if d1['type'] == 'images' else "Smart Slice (Texto)"
                modo2 = "OCR (Imagem)" if d2['type'] == 'images' else "Smart Slice (Texto)"
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
