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
    """Limpa cabeçalhos e rodapés sem remover conteúdo relevante"""
    lines = text.split('\n')
    cleaned_lines = []
    ignore_patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$',
        r'^BELFAR$', r'^UBELFAR$', r'^SANOFI$', r'^MEDLEY$',
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\d{2}\s*\d{4}-\d{4}$',  # Telefones
        r'^Belcomplex_B_comprimido_BUL\d+V\d+$',  # Códigos de arquivo
        r'^(FRENTE|VERSO)$', r'^Medida da bula:', r'^Tipologia da bula:',
        r'^Impressão:', r'^Papel:', r'^Cor:', r'^Belcomplex: Times'
    ]
    
    for line in lines:
        l = line.strip()
        should_skip = False
        if len(l) < 60:  # Aumentei para não cortar parágrafos curtos importantes
            for pattern in ignore_patterns:
                if re.match(pattern, l, re.IGNORECASE):
                    should_skip = True
                    break
        if not should_skip and l:  # Só adiciona se tiver conteúdo
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """Lê o arquivo preservando ordem de colunas e estrutura"""
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            
            # Lê texto nativo com ordenação de blocos (respeitando colunas)
            for page in doc: 
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0:  # Tipo texto
                        full_text += b[4] + "\n"
            
            # Se pouco texto, usa OCR de alta resolução
            if len(full_text.strip()) < 500:
                images = []
                limit_pages = min(10, len(doc))  # Aumentei para 10 páginas
                for i in range(limit_pages):
                    page = doc[i]
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                    try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                    except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                    img = Image.open(img_byte_arr)
                    if img.width > 2500: img.thumbnail((2500, 2500), Image.Resampling.LANCZOS)
                    images.append(img)
                doc.close()
                return {"type": "images", "data": images}
            
            full_text = clean_noise(full_text)
            doc.close()
            return {"type": "text", "data": sanitize_text(full_text)}
            
    except Exception as e:
        return {"type": "text", "data": ""}

