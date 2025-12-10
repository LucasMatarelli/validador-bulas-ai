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

# --- FUNÇÕES ---

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
    # Normaliza Unicode e remove espaços invisíveis
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u0000', '').replace('\u200b', '')
    # Transforma múltiplos espaços em um só
    return re.sub(r'\s+', ' ', text).strip()

def remove_numbering(text):
    if not text: return ""
    # Remove "5.", "5 ", "9." do início
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
            
            # OCR se for imagem
            images = []
            limit_pages = min(5, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except: return None
    return None

# --- CORREÇÃO DE JSON (Salva vidas quando a IA corta o texto) ---
def extract_json(text):
    # Limpa markdown
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```', '', text).strip()
    
    try:
        # Tenta extrair o JSON puro
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            clean_text = text[start:end+1]
            return json.loads(clean_text)
        return json.loads(text)
    except json.JSONDecodeError:
        # Se falhar, tenta "consertar" o JSON cortado fechando as aspas e chaves
        # Isso é um fallback básico
        try:
            return json.loads(text + '"}') 
        except:
            return None

# --- WORKER AJUSTADO (Prompt Anti-Erro) ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, proxima_secao, modo_arte=False):
    
    eh_dizeres = "DIZERES LEGAIS" in secao.upper()
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    limite_instrucao = ""
    if proxima_secao:
        limite_instrucao = f"O texto desta seção TERMINA antes do título '{proxima_secao}'. NÃO leia além disso."
    else:
        limite_instrucao = "Leia até o fim do documento."

    prompt_text = ""
    
    if eh_dizeres:
        prompt_text = f"""
        Atue como Auditor. Extraia "DIZERES LEGAIS".
        ONDE: Rodapé (CNPJ, Farm. Resp). Se começar com "Como usar", está errado.
        REGRAS: 
        1. Copie o texto. 
        2. Destaque datas (DD/MM/AAAA) com <mark class='anvisa'>DATA</mark>.
        3. NÃO use amarelo.
        JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    elif eh_visualizacao:
        prompt_text = f"""
        Atue como Formatador. Transcreva "{secao}".
        REGRAS: Apenas texto puro. Sem marcações.
        JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    else:
        # PROMPT DE COMPARAÇÃO CORRIGIDO (FIM DOS FALSOS POSITIVOS)
        prompt_text = f"""
        Atue como Auditor Rigoroso. Compare "{secao}" entre Doc 1 e Doc 2.
        
        LIMITES: O texto começa após o título "{secao}". {limite_instrucao}
        
        REGRAS CRÍTICAS DE COMPARAÇÃO (LEIA COM ATENÇÃO):
        1. IGNORE pontuação grudada ("Candida" == "Candida:" == "Candida)").
        2. IGNORE espaços ("150mg" == "150 mg").
        3. SE A PALAVRA FOR VISUALMENTE IGUAL, NÃO MARQUE.
        
        COMO USAR O AMARELO (<mark class='diff'>):
        - Use APENAS se houver uma palavra errada, trocada ou faltando.
        - Exemplo: "paranoide" vs "paranóide" -> MARQUE (acento conta).
        - Exemplo: "tomar" vs "comer" -> MARQUE.
        
        JSON OBRIGATÓRIO: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "CONFORME ou DIVERGENTE" }}
        """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Limita tamanho para evitar estouro de memória e Erro JSON
    limit = 40000 
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGEM {nome} ---"})
            for img in d['data'][:2]: # Envia max 2 imagens
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"}
            )
            dados = extract_json(chat_response.choices[0].message.content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                dados['ref'] = remove_numbering(dados.get('ref', ''))
                dados['bel'] = remove_numbering(dados.get('bel', ''))

                # Auto-Correção de Status
                if not eh_visualizacao and not eh_dizeres:
                    txt = (str(dados.get('bel', '')) + str(dados.get('ref', ''))).lower()
                    tem_marca = 'class="diff"' in txt or "class='diff'" in txt or "class='ort'" in txt
                    if not tem_marca:
                        dados['status'] = 'CONFORME'
                
                if eh_dizeres: dados['status'] = 'VISUALIZACAO'
                return dados
                
        except Exception:
            time.sleep(1)
            continue
    
    # Fallback se der erro no JSON (Devolve texto puro para você ler)
    return {
        "titulo": secao,
        "ref": d1['data'][:2000] + "..." if d1['type']=='text' else "Texto imagem...",
        "bel": d2['data'][:2000] + "..." if d2['type']=='text' else "Texto imagem...",
        "status": "ERRO LEITURA (Texto Bruto)"
    }
