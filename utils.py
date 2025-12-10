import streamlit as st
from mistralai import Mistral
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import base64
import unicodedata
import time
from PIL import Image

# --- CONSTANTES ---
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

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO"]

# --- FUNÇÕES DE CONEXÃO E LEITURA ---

def get_mistral_client():
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    return Mistral(api_key=api_key) if api_key else None

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    # Remove espaços invisíveis e normaliza para espaço simples
    text = text.replace('\xa0', ' ').replace('\u0000', '').replace('\u200b', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def remove_numbering(text):
    if not text: return ""
    # Remove "5. ", "5 ", "9. " do início
    return re.sub(r'^\s*\d+[\.\)]\s*', '', text)

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: full_text += page.get_text() + " "
            
            if len(full_text.strip()) > 100:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            images = []
            limit_pages = min(5, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except: return None
    return None

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    if text.startswith("json"): text = text[4:]
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

# --- WORKER DE AUDITORIA (CÉREBRO CENTRAL) ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, proxima_secao, modo_arte=False):
    
    eh_dizeres = "DIZERES LEGAIS" in secao.upper()
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Limites
    limite_instrucao = ""
    if proxima_secao:
        limite_instrucao = f"O texto desta seção TERMINA imediatamente antes do título '{proxima_secao}'. PARE A LEITURA ALI."
    else:
        limite_instrucao = "Este é o último tópico. Leia até o fim do conteúdo relevante."

    prompt_text = ""
    
    if eh_dizeres:
        prompt_text = f"""
        Atue como Auditor de Bulas.
        TAREFA: Extrair "DIZERES LEGAIS".
        
        ONDE PROCURAR: Rodapé (CNPJ, Farm. Resp, SAC, M.S.).
        ATENÇÃO: Se o texto começar com "Como devo usar", VOCÊ PEGOU A SEÇÃO ERRADA.
        
        REGRAS:
        1. Copie o texto fielmente.
        2. Destaque a data (DD/MM/AAAA) com <mark class='anvisa'>DATA</mark> NOS DOIS TEXTOS.
        3. NÃO use tag amarela.
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    elif eh_visualizacao:
        arte_extra = "- Ignore informações técnicas de gráfica (cores, dimensões, gramatura)." if modo_arte else ""
        prompt_text = f"""
        Atue como Formatador.
        TAREFA: Transcrever "{secao}".
        {limite_instrucao}
        REGRAS: 
        1. Apenas transcreva o texto. Sem marcações.
        2. {arte_extra}
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    else:
        # LÓGICA DE COMPARAÇÃO (TEXTO A MAIS/DIFERENTE)
        prompt_text = f"""
        Atue como Auditor de Texto Rigoroso.
        TAREFA: Comparar "{secao}" entre Doc 1 e Doc 2.
        
        DELIMITAÇÃO: O texto começa após o título "{secao}". {limite_instrucao}
        
        REGRAS DE COMPARAÇÃO (CRÍTICO):
        1. IGNORE: Espaços extras, pontuação colada ("palavra:" = "palavra").
        2. IGNORE: Numeração no início do parágrafo (ex: "5. Onde...").
        
        3. REGRA DO MARCA-TEXTO AMARELO (<mark class='diff'>):
           - Se o Doc 2 tem um trecho que NÃO existe no Doc 1 -> MARQUE ESSE TRECHO NO DOC 2.
           - Se o Doc 1 tem um trecho que SUMIU no Doc 2 -> MARQUE ESSE TRECHO NO DOC 1.
           - Se a palavra mudou -> MARQUE EM AMBOS.
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "CONFORME ou DIVERGENTE" }}
        """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    limit = 60000 
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGEM {nome} ---"})
            for img in d['data'][:2]:
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"}
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                dados['ref'] = remove_numbering(dados.get('ref', ''))
                dados['bel'] = remove_numbering(dados.get('bel', ''))

                if not eh_visualizacao and not eh_dizeres:
                    texto_completo = (str(dados.get('bel', '')) + str(dados.get('ref', ''))).lower()
                    tem_diff = 'class="diff"' in texto_completo or "class='diff'" in texto_completo
                    tem_ort = 'class="ort"' in texto_completo or "class='ort'" in texto_completo
                    if not tem_diff and not tem_ort:
                        dados['status'] = 'CONFORME'
                
                if eh_dizeres: dados['status'] = 'VISUALIZACAO'
                return dados
                
        except Exception:
            time.sleep(1)
            continue
    
    return {
        "titulo": secao,
        "ref": d1['data'][:3000] + "...",
        "bel": d2['data'][:3000] + "...",
        "status": "ERRO LEITURA"
    }
