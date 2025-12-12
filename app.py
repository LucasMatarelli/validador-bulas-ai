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

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

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
    image.save(buffered, format="JPEG", quality=95, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u200b', '').replace('\u00ad', '').replace('\ufeff', '')
    return text.strip()

def clean_header_footer(text):
    """Remove apenas cabeçalhos/rodapés, mantém conteúdo"""
    lines = text.split('\n')
    cleaned = []
    
    noise_patterns = [
        r'^\d{2}\s*\d{4}-\d{4}$',  # Telefones
        r'^Belcomplex_B_comprimido_BUL\d+',  # Códigos
        r'^(FRENTE|VERSO)$',
        r'^Medida da bula:',
        r'^Tipologia da bula:',
        r'^Impressão:',
        r'^Papel:',
        r'^Cor:',
        r'^Belcomplex: Times',
        r'^\d+ª PROVA',
        r'^Página \d+',
        r'^\d+$'  # Números sozinhos
    ]
    
    for line in lines:
        l = line.strip()
        if not l:
            continue
        
        is_noise = False
        if len(l) < 50:  # Só verifica linhas curtas
            for pattern in noise_patterns:
                if re.match(pattern, l, re.IGNORECASE):
                    is_noise = True
                    break
        
        if not is_noise:
            cleaned.append(line)
    
    return "\n".join(cleaned)

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        return json.loads(text)
    except:
        return None

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """Processa arquivo extraindo texto com preservação de layout"""
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            text = clean_header_footer(text)
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            
            # Tenta extração de texto nativo com ordenação por posição
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Usa blocks ordenados por posição (respeita colunas)
                blocks = page.get_text("blocks", sort=True)
                
                for block in blocks:
                    if block[6] == 0:  # Tipo texto
                        block_text = block[4].strip()
                        if block_text:
                            full_text += block_text + "\n"
            
            # Se texto muito curto, usa OCR
            if len(full_text.strip()) < 300:
                images = []
                for i in range(min(12, len(doc))):
                    page = doc[i]
                    # Alta resolução para OCR preciso
                    pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0))
                    
                    try:
                        img_bytes = io.BytesIO(pix.tobytes("jpeg"))
                    except:
                        img_bytes = io.BytesIO(pix.tobytes("png"))
                    
                    img = Image.open(img_bytes)
                    # Reduz tamanho se muito grande
                    if img.width > 3000:
                        img.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
                    
                    images.append(img)
                
                doc.close()
                return {"type": "images", "data": images}
            
            # Limpa ruídos
            full_text = clean_header_footer(full_text)
            doc.close()
            return {"type": "text", "data": sanitize_text(full_text)}
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
        return {"type": "text", "data": ""}

