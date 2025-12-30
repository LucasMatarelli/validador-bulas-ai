import streamlit as st
import json
import utils  # Importa nossas ferramentas centralizadas

st.set_page_config(page_title="Ref x Belfar", page_icon="💊", layout="wide")
utils.mostrar_sidebar_contador()

st.title("💊 Medicamento Referência x BELFAR")
st.markdown("---")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf", "docx"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"])

if st.button("🚀 Processar Conferência", type="primary"):
    if f1 and f2:
        with st.spinner("Lendo arquivos e analisando..."):
            f1.seek(0); f2.seek(0)
            cont_ref = utils.processar_arquivo(f1)
            cont_belfar = utils.processar_arquivo(f2)
            
            prompt = f"""
            Você é um Auditor Farmacêutico. Compare os dois textos abaixo.
            LISTA DE SEÇÕES ESPERADAS: {utils.SECOES_PADRAO}
            
            SAÍDA JSON OBRIGATÓRIA:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto Ref...",
                        "texto_mkt": "Texto Belfar...",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            # Envia para a IA
            res_text = utils.chamar_gemini(prompt, ["--- REF ---"] + cont_ref + ["--- BELFAR ---"] + cont_belfar)
            
            # Processa Resposta
            try:
                data = json.loads(utils.repair_json(res_text))
                
                # Exibição (Simplificada para brevidade, adicione seus estilos aqui se quiser)
                st.success("Análise concluída!")
                st.json(data) # Exibe o JSON bonito ou use sua lógica de HTML antiga
                
            except Exception as e:
                st.error("Erro ao processar resposta da IA")
                st.code(res_text)
    else:
        st.warning("Faça upload dos arquivos.")
