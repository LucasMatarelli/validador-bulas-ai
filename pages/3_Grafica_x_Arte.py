import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler Word
import io
import json

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

st.markdown("""
<style>
    /* Caixas de Texto */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        height: 100%; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        white-space: pre-wrap; /* Mantém parágrafos */
        text-align: justify;
    }

    /* Destaques Precisos */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
    }
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; font-weight: bold; 
    }
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ffc107 !important; } /* Amarelo */
    .border-info { border-left: 6px solid #17a2b8 !important; } /* Azul */

    /* Métricas no Topo */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 3. PROCESSAMENTO -----------------
def process_file_content(uploaded_file):
    """Lê PDF (Imagens), Imagens Diretas ou DOCX (Texto)."""
    try:
        # 1. PDF -> Imagens (OCR Visual)
        if uploaded_file.name.lower().endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            return images
        
        # 2. Imagens Diretas
        elif uploaded_file.name.lower().endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
        
        # 3. DOCX -> Texto
        elif uploaded_file.name.lower().endswith(".docx"):
            doc = docx.Document(uploaded_file)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return ["\n".join(full_text)]
            
    except: return []

SECOES_COMPLETAS = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Validador de Bulas (Gráfica x Arte)")

c1, c2 = st.columns(2)
# Tipos atualizados
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    
    # Prepara as chaves disponíveis
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando leitura inteligente (ignorando espaçamento de gráfica)..."):
            # Reseta ponteiros
            f1.seek(0)
            f2.seek(0)
            
            # Processa conteúdo (Imagens ou Texto)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # PROMPT
            prompt = f"""
            Você é um leitor de OCR especializado em Bulas Farmacêuticas.
            
            INPUT: Imagens ou Texto de documentos justificados (com espaçamento irregular).
            TAREFA: Extrair e comparar o texto das seções: {SECOES_COMPLETAS}

            ⚠️ REGRAS DE LEITURA (CRÍTICO):
            1. **CORREÇÃO DE JUSTIFICAÇÃO:** Documentos de gráfica usam texto justificado que cria espaços visuais falsos dentro das palavras (ex: "Em bora" visualmente, mas é "Embora"). 
               - Você DEVE ignorar esses espaços visuais e ler a palavra correta ("Embora").
               - NÃO separe palavras que o português define como juntas.
            
            2. **LIMITES:** Copie do Título da Seção até o Título da Próxima Seção.
            
            REGRAS DE COMPARAÇÃO:
            - GRUPO 1 ("APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"):
                * Status SEMPRE "CONFORME". Apenas transcreva o texto limpo.
                * "DIZERES LEGAIS": Se achar data (dd/mm/aaaa), marque <span class="highlight-blue">DATA</span>. Se não achar, não marque nada.
            
            - GRUPO 2 (Outras Seções):
                * Compare o texto REAL (sem os bugs de espaçamento).
                * Se houver divergência REAL (palavra errada, texto faltando), marque <span class="highlight-yellow">PALAVRA</span>.
                * Erros ortográficos REAIS: Marque <span class="highlight-red">PALAVRA</span>.
                * Não marque falsos positivos causados por espaçamento (ex: "Em bora" vs "Embora" -> Considere igual).

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_grafica": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto da arte",
                        "texto_grafica": "Texto da gráfica com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            # Prepara o payload
            payload = [prompt, "--- ARTE ---"] + conteudo1 + ["--- GRAFICA ---"] + conteudo2
            
            response = None
            ultimo_erro = ""

            # --- LÓGICA DE TENTATIVA DE CHAVES ---
            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    
                    response = model.generate_content(payload)
                    break # Sucesso! Sai do loop

                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        st.warning(f"⚠️ Chave {i+1} falhou. Tentando Chave {i+2}...")
                        continue
                    else:
                        st.error(f"❌ Todas as chaves falharam. Erro: {ultimo_erro}")
                        st.stop()
            
            # --- PROCESSAMENTO DO RESULTADO ---
            if response:
                try:
                    resultado = json.loads(response.text)
                    
                    # Dados globais
                    data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                    data_graf = resultado.get("data_anvisa_grafica", "Não encontrada")
                    secoes = resultado.get("secoes", [])

                    # --- 1. RESUMO NO TOPO ---
                    st.markdown("### 📊 Resumo da Conferência")
                    
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Data Anvisa (Ref)", data_ref)
                    
                    cor_delta = "normal" if data_ref == data_graf and data_ref != "Não encontrada" else "inverse"
                    msg_delta = "Vigência" if data_ref == data_graf else "Diferente"
                    if data_graf == "Não encontrada": msg_delta = ""
                    
                    k2.metric("Data Anvisa (Gráfica)", data_graf, delta=msg_delta, delta_color=cor_delta)
                    k3.metric("Seções Analisadas", len(secoes))

                    div_count = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    ok_count = len(secoes) - div_count
                    
                    b1, b2 = st.columns(2)
                    b1.success(f"✅ **Conformes: {ok_count}**")
                    if div_count > 0:
                        b2.warning(f"⚠️ **Divergentes: {div_count}**")
                    else:
                        b2.success("✨ **Divergentes: 0**")
                    
                    st.divider()

                    # --- 2. LISTA DE SEÇÕES ---
                    for item in secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon, css, aberto = "📅", "border-info", True
                        elif status == "CONFORME":
                            icon, css, aberto = "✅", "border-ok", False
                        else:
                            icon, css, aberto = "⚠️", "border-warn", True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("Referência (Arte)")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("Validação (Gráfica)")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro no processamento do JSON: {e}")
                    st.warning("Tente novamente. O modelo pode ter oscilado.")

    else:
        st.warning("Adicione os arquivos.")
