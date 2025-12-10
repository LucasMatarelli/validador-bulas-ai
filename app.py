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
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    .stRadio > div[role="radiogroup"] > label {
        background-color: white; border: 1px solid #e1e4e8; padding: 12px 15px;
        border-radius: 8px; margin-bottom: 8px; transition: all 0.2s;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #f0fbf7; border-color: #55a68e; color: #55a68e; cursor: pointer;
    }

    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); box-shadow: 0 15px 30px rgba(0,0,0,0.1); border-color: #55a68e; }

    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Marcações de texto */
    mark.diff { 
        background-color: #fff3cd; 
        color: #856404; 
        padding: 2px 4px; 
        border-radius: 3px; 
        font-weight: 500;
        border-bottom: 2px solid #ffc107;
    } 
    mark.ort { 
        background-color: #f8d7da; 
        color: #721c24; 
        padding: 2px 4px; 
        border-radius: 3px; 
        font-weight: 600;
        border-bottom: 2px solid #dc3545;
        text-decoration: underline wavy #dc3545;
    } 
    mark.anvisa { 
        background-color: #d1ecf1; 
        color: #0c5460; 
        padding: 3px 6px; 
        border-radius: 3px; 
        font-weight: bold;
        border: 1.5px solid #17a2b8;
        box-shadow: 0 1px 3px rgba(23, 162, 184, 0.2);
    }

    .stButton>button { 
        width: 100%; 
        background-color: #55a68e; 
        color: white; 
        font-weight: bold; 
        border-radius: 10px; 
        height: 55px; 
        border: none; 
        font-size: 16px; 
        box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); 
    }
    .stButton>button:hover { 
        background-color: #448c75; 
        box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); 
    }
    
    .texto-bula { 
        font-size: 1.05rem; 
        line-height: 1.7; 
        color: #333; 
    }
    
    /* Animação de loading */
    .loading-spinner {
        border: 3px solid #f3f3f3;
        border-top: 3px solid #55a68e;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        animation: spin 1s linear infinite;
        margin: 20px auto;
    }
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
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
    """Converte imagem para base64 otimizado"""
    buffered = io.BytesIO()
    # Reduz qualidade para 80 (boa qualidade, menor tamanho)
    image.save(buffered, format="JPEG", quality=80, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    """Remove caracteres invisíveis e normaliza texto"""
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ')
    text = text.replace('\u200b', '')
    text = text.replace('\u00ad', '')
    text = text.replace('\ufeff', '')
    text = text.replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """Processa arquivo com cache otimizado"""
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: 
                full_text += page.get_text() + " "
            
            # Se tem texto nativo suficiente, usa direto
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            # OCR apenas se necessário
            images = []
            limit_pages = min(5, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                # Zoom 2.5 - equilíbrio entre qualidade e velocidade
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                try: 
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                except: 
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                
                img = Image.open(img_byte_arr)
                # Reduz tamanho se muito grande
                if img.width > 2000:
                    img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                images.append(img)
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {str(e)}")
        return None
    return None

def extract_json(text):
    """Extrai JSON de forma robusta"""
    text = re.sub(r'```json|```', '', text).strip()
    if text.startswith("json"): text = text[4:]
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: 
        return None

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2):
    """Worker otimizado com prompts melhorados e retry inteligente"""
    
    eh_dizeres = "DIZERES LEGAIS" in secao.upper()
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Prompt base otimizado
    base_instruction = """
INSTRUÇÕES CRÍTICAS DE COMPARAÇÃO:

1. **NORMALIZAÇÃO ABSOLUTA**: 
   - Ignore TOTALMENTE formatação, espaços, quebras de linha, tabs, caracteres invisíveis
   - Compare APENAS o significado e conteúdo visível
   - "maleato de enalapril" = "maleato de enalapril" mesmo com códigos diferentes

2. **REGRA DE OURO - FALSO POSITIVO**:
   - Se as palavras parecem VISUALMENTE IDÊNTICAS ao ler, são IDÊNTICAS
   - NÃO MARQUE diferenças se o texto for o mesmo
   - Exemplo: "insuficiência renal" nos dois textos → NÃO MARCAR

3. **MARCAÇÃO AMARELA** (<mark class='diff'>) - USE APENAS QUANDO:
   - Palavra COMPLETAMENTE DIFERENTE: "10mg" vs "20mg"
   - Frase FALTANDO: texto existe em um mas não no outro
   - Informação DIVERGENTE: dados conflitantes
   - ❌ NUNCA marque texto idêntico
   - ❌ NUNCA marque por diferenças de formatação

4. **MARCAÇÃO VERMELHA** (<mark class='ort'>):
   - USE APENAS para erros ortográficos ÓBVIOS
   - Exemplos: "mediçamento", "efeicácia", "paciennte"
   - NÃO marque termos científicos corretos

5. **MARCAÇÃO AZUL** (<mark class='anvisa'>):
   - USE APENAS para datas DD/MM/AAAA
   - Marque em AMBOS os textos (ref e bel)

6. **TESTE FINAL**: Antes de marcar, pergunte-se: "Esse texto é REALMENTE diferente ou apenas parece diferente?"
"""
    
    prompt_text = ""
    
    if eh_dizeres:
        prompt_text = f"""
{base_instruction}

TAREFA ESPECIAL: Extrair "DIZERES LEGAIS" - MODO VISUALIZAÇÃO PURA

⚠️ ATENÇÃO CRÍTICA: Esta seção é APENAS para visualização. NÃO compare conteúdo.

INSTRUÇÕES:
1. Localize a seção "DIZERES LEGAIS" em cada documento
2. Extraia o texto completo SEM COMPARAR
3. Marque APENAS as datas com <mark class='anvisa'>DD/MM/AAAA</mark>
4. ❌ NÃO USE <mark class='diff'> em NENHUMA HIPÓTESE
5. ❌ NÃO USE <mark class='ort'> em NENHUMA HIPÓTESE

PROCURE POR:
- Farm. Resp. / Farmacêutico Responsável
- M.S. / Registro MS
- CNPJ
- SAC / Telefone
- Datas (marque com azul)

SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "texto extraído SEM marcação amarela, APENAS datas em azul",
  "bel": "texto extraído SEM marcação amarela, APENAS datas em azul",
  "status": "VISUALIZACAO"
}}

LEMBRE-SE: Dizeres Legais = VISUALIZAÇÃO PURA, sem comparação!
"""
        
    elif eh_visualizacao:
        prompt_text = f"""
{base_instruction}

TAREFA ESPECIAL: Extrair "{secao}" - MODO VISUALIZAÇÃO PURA

⚠️ ATENÇÃO CRÍTICA: Esta seção é APENAS para visualização. NÃO compare conteúdo.

INSTRUÇÕES:
1. Localize e extraia a seção "{secao}" de ambos os documentos
2. Copie o texto COMPLETO e LIMPO
3. ❌ NÃO USE <mark class='diff'> - Esta é uma seção de VISUALIZAÇÃO
4. ❌ NÃO USE <mark class='ort'> - Esta é uma seção de VISUALIZAÇÃO
5. ❌ NÃO USE <mark class='anvisa'> - Não há datas nesta seção
6. Remova apenas lixo técnico de impressão (códigos de barra, instruções de gráfica)

IMPORTANTE: 
- "Apresentações" e "Composição" são seções de REFERÊNCIA VISUAL
- O objetivo é VER o conteúdo, NÃO comparar
- Retorne texto puro sem nenhuma marcação

SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "texto extraído SEM MARCAÇÕES",
  "bel": "texto extraído SEM MARCAÇÕES",
  "status": "VISUALIZACAO"
}}
"""
        
    else:
        prompt_text = f"""
{base_instruction}

TAREFA: Comparar seção "{secao}" com PRECISÃO CIRÚRGICA.

PROCESSO DE 3 ETAPAS:

**ETAPA 1 - NORMALIZAÇÃO EXTREMA**:
- Remova mentalmente: espaços extras, quebras de linha, tabs, pontuação extra
- Converta para minúsculas mentalmente
- Normalize caracteres especiais (á = a, ç = c para comparação)
- Exemplo: "maleato  de\nenalapril" = "MALEATO DE ENALAPRIL" = "maleato de enalapril"

**ETAPA 2 - COMPARAÇÃO SEMÂNTICA**:
- Compare o SIGNIFICADO, não os bytes
- Se ambos dizem a mesma coisa = SÃO IGUAIS
- Exemplo: "Não tome maleato de enalapril" = "Não tome maleato de enalapril"

**ETAPA 3 - DECISÃO CRÍTICA**:
Pergunte-se ANTES de marcar: 
- "Esse texto transmite informação DIFERENTE?"
- Se NÃO → NÃO MARQUE
- Se SIM → marque apenas a palavra/frase específica diferente

✅ MARQUE COM AMARELO (<mark class='diff'>) SOMENTE SE:
- Palavra COMPLETAMENTE DIFERENTE: "hipertensão" vs "diabetes"  
- Número DIFERENTE: "10mg" vs "20mg"
- Frase que existe APENAS EM UM dos textos
- Informação que CONTRADIZ a outra

❌ NUNCA MARQUE SE:
- Textos são idênticos (mesmo com formatação diferente)
- "maleato de enalapril" aparece igual nos dois
- Mesmas palavras, mesma ordem, mesmo significado
- Diferenças apenas em espaçamento ou quebra de linha

🔴 MARQUE COM VERMELHO (<mark class='ort'>) SOMENTE:
- Erros ortográficos ÓBVIOS e INCONTESTÁVEIS
- Exemplos: "mediçamento", "efeicácia", "paciennte"

🔵 MARQUE COM AZUL (<mark class='anvisa'>):
- Datas DD/MM/AAAA em AMBOS os textos

**VALIDAÇÃO FINAL OBRIGATÓRIA**:
Antes de gerar o JSON, execute esta checklist:
1. ✓ Li ambos os textos completamente?
2. ✓ Comparei o SIGNIFICADO, não os bytes?
3. ✓ Cada marcação amarela marca uma diferença REAL?
4. ✓ Textos idênticos ficaram SEM marcação amarela/vermelha?
5. ✓ Se "maleato de enalapril" está igual nos dois, NÃO marquei?

EXEMPLO DE COMPARAÇÃO CORRETA:
Texto 1: "Não tome maleato de enalapril se você já teve uma reação alérgica"
Texto 2: "Não tome maleato de enalapril se você já teve uma reação alérgica"
RESULTADO: ✅ TEXTOS IDÊNTICOS - NÃO MARCAR NADA

EXEMPLO DE DIFERENÇA REAL:
Texto 1: "Não tome maleato de enalapril 10mg"
Texto 2: "Não tome maleato de enalapril 20mg"
RESULTADO: ⚠️ Marcar apenas "<mark class='diff'>10mg</mark>" vs "<mark class='diff'>20mg</mark>"

SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "texto completo com marcações APENAS onde há diferença REAL",
  "bel": "texto completo com marcações APENAS onde há diferença REAL",
  "status": "será determinado automaticamente"
}}
"""
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Limite de texto otimizado
    limit = 60000
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({
                "type": "text", 
                "text": f"\n--- {nome} ---\n{d['data'][:limit]}"
            }) 
        else:
            messages_content.append({
                "type": "text", 
                "text": f"\n--- {nome} (Imagem) ---"
            })
            # Apenas primeiras 2 imagens para velocidade
            for img in d['data'][:2]: 
                b64 = image_to_base64(img)
                messages_content.append({
                    "type": "image_url", 
                    "image_url": f"data:image/jpeg;base64,{b64}"
                })

    # Retry inteligente com backoff exponencial
    max_retries = 3
    for attempt in range(max_retries):
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
                
                # Verifica status automaticamente
                if not eh_visualizacao and not eh_dizeres:
                    texto_ref = str(dados.get('ref', '')).lower()
                    texto_bel = str(dados.get('bel', '')).lower()
                    
                    # Remove todas as marcações para comparação limpa
                    texto_ref_limpo = re.sub(r'<mark[^>]*>|</mark>', '', texto_ref)
                    texto_bel_limpo = re.sub(r'<mark[^>]*>|</mark>', '', texto_bel)
                    
                    # Normaliza para comparação
                    texto_ref_norm = re.sub(r'\s+', ' ', texto_ref_limpo).strip()
                    texto_bel_norm = re.sub(r'\s+', ' ', texto_bel_limpo).strip()
                    
                    # Se textos normalizados são idênticos, remove TODAS as marcações diff e ort
                    if texto_ref_norm == texto_bel_norm:
                        # Remove marcações amarelas e vermelhas
                        dados['ref'] = re.sub(r"<mark class=['\"]diff['\"]>|</mark>", '', dados.get('ref', ''))
                        dados['ref'] = re.sub(r"<mark class=['\"]ort['\"]>|</mark>", '', dados.get('ref', ''))
                        dados['bel'] = re.sub(r"<mark class=['\"]diff['\"]>|</mark>", '', dados.get('bel', ''))
                        dados['bel'] = re.sub(r"<mark class=['\"]ort['\"]>|</mark>", '', dados.get('bel', ''))
                        
                        # Mantém apenas marcações de data (anvisa)
                        dados['status'] = 'CONFORME'
                    else:
                        # Verifica se realmente há marcações de diferença
                        tem_diff = ('class="diff"' in texto_ref or "class='diff'" in texto_ref or
                                   'class="diff"' in texto_bel or "class='diff'" in texto_bel)
                        tem_ort = ('class="ort"' in texto_ref or "class='ort'" in texto_ref or
                                  'class="ort"' in texto_bel or "class='ort'" in texto_bel)
                        
                        if not tem_diff and not tem_ort:
                            dados['status'] = 'CONFORME'
                        else:
                            dados['status'] = 'DIVERGENTE'
                
                if eh_dizeres: 
                    dados['status'] = 'VISUALIZACAO'
                
                return dados
                
        except Exception as e:
            if attempt < max_retries - 1:
                # Backoff exponencial: 1s, 2s, 4s
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            else:
                return {
                    "titulo": secao,
                    "ref": f"⚠️ Erro após {max_retries} tentativas: {str(e)[:100]}",
                    "bel": f"⚠️ Erro após {max_retries} tentativas: {str(e)[:100]}",
                    "status": "ERRO"
                }
    
    return {
        "titulo": secao,
        "ref": "Texto não processado após tentativas.",
        "bel": "Texto não processado após tentativas.",
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
        st.error("❌ Configuração pendente")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()
    st.caption("v2.0 - Otimizado")

if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #55a68e; font-size: 3em;">Validador de Bulas</h1>
        <p style="font-size: 1.2em; color: #7f8c8d;">Auditoria Inteligente e Precisa</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">🎯 Marcação Precisa</div>
            <p class="card-text">
            <mark class="diff">Amarelo</mark>: diferenças de conteúdo<br>
            <mark class="ort">Vermelho</mark>: erros ortográficos<br>
            <mark class="anvisa">Azul</mark>: datas Anvisa
            </p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">⚡ Performance</div>
            <p class="card-text">
            Processamento paralelo de seções.<br>
            Cache inteligente.<br>
            Otimização de imagens e OCR.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">🔍 Análise Completa</div>
            <p class="card-text">
            Comparação palavra por palavra.<br>
            Detecção automática de erros.<br>
            Extração de dados regulatórios.
            </p>
        </div>
        """, unsafe_allow_html=True)

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
            if tipo_bula == "Profissional": 
                lista_secoes = SECOES_PROFISSIONAL
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
    with c1:
        st.markdown(f"##### {label_box1}")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2:
        st.markdown(f"##### {label_box2}")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2:
            st.warning("⚠️ Selecione ambos os arquivos.")
        elif not client:
            st.error("❌ Cliente Mistral não configurado. Verifique a API Key.")
            st.stop()
        else:
            # Feedback visual melhorado
            with st.status("🔄 Processando documentos...", expanded=True) as status:
                st.write("📖 Lendo arquivos...")
                
                b1 = f1.getvalue()
                b2 = f2.getvalue()
                d1 = process_file_content(b1, f1.name.lower())
                d2 = process_file_content(b2, f2.name.lower())
                gc.collect()

                if not d1 or not d2:
                    st.error("❌ Erro ao processar arquivos.")
                    st.stop()
                
                st.write("✅ Arquivos carregados")
                st.write(f"🔍 Analisando {len(lista_secoes)} seções...")
                
                resultados_secoes = []
                progress_bar = st.progress(0)
                
                # Processamento paralelo otimizado com timeout individual
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    future_to_secao = {
                        executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2): secao 
                        for secao in lista_secoes
                    }
                    
                    completed = 0
                    for future in concurrent.futures.as_completed(future_to_secao, timeout=120):
                        try:
                            data = future.result(timeout=90)  # 90s por seção
                            if data: 
                                resultados_secoes.append(data)
                        except concurrent.futures.TimeoutError:
                            secao = future_to_secao[future]
                            resultados_secoes.append({
                                "titulo": secao,
                                "ref": "⏱️ Tempo limite excedido (seção muito extensa)",
                                "bel": "⏱️ Tempo limite excedido (seção muito extensa)",
                                "status": "TIMEOUT"
                            })
                        except Exception as e:
                            secao = future_to_secao[future]
                            resultados_secoes.append({
                                "titulo": secao,
                                "ref": f"⚠️ Erro: {str(e)[:100]}",
                                "bel": f"⚠️ Erro: {str(e)[:100]}",
                                "status": "ERRO"
                            })
                        
                        completed += 1
                        progress_bar.progress(completed / len(lista_secoes))
                        st.write(f"✓ Seção {completed}/{len(lista_secoes)} concluída")
                
                status.update(label="✅ Análise concluída!", state="complete", expanded=False)
            
            # Ordena resultados
            resultados_secoes.sort(
                key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999
            )
            
            # Métricas
            total = len(resultados_secoes)
            conformes = sum(1 for x in resultados_secoes if "CONFORME" in str(x.get('status', '')))
            divergentes = sum(1 for x in resultados_secoes if "DIVERGENTE" in str(x.get('status', '')))
            visuais = sum(1 for x in resultados_secoes if "VISUALIZACAO" in str(x.get('status', '')))
            erros = sum(1 for x in resultados_secoes if "ERRO" in str(x.get('status', '')) or "TIMEOUT" in str(x.get('status', '')))
            
            score = int(((conformes + visuais) / max(total, 1)) * 100)  # Evita divisão por zero
            
            # Extrai datas
            datas_encontradas = []
            for r in resultados_secoes:
                if "DIZERES LEGAIS" in r['titulo']:
                    texto_combinado = str(r.get('ref', '')) + " " + str(r.get('bel', ''))
                    matches = re.findall(r'\d{2}/\d{2}/\d{4}', texto_combinado)
                    for m in matches:
                        if m not in datas_encontradas: 
                            datas_encontradas.append(m)
            
            datas_texto = " | ".join(sorted(set(datas_encontradas))) if datas_encontradas else "N/D"

            # Dashboard de métricas
            m1, m2, m3, m4 = st.columns(4)
            
            # Cor dinâmica baseada no score
            score_color = "🟢" if score >= 90 else "🟡" if score >= 70 else "🔴"
            m1.metric("Conformidade", f"{score_color} {score}%", f"{conformes} seções")
            m2.metric("Divergências", divergentes, delta_color="inverse" if divergentes > 0 else "off")
            m3.metric("Total Seções", total)
            m4.metric("Datas Anvisa", len(datas_encontradas))
            
            # Alerta de erros
            if erros > 0:
                st.warning(f"⚠️ {erros} seção(ões) com erro de processamento. Verifique abaixo.")
            
            if datas_encontradas:
                st.info(f"📅 **Datas encontradas:** {datas_texto}")
            
            st.divider()
            
            # Legenda
            st.markdown("""
            **Legenda de Marcações:**  
            <mark class='diff'>Amarelo</mark> = Diferença de conteúdo | 
            <mark class='ort'>Vermelho</mark> = Erro ortográfico | 
            <mark class='anvisa'>Azul</mark> = Data Anvisa
            """, unsafe_allow_html=True)
            
            st.divider()
            
            # Resultados por seção com ícones dinâmicos
            for sec in resultados_secoes:
                status = sec.get('status', 'N/A')
                titulo = sec.get('titulo', '').upper()
                
                # Ícones e cores por status
                if "CONFORME" in status:
                    icon = "✅"
                    cor_borda = "#28a745"
                elif "DIVERGENTE" in status:
                    icon = "⚠️"
                    cor_borda = "#ffc107"
                elif "VISUALIZACAO" in status:
                    icon = "👁️"
                    cor_borda = "#17a2b8"
                elif "TIMEOUT" in status:
                    icon = "⏱️"
                    cor_borda = "#fd7e14"
                elif "ERRO" in status:
                    icon = "❌"
                    cor_borda = "#dc3545"
                else:
                    icon = "❓"
                    cor_borda = "#6c757d"
                
                # Expande automaticamente apenas divergências e erros
                expandir = "DIVERGENTE" in status or "ERRO" in status or "TIMEOUT" in status
                
                with st.expander(f"{icon} {titulo} — {status}", expanded=expandir):
                    cA, cB = st.columns(2)
                    with cA:
                        st.markdown(f"**{nome_doc1}**")
                        st.markdown(
                            f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-radius:5px; border-left: 4px solid {cor_borda};'>{str(sec.get('ref', 'Texto não extraído'))}</div>", 
                            unsafe_allow_html=True
                        )
                    with cB:
                        st.markdown(f"**{nome_doc2}**")
                        st.markdown(
                            f"<div class='texto-bula' style='background:#fff; border:1px solid #ddd; padding:15px; border-radius:5px; border-left: 4px solid {cor_borda};'>{str(sec.get('bel', 'Texto não extraído'))}</div>", 
                            unsafe_allow_html=True
                        )
            
            # Resumo final com recomendações
            st.divider()
            
            if score >= 95:
                st.success(f"🎉 **Excelente!** {conformes + visuais}/{total} seções conformes. Documentos altamente compatíveis.")
            elif score >= 80:
                st.success(f"✅ **Bom resultado!** {conformes + visuais}/{total} seções conformes. Revise as divergências encontradas.")
            elif score >= 60:
                st.warning(f"⚠️ **Atenção necessária.** {divergentes} divergência(s) encontrada(s). Revisão manual recomendada.")
            else:
                st.error(f"❌ **Revisão crítica necessária.** Múltiplas divergências detectadas. Verifique cada seção cuidadosamente.")
            
            # Botão de exportação (placeholder para futura funcionalidade)
            if st.button("📥 Exportar Relatório (Em breve)"):
                st.info("Funcionalidade de exportação será adicionada em breve!")
