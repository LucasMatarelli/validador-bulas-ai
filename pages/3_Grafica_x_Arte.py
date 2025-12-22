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
    [data-testid="stHeader"] { visibility: hidden; }

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

    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    
    b { font-weight: bold; color: #000; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. MODELOS E CONFIGURAÇÃO -----------------
MODELOS_POSSIVEIS = [
    "models/gemini-2.5-flash",        # Tenta o mais novo primeiro
    "models/gemini-flash-latest",     # Seu preferido
    "models/gemini-1.5-flash-latest", # Fallback
    "models/gemini-1.5-pro-latest"    # Último recurso
]

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# A LISTA EXATA QUE VOCÊ PEDIU
SECOES_OBRIGATORIAS = [
    "APRESENTAÇÕES", 
    "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

# ----------------- 3. FUNÇÕES -----------------
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
    if not texto_json: return {"secoes": [], "erro_parse": True}
    try:
        return json.loads(texto_json, strict=False)
    except:
        texto_limpo = texto_json.strip()
        if not (texto_limpo.endswith("}") or texto_limpo.endswith("]")):
            conta_aspas = texto_limpo.count('"') - texto_limpo.count('\\"')
            if conta_aspas % 2 != 0: texto_limpo += '"'
            tentativas = ["}", "]}", "] }", "}]}", "\"}]}"]
            for t in tentativas:
                try: return json.loads(texto_limpo + t, strict=False)
                except: continue
        
        # Tentativa de recuperar objetos parciais (Regex para salvar o que deu pra ler)
        objetos = re.findall(r'\{[^{}]*"titulo"[^{}]*\}', texto_limpo, re.DOTALL)
        if objetos:
            novo_json = '{"secoes": [' + ','.join(objetos) + ']}'
            try: return json.loads(novo_json, strict=False)
            except: pass

    return {"secoes": [], "erro_parse": True}

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    
    # ADICIONADA A KEY 3 AQUI
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
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
        
        # --- PROMPT "ANTI-PREGUIÇA" ---
        prompt_base = f"""
        ATUE COMO UM AUDITOR FARMACÊUTICO RÍGIDO.
        
        Sua missão é extrair e comparar texto de DUAS fontes: ARTE (Referência) e GRÁFICA (Prova).
        
        VOCÊ É OBRIGADO A ITERAR SOBRE ESTA LISTA DE SEÇÕES, UMA POR UMA. NÃO PULE NENHUMA:
        {json.dumps(SECOES_OBRIGATORIAS, ensure_ascii=False)}

        REGRAS DE EXECUÇÃO:
        1. Para CADA item da lista acima, procure o texto correspondente nos documentos.
        2. Se encontrar o título (ex: "COMPOSIÇÃO"), copie TODO o texto abaixo dele até o próximo título.
        3. Se não encontrar uma seção específica, você DEVE retornar um objeto com status "NÃO ENCONTRADO".
        4. NÃO RESUMA. Copie ipsis litteris.
        5. Ignore linhas pontilhadas ("....").
        
        SAÍDA JSON OBRIGATÓRIA:
        {{
            "data_anvisa_ref": "dd/mm/aaaa",
            "data_anvisa_grafica": "dd/mm/aaaa",
            "secoes": [
                {{
                    "titulo": "NOME DA SEÇÃO DA LISTA",
                    "texto_arte": "Texto completo...",
                    "texto_grafica": "Texto completo...",
                    "status": "CONFORME" ou "DIVERGENTE" ou "NÃO ENCONTRADO"
                }}
            ]
        }}
        """
        
        payload = [prompt_base, "=== ARTE ==="] + conteudo1 + ["=== GRÁFICA ==="] + conteudo2
        
        final_result = None
        modelo_vencedor = ""
        erros_log = []

        for api_key in keys_validas:
            genai.configure(api_key=api_key)
            
            for model_name in MODELOS_POSSIVEIS:
                try:
                    status_box.text(f"Processando com: {model_name}...")
                    
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
                    
                    if not response.candidates or not response.candidates[0].content.parts:
                        erros_log.append(f"{model_name}: Bloqueio vazio.")
                        continue

                    texto_raw = response.text.replace("```json", "").replace("```", "")
                    match = re.search(r'\{.*\}', texto_raw, re.DOTALL)
                    if match: texto_raw = match.group(0)

                    resultado = reparar_json_quebrado(texto_raw)
                    secoes = resultado.get("secoes", [])

                    # TRAVA DE SEGURANÇA: Se retornou menos de 3 seções, o modelo foi preguiçoso. Tenta o próximo.
                    if len(secoes) < 3: 
                        erros_log.append(f"{model_name}: Retornou apenas {len(secoes)} seções (Incompleto).")
                        continue 
                    
                    final_result = resultado
                    modelo_vencedor = model_name
                    break 

                except Exception as e:
                    erros_log.append(f"{model_name}: Erro {str(e)}")
                    continue
            
            if final_result: break

        status_box.empty()

        if final_result:
            try:
                data_ref = final_result.get("data_anvisa_ref", "---")
                data_graf = final_result.get("data_anvisa_grafica", "---")
                secoes = final_result.get("secoes", [])

                st.markdown(f"### 📊 Resultado (Modelo: `{modelo_vencedor}`)")
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Ref", data_ref)
                k2.metric("Data Gráfica", data_graf)
                k3.metric("Seções Encontradas", len(secoes))

                # Contagem real de divergências
                div_count = sum(1 for s in secoes if s.get('status') not in ['CONFORME', 'NÃO ENCONTRADO'])
                
                if div_count == 0:
                    st.success("✅ **Tudo Conforme!**")
                else:
                    st.warning(f"⚠️ **{div_count} Divergências Encontradas**")
                
                st.divider()

                for item in secoes:
                    status = item.get('status', 'CONFORME')
                    
                    if status == "CONFORME":
                        css, icon, aberto = "border-ok", "✅", False
                    elif status == "NÃO ENCONTRADO":
                        css, icon, aberto = "border-info", "❓", True
                    else:
                        css, icon, aberto = "border-warn", "⚠️", True

                    with st.expander(f"{icon} {item.get('titulo', 'Seção')}", expanded=aberto):
                        if status == "NÃO ENCONTRADO":
                            st.info("Esta seção não foi identificada no documento.")
                        else:
                            cA, cB = st.columns(2)
                            with cA:
                                st.caption("Arte")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with cB:
                                st.caption("Gráfica")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error("❌ Erro ao exibir os dados.")
                st.write(e)
        else:
             st.error("❌ Falha crítica: Os modelos não conseguiram ler todas as seções.")
             with st.expander("Ver log de erros"):
                 for erro in erros_log:
                     st.write(erro)

    else:
        st.warning("Adicione os arquivos.")
