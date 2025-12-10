import streamlit as st
import concurrent.futures
import sys
import os

# Caminho para importar utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import (
    process_file_content, auditar_secao_worker, get_mistral_client,
    SECOES_PACIENTE, SECOES_PROFISSIONAL
)

st.set_page_config(page_title="Ref x Belfar", page_icon="💊", layout="wide")

st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; } 
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; } 
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
    .texto-bula { font-size: 1.15rem !important; line-height: 1.6; color: #333; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 12px; height: 60px; border: none; }
</style>
""", unsafe_allow_html=True)

st.markdown("## 💊 Referência x BELFAR")

tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
lista_secoes = SECOES_PROFISSIONAL if tipo_bula == "Profissional" else SECOES_PACIENTE

c1, c2 = st.columns(2)
with c1:
    st.markdown("##### 📄 Arquivo Referência")
    # CORREÇÃO AQUI: Label obrigatório, mas escondido
    f1 = st.file_uploader("Arquivo Referência", type=["pdf", "docx"], key="f1", label_visibility="collapsed")
with c2:
    st.markdown("##### 📄 Arquivo BELFAR")
    # CORREÇÃO AQUI: Label obrigatório, mas escondido
    f2 = st.file_uploader("Arquivo Belfar", type=["pdf", "docx"], key="f2", label_visibility="collapsed")

if st.button("INICIAR AUDITORIA"):
    client = get_mistral_client()
    if not client or not f1 or not f2:
        st.warning("Verifique a conexão e os arquivos.")
        st.stop()

    with st.spinner("🚀 Lendo arquivos..."):
        d1 = process_file_content(f1.getvalue(), f1.name.lower())
        d2 = process_file_content(f2.getvalue(), f2.name.lower())
    
    if not d1 or not d2:
        st.error("Erro na leitura.")
        st.stop()

    resultados = []
    progress = st.progress(0)
    status = st.empty()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_secao = {}
        for i, secao in enumerate(lista_secoes):
            proxima = lista_secoes[i+1] if i + 1 < len(lista_secoes) else None
            future = executor.submit(auditar_secao_worker, client, secao, d1, d2, "REFERÊNCIA", "BELFAR", proxima, modo_arte=False)
            future_to_secao[future] = secao
        
        completed = 0
        for future in concurrent.futures.as_completed(future_to_secao):
            try:
                data = future.result()
                if data: resultados.append(data)
            except: pass
            completed += 1
            progress.progress(completed / len(lista_secoes))
            status.text(f"Analisando: {completed}/{len(lista_secoes)}")

    status.empty()
    progress.empty()
    resultados.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)

    total = len(resultados)
    conformes = sum(1 for x in resultados if "CONFORME" in x.get('status', ''))
    visuais = sum(1 for x in resultados if "VISUALIZACAO" in x.get('status', ''))
    score = int(((conformes + visuais) / total) * 100) if total > 0 else 0
    
    m1, m2 = st.columns(2)
    m1.metric("Conformidade", f"{score}%")
    m2.metric("Seções Analisadas", total)
    st.divider()

    for sec in resultados:
        stt = sec.get('status', 'N/A')
        icon = "✅"
        if "DIVERGENTE" in stt: icon = "❌"
        elif "ERRO" in stt: icon = "⚠️"
        elif "VISUALIZACAO" in stt: icon = "👁️"
        
        with st.expander(f"{icon} {sec['titulo']} — {stt}"):
            cA, cB = st.columns(2)
            with cA:
                st.markdown("**REFERÊNCIA**")
                st.markdown(f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-radius:5px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
            with cB:
                st.markdown("**BELFAR**")
                st.markdown(f"<div class='texto-bula' style='background:#fff; border:1px solid #eee; padding:15px; border-radius:5px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
