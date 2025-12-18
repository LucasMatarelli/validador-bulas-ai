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
    
    # 1. RECUPERA CHAVES PARA O FAILOVER
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Lendo arquivos e extraindo texto original (sem alucinações)..."):
            # Reseta o ponteiro do arquivo
            f1.seek(0)
            f2.seek(0)
            
            # Extração do texto
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("Erro: Arquivo vazio ou ilegível (imagem sem OCR).")
                st.stop()

            # PROMPT BLINDADO CONTRA ALUCINAÇÃO
            prompt = f"""
            Você é um Extrator de Texto LITERAL e Comparador Lógico.
            
            INPUT:
            TEXTO 1 (REFERÊNCIA): {t_anvisa[:60000]}
            TEXTO 2 (MKT): {t_mkt[:40000]}

            SUA MISSÃO:
            1. Extrair o conteúdo das seções listadas abaixo.
            2. **REGRA DE OURO (ANTI-ALUCINAÇÃO):** Copie o texto EXATAMENTE como ele aparece no arquivo. 
               - NÃO corrija português.
               - NÃO altere palavras (ex: não troque "fabricação" por "validade").
               - Se o texto original estiver errado, mantenha o erro na extração.
            3. Comparar o conteúdo extraído.

            LISTA DE SEÇÕES: {SECOES_PACIENTE}

            REGRAS DE STATUS:
            - "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS": 
                * Status SEMPRE "CONFORME".
                * Apenas transcreva o texto original limpo (sem quebras de linha malucas).
                * NÃO aponte divergências nestas seções.
                * Exceção: Em "DIZERES LEGAIS", envolva a data da Anvisa (se houver) em <span class="highlight-blue">DATA</span>.
            
            - OUTRAS SEÇÕES: 
                * Compare palavra por palavra.
                * Use <span class="highlight-yellow">TEXTO</span> para palavras divergentes.
                * Use <span class="highlight-red">TEXTO</span> para erros ortográficos graves.

            SAÍDA JSON OBRIGATÓRIA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_mkt": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto original extraído fielmente",
                        "texto_mkt": "Texto original extraído fielmente (com highlights se aplicável)",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            response = None
            ultimo_erro = ""

            # --- LÓGICA DE FAILOVER (TESTA CHAVE 1, DEPOIS CHAVE 2) ---
            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    
                    # request_options={'retry': None} força o erro rápido para trocar logo de chave
                    response = model.generate_content(prompt, request_options={'retry': None})
                    break # Se funcionou, sai do loop

                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        st.warning(f"⚠️ Chave {i+1} instável. Tentando Chave {i+2}...")
                        continue
                    else:
                        st.error(f"❌ Todas as chaves falharam. Erro final: {ultimo_erro}")
                        st.stop()

            # --- PROCESSAMENTO DO JSON ---
            if response:
                try:
                    resultado = json.loads(response.text)
                    
                    # Extrai dados globais
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_mkt = resultado.get("data_anvisa_mkt", "-")
                    dados_secoes = resultado.get("secoes", [])

                    # --- ÁREA DE MÉTRICAS ---
                    st.markdown("### 📊 Resumo da Conferência")
                    
                    c_d1, c_d2, c_d3 = st.columns(3)
                    c_d1.metric("Data Anvisa (Ref)", data_ref)
                    c_d2.metric("Data Anvisa (MKT)", data_mkt, delta="Vigência" if data_ref == data_mkt else "Diferente")
                    
                    total = len(dados_secoes)
                    divergentes = sum(1 for d in dados_secoes if d['status'] != 'CONFORME')
                    c_d3.metric("Seções Analisadas", total)

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
                    st.warning("Tente novamente.")
    else:
        st.warning("Por favor, envie os dois arquivos (PDF ou DOCX).")
