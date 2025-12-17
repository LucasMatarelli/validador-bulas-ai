import streamlit as st
import google.generativeai as genai
from mistralai import Mistral
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import time
from PIL import Image
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Híbrido Pro",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .stButton>button { 
        width: 100%; 
        background-color: #55a68e; 
        color: white; 
        font-weight: bold; 
        border-radius: 10px; 
        height: 55px; 
        font-size: 16px; 
        transition: all 0.3s;
    }
    .stButton>button:hover { background-color: #3d8070; transform: scale(1.02); }
    
    .ia-badge { 
        padding: 6px 12px; 
        border-radius: 6px; 
        font-weight: bold; 
        font-size: 0.85em; 
        margin-bottom: 15px; 
        display: inline-block; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .mistral-badge { background-color: #e3f2fd; color: #1565c0; border: 2px solid #90caf9; }
    .gemini-badge { background-color: #fff3e0; color: #e65100; border: 2px solid #ffb74d; }
    
    .box-content { 
        background-color: #ffffff; 
        padding: 18px; 
        border-radius: 10px; 
        font-size: 0.95em; 
        white-space: pre-wrap; 
        line-height: 1.7; 
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        min-height: 100px;
    }
    .box-bel { background-color: #f9fbe7; border-left: 5px solid #827717; }
    .box-ref { background-color: #f5f5f5; border-left: 5px solid #757575; }
    
    /* MARCADORES VISUAIS INTENSOS */
    mark.diff { 
        background-color: #ffeb3b !important; 
        color: #000000 !important;
        padding: 2px 4px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #f9a825;
        box-shadow: 0 0 5px rgba(253, 216, 53, 0.4);
        text-decoration: none;
    }
    mark.ort { 
        background-color: #ff1744 !important; 
        color: #ffffff !important; 
        padding: 2px 4px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #b71c1c;
        text-decoration: underline wavy #fff;
        box-shadow: 0 0 5px rgba(255, 23, 68, 0.4);
    }
    mark.anvisa { 
        background-color: #00e5ff !important; 
        color: #000000 !important; 
        padding: 2px 4px; 
        border-radius: 4px; 
        font-weight: bold; 
        border: 1px solid #006064; 
    }
    
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* Ajuste para garantir que HTML cru funcione bem */
    .stMarkdown p { margin-bottom: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
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

# Seções que NÃO devem ser auditadas para diferenças (ficam verdes)
SECOES_IGNORAR_DIFF = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES BACKEND -----------------

def configure_apis():
    """Configura as APIs do Gemini e Mistral"""
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gem_key: 
        genai.configure(api_key=gem_key)
    
    mis_key = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    mistral_client = Mistral(api_key=mis_key) if mis_key else None
    
    return (gem_key is not None), mistral_client

def ocr_with_gemini(images, model_name="gemini-1.5-flash"):
    """
    Realiza OCR usando Gemini Flash (Rápido e Eficiente).
    Usado apenas quando o texto não é extraível via código.
    """
    try:
        model = genai.GenerativeModel(model_name)
        
        prompt = """TRANSCRIÇÃO LITERAL E ESTRUTURADA DE BULA.
        
Instruções:
1. Extraia TODO o texto visível nas imagens.
2. Mantenha a ordem exata de leitura (colunas, seções).
3. Não resuma nada.
4. Se houver tabelas, tente manter a estrutura com espaçamento.
5. Não adicione comentários seus ("Aqui está o texto..."). Apenas o texto cru."""
        
        # Envia prompt + todas as imagens da bula
        response = model.generate_content(
            [prompt, *images],
            generation_config={"temperature": 0.0},
            safety_settings=SAFETY
        )
        
        return response.text if response.text else ""
    except Exception as e:
        st.warning(f"Erro no OCR Gemini: {e}")
        return ""

def extract_text_from_pdf(file_bytes, filename):
    """
    Decisão inteligente entre Extração Nativa vs OCR.
    Analisa cada arquivo individualmente.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        
        # 1. Tenta extração rápida (nativa)
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
        
        # Critério de densidade: Se tiver pouco texto (menos de 50 chars por página média), é imagem.
        avg_chars = len(full_text) / max(1, len(doc))
        
        if avg_chars > 100:
            doc.close()
            return {"type": "text", "data": full_text, "len": len(full_text), "method": "Nativa (Rápida)"}
        
        # 2. Se falhar, aciona OCR Gemini
        st.toast(f"👁️ '{filename}': Texto não selecionável. Ativando OCR com IA...", icon="🤖")
        
        images = []
        # Limita a 15 páginas para não estourar payload, geralmente bulas tem menos
        limit = min(15, len(doc))
        
        for i in range(limit):
            # Zoom de 2x para garantir que leia letras pequenas da bula
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            try:
                img_data = pix.tobytes("jpeg", jpg_quality=90)
            except:
                img_data = pix.tobytes("png")
                
            images.append(Image.open(io.BytesIO(img_data)))
        
        doc.close()
        gc.collect()
        
        extracted = ocr_with_gemini(images)
        
        if extracted and len(extracted) > 50:
            return {"type": "text", "data": extracted, "len": len(extracted), "method": "OCR Gemini Flash"}
        else:
            st.error(f"Falha ao ler '{filename}' mesmo com OCR.")
            return None
            
    except Exception as e:
        st.error(f"Erro ao ler PDF '{filename}': {e}")
        return None

def process_uploaded_file(uploaded_file):
    """Roteador de arquivos (DOCX ou PDF)"""
    if not uploaded_file:
        return None
    
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            txt = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": txt, "len": len(txt), "method": "DOCX Nativo"}
        
        # PDF
        elif filename.endswith('.pdf'):
            return extract_text_from_pdf(file_bytes, uploaded_file.name)
        
        else:
            st.error("Formato inválido. Use PDF ou DOCX.")
            return None
            
    except Exception as e:
        st.error(f"Erro processando '{uploaded_file.name}': {e}")
        return None

def extract_json(text):
    """Limpeza robusta de JSON vindo da LLM"""
    if not text: return None
    # Remove crases de markdown
    clean = text.replace("```json", "").replace("```", "").strip()
    # Pega o primeiro { e o último }
    start = clean.find('{')
    end = clean.rfind('}') + 1
    if start != -1 and end != -1:
        clean = clean[start:end]
    try:
        return json.loads(clean)
    except:
        return None

def normalize_sections(data, allowed):
    """Padroniza títulos das seções"""
    if not data or "SECOES" not in data: return data
    
    # Mapa de normalização (remove acentos e espaços)
    def clean_str(s): return re.sub(r'[^A-Z0-9]', '', s.upper())
    
    allowed_map = {clean_str(k): k for k in allowed}
    new_sections = []
    
    for sec in data["SECOES"]:
        # Tenta match exato
        t_raw = sec.get("titulo", "").upper()
        t_clean = clean_str(t_raw)
        
        matched_title = allowed_map.get(t_clean)
        
        # Match aproximado (fuzzy) se não achar exato
        if not matched_title:
            for k_allow, v_allow in allowed_map.items():
                if k_allow in t_clean or t_clean in k_allow: # Contém
                    matched_title = v_allow
                    break
        
        if matched_title:
            sec["titulo"] = matched_title
            new_sections.append(sec)
        # Se não der match, descarta (ou poderia manter como "OUTROS")
            
    # Ordenar conforme a lista oficial
    new_sections.sort(key=lambda x: allowed.index(x["titulo"]) if x["titulo"] in allowed else 999)
    data["SECOES"] = new_sections
    return data

def create_comparison_prompt(tipo_doc, secoes_lista):
    """Prompt Engenharia Avançada para HTML e Comparação"""
    
    secoes_str = "\n".join([f"- {s}" for s in secoes_lista])
    secoes_ignorar_str = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor Farmacêutico Sênior (QA). Sua tarefa é comparar o texto de REFERÊNCIA com o CANDIDATO.

SEÇÕES OBRIGATÓRIAS NA SAÍDA:
{secoes_str}

REGRAS CRÍTICAS PARA SEÇÕES ESPECIAIS:
As seções: [{secoes_ignorar_str}] DEVEM SER EXTRAÍDAS, MAS IGNORE DIFERENÇAS. 
Para estas seções:
1. Copie o texto.
2. Defina status = "OK".
3. NÃO use a tag <mark>. Deixe o texto limpo.

REGRAS PARA AS DEMAIS SEÇÕES (AUDITORIA RIGOROSA):
Compare palavra por palavra. Use as tags HTML abaixo para marcar o texto do CANDIDATO ("bel"):

1. <mark class='diff'>texto diferente</mark>
   - Use para: Palavras trocadas, números diferentes, pontuação alterada, acréscimos ou omissões.
   - Exemplo: "Tomar <mark class='diff'>20ml</mark>" (se original era 10ml).

2. <mark class='ort'>erro</mark>
   - Use ESTRITAMENTE para erros de português grosseiros (digitação, concordância absurda).
   - Não use para preferências estilísticas.

3. <mark class='anvisa'>dd/mm/aaaa</mark>
   - Use APENAS para destacar datas de aprovação da Anvisa nos "DIZERES LEGAIS" ou rodapé.

ESTRUTURA DE SAÍDA JSON (Não inclua markdown extra):
{{
  "METADADOS": {{
    "datas": ["extraia datas encontradas"],
    "produto": "nome do medicamento identificado"
  }},
  "SECOES": [
    {{
      "titulo": "NOME DA SEÇÃO DA LISTA ACIMA",
      "ref": "Texto completo da referência (sem tags)",
      "bel": "Texto completo do candidato (COM tags nas divergências)",
      "status": "OK" (se igual ou ignorada) ou "DIVERGENTE" (se tem mark diff) ou "FALTANTE"
    }}
  ]
}}

IMPORTANTE: 
- Retorne O CONTEÚDO COMPLETO de cada seção. Não resuma. Não trunque.
- Se uma seção existe em um e não no outro, marque como FALTANTE.
"""
    return prompt

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.title("🎯 Validador Pro")
    st.markdown("---")
    
    pag = st.radio(
        "📋 Tipo de Auditoria:", 
        ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"],
        help="Define qual IA será usada."
    )
    
    st.divider()
    
    # Status das APIs
    gem_ok, mis_client = configure_apis()
    
    col1, col2 = st.columns(2)
    with col1:
        if mis_client: st.success("🌪️ Mistral ON")
        else: st.error("⚠️ Mistral OFF")
    
    with col2:
        if gem_ok: st.success("💎 Gemini ON")
        else: st.error("❌ Gemini OFF")
    
    st.markdown("---")
    st.caption("vFinal - Roteamento Inteligente")

# Cabeçalho
st.markdown(f"## 📊 {pag}")

# Lógica de Seções
if pag == "Ref x BELFAR":
    tipo = st.radio("📄 Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
    lista_secoes = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE
else:
    tipo = "Paciente"
    lista_secoes = SECOES_PACIENTE

st.markdown("---")

# Upload
c1, c2 = st.columns(2)
with c1:
    st.markdown("### 📎 Referência (Padrão)")
    f1 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f1")
with c2:
    st.markdown("### 📎 Candidato (Validar)")
    f2 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f2")

# Botão Iniciar
if st.button("🚀 INICIAR AUDITORIA COMPLETA", use_container_width=True):
    if not f1 or not f2:
        st.warning("⚠️ Envie os dois arquivos.")
        st.stop()
    
    progress = st.progress(0, "Iniciando processamento...")
    
    # 1. Processamento de Arquivos (OCR sob demanda)
    d1 = process_uploaded_file(f1)
    progress.progress(30, "Referência processada...")
    
    d2 = process_uploaded_file(f2)
    progress.progress(60, "Candidato processado...")
    
    if not d1 or not d2:
        st.error("Erro na leitura dos arquivos.")
        st.stop()
        
    st.info(f"📄 Ref: {d1['len']} chars ({d1['method']}) | 📄 Cand: {d2['len']} chars ({d2['method']})")
    
    # 2. Definição do Modelo (Roteamento)
    prompt_sys = create_comparison_prompt(tipo, lista_secoes)
    prompt_user = f"=== TEXTO REFERÊNCIA ===\n{d1['data']}\n\n=== TEXTO CANDIDATO ===\n{d2['data']}"
    
    final_json_str = None
    model_name_display = ""
    
    start_time = time.time()
    
    try:
        # ROTEAMENTO: MISTRAL para Texto Puro
        if pag in ["Ref x BELFAR", "Conferência MKT"]:
            if not mis_client:
                st.error("Erro: Mistral API Key não configurada.")
                st.stop()
            
            progress.progress(70, "🌪️ Analisando com Mistral Large...")
            model_name_display = "Mistral Large (Latest)"
            
            chat_response = mis_client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": prompt_sys},
                    {"role": "user", "content": prompt_user}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            final_json_str = chat_response.choices[0].message.content
            
        # ROTEAMENTO: GEMINI para Gráfica/Arte (Maior Contexto/Raciocínio)
        else: # Gráfica x Arte
            if not gem_ok:
                st.error("Erro: Gemini API Key não configurada.")
                st.stop()
                
            progress.progress(70, "💎 Analisando com Gemini 1.5 Pro...")
            model_name_display = "Gemini 1.5 Pro"
            
            model = genai.GenerativeModel("gemini-1.5-pro")
            response = model.generate_content(
                f"{prompt_sys}\n\n{prompt_user}",
                generation_config={"response_mime_type": "application/json", "temperature": 0.1}
            )
            final_json_str = response.text
            
    except Exception as e:
        st.error(f"Erro fatal na IA: {e}")
        st.stop()

    progress.progress(100, "Concluído!")
    time.sleep(0.5)
    progress.empty()
    
    # 3. Renderização
    if final_json_str:
        data = extract_json(final_json_str)
        if data:
            data = normalize_sections(data, lista_secoes)
            
            # Badge do Modelo Usado
            cls_badge = "mistral-badge" if "Mistral" in model_name_display else "gemini-badge"
            st.markdown(f"<div class='ia-badge {cls_badge}'>🤖 Processado por: {model_name_display} ({time.time()-start_time:.1f}s)</div>", unsafe_allow_html=True)
            
            # Métricas
            secs = data.get("SECOES", [])
            # Filtra apenas seções auditáveis para calcular erro
            auditaveis = [s for s in secs if s['titulo'] not in SECOES_IGNORAR_DIFF]
            erros = sum(1 for s in auditaveis if s.get("status") != "OK")
            score = 100 - (erros * 5) # Penalidade simples
            if score < 0: score = 0
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Score Aprovação", f"{score}%", delta="Revisar" if erros > 0 else "Aprovado", delta_color="inverse")
            m2.metric("Seções Auditadas", f"{len(auditaveis)}")
            m3.metric("Divergências", f"{erros}")
            
            meta_datas = data.get("METADADOS", {}).get("datas", [])
            data_anvisa = meta_datas[0] if meta_datas else "N/A"
            m4.markdown(f"**📅 Data Anvisa:**<br><mark class='anvisa'>{data_anvisa}</mark>", unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Loop de Exibição das Seções
            for i, sec in enumerate(secs):
                tit = sec.get("titulo", "SEÇÃO")
                stat = sec.get("status", "OK")
                ref_txt = sec.get("ref", "")
                bel_txt = sec.get("bel", "")
                
                # Ícones e Cores
                if tit in SECOES_IGNORAR_DIFF:
                    icon = "🔒" # Ignorado
                    color_st = "OK"
                    obs = " (Não Auditada - Conteúdo Apenas Extraído)"
                    # Força status visual OK
                    stat_visual = "OK (Sem verificação de diff)"
                else:
                    obs = ""
                    if "DIVERGENTE" in stat:
                        icon = "❌"
                        stat_visual = "DIVERGENTE"
                    elif "FALTANTE" in stat:
                        icon = "🚨"
                        stat_visual = "FALTANTE"
                    else:
                        icon = "✅"
                        stat_visual = "OK"
                
                # Expander
                abrir = (stat_visual != "OK" and "OK" not in stat_visual)
                with st.expander(f"{icon} {tit} - {stat_visual}{obs}", expanded=abrir):
                    cR, cB = st.columns(2)
                    with cR:
                        st.caption("Referência (Original)")
                        st.markdown(f"<div class='box-content box-ref'>{ref_txt}</div>", unsafe_allow_html=True)
                    with cB:
                        st.caption("Candidato (Sua Arte)")
                        st.markdown(f"<div class='box-content box-bel'>{bel_txt}</div>", unsafe_allow_html=True)
            
            st.success("Fim da Auditoria.")
            
        else:
            st.error("Erro ao ler JSON da resposta da IA.")