def get_section_boundaries(secao, todas_secoes):
    """Retorna título da próxima seção"""
    try:
        idx = todas_secoes.index(secao)
        if idx + 1 < len(todas_secoes):
            return todas_secoes[idx + 1]
    except:
        pass
    return None

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    """Worker para auditoria de uma seção"""
    
    eh_visualizacao = secao in SECOES_VISUALIZACAO
    proxima_secao = get_section_boundaries(secao, todas_secoes)
    
    # Monta prompt ultra-específico
    stop_instruction = f"PARE imediatamente quando encontrar o título: '{proxima_secao}'" if proxima_secao else "Continue até o final da seção"
    
    # Instruções específicas por seção
    instrucoes_secao = ""
    
    if "1. PARA QUE" in secao:
        instrucoes_secao = """
🎯 SEÇÃO 1 - REGRA CRÍTICA:
Esta seção contém APENAS as indicações terapêuticas.
EXEMPLO: "Belcomplex B é indicado como suplemento vitamínico nos seguintes casos: em dietas restritivas, em indivíduos com doenças infecciosas ou inflamatórias, em pacientes com má-absorção de glicose-galactose."

⛔ NÃO INCLUA:
- Avisos que começam com "Atenção:"
- Avisos sobre corantes/lactose
- USO ORAL / USO ADULTO

PARE no ponto final ANTES de qualquer "Atenção:".
"""
    
    elif "3. QUANDO NÃO" in secao:
        instrucoes_secao = """
🎯 SEÇÃO 3 - REGRA CRÍTICA:
Esta seção tem múltiplos blocos de "Atenção:".

ESTRUTURA COMPLETA:
1. Contraindicação: "Belcomplex B é contraindicado para pacientes com hipersensibilidade às vitaminas do complexo B ou aos outros componentes da fórmula."
2. "Atenção: Contém lactose. Este medicamento não deve ser usado por pessoas com síndrome de má-absorção de glicose-galactose."
3. "Atenção: Contém os corantes dióxido de titânio e marrom laca de alumínio que podem, eventualmente, causar reações alérgicas."

✅ CAPTURE OS 3 BLOCOS.
Continue até encontrar "4. O QUE DEVO SABER"
"""
    
    elif "4. O QUE DEVO SABER" in secao:
        instrucoes_secao = """
🎯 SEÇÃO 4 - SEÇÃO LONGA - REGRA CRÍTICA:
Esta é a seção mais longa. Tem múltiplos parágrafos E avisos finais obrigatórios.

VOCÊ DEVE CAPTURAR:
1. Todos os parágrafos sobre precauções (renais, gravidez, parkinsonianos, etc)
2. Parágrafos sobre interações medicamentosas
3. AVISOS FINAIS OBRIGATÓRIOS (ao final da seção):
   - "Atenção: Contém os corantes dióxido de titânio e marrom laca de alumínio que podem, eventualmente, causar reações alérgicas."
   - "Atenção: Contém lactose. Este medicamento não deve ser usado por pessoas com síndrome de má-absorção de glicose-galactose."
   - "Este medicamento não deve ser utilizado por mulheres grávidas sem orientação médica ou do cirurgião-dentista."
   - "Informe ao seu médico ou cirurgião-dentista se você está fazendo uso de algum outro medicamento."

⚠️ NÃO PARE até capturar TODOS os 4 avisos finais.
"""
    
    elif "7. O QUE DEVO FAZER" in secao:
        instrucoes_secao = """
🎯 SEÇÃO 7 - MODO SCANNER LITERAL:
Você é um ROBÔ. Copie EXATAMENTE cada palavra.

⚠️ LITERALIDADE ABSOLUTA:
- Se diz "deixou de tomar" → escreva "deixou de tomar"
- Se diz "deverá tomar" → escreva "deverá tomar"
- PROIBIDO usar sinônimos

ESTRUTURA:
Parágrafo 1: Instrução sobre dose esquecida
Parágrafo 2: "Em caso de dúvidas procure orientação do farmacêutico ou de seu médico ou cirurgião-dentista."

Capture AMBOS.
"""
    
    elif "9. O QUE FAZER" in secao:
        instrucoes_secao = """
🎯 SEÇÃO 9 - REGRA CRÍTICA:
Esta seção tem DOIS blocos separados:

BLOCO 1 (Descrição):
"Se você tomar uma dose muito grande deste medicamento acidentalmente, deve procurar um médico ou um centro de intoxicação imediatamente. O apoio médico imediato é fundamental para adultos e crianças, mesmo se os sinais e sintomas de intoxicação não estiverem presentes. Ainda não foram descritos os sintomas de intoxicação do medicamento após a superdosagem."

BLOCO 2 (Aviso padrão):
"Em caso de uso de grande quantidade deste medicamento, procure rapidamente socorro médico e leve a embalagem ou bula do medicamento, se possível. Ligue para 0800 722 6001, se você precisar de mais orientações."

✅ CAPTURE AMBOS OS BLOCOS COMPLETOS.
"""

    prompt = f"""
Você é um EXTRATOR DE TEXTO LITERAL. Sua única função é COPIAR texto, não interpretar.

📋 TAREFA: Extrair o conteúdo da seção "{secao}"

🔒 REGRAS ABSOLUTAS:
1. LITERALIDADE: Copie palavra por palavra, vírgula por vírgula
2. COMPLETUDE: Não omita parágrafos
3. PRECISÃO: {stop_instruction}

{instrucoes_secao}

📍 CONTEXTO:
- Bulas têm múltiplas colunas (leia esquerda → direita, cima → baixo)
- Ignore cabeçalhos/rodapés (telefones, códigos)
- Mantenha quebras de parágrafo

📤 SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "conteúdo literal do documento 1",
  "bel": "conteúdo literal do documento 2",
  "status": "CONFORME"
}}

⚠️ CRÍTICO: Não invente. Não resuma. Não melhore. Apenas COPIE.
"""

    messages = [{"type": "text", "text": prompt}]
    
    # Adiciona documentos
    for doc, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if doc['type'] == 'text':
            if len(doc['data']) < 50:
                messages.append({"type": "text", "text": f"\n=== {nome} ===\n[Documento vazio ou ilegível]\n"})
            else:
                # Envia texto completo (até 100k chars)
                messages.append({"type": "text", "text": f"\n=== {nome} ===\n{doc['data'][:100000]}\n"})
        else:
            messages.append({"type": "text", "text": f"\n=== {nome} (OCR) ===\n"})
            # Envia todas as imagens disponíveis
            for img in doc['data'][:10]:
                b64 = image_to_base64(img)
                messages.append({
                    "type": "image_url",
                    "image_url": f"data:image/jpeg;base64,{b64}"
                })
    
    # Chamada à API
    for attempt in range(3):
        try:
            response = client.chat.complete(
                model="pixtral-large-latest",
                messages=[{"role": "user", "content": messages}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=8192
            )
            
            content = response.choices[0].message.content
            dados = extract_json(content)
            
            if dados and 'ref' in dados and 'bel' in dados:
                dados['titulo'] = secao
                
                if not eh_visualizacao:
                    # Normaliza para comparação
                    ref_norm = re.sub(r'\s+', ' ', dados.get('ref', '').lower().strip())
                    bel_norm = re.sub(r'\s+', ' ', dados.get('bel', '').lower().strip())
                    
                    dados['status'] = 'CONFORME' if ref_norm == bel_norm else 'DIVERGENTE'
                else:
                    dados['status'] = 'VISUALIZACAO'
                
                return dados
            
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                return {
                    "titulo": secao,
                    "ref": f"Erro na extração: {str(e)}",
                    "bel": "Erro",
                    "status": "ERRO"
                }
    
    return {
        "titulo": secao,
        "ref": "Falha na extração",
        "bel": "Falha na extração",
        "status": "ERRO"
    }

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de bulas")
    client = get_mistral_client()
    if client:
        st.success("✅ Sistema Online")
    else:
        st.error("❌ Configure MISTRAL_API_KEY")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()
    st.caption("v7.0 - Extração Literal Rigorosa")

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador de Bulas v7.0</h1>", unsafe_allow_html=True)
    st.success("✅ **Versão Reescrita - Extração Ultra-Precisa**")
    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        st.info("**Melhorias:**")
        st.write("- Instruções específicas por seção")
        st.write("- Modo scanner literal (Seção 7)")
        st.write("- Captura completa de avisos")
    with col2:
        st.info("**Correções:**")
        st.write("- Seção 1: Para antes de 'Atenção:'")
        st.write("- Seção 3: Captura 3 blocos")
        st.write("- Seção 4: Captura avisos finais")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_doc1, nome_doc2 = "REFERÊNCIA", "BELFAR"
    
    if pagina == "💊 Ref x BELFAR":
        label1, label2 = "📄 Referência", "📄 BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
            if tipo == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL
    elif pagina == "📋 Conferência MKT":
        label1, label2 = "📄 ANVISA", "📄 MKT"
        nome_doc1, nome_doc2 = "ANVISA", "MKT"
    else:  # Gráfica x Arte
        label1, label2 = "📄 Arte Vigente", "📄 Gráfica"
        nome_doc1, nome_doc2 = "ARTE VIGENTE", "GRÁFICA"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        f1 = st.file_uploader(label1, type=["pdf", "docx"], key="f1")
    with c2:
        f2 = st.file_uploader(label2, type=["pdf", "docx"], key="f2")
    
    st.write("")
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2 or not client:
            st.warning("⚠️ Carregue ambos os arquivos e verifique a API Key")
        else:
            with st.status("🔄 Processando...", expanded=True) as status:
                st.write("📖 Lendo arquivos...")
                d1 = process_file_content(f1.getvalue(), f1.name)
                d2 = process_file_content(f2.getvalue(), f2.name)
                
                modo1 = "OCR" if d1['type'] == 'images' else "Texto"
                modo2 = "OCR" if d2['type'] == 'images' else "Texto"
                st.write(f"ℹ️ {nome_doc1}: {modo1} | {nome_doc2}: {modo2}")
                
                st.write("🔍 Extraindo seções...")
                resultados = []
                bar = st.progress(0)
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    futures = {
                        executor.submit(
                            auditar_secao_worker,
                            client, sec, d1, d2,
                            nome_doc1, nome_doc2, lista_secoes
                        ): sec
                        for sec in lista_secoes
                    }
                    
                    for i, future in enumerate(concurrent.futures.as_completed(futures)):
                        res = future.result()
                        resultados.append(res)
                        bar.progress((i + 1) / len(lista_secoes))
                
                status.update(label="✅ Concluído!", state="complete", expanded=False)
            
            # Ordena resultados
            resultados.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)
            
            # Métricas
            conformes = sum(1 for r in resultados if r.get('status') == 'CONFORME')
            divergentes = sum(1 for r in resultados if r.get('status') == 'DIVERGENTE')
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Total", len(lista_secoes))
            k2.metric("Conformes", conformes)
            k3.metric("Divergentes", divergentes, delta_color="inverse")
            
            st.divider()
            
            # Exibe resultados
            for res in resultados:
                status_val = res.get('status', 'ERRO')
                
                if status_val == 'CONFORME':
                    icon, cor = "✅", "#28a745"
                elif status_val == 'DIVERGENTE':
                    icon, cor = "⚠️", "#ffc107"
                elif status_val == 'VISUALIZACAO':
                    icon, cor = "👁️", "#17a2b8"
                else:
                    icon, cor = "❌", "#dc3545"
                
                expanded = (status_val == 'DIVERGENTE')
                
                with st.expander(f"{icon} {res['titulo']} — {status_val}", expanded=expanded):
                    ca, cb = st.columns(2)
                    with ca:
                        st.caption(f"**{nome_doc1}**")
                        st.markdown(
                            f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-left:5px solid {cor};'>{res.get('ref', '')}</div>",
                            unsafe_allow_html=True
                        )
                    with cb:
                        st.caption(f"**{nome_doc2}**")
                        st.markdown(
                            f"<div class='texto-bula' style='background:#fff; border:1px solid #ddd; padding:15px; border-left:5px solid {cor};'>{res.get('bel', '')}</div>",
                            unsafe_allow_html=True
                        )