def get_next_section_title(current_section, all_sections):
    """Retorna o título da próxima seção"""
    try:
        idx = all_sections.index(current_section)
        if idx + 1 < len(all_sections):
            return all_sections[idx + 1]
        return "DIZERES LEGAIS"
    except:
        return "DIZERES LEGAIS"

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Identifica a PRÓXIMA seção para saber onde parar
    proxima_secao = get_next_section_title(secao, todas_secoes)
    
    # Lista completa de barreiras
    barreiras = [s for s in todas_secoes if s != secao]
    stop_markers_str = "\n".join([f"- {s}" for s in barreiras[:15]])  # Limita para não explodir o prompt

    # ===== INSTRUÇÕES UNIVERSAIS =====
    instrucoes_base = f"""
🤖 VOCÊ É UM EXTRATOR DE TEXTO LITERAL - NÃO REESCREVA NADA

📍 CONTEXTO DE LEITURA:
- Bulas têm MÚLTIPLAS COLUNAS (esquerda → direita)
- SEMPRE leia coluna por coluna, de cima para baixo
- O texto continua na próxima coluna quando acaba uma

🎯 SUA MISSÃO:
Extrair TODO o conteúdo da seção "{secao}" até encontrar o título "{proxima_secao}"

⚠️ REGRAS CRÍTICAS:

1️⃣ LITERALIDADE 100%:
   - Copie cada palavra EXATAMENTE como está
   - Mantenha erros de digitação do original
   - NÃO corrija gramática
   - NÃO use sinônimos
   - NÃO resuma

2️⃣ COMPLETUDE:
   - Capture TODOS os parágrafos
   - Não pare no primeiro ponto final
   - Continue até encontrar o próximo título numerado
   - Se há avisos "Atenção:", capture TODOS eles

3️⃣ DELIMITAÇÃO:
   - COMECE em: "{secao}"
   - PARE em: "{proxima_secao}"
   - Ignore cabeçalhos/rodapés (ex: "BELFAR", "31 3514-2900")
"""

    # ===== REGRAS ESPECÍFICAS POR SEÇÃO =====
    regra_especifica = ""
    
    if "1. PARA QUE" in secao.upper():
        regra_especifica = """
🚨 ATENÇÃO SEÇÃO 1:
Esta seção contém APENAS indicações terapêuticas.
PARE ANTES de qualquer texto que comece com "Atenção:".

❌ NÃO INCLUA:
- "Atenção: Contém açúcar..."
- "Atenção: Contém lactose..."
- "Atenção: Contém os corantes..."

Esses textos pertencem à SEÇÃO 3.

✅ FORMATO ESPERADO:
"[Nome do medicamento] é indicado como suplemento vitamínico nos seguintes casos: em dietas restritivas, em indivíduos com doenças infecciosas ou inflamatórias, em pacientes com má-absorção de glicose-galactose."
[FIM - PARE AQUI]
"""
    
    elif "3. QUANDO NÃO" in secao.upper():
        regra_especifica = """
🚨 ATENÇÃO SEÇÃO 3:
Esta seção é COMPLEXA e tem múltiplos blocos:

ESTRUTURA OBRIGATÓRIA:
1️⃣ Contraindicação principal (hipersensibilidade)
2️⃣ "Atenção: Contém lactose. Este medicamento não deve ser usado..."
3️⃣ "Atenção: Contém os corantes dióxido de titânio e marrom laca de alumínio..."

✅ VOCÊ DEVE capturar os 3 blocos acima.
Continue lendo até encontrar "4. O QUE DEVO SABER"
"""
    
    elif "4. O QUE DEVO SABER" in secao.upper():
        regra_especifica = """
🚨 ATENÇÃO SEÇÃO 4:
Esta é a seção MAIS LONGA da bula. Pode ter 3-4 parágrafos.

✅ VOCÊ DEVE capturar:
1️⃣ Todos os parágrafos sobre precauções
2️⃣ Informações sobre interações medicamentosas
3️⃣ Avisos finais em negrito:
   - "Atenção: Contém lactose. Este medicamento não deve ser usado..."
   - "Atenção: Contém os corantes dióxido de titânio..."
   - "Este medicamento não deve ser utilizado por mulheres grávidas..."
   - "Informe ao seu médico ou cirurgião-dentista se você está fazendo uso..."

⚠️ NÃO PARE até capturar TODOS os 4 avisos finais acima.
Continue até encontrar "5. ONDE, COMO E POR QUANTO TEMPO"
"""
    
    elif "7. O QUE DEVO FAZER" in secao.upper():
        regra_especifica = """
🚨 ATENÇÃO SEÇÃO 7 - MODO SCANNER:
Você é um SCANNER de texto. Copie EXATAMENTE.

❌ PROIBIDO:
- Mudar "deixou de tomar" para "esqueceu"
- Mudar "deverá tomar" para "deve tomar"
- Alterar QUALQUER palavra

✅ ESTRUTURA ESPERADA:
Parágrafo 1: Instruções sobre dose esquecida
Parágrafo 2: "Em caso de dúvidas procure orientação do farmacêutico..."

Capture AMBOS os parágrafos.
"""
    
    elif "9. O QUE FAZER" in secao.upper():
        regra_especifica = """
🚨 ATENÇÃO SEÇÃO 9:
Esta seção tem DOIS blocos distintos:

BLOCO 1 (Descrição clínica):
"Se você tomar uma dose muito grande deste medicamento acidentalmente, deve procurar um médico ou um centro de intoxicação imediatamente. O apoio médico imediato é fundamental para adultos e crianças, mesmo se os sinais e sintomas de intoxicação não estiverem presentes. Ainda não foram descritos os sintomas de intoxicação do medicamento após a superdosagem."

BLOCO 2 (Aviso padrão):
"Em caso de uso de grande quantidade deste medicamento, procure rapidamente socorro médico e leve a embalagem ou bula do medicamento, se possível. Ligue para 0800 722 6001, se você precisar de mais orientações."

✅ CAPTURE AMBOS OS BLOCOS COMPLETOS.
"""

    prompt_final = f"""
{instrucoes_base}

{regra_especifica}

🛑 PARE SE ENCONTRAR (próxima seção):
{proxima_secao}

📤 FORMATO DE SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "texto literal copiado do documento 1",
  "bel": "texto literal copiado do documento 2",
  "status": "CONFORME"
}}

⚠️ LEMBRE-SE: Você é um robô. Não pense, apenas COPIE.
"""
    
    messages_content = [{"type": "text", "text": prompt_final}]

    # Prepara os documentos
    limit = 80000  # Aumentei o limite
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            if len(d['data']) < 50:
                 messages_content.append({"type": "text", "text": f"\n--- {nome}: (Vazio/Ilegível) ---\n"})
            else:
                 messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- {nome} (Imagens OCR) ---"})
            for img in d['data'][:8]:  # Aumentei para 8 imagens
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    # Chamada à API com retry
    for attempt in range(3):  # 3 tentativas
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=4096  # Aumentei para respostas longas
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                
                if not eh_visualizacao:
                    # Comparação para definir status
                    t_ref = re.sub(r'\s+', ' ', str(dados.get('ref', '')).strip().lower())
                    t_bel = re.sub(r'\s+', ' ', str(dados.get('bel', '')).strip().lower())
                    t_ref = re.sub(r'<[^>]+>', '', t_ref)
                    t_bel = re.sub(r'<[^>]+>', '', t_bel)

                    if t_ref == t_bel:
                        dados['status'] = 'CONFORME'
                        dados['ref'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('ref', ''))
                        dados['bel'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('bel', ''))
                    else:
                        dados['status'] = 'DIVERGENTE'
                
                if "DIZERES LEGAIS" in secao.upper():
                    dados['status'] = "VISUALIZACAO"

                return dados
                
        except Exception as e:
            if attempt < 2:
                time.sleep(2)  # Aguarda antes de retry
            else:
                return {"titulo": secao, "ref": f"Erro: {str(e)}", "bel": "Erro", "status": "ERRO"}
    
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
    st.caption("v6.0 - Extração Sequencial")

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador de Bulas</h1>", unsafe_allow_html=True)
    st.success("✅ **Nova Versão - Extração Sequencial por Colunas**")
    st.write("")
    st.write("**Melhorias implementadas:**")
    st.write("- ✅ Leitura coluna por coluna (esquerda → direita)")
    st.write("- ✅ Delimitação precisa: para na próxima seção")
    st.write("- ✅ Captura completa de avisos 'Atenção:' nas seções corretas")
    st.write("- ✅ Modo literal: não reescreve texto original")
    st.write("- ✅ Remove ruídos (telefones, códigos de arquivo)")

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
                st.write("📖 Lendo arquivos (coluna por coluna)...")
                d1 = process_file_content(f1.getvalue(), f1.name)
                d2 = process_file_content(f2.getvalue(), f2.name)
                
                modo1 = "OCR (Imagem)" if d1['type'] == 'images' else "Texto Nativo"
                modo2 = "OCR (Imagem)" if d2['type'] == 'images' else "Texto Nativo"
                st.write(f"ℹ️ {nome_doc1}: {modo1} | {nome_doc2}: {modo2}")

                st.write("🔍 Extraindo seções literalmente...")
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
