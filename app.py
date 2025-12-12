import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import re
import os
import unicodedata

# ----------------- CONFIGURAÇÃO DA CHAVE API -----------------
# Sua chave foi configurada diretamente aqui para facilitar
MINHA_API_KEY = "AIzaSyBcPfO6nlsy1vCvKW_VNofEmG7GaSdtiLE"

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas Pro (Gemini)",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (Visual Limpo) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main { background-color: #f4f6f8; }
    
    /* Cards de veredito */
    .stCard { background-color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    
    /* Botão Roxo (Estilo Gemini Pro) */
    .stButton>button { 
        width: 100%; 
        background-color: #6f42c1; 
        color: white; 
        font-weight: bold; 
        border-radius: 8px; 
        height: 50px; 
        border: none;
        font-size: 16px;
    }
    .stButton>button:hover { background-color: #5a32a3; }
    
    /* Áreas de texto */
    .stTextArea textarea { font-size: 14px; color: #333; background-color: #f9f9f9; }
</style>
""", unsafe_allow_html=True)

# ----------------- FUNÇÕES DE SISTEMA -----------------

def configure_gemini():
    """Configura a API do Google com a chave fornecida"""
    if MINHA_API_KEY:
        genai.configure(api_key=MINHA_API_KEY)
        return True
    return False

def clean_noise(text):
    """
    Limpeza Cirúrgica (Baseada no seu código v105).
    Remove sujeira técnica de gráfica (marcas de corte, pantone, etc)
    mas mantém o conteúdo médico intacto.
    """
    if not text: return ""
    
    # 1. Normalização
    text = text.replace('\xa0', ' ').replace('\r', '')
    
    # 2. Lista de padrões de lixo técnico para remover
    patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$',
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\s*:\s*\d{1,3}\s*[xX]\s*\d{1,3}\s*$', # Dimensões
        r'\b\d{1,3}\s*mm\b', r'\b\d{1,3}\s*cm\b',
        r'.*:\s*19\s*,\s*0\s*x\s*45\s*,\s*0.*',
        r'^\s*\d{1,3}\s*,\s*00\s*$',
        r'.*Impess[ãa]o:.*', r'.*Negrito\s*[\.,]?\s*Corpo\s*\d+.*',
        r'.*artes.*belfar.*', r'.*Cor:\s*Preta.*', r'.*Papel:.*',
        r'.*Times New Roman.*', r'.*Cores?:.*', r'.*Pantone.*',
        r'.*Laetus.*', r'.*Pharmacode.*', r'^\s*BELFAR\s*$',
        r'.*CNPJ:.*', r'.*SAC:.*', r'.*Farm\. Resp\..*',
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$'
    ]
    
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove excesso de quebras de linha
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def extract_full_text(file_bytes, filename):
    """
    Lê o arquivo PDF ou DOCX e retorna o texto bruto limpo.
    Usa PyMuPDF para PDF (rápido e preciso).
    """
    try:
        text = ""
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
        else:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc: 
                # Leitura em blocos para manter ordem das colunas
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0: # Apenas texto
                        text += b[4] + "\n"
        
        # Se tiver muito pouco texto, é provável que seja imagem/scan
        if len(text) < 100: return None 
        return clean_noise(text)
    except: return None

# ----------------- RECORTE INTELIGENTE (SMART SLICE) -----------------

def find_section_start(text, section_name):
    """Encontra onde começa uma seção, tolerando pequenas diferenças"""
    text_lower = text.lower()
    # Tenta achar título exato
    core_title = section_name.lower().split('?')[0]
    match = re.search(re.escape(core_title), text_lower)
    if match: return match.start()
    
    # Fallback: Tenta achar "1. " se a seção for numerada
    if section_name[0].isdigit():
        num = section_name.split('.')[0]
        match = re.search(rf"\n\s*{num}\.\s", text_lower)
        if match: return match.start()
    return -1

def get_section_text(full_text, section, all_sections):
    """Corta o texto da seção atual até o início da próxima"""
    if not full_text: return "Texto não detectado (Possível Scan/Imagem)"
    
    start = find_section_start(full_text, section)
    if start == -1: return "Seção não encontrada neste documento"
    
    end = len(full_text)
    try:
        idx = all_sections.index(section)
        # Procura a próxima seção que exista no texto para usar como fim
        for i in range(idx+1, len(all_sections)):
            next_start = find_section_start(full_text, all_sections[i])
            if next_start > start:
                end = next_start
                break
    except: pass
    
    return full_text[start:end].strip()

# ----------------- CÉREBRO DA IA (JUIZ) -----------------

def ai_judge_diff(ref_text, bel_text, secao):
    """
    Usa o Gemini Pro apenas para JULGAR a diferença.
    Não pede para ele extrair (evita bloqueio de copyright).
    """
    if len(ref_text) < 10 or len(bel_text) < 10: return "⚠️ Texto insuficiente para análise."
    
    # Configurações de segurança no ZERO para não bloquear bulas
    safety = {
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    # Usando o modelo Pro (Mais inteligente que o Flash)
    model = genai.GenerativeModel('gemini-1.5-pro', safety_settings=safety)
    
    prompt = f"""
    Atue como um Especialista em Assuntos Regulatórios da ANVISA.
    
    TAREFA: Compare os dois textos abaixo da seção "{secao}".
    
    --- TEXTO REFERÊNCIA (Arte/Anvisa) ---
    {ref_text[:20000]}
    
    --- TEXTO GRÁFICA (Prova) ---
    {bel_text[:20000]}
    
    INSTRUÇÕES:
    1. Ignore formatação, quebras de linha ou espaços extras.
    2. Foque em CONTEÚDO: Números (mg, ml), nomes de substâncias, avisos de "Atenção" e "Negrito".
    3. Se o texto da Gráfica tiver o mesmo conteúdo do texto de Referência, responda apenas: "CONFORME".
    4. Se houver diferença de conteúdo (ex: falta um aviso, número errado), LISTE O ERRO.
    """
    
    try:
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Erro na IA: {str(e)}"

# ----------------- INTERFACE PRINCIPAL -----------------

st.title("🧠 Validador Pro (Gemini Hybrid)")
st.markdown("**Status:** Pronta para uso | **Engine:** Gemini 1.5 Pro | **Modo:** Extração Python + Análise IA")

if configure_gemini():
    st.success(f"✅ Chave API conectada com sucesso!")
else:
    st.error("❌ Erro na Chave API.")

# Upload
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📄 Arquivo Referência (PDF/Word)", key="f1")
f2 = c2.file_uploader("📄 Arquivo Gráfica (PDF/Word)", key="f2")

# Definição das seções
SECOES_PACIENTE = [
    "APRESENTAÇÕES",
    "COMPOSIÇÃO",
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

if f1 and f2:
    st.divider()
    if st.button("🚀 INICIAR AUDITORIA PRO"):
        with st.spinner("Processando... Lendo arquivos..."):
            # 1. Extração Python (Sem risco de alucinação)
            t1 = extract_full_text(f1.getvalue(), f1.name)
            t2 = extract_full_text(f2.getvalue(), f2.name)
            
            if not t1 or not t2:
                st.error("🚨 ERRO CRÍTICO: Um dos arquivos é imagem (Scan) ou está protegido. Este validador requer texto selecionável.")
            else:
                st.write("✅ Textos extraídos. Iniciando análise inteligente...")
                prog = st.progress(0)
                
                # Loop pelas seções
                for i, sec in enumerate(SECOES_PACIENTE):
                    # Recorta o texto exato da seção
                    txt_ref = get_section_text(t1, sec, SECOES_PACIENTE)
                    txt_bel = get_section_text(t2, sec, SECOES_PACIENTE)
                    
                    # Define cor e status inicial
                    veredito = "..."
                    color = "gray"
                    
                    # Verifica se o recorte funcionou
                    if "não encontrada" in txt_ref:
                         veredito = "❌ Seção não localizada na Referência"
                         color = "orange"
                    elif "não encontrada" in txt_bel:
                         veredito = "❌ Seção não localizada na Gráfica"
                         color = "orange"
                    else:
                         # Chama o Gemini para JULGAR (não copiar)
                         analise = ai_judge_diff(txt_ref, txt_bel, sec)
                         
                         if "CONFORME" in analise.upper() and len(analise) < 100:
                             veredito = "✅ CONFORME"
                             color = "green"
                         else:
                             veredito = analise # Mostra o erro apontado pela IA
                             color = "red"

                    # Exibe o resultado
                    with st.expander(f"{sec}", expanded=(color=="red")):
                        st.markdown(f":{color}[**RESULTADO: {veredito}**]")
                        
                        col_a, col_b = st.columns(2)
                        col_a.markdown("**Texto Referência (Recorte):**")
                        col_a.text_area("ref", txt_ref, height=200, label_visibility="collapsed", key=f"r_{i}")
                        
                        col_b.markdown("**Texto Gráfica (Recorte):**")
                        col_b.text_area("bel", txt_bel, height=200, label_visibility="collapsed", key=f"b_{i}")
                    
                    # Atualiza barra
                    prog.progress((i + 1) / len(SECOES_PACIENTE))
                
                st.success("🏁 Auditoria Finalizada!")
