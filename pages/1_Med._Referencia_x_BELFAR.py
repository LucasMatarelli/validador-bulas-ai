import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import time

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

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

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. FUNÇÕES DE EXTRAÇÃO E DIFF -----------------

def extract_text_from_file(uploaded_file):
    """Lê o PDF de forma bruta apenas para o Gemini entender o contexto."""
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                text += page.get_text("text") + "\n\n"
        
        # Limpeza cirúrgica
        text = re.sub(r'(\w)-\s+(\w)', r'\1-\2', text)
        text = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', text)
        text = re.sub(r'(?i)\b\d*\s*VP\d+\s*=\s*[a-zA-Z0-9_]+\s*\d*', '', text)
        text = re.sub(r'(?i)\b[a-zA-Z0-9_]+_bula_(?:paciente|profissional)\s*\d*', '', text)
        return text
    except: 
        return ""

def achar_frases_divergentes(texto_ref, texto_novo):
    """
    Compara os textos e retorna UMA LISTA com as frases exatas 
    que foram adicionadas ou modificadas na bula da BELFAR.
    """
    def limpar_espacos(t):
        t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
        t = re.sub(r'[ \t]+', ' ', t) 
        return t
        
    texto_ref = limpar_espacos(texto_ref)
    texto_novo = limpar_espacos(texto_novo)

    tokens_ref = [t for t in re.split(r'(\s+)', texto_ref) if t]
    tokens_novo = [t for t in re.split(r'(\s+)', texto_novo) if t]

    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_novo, autojunk=False)
    matcher.set_seqs(tokens_ref, tokens_novo)
    
    frases_com_erro = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ['replace', 'insert']:
            # Pega o bloco de palavras divergentes e junta numa frase só
            frase = "".join(tokens_novo[j1:j2]).strip()
            # Se tiver mais que 3 letras (evita pintar vírgulas sozinhas)
            if len(frase) > 3:
                frases_com_erro.append(frase)
                
    return frases_com_erro

# ----------------- 4. A MÁGICA: PDF PARA IMAGEM GRIFADA -----------------

def gerar_imagens_pdf_grifado(uploaded_file, frases_para_grifar):
    """Abre o PDF, pinta as divergências de amarelo e tira as fotos."""
    # Abre o PDF na memória
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens_geradas = []

    for page in doc:
        # 1. O Radar: Para cada frase com erro, procura na página
        for frase in frases_para_grifar:
            # O fitz procura a frase exata e retorna as coordenadas
            areas = page.search_for(frase)
            
            # 2. O Pincel: Desenha o marca-texto amarelo
            for area in areas:
                anotacao = page.add_highlight_annot(area)
                anotacao.update() # Salva a pintura na memória

        # 3. A Câmera: Tira um print em alta resolução (Matrix 2,2 dá zoom 2x)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        imagem_bytes = pix.tobytes("png")
        imagens_geradas.append(imagem_bytes)
        
    return imagens_geradas

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Auditor Visual de Bulas (Referência x BELFAR)")

tipo_bula = st.radio(
    "Escolha o Tipo de Bula:",
    ("Paciente", "Profissional"),
    horizontal=True
)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"], key="f2")

if st.button("🚀 Processar Auditoria Visual"):
    
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo arquivos e realizando auditoria invisível..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível."); st.stop()

            # O prompt manda a IA extrair os textos brutos
            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.
            INPUT TEXTO 1 (REF): {t_anvisa[:150000]}
            INPUT TEXTO 2 (MKT): {t_mkt[:150000]}
            
            Extraia TODO o conteúdo de cada seção. NÃO RESUMA NENHUMA FRASE.
            LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "...",
                        "texto_mkt": "..."
                    }}
                ]
            }}
            """
            
            response = None
            sucesso = False
            log_erros = []

            for idx_key, key in enumerate(keys_validas):
                if sucesso: break
                genai.configure(api_key=key)
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model_instance = genai.GenerativeModel(
                            modelo, 
                            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                        )
                        response = model_instance.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {str(e)}")
                        time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total da IA.")
                st.stop()
            
            try:
                texto_resposta = response.text.replace("```json", "").replace("
```", "").strip()
                resultado = json.loads(texto_resposta)
                dados_secoes = resultado.get("secoes", [])
                
                todas_frases_para_grifar = []

                # Compara as seções e coleta as frases que devem ser pintadas
                for item in dados_secoes:
                    titulo = item.get('titulo', '').strip().upper()
                    txt_ref = item.get('texto_anvisa', '').strip()
                    txt_mkt = item.get('texto_mkt', '').strip()
                    
                    eh_blindada = any(b in titulo for b in SECOES_SEM_COMPARACAO)

                    if not eh_blindada:
                        # Descobre quais frases estão com erro na Bula Belfar
                        frases_divergentes = achar_frases_divergentes(txt_ref, txt_mkt)
                        todas_frases_para_grifar.extend(frases_divergentes)

        with st.spinner("Pintando o PDF da BELFAR e gerando imagens..."):
            # Reseta o ponteiro do arquivo PDF para ler do começo
            f2.seek(0)
            
            # Chama a Mágica! Passa o PDF e as frases que devem ficar amarelas
            fotos_da_bula = gerar_imagens_pdf_grifado(f2, todas_frases_para_grifar)

            st.success("✅ Auditoria Concluída! Veja o resultado grifado abaixo:")
            st.divider()

            # Mostra as imagens geradas na tela do usuário
            for i, imagem_bytes in enumerate(fotos_da_bula):
                st.markdown(f"### Página {i+1}")
                st.image(imagem_bytes, use_container_width=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}")
                st.code(response.text)
    else:
        st.warning("Adicione os arquivos PDF.")
