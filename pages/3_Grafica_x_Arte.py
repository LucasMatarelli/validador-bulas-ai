import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import io
import json
import re

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

st.markdown("""
<style>
    /* --- ESCONDER MENU SUPERIOR --- */
    [data-testid="stHeader"] { visibility: hidden; }

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
        white-space: pre-wrap; 
        text-align: justify;
    }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }
    
    /* Highlight de Erros */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    
    /* Negrito */
    b { font-weight: bold; color: #000; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. SEUS MODELOS (COM FALLBACK DE SEGURANÇA) -----------------
MODELOS_POSSIVEIS = [
    "models/gemini-2.5-flash",        # Sua preferência
    "models/gemini-flash-latest",     # Sua preferência
    "models/gemini-1.5-flash-latest", # Backup rápido
    "models/gemini-1.5-pro-latest"    # Backup POTENTE (lento, mas não erra)
]

# ----------------- 3. CONFIGURAÇÃO DE SEGURANÇA (ABERTA) -----------------
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# ----------------- 4. FUNÇÕES AUXILIARES -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            has_digital_text = False
            for page in doc:
                text = page.get_text("text")
                if len(text.strip()) > 50: has_digital_text = True
                full_text += text + "\n"
            if has_digital_text: return [full_text]
            else:
                images = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            return ["\n".join([para.text for para in doc.paragraphs])]
    except: return []

def reparar_json_quebrado(texto_json):
    """
    Tenta consertar JSONs cortados ou mal formatados.
    """
    if not texto_json: return {"secoes": [], "erro_parse": True}

    # 1. Tenta carregar direto
    try:
        return json.loads(texto_json, strict=False)
    except:
        pass

    # 2. Limpeza cirúrgica
    texto_limpo = texto_json.strip()
    
    # Se não termina com chave/colchete fechando, tenta fechar na força bruta
    if not (texto_limpo.endswith("}") or texto_limpo.endswith("]")):
        # Verifica aspas abertas
        conta_aspas = texto_limpo.count('"') - texto_limpo.count('\\"')
        if conta_aspas % 2 != 0: texto_limpo += '"'
        
        # Tenta fechar estruturas comuns
        tentativas = ["}", "]}", "] }", "}]}", "\"}]}"]
        for t in tentativas:
            try:
                return json.loads(texto_limpo + t, strict=False)
            except: continue
    
    # 3. Tentativa desesperada de recuperar objetos válidos
    try:
        # Pega tudo que parece um objeto de seção
        objetos = re.findall(r'\{[^{}]*"titulo"[^{}]*\}', texto_limpo, re.DOTALL)
        if objetos:
            # Reconstrói um JSON válido com o que achou
            novo_json = '{"secoes": [' + ','.join(objetos) + ']}'
            return json.loads(novo_json, strict=False)
    except:
        pass

    return {"secoes": [], "erro_parse": True}

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        status_box = st.empty()
        status_box.info("Lendo arquivos...")

        f1.seek(0)
        f2.seek(0)
        
        conteudo1 = process_file_content(f1)
        conteudo2 = process_file_content(f2)
        
        prompt_base = """
        ATUE COMO UM VALIDADOR DE BULAS FARMACÊUTICAS.
        TAREFA: Extrair texto e comparar ARTE (Referência) vs GRÁFICA (Prova).
        
        REGRAS RÍGIDAS:
        1. Transcreva o texto COMPLETO de cada seção.
        2. Se houver negrito visual, use tags <b>...</b>.
        3. Ignore linhas pontilhadas ("...."), substitua por " ".
        4. Marque divergências na GRÁFICA com <span class='highlight-yellow'>...</span>.
        
        SAÍDA OBRIGATÓRIA (JSON PURO):
        {
            "data_anvisa_ref": "dd/mm/aaaa",
            "data_anvisa_grafica": "dd/mm/aaaa",
            "secoes": [
                {
                    "titulo": "NOME DA SEÇÃO",
                    "texto_arte": "Texto da arte...",
                    "texto_grafica": "Texto da gráfica...",
                    "status": "CONFORME"
                }
            ]
        }
        """
        
        payload = [prompt_base, "=== ARTE ==="] + conteudo1 + ["=== GRÁFICA ==="] + conteudo2
        
        final_result = None
        modelo_vencedor = ""
        historico_erros = []

        # --- LOOP INTELIGENTE DE MODELOS ---
        for api_key in keys_validas:
            genai.configure(api_key=api_key)
            
            for model_name in MODELOS_POSSIVEIS:
                try:
                    status_box.text(f"Tentando modelo: {model_name}...")
                    
                    model = genai.GenerativeModel(
                        model_name, 
                        safety_settings=SAFETY_SETTINGS,
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            "max_output_tokens": 8192 
                        }
                    )
                    
                    response = model.generate_content(payload)
                    
                    # 1. Verifica se bloqueou
                    if not response.candidates or not response.candidates[0].content.parts:
                        historico_erros.append(f"{model_name}: Bloqueio de segurança.")
                        continue 

                    # 2. Tenta extrair e limpar JSON
                    texto_raw = response.text.replace("```json", "").replace("```", "")
                    match = re.search(r'\{.*\}', texto_raw, re.DOTALL)
                    if match: texto_raw = match.group(0)

                    resultado_temp = reparar_json_quebrado(texto_raw)
                    secoes_temp = resultado_temp.get("secoes", [])

                    # 3. VERIFICAÇÃO CRÍTICA: Se achou 0 seções, o modelo falhou!
                    if not secoes_temp:
                        historico_erros.append(f"{model_name}: Retornou 0 seções (Conteúdo vazio).")
                        continue # Tenta o próximo modelo
                    
                    # Se chegou aqui, temos dados válidos!
                    final_result = resultado_temp
                    modelo_vencedor = model_name
                    break # Sai do loop de modelos

                except Exception as e:
                    historico_erros.append(f"{model_name}: Erro técnico ({str(e)})")
                    continue
            
            if final_result: break # Sai do loop de chaves

        status_box.empty()

        if final_result:
            try:
                data_ref = final_result.get("data_anvisa_ref", "---")
                data_graf = final_result.get("data_anvisa_grafica", "---")
                secoes = final_result.get("secoes", [])

                st.markdown(f"### 📊 Resultado (Gerado por: `{modelo_vencedor}`)")
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Ref", data_ref)
                k2.metric("Data Gráfica", data_graf)
                k3.metric("Seções", len(secoes))

                div_count = sum(1 for s in secoes if s.get('status') != 'CONFORME')
                
                # SÓ MOSTRA VERDE SE TIVER SEÇÕES E ZERO ERROS
                if len(secoes) > 0 and div_count == 0:
                    st.success("✅ **Tudo Conforme!**")
                elif len(secoes) == 0:
                     st.error("❌ **Nenhuma seção foi encontrada.** Verifique se o arquivo é legível.")
                else:
                    st.warning(f"⚠️ **{div_count} Divergências Encontradas**")
                
                if final_result.get("erro_parse"):
                    st.warning("⚠️ Nota: O texto foi longo demais para a IA, mas recuperamos o início.")

                st.divider()

                for item in secoes:
                    status = item.get('status', 'CONFORME')
                    css = "border-ok" if status == "CONFORME" else "border-warn"
                    icon = "✅" if status == "CONFORME" else "⚠️"
                    aberto = status != "CONFORME"

                    with st.expander(f"{icon} {item.get('titulo', 'Seção')}", expanded=aberto):
                        cA, cB = st.columns(2)
                        with cA:
                            st.caption("Arte")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                        with cB:
                            st.caption("Gráfica")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error("❌ Erro ao exibir resultados.")
                st.write(e)
        else:
             st.error("❌ Falha crítica: Nenhum modelo conseguiu ler o documento.")
             with st.expander("Ver detalhes dos erros (Debug)"):
                 for erro in historico_erros:
                     st.write(erro)

    else:
        st.warning("Adicione os arquivos.")
