import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import utils  # <--- IMPORTANTE: O arquivo que controla as 2 chaves e o contador

# ----------------- 1. VISUAL & CSS (Design Limpo) -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

# Chama o contador na barra lateral (Universal para todas as páginas)
utils.mostrar_sidebar_contador()

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

# ----------------- 2. CONFIGURAÇÃO MODELO (INTEGRADO AO UTILS) -----------------
# Agora usamos o utils para decidir qual chave usar (1 ou 2) baseado no contador
def setup_model():
    # Essa função do utils já checa o contador:
    # Se uso < 20: Pega Key 1
    # Se uso >= 20: Pega Key 2
    # Se uso >= 40: Retorna None (Bloqueado)
    return utils.configurar_modelo_inteligente()

# ----------------- 3. EXTRAÇÃO DE TEXTO -----------------
def extract_text_from_pdf(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        return text
    except: return ""

# ----------------- 4. DEFINIÇÃO DAS LISTAS DE SEÇÕES -----------------
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

# ----------------- 5. INTERFACE PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

# Seletor de Tipo de Bula
tipo_bula = st.radio("Selecione o tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)

# Define qual lista usar baseada na escolha
lista_secoes_ativa = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

st.divider()

c1, c2 = st.columns(2)
# Uploaders renomeados conforme pedido
f1 = c1.file_uploader("📂 Arquivo Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📂 Arquivo BELFAR", type=["pdf"], key="f2")

if st.button("🚀 Processar Conferência"):
    if f1 and f2:
        # Configura o modelo usando a lógica inteligente de chaves
        model = setup_model()
        
        if not model:
            st.error("⛔ Limite diário de 40 créditos atingido! O sistema voltará amanhã.")
            st.stop()

        with st.spinner("Lendo arquivos, corrigindo formatação e organizando seções..."):
            # Importante: resetar o ponteiro do arquivo antes de ler caso tenha sido lido antes
            f1.seek(0)
            f2.seek(0)
            
            t_ref = extract_text_from_pdf(f1)
            t_belfar = extract_text_from_pdf(f2)

            if len(t_ref) < 50 or len(t_belfar) < 50:
                st.error("Erro: Arquivo vazio ou ilegível (imagem sem OCR).")
                st.stop()

            # PROMPT AVANÇADO: SEPARAÇÃO DE DADOS E FORMATAÇÃO
            prompt = f"""
            Você é um Revisor Farmacêutico Meticuloso da Indústria Farmacêutica.
            
            INPUT:
            TEXTO 1 (REFERÊNCIA): {t_ref[:50000]}
            TEXTO 2 (BELFAR): {t_belfar[:30000]}

            SUA MISSÃO:
            1. Encontre a "Data de Aprovação da Anvisa" nos Dizeres Legais de AMBOS os textos.
            2. Mapeie o conteúdo do TEXTO 2 (BELFAR) nas seções da lista abaixo.
            3. Compare com o TEXTO 1 (REFERÊNCIA).
            4. **CRÍTICO: CORRIJA A FORMATAÇÃO.** O texto extraído do PDF pode ter quebras de linha erradas. Junte as frases para formarem parágrafos normais.

            LISTA DE SEÇÕES ({tipo_bula}): {lista_secoes_ativa}

            REGRAS DE STATUS:
            - "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS": Sempre "CONFORME". Apenas transcreva o texto (Sem highlights de erro).
            - OUTRAS SEÇÕES: Compare rigorosamente. Use <span class="highlight-yellow">TEXTO</span> para divergências de conteúdo e <span class="highlight-red">TEXTO</span> para erros graves de português.
            - DIZERES LEGAIS: Destaque a data da Anvisa (se houver no texto) com <span class="highlight-blue">DATA</span>.

            SAÍDA JSON OBRIGATÓRIA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_belfar": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_ref": "Texto formatado da Referência",
                        "texto_belfar": "Texto formatado da BELFAR com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                response = model.generate_content(prompt)
                resultado = json.loads(response.text)
                
                # --- SUCESSO: INCREMENTA O CONTADOR NO UTILS ---
                utils.gerenciar_uso_diario(incrementar=True)
                
                # Extrai dados globais
                data_ref = resultado.get("data_anvisa_ref", "-")
                data_belfar = resultado.get("data_anvisa_belfar", "-")
                dados_secoes = resultado.get("secoes", [])

                # --- ÁREA DE MÉTRICAS ---
                st.markdown("### 📊 Resumo da Conferência")
                
                # Linha 1: Datas
                c_d1, c_d2, c_d3 = st.columns(3)
                c_d1.metric("Data Ref.", data_ref)
                c_d2.metric("Data BELFAR", data_belfar, delta="Igual" if data_ref == data_belfar else "Diferente")
                
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
                            st.caption("📜 Referência")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_ref", "")}</div>', unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("💊 BELFAR")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_belfar", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar o retorno: {e}")
                st.warning("Tente novamente, o modelo pode ter falhado na formatação do JSON.")
    else:
        st.warning("Por favor, envie os dois arquivos PDF (Referência e BELFAR).")
