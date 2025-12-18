import streamlit as st
import google.generativeai as genai
from google.api_core import retry # Importante para controlar o tempo de resposta
import fitz  # PyMuPDF
import json

# ----------------- 1. VISUAL & CSS (Design Limpo) -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

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
f1 = c1.file_uploader("📂 Arquivo Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📂 Arquivo BELFAR", type=["pdf"], key="f2")

if st.button("🚀 Processar Conferência"):
    # 1. PREPARAÇÃO DAS CHAVES
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada nos Secrets.")
        st.stop()

    if f1 and f2:
        with st.spinner("Lendo arquivos, estruturando seções e comparando..."):
            f1.seek(0)
            f2.seek(0)
            
            t_ref = extract_text_from_pdf(f1)
            t_belfar = extract_text_from_pdf(f2)

            if len(t_ref) < 50 or len(t_belfar) < 50:
                st.error("Erro: Arquivo vazio ou ilegível (imagem sem OCR).")
                st.stop()

            # PROMPT EXTREMAMENTE ESPECÍFICO PARA ORGANIZAÇÃO E CORREÇÃO
            prompt = f"""
            Você é um Auditor de Qualidade Farmacêutica Especialista em Bulas.
            
            CONTEXTO:
            Você receberá dois textos extraídos de PDF (Referência e BELFAR). O texto cru contém quebras de linha aleatórias que deixam o conteúdo bagunçado.
            
            INPUT:
            --- TEXTO REFERÊNCIA ---
            {t_ref[:50000]}
            ------------------------
            --- TEXTO BELFAR ---
            {t_belfar[:30000]}
            --------------------

            SUA TAREFA:
            1. Para CADA seção da lista abaixo, localize o texto correspondente nos dois arquivos.
            2. **LIMPEZA OBRIGATÓRIA:** O texto extraído do PDF vem quebrado (ex: "comprim-\nido"). Você DEVE juntar as linhas para formar frases fluídas e parágrafos corretos. Não devolva texto quebrado.
            3. Compare o conteúdo da BELFAR com a REFERÊNCIA.
            4. Se uma seção não existir no texto, preencha como "Não encontrado". Não invente texto.

            LISTA DE SEÇÕES ALVO ({tipo_bula}): 
            {lista_secoes_ativa}

            REGRAS DE FORMATAÇÃO (HTML):
            - Use <span class="highlight-yellow">TEXTO</span> para destacar trechos divergentes/diferentes no texto da BELFAR.
            - Use <span class="highlight-red">TEXTO</span> para erros ortográficos graves.
            - Na seção DIZERES LEGAIS, envolva a data da ANVISA (se houver) com <span class="highlight-blue">DATA</span>.
            - Se o texto for igual, mantenha sem highlight.

            SAÍDA JSON (ESTRITA):
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_belfar": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO DA LISTA",
                        "texto_ref": "Texto limpo, organizado e sem quebras de linha erradas.",
                        "texto_belfar": "Texto limpo com os highlights de diferença aplicados.",
                        "status": "CONFORME" (se o sentido for igual) ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            response = None
            ultimo_erro = ""

            # Loop Failover (Tenta Key 1 -> Se der erro -> Tenta Key 2 imediatamente)
            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    
                    # request_options={'retry': None} impede que o código fique "dormindo" esperando o erro passar.
                    # Ele força o erro a acontecer na hora para pularmos para a próxima chave.
                    response = model.generate_content(prompt, request_options={'retry': None})
                    break 

                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        st.warning(f"⚠️ Chave {i+1} instável. Trocando para Chave {i+2}...")
                        continue
                    else:
                        st.error(f"❌ Todas as chaves falharam. Erro: {ultimo_erro}")
                        st.stop()

            # --- PROCESSAMENTO DO RESULTADO ---
            if response:
                try:
                    resultado = json.loads(response.text)
                    
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_belfar = resultado.get("data_anvisa_belfar", "-")
                    dados_secoes = resultado.get("secoes", [])

                    # --- EXIBIÇÃO ---
                    st.markdown("### 📊 Resumo da Conferência")
                    
                    c_d1, c_d2, c_d3 = st.columns(3)
                    c_d1.metric("Data Ref.", data_ref)
                    c_d2.metric("Data BELFAR", data_belfar, delta="Igual" if data_ref == data_belfar else "Diferente")
                    
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

                    for item in dados_secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        
                        # Ícones e cores
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon = "⚖️"; css = "border-info"; aberto = True
                        elif status == "CONFORME":
                            icon = "✅"; css = "border-ok"; aberto = False
                        else:
                            icon = "⚠️"; css = "border-warn"; aberto = True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("📜 Referência (Organizado)")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_ref", "")}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("💊 BELFAR (Validado)")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_belfar", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro ao ler resposta da IA: {e}")
    else:
        st.warning("Por favor, envie os dois arquivos PDF.")
