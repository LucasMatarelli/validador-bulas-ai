import streamlit as st
import google.generativeai as genai
from google.api_core import retry
import fitz  # PyMuPDF
import json

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
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
        white-space: pre-wrap;
        text-align: justify;
    }
    .highlight-yellow { background-color: #fff9c4; color: #000; padding: 2px 4px; border-radius: 4px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 4px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 4px; border-radius: 4px; border: 1px solid #1976d2; font-weight: bold; }
    
    .border-ok { border-left: 6px solid #4caf50 !important; }
    .border-warn { border-left: 6px solid #ff9800 !important; }
    .border-info { border-left: 6px solid #2196f3 !important; }
    
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

# ----------------- 4. LISTAS DE SEÇÕES -----------------
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

tipo_bula = st.radio("Selecione o tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
lista_secoes_ativa = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

st.divider()

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arquivo Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📂 Arquivo BELFAR", type=["pdf"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada nos Secrets.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando Inteligência Artificial (Isso pode levar alguns segundos)..."):
            f1.seek(0)
            f2.seek(0)
            
            t_ref = extract_text_from_pdf(f1)
            t_belfar = extract_text_from_pdf(f2)

            if len(t_ref) < 50 or len(t_belfar) < 50:
                st.error("Erro: Arquivo vazio ou ilegível.")
                st.stop()

            # --- PROMPT ANTI-ALUCINAÇÃO ---
            # Aumentei o limite de caracteres para garantir que ele leia tudo
            prompt = f"""
            Você é um Auditor de Qualidade Farmacêutica Rígido, mas justo.
            
            INPUT TEXTO REFERÊNCIA:
            {t_ref} 
            
            INPUT TEXTO BELFAR:
            {t_belfar}

            SUA TAREFA:
            1. Para cada seção listada, extraia o texto correspondente.
            2. **REGRA DE OURO (ANTI-ALUCINAÇÃO):** O PDF original pode ter quebras de linha (`\\n`) em lugares diferentes do PDF novo. Isso NÃO é uma diferença.
               - Antes de comparar, remova mentalmente todas as quebras de linha e espaços extras.
               - Se a SEQUÊNCIA DE PALAVRAS for a mesma, o texto é **CONFORME**.
               - Só marque DIVERGENTE se houver palavras diferentes, números diferentes ou frases faltando.

            LISTA DE SEÇÕES: {lista_secoes_ativa}

            REGRAS DE FORMATAÇÃO DO OUTPUT:
            
            CASO 1: Seções "APRESENTAÇÕES", "COMPOSIÇÃO" e "DIZERES LEGAIS":
               - Status SEMPRE "CONFORME".
               - NÃO use highlight amarelo.
               - Apenas transcreva o texto limpo (parágrafos unidos).
               - Exceção: Destaque a Data da Anvisa em "DIZERES LEGAIS" com <span class="highlight-blue">DATA</span>.

            CASO 2: TODAS AS OUTRAS SEÇÕES:
               - Compare a sequência de palavras.
               - Se for IDÊNTICO (ignorando quebra de linha): Status "CONFORME", sem highlight.
               - Se for DIFERENTE: Status "DIVERGENTE". Use <span class="highlight-yellow">TRECHO NOVO/ALTERADO</span> apenas na parte que mudou.
               - Erros graves de PT: <span class="highlight-red">ERRO</span>.

            SAÍDA JSON OBRIGATÓRIA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_belfar": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_ref": "Texto completo da Referência (sem cortar o final)",
                        "texto_belfar": "Texto completo da Belfar",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    
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

            if response:
                try:
                    resultado = json.loads(response.text)
                    
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_belfar = resultado.get("data_anvisa_belfar", "-")
                    dados_secoes = resultado.get("secoes", [])

                    # Correção de Status via Python
                    divergentes_count = 0
                    for item in dados_secoes:
                        if 'highlight-yellow' in item.get('texto_belfar', '') or item.get('status') == 'DIVERGENTE':
                            item['status'] = 'DIVERGENTE'
                            divergentes_count += 1
                        else:
                            item['status'] = 'CONFORME'

                    st.markdown("### 📊 Resumo da Conferência")
                    
                    c_d1, c_d2, c_d3 = st.columns(3)
                    c_d1.metric("Data Ref.", data_ref)
                    c_d2.metric("Data BELFAR", data_belfar, delta="Igual" if data_ref == data_belfar else "Diferente")
                    
                    total = len(dados_secoes)
                    c_d3.metric("Seções Analisadas", total)

                    sub1, sub2 = st.columns(2)
                    sub1.info(f"✅ **Conformes:** {total - divergentes_count}")
                    if divergentes_count > 0:
                        sub2.warning(f"⚠️ **Divergentes:** {divergentes_count}")
                    else:
                        sub2.success("✨ **Divergências:** 0")

                    st.divider()

                    for item in dados_secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon = "⚖️"; css = "border-info"; aberto = True
                        elif status == "CONFORME":
                            icon = "✅"; css = "border-ok"; aberto = False
                        else:
                            icon = "⚠️"; css = "border-warn"; aberto = True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("📜 Referência")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_ref", "")}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("💊 BELFAR")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_belfar", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro ao ler resposta da IA: {e}")
    else:
        st.warning("Por favor, envie os dois arquivos PDF.")
