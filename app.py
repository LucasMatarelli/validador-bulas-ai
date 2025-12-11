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
import concurrent.futures
import time
import unicodedata
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    .stRadio > div[role="radiogroup"] > label {
        background-color: white; border: 1px solid #e1e4e8; padding: 12px 15px;
        border-radius: 8px; margin-bottom: 8px; transition: all 0.2s;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #f0fbf7; border-color: #55a68e; color: #55a68e; cursor: pointer;
    }

    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); box-shadow: 0 15px 30px rgba(0,0,0,0.1); border-color: #55a68e; }

    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    mark.diff { 
        background-color: #fff3cd; 
        color: #856404; 
        padding: 2px 4px; 
        border-radius: 3px; 
        font-weight: 500;
        border-bottom: 2px solid #ffc107;
    } 
    mark.ort { 
        background-color: #f8d7da; 
        color: #721c24; 
        padding: 2px 4px; 
        border-radius: 3px; 
        font-weight: 600;
        border-bottom: 2px solid #dc3545;
        text-decoration: underline wavy #dc3545;
    } 
    mark.anvisa { 
        background-color: #d1ecf1; 
        color: #0c5460; 
        padding: 3px 6px; 
        border-radius: 3px; 
        font-weight: bold;
        border: 1.5px solid #17a2b8;
        box-shadow: 0 1px 3px rgba(23, 162, 184, 0.2);
    }

    .stButton>button { 
        width: 100%; 
        background-color: #55a68e; 
        color: white; 
        font-weight: bold; 
        border-radius: 10px; 
        height: 55px; 
        border: none; 
        font-size: 16px; 
        box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); 
    }
    .stButton>button:hover { 
        background-color: #448c75; 
        box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); 
    }
    
    .texto-bula { 
        font-size: 1.05rem; 
        line-height: 1.7; 
        color: #333; 
    }

</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES",
    "COMPOSIÇÃO",
    "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "2. COMO ESTE MEDICAMENTO FUNCIONA?",
    "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "6. COMO DEVO USAR ESTE MEDICAMENTO?",
    "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
    "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES",
    "COMPOSIÇÃO",
    "1. INDICAÇÕES",
    "2. RESULTADOS DE EFICÁCIA",
    "3. CARACTERÍSTICAS FARMACOLÓGICAS",
    "4. CONTRAINDICAÇÕES",
    "5. ADVERTÊNCIAS E PRECAUÇÕES",
    "6. INTERAÇÕES MEDICAMENTOSAS",
    "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
    "8. POSOLOGIA E MODO DE USAR",
    "9. REAÇÕES ADVERSAS",
    "10. SUPERDOSE",
    "DIZERES LEGAIS"
]

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO"]

# ----------------- FUNÇÕES AUXILIARES -----------------

@st.cache_resource
def get_mistral_client():
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    return Mistral(api_key=api_key) if api_key else None
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):

    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)

    # REGRAS SUPER RÍGIDAS
    base_instruction = """
REGRAS ABSOLUTAS — VOCÊ É UM ROBÔ DE EXTRAÇÃO, NÃO UM REVISOR:

1. ❌ PROIBIDO reescrever, corrigir, melhorar ou ajustar textos.
2. ❌ PROIBIDO trocar palavras por sinônimos.
3. ❌ PROIBIDO corrigir frases, ortografia ou redação.
4. ❌ PROIBIDO mover textos entre seções.
5. ❌ PROIBIDO remover repetições. Se estiver repetido, mantenha repetido.
6. ❌ PROIBIDO criar textos ou completar com lógica.
7. ❌ PROIBIDO inferir nada.

VOCÊ DEVE COPIAR EXATAMENTE O TEXTO DO DOCUMENTO.

VOCÊ DEVE PARAR ASSIM QUE ENCONTRAR O PRÓXIMO TÍTULO DE SEÇÃO.

VOCÊ NÃO PODE COPIAR NEM UMA PALAVRA DA PRÓXIMA SEÇÃO.
"""

    # Lista de paradas
    barreiras = [s for s in todas_secoes if s != secao]
    barreiras.extend(["DIZERES LEGAIS", "Histórico de Alteração"])
    stop_markers_str = "\n".join([f"⛔ {s}" for s in barreiras])

    # SEÇÃO DE VISUALIZAÇÃO
    if eh_visualizacao:
        prompt_text = f"""
{base_instruction}

TAREFA:
Extrair a seção "{secao}" EXATAMENTE como aparece, sem alterar nada.

SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "texto literal",
  "bel": "texto literal",
  "status": "VISUALIZACAO"
}}
"""
    else:
        # SEÇÕES NORMAIS — COM STOP MARKERS
        prompt_text = f"""
{base_instruction}

TAREFA:
1. Localize exatamente o título: "{secao}".
2. Copie todo o texto que vem depois.
3. PARE imediatamente quando encontrar QUALQUER UM dos seguintes títulos:

{stop_markers_str}

4. NÃO copie o título da próxima seção.
5. NÃO mova informações entre seções.
6. NÃO melhore nem uma vírgula.
7. NÃO corrija nada.

SAÍDA JSON:
{{
  "titulo": "{secao}",
  "ref": "TEXTO EXATO DO DOC REFERÊNCIA",
  "bel": "TEXTO EXATO DO DOC BELFAR",
  "status": "A VALIDAR"
}}
"""

    # Montagem da mensagem ao modelo
    messages_content = [{"type": "text", "text": prompt_text}]

    limit = 60000
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d["type"] == "text":
            messages_content.append({
                "type": "text",
                "text": f"\n--- {nome} ---\n{d['data'][:limit]}"
            })
        else:
            messages_content.append({"type": "text", "text": f"\n--- {nome} (Imagem OCR) ---"})
            for img in d["data"][:2]:
                b64 = image_to_base64(img)
                messages_content.append({
                    "type": "image_url",
                    "image_url": f"data:image/jpeg;base64,{b64}"
                })

    # Execução com retry
    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest",
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"},
                temperature=0.0
            )

            dados = extract_json(chat_response.choices[0].message.content)
            if not dados:
                continue

            dados["titulo"] = secao

            # Comparação
            if not eh_visualizacao:
                ref_l = re.sub(r"<mark[^>]*>|</mark>", "", str(dados.get("ref", ""))).strip().lower()
                bel_l = re.sub(r"<mark[^>]*>|</mark>", "", str(dados.get("bel", ""))).strip().lower()

                if ref_l == bel_l:
                    dados["status"] = "CONFORME"
                else:
                    dados["status"] = "DIVERGENTE"

            return dados

        except:
            time.sleep(1)

    return {
        "titulo": secao,
        "ref": "Erro",
        "bel": "Erro",
        "status": "ERRO"
    }
# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    client = get_mistral_client()
    if client:
        st.success("✅ Sistema Online")
    else:
        st.error("❌ API não configurada")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()
    st.caption("v2.5 - Correção Final de Texto")


if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #55a68e; font-size: 3em;">Validador de Bulas</h1>
        <p style="font-size: 1.2em; color: #7f8c8d;">Auditoria Inteligente e Precisa</p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"## {pagina}")

    lista_secoes = SECOES_PACIENTE
    nome_doc1 = "REFERÊNCIA"
    nome_doc2 = "BELFAR"

    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Referência"
        label_box2 = "📄 BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL

    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 ANVISA"
        label_box2 = "📄 MKT"
        nome_doc1 = "ANVISA"
        nome_doc2 = "MKT"

    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"
        label_box2 = "📄 Gráfica"
        nome_doc1 = "ARTE VIGENTE"
        nome_doc2 = "GRÁFICA"

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"##### {label_box1}")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")

    with c2:
        st.markdown(f"##### {label_box2}")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")

    st.write("")
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2:
            st.warning("⚠️ Selecione ambos os arquivos.")
            st.stop()
        if not client:
            st.error("❌ API não configurada.")
            st.stop()

        with st.status("🔄 Processando...", expanded=True) as status:
            st.write("📖 Lendo arquivos...")

            b1 = f1.getvalue()
            b2 = f2.getvalue()
            d1 = process_file_content(b1, f1.name.lower())
            d2 = process_file_content(b2, f2.name.lower())

            if not d1 or not d2:
                st.error("❌ Erro ao processar arquivos.")
                st.stop()

            st.write("🔍 Analisando seções...")
            resultados = []
            progress = st.progress(0)

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_sec = {
                    executor.submit(auditar_secao_worker, client, sec, d1, d2, nome_doc1, nome_doc2, lista_secoes): sec
                    for sec in lista_secoes
                }

                done = 0
                total = len(lista_secoes)

                for future in concurrent.futures.as_completed(future_to_sec, timeout=200):
                    try:
                        data = future.result(timeout=120)
                        resultados.append(data)
                    except:
                        resultados.append({
                            "titulo": future_to_sec[future],
                            "ref": "Erro",
                            "bel": "Erro",
                            "status": "ERRO"
                        })

                    done += 1
                    progress.progress(done / total)
                    st.write(f"✓ {done}/{total} concluído")

            status.update(label="✅ Concluído!", state="complete", expanded=False)

        # Ordena
        resultados.sort(key=lambda x: lista_secoes.index(x["titulo"]) if x["titulo"] in lista_secoes else 999)

        # Métricas
        total = len(resultados)
        conformes = sum(1 for x in resultados if x["status"] == "CONFORME")
        divergentes = sum(1 for x in resultados if x["status"] == "DIVERGENTE")
        visuais = sum(1 for x in resultados if x["status"] == "VISUALIZACAO")
        erros = sum(1 for x in resultados if "ERRO" in x["status"])

        score = int(((conformes + visuais) / max(1, total)) * 100)

        # Painel
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Conformidade", f"{score}%", f"{conformes} seções")
        m2.metric("Divergências", divergentes)
        m3.metric("Total", total)
        m4.metric("Erros", erros)

        st.divider()

        for sec in resultados:
            titulo = sec["titulo"]
            status_s = sec["status"]

            icon = "🟢" if status_s == "CONFORME" else "🟡" if status_s == "DIVERGENTE" else "🔵" if status_s == "VISUALIZACAO" else "🔴"

            expandir = status_s != "CONFORME"

            with st.expander(f"{icon} {titulo} — {status_s}", expanded=expandir):
                colA, colB = st.columns(2)

                with colA:
                    st.markdown(f"### {nome_doc1}")
                    st.markdown(f"<div class='texto-bula'>{sec['ref']}</div>", unsafe_allow_html=True)

                with colB:
                    st.markdown(f"### {nome_doc2}")
                    st.markdown(f"<div class='texto-bula'>{sec['bel']}</div>", unsafe_allow_html=True)

        st.divider()

        if score >= 90:
            st.success("🎉 Alta conformidade.")
        elif score >= 70:
            st.warning("⚠️ Algumas divergências encontradas.")
        else:
            st.error("❌ Revisão crítica necessária.")
