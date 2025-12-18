import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import json

# ----------------- 1. VISUAL & CSS (Design Limpo) -----------------
st.set_page_config(page_title="MKT Final", page_icon="📢", layout="wide")

st.markdown("""
<style>
    /* Estilo das Caixas de Texto */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #333;
        background-color: #ffffff;
        padding: 18px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        white-space: pre-wrap; /* Mantém parágrafos corretos */
        text-align: justify;
    }

    /* Destaques */
    .highlight-yellow { background-color: #fff9c4; color: #000; padding: 2px 4px; border-radius: 4px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 4px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 4px; border-radius: 4px; border: 1px solid #1976d2; font-weight: bold; }

    /* Bordas de Status */
    .border-ok { border-left: 6px solid #4caf50 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ff9800 !important; } /* Laranja */
    .border-info { border-left: 6px solid #2196f3 !important; } /* Azul */

    /* Card de Métricas */
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

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            # Temperatura 0.0 para precisão máxima
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. EXTRAÇÃO DE TEXTO (PDF E DOCX) -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        # Verifica se é PDF
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc:
                text += page.get_text("text") + "\n"
        
        # Verifica se é DOCX
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        
        return text
    except: return ""

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

# ----------------- 4. INTERFACE PRINCIPAL -----------------
st.title("📢 Conferência MKT (Relatório Estruturado)")

c1, c2 = st.columns(2)
# Atualizado para aceitar docx
f1 = c1.file_uploader("📜 Bula Anvisa (Referência)", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("🎨 Arte MKT (Para Validar)", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Sem chave API.")
            st.stop()

        with st.spinner("Lendo arquivos, corrigindo formatação e organizando seções..."):
            # Reseta o ponteiro do arquivo para garantir leitura correta
            f1.seek(0)
            f2.seek(0)
            
            # Chama a função nova que lê os dois tipos
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("Erro: Arquivo vazio ou ilegível (imagem sem OCR).")
                st.stop()

            # PROMPT AVANÇADO: SEPARAÇÃO DE DADOS E FORMATAÇÃO
            prompt = f"""
            Você é um Revisor Farmacêutico Meticuloso.
            
            INPUT:
            TEXTO 1 (ANVISA): {t_anvisa[:50000]}
            TEXTO 2 (MKT): {t_mkt[:30000]}

            SUA MISSÃO:
            1. Encontre a "Data de Aprovação da Anvisa" nos Dizeres Legais de AMBOS os textos.
            2. Mapeie o conteúdo do TEXTO 2 (MKT) nas seções da lista abaixo.
            3. Compare com o TEXTO 1.
            4. **CRÍTICO: CORRIJA A FORMATAÇÃO.** O texto extraído do PDF pode ter quebras de linha erradas (uma palavra por linha). Junte as frases para formarem parágrafos normais e bonitos.

            LISTA DE SEÇÕES: {SECOES_PACIENTE}

            REGRAS DE STATUS:
            - "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS": Sempre "CONFORME". Apenas transcreva o texto (Sem highlights de erro).
            - OUTRAS SEÇÕES: Compare rigorosamente. Use <span class="highlight-yellow">TEXTO</span> para divergências e <span class="highlight-red">TEXTO</span> para erros de PT.
            - DIZERES LEGAIS: Destaque a data da Anvisa (se houver no texto) com <span class="highlight-blue">DATA</span>. NÃO adicione "N/A" se não tiver.

            SAÍDA JSON OBRIGATÓRIA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_mkt": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto formatado (sem quebras malucas)",
                        "texto_mkt": "Texto formatado (sem quebras malucas) com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                response = model.generate_content(prompt)
                resultado = json.loads(response.text)
                
                # Extrai dados globais
                data_ref = resultado.get("data_anvisa_ref", "-")
                data_mkt = resultado.get("data_anvisa_mkt", "-")
                dados_secoes = resultado.get("secoes", [])

                # --- ÁREA DE MÉTRICAS (LÁ EM CIMA) ---
                st.markdown("### 📊 Resumo da Conferência")
                
                # Linha 1: Datas
                c_d1, c_d2, c_d3 = st.columns(3)
                c_d1.metric("Data Anvisa (Ref)", data_ref)
                c_d2.metric("Data Anvisa (MKT)", data_mkt, delta="Vigência" if data_ref == data_mkt else "Diferente")
                
                # Linha 2: Estatísticas
                total = len(dados_secoes)
                divergentes = sum(1 for d in dados_secoes if d['status'] != 'CONFORME')
                c_d3.metric("Seções Analisadas", total)

                # Mostra contadores menores abaixo
                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ **Conformes:** {total - divergentes}")
                if divergentes > 0:
                    sub2.warning(f"⚠️ **Divergentes:** {divergentes}")
                else:
                    sub2.success("✨ **Divergências:** 0")

                st.divider()

                # --- LOOP DE SEÇÕES ---
                for item in dados_secoes:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Seção')
                    
                    # Definição visual (ícone e borda)
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon = "⚖️"
                        css = "border-info"
                        aberto = True
                    elif status == "CONFORME":
                        icon = "✅"
                        css = "border-ok"
                        aberto = False
                    else:
                        icon = "⚠️"
                        css = "border-warn"
                        aberto = True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("📜 Bula Anvisa (Referência)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_anvisa", "")}</div>', unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("🎨 Arte MKT (Validado)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_mkt", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar o retorno: {e}")
                st.warning("Tente novamente, o modelo pode ter falhado na formatação do JSON.")
    else:
        st.warning("Por favor, envie os dois arquivos (PDF ou DOCX).")
