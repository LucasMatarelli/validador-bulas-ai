import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update
import dash_bootstrap_components as dbc
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import io
import base64
import json
import re
from PIL import Image

# ----------------- CONFIGURAÇÃO -----------------
FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw"

# Inicializa o App com tema Bootstrap MINTY (Visual Limpo)
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.MINTY, "https://use.fontawesome.com/releases/v6.4.0/css/all.css"],
    title="Validador Belfar",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ----------------- CSS PERSONALIZADO (VISUAL + MARCAÇÕES) -----------------
GLOBAL_STYLES = {
    # Marcações no Texto
    'mark-diff': {'backgroundColor': '#fff3cd', 'color': '#856404', 'padding': '2px 4px', 'borderRadius': '4px', 'border': '1px solid #ffeeba'}, # Amarelo
    'mark-ort': {'backgroundColor': '#f8d7da', 'color': '#721c24', 'padding': '2px 4px', 'borderRadius': '4px', 'borderBottom': '2px solid #dc3545'}, # Vermelho
    'mark-anvisa': {'backgroundColor': '#cff4fc', 'color': '#055160', 'padding': '2px 4px', 'borderRadius': '4px', 'border': '1px solid #b6effb', 'fontWeight': 'bold'}, # Azul
    
    # Layout
    'upload-box': {
        'width': '100%', 'height': '120px', 'lineHeight': '30px',
        'borderWidth': '2px', 'borderStyle': 'dashed', 'borderRadius': '12px',
        'textAlign': 'center', 'borderColor': '#dee2e6', 'backgroundColor': '#f8f9fa',
        'cursor': 'pointer', 'padding': '25px', 'transition': 'all 0.3s ease'
    },
    'bula-box': {
        'height': '400px', 'overflowY': 'auto', 'border': '1px solid #e9ecef',
        'borderRadius': '8px', 'padding': '20px', 'backgroundColor': '#ffffff',
        'fontFamily': '"Georgia", serif', 'fontSize': '15px', 'lineHeight': '1.6',
        'color': '#212529', 'boxShadow': 'inset 0 0 10px rgba(0,0,0,0.02)'
    }
}

# ----------------- LISTAS DE SEÇÕES -----------------
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

SECOES_NAO_COMPARAR = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- BACKEND -----------------
def get_gemini_model():
    try:
        genai.configure(api_key=FIXED_API_KEY)
        return genai.GenerativeModel('models/gemini-1.5-flash')
    except: return None

def process_uploaded_file(contents, filename):
    if not contents: return None
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        
        if filename.lower().endswith('.docx'):
            doc = docx.Document(io.BytesIO(decoded))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}

        elif filename.lower().endswith('.pdf'):
            doc = fitz.open(stream=decoded, filetype="pdf")
            images = []
            for i in range(min(12, len(doc))): # Aumentei um pouco o limite de páginas
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                images.append(Image.open(img_byte_arr))
            return {"type": "images", "data": images}
    except Exception as e:
        print(f"Erro processamento: {e}")
        return None
    return None

# ----------------- LAYOUTS (PÁGINAS) -----------------

def build_home_layout():
    return dbc.Container([
        html.Div([
            html.H1([html.I(className="fas fa-robot text-primary me-3"), "Validador Inteligente"], className="display-5 fw-bold mb-3"),
            html.P("Central de auditoria e conformidade de bulas farmacêuticas.", className="lead text-muted mb-5"),
            
            dbc.Alert([
                html.I(className="fas fa-hand-point-left me-2"), 
                html.Strong("Como usar: "), "Selecione a ferramenta desejada no menu lateral esquerdo."
            ], color="primary", className="d-inline-block px-4 py-3 rounded-pill shadow-sm mb-5"),
            
            html.H4("Ferramentas Disponíveis:", className="fw-bold text-dark mb-4 border-bottom pb-2"),
            
            dbc.Row([
                dbc.Col(dbc.Card([
                    dbc.CardBody([
                        html.Div(html.I(className="fas fa-pills fa-2x text-primary"), className="mb-3 bg-light rounded-circle p-3 d-inline-block"),
                        html.H5("1. Ref x BELFAR", className="fw-bold"),
                        html.P("Comparação semântica completa. Detecta divergências de texto, erros e datas.", className="text-muted small"),
                    ])
                ], className="h-100 shadow-sm border-0 hover-card text-center py-4"), md=4),
                
                dbc.Col(dbc.Card([
                    dbc.CardBody([
                        html.Div(html.I(className="fas fa-clipboard-check fa-2x text-warning"), className="mb-3 bg-light rounded-circle p-3 d-inline-block"),
                        html.H5("2. Conferência MKT", className="fw-bold"),
                        html.P("Validação de arquivos de marketing contra o padrão exigido.", className="text-muted small"),
                    ])
                ], className="h-100 shadow-sm border-0 hover-card text-center py-4"), md=4),
                
                dbc.Col(dbc.Card([
                    dbc.CardBody([
                        html.Div(html.I(className="fas fa-print fa-2x text-danger"), className="mb-3 bg-light rounded-circle p-3 d-inline-block"),
                        html.H5("3. Gráfica x Arte", className="fw-bold"),
                        html.P("Comparação visual para pré-impressão. Detecta erros gráficos.", className="text-muted small"),
                    ])
                ], className="h-100 shadow-sm border-0 hover-card text-center py-4"), md=4),
            ])
        ], className="py-5 animate-fade-in")
    ], fluid=True)

def build_tool_page(title, subtitle, scenario_id, icon, color):
    # Seletor de Tipo (Apenas Cenário 1)
    type_selector = html.Div()
    if scenario_id == "1":
        type_selector = html.Div([
            html.Label("Selecione o Tipo de Bula:", className="fw-bold text-dark me-3"),
            dbc.RadioItems(
                options=[
                    {"label": "Paciente", "value": "PACIENTE"},
                    {"label": "Profissional", "value": "PROFISSIONAL"},
                ],
                value="PACIENTE",
                id="radio-tipo-bula",
                inline=True,
                className="btn-group-toggle",
                inputClassName="btn-check",
                labelClassName="btn btn-outline-primary px-4 py-2 rounded-pill fw-bold",
                labelCheckedClassName="active"
            )
        ], className="d-flex align-items-center justify-content-center bg-white p-3 rounded-pill shadow-sm mb-5 border")

    return dbc.Container([
        html.Div([
            html.H2([html.I(className=f"fas {icon} text-{color} me-3"), title], className="fw-bold"),
            html.P(subtitle, className="text-muted"),
        ], className="mb-5 border-bottom pb-3"),
        
        type_selector,
        
        dbc.Row([
            dbc.Col([
                html.H6("📄 Arquivo Referência / Padrão", className="fw-bold text-primary mb-3 text-center"),
                dcc.Upload(
                    id="upload-1",
                    children=html.Div([html.I(className="fas fa-cloud-arrow-up fa-3x text-muted mb-3"), html.Br(), html.Span("Arraste ou Clique", className="fw-bold")]),
                    style=GLOBAL_STYLES['upload-box'], multiple=False
                ),
                html.Div(id="fn-1", className="text-center small mt-2 text-success fw-bold")
            ], md=6),
            
            dbc.Col([
                html.H6("📄 Arquivo Belfar / Candidato", className="fw-bold text-success mb-3 text-center"),
                dcc.Upload(
                    id="upload-2",
                    children=html.Div([html.I(className="fas fa-cloud-arrow-up fa-3x text-muted mb-3"), html.Br(), html.Span("Arraste ou Clique", className="fw-bold")]),
                    style=GLOBAL_STYLES['upload-box'], multiple=False
                ),
                html.Div(id="fn-2", className="text-center small mt-2 text-success fw-bold")
            ], md=6),
        ], className="mb-5"),
        
        dbc.Button([html.I(className="fas fa-rocket me-2"), "INICIAR AUDITORIA COMPLETA"], 
                   id="btn-run", color=color, size="lg", className="w-100 py-3 fw-bold shadow hover-lift"),
        
        dcc.Loading(id="loading", type="dot", color=color, children=html.Div(id="output-results", className="mt-5")),
        
        dcc.Store(id="scenario-store", data=scenario_id)
    ], fluid=True, className="py-4")

# ----------------- APP LAYOUT PRINCIPAL -----------------
sidebar = html.Div([
    dcc.Link([
        html.Div([
            html.I(className="fas fa-shield-alt fa-2x text-primary me-2"),
            html.Span("Validador", className="h4 fw-bold align-middle text-dark")
        ], className="text-center py-4 border-bottom bg-light")
    ], href="/", className="text-decoration-none"),
    
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home w-25"), "Início"], href="/", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-pills w-25"), "Ref x Belfar"], href="/ref-bel", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-file-contract w-25"), "Conferência MKT"], href="/mkt", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-print w-25"), "Gráfica x Arte"], href="/graf", active="exact", className="py-3 fw-bold"),
    ], vertical=True, pills=True, className="px-3 py-4"),
], style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "260px", "backgroundColor": "#fff", "borderRight": "1px solid #dee2e6", "zIndex": 100})

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    sidebar,
    html.Div(id="page-content", style={"marginLeft": "260px", "padding": "2rem", "backgroundColor": "#fcfcfc", "minHeight": "100vh"})
])

# ----------------- CALLBACKS -----------------

@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_content(pathname):
    if pathname == "/ref-bel":
        return build_tool_page("Medicamento Ref x BELFAR", "Comparação de Bula Paciente ou Profissional.", "1", "fa-pills", "primary")
    elif pathname == "/mkt":
        return build_tool_page("Conferência MKT", "Validação de itens obrigatórios.", "2", "fa-clipboard-check", "warning")
    elif pathname == "/graf":
        return build_tool_page("Gráfica x Arte Vigente", "Validação visual para impressão.", "3", "fa-print", "danger")
    return build_home_layout()

@app.callback([Output("fn-1", "children"), Output("fn-2", "children")], 
              [Input("upload-1", "filename"), Input("upload-2", "filename")])
def update_filenames(n1, n2):
    return (f"✅ {n1}" if n1 else ""), (f"✅ {n2}" if n2 else "")

@app.callback(
    Output("output-results", "children"),
    Input("btn-run", "n_clicks"),
    [State("upload-1", "contents"), State("upload-2", "contents"),
     State("scenario-store", "data"), State("radio-tipo-bula", "value")]
)
def run_analysis(n_clicks, c1, c2, scenario, tipo_bula):
    if not n_clicks: return no_update
    if not c1 and not c2: return dbc.Alert("⚠️ Por favor, faça o upload dos arquivos.", color="warning", className="fw-bold")

    try:
        model = get_gemini_model()
        if not model: return dbc.Alert("Erro na API Key.", color="danger")

        # Processamento
        d1 = process_uploaded_file(c1, "f1.pdf") if c1 else None
        d2 = process_uploaded_file(c2, "f2.pdf") if c2 else None
        
        payload = []
        if d1: payload.append("--- REF ---") if d1['type']=='text' else None; payload.extend(d1['data'] if d1['type']=='images' else [d1['data']])
        if d2: payload.append("--- BELFAR ---") if d2['type']=='text' else None; payload.extend(d2['data'] if d2['type']=='images' else [d2['data']])

        # Definição de Seções e Prompt
        lista_ativa = SECOES_PACIENTE # Default para MKT e Grafica
        nome_tipo = "Paciente"

        if scenario == "1":
            if tipo_bula == "PROFISSIONAL":
                lista_ativa = SECOES_PROFISSIONAL
                nome_tipo = "Profissional"
            else:
                lista_ativa = SECOES_PACIENTE
                nome_tipo = "Paciente"
        
        secoes_str = "\n".join([f"- {s}" for s in lista_ativa])
        nao_comparar_str = ", ".join(SECOES_NAO_COMPARAR)

        prompt = f"""
        Atue como Auditor de Qualidade Farmacêutica.
        Analise os documentos (Ref vs Belfar).
        
        TAREFA: Extraia o texto COMPLETO de cada seção abaixo.
        LISTA ({nome_tipo}):
        {secoes_str}
        
        REGRAS DE FORMATAÇÃO (Retorne texto com estas tags HTML):
        1. Divergências de sentido: <mark style="background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba;">texto diferente</mark>
           (IGNORE divergências nas seções: {nao_comparar_str}).
        2. Erros de Português: <mark style="background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545;">erro</mark>
        3. Datas ANVISA: <mark style="background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold;">dd/mm/aaaa</mark>
        
        SAÍDA JSON:
        {{
            "METADADOS": {{ "score": 90, "datas": ["..."] }},
            "SECOES": [
                {{ "titulo": "NOME SEÇÃO", "ref": "texto...", "bel": "texto...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" | "INFORMATIVO" }}
            ]
        }}
        """

        response = model.generate_content([prompt] + payload)
        txt = response.text.replace("```json", "").replace("```", "").strip()
        # Limpeza extra para json inválido
        if txt.startswith("json"): txt = txt[4:]
        data = json.loads(txt)
        
        # Renderização
        meta = data.get("METADADOS", {})
        
        cards = dbc.Row([
            dbc.Col(dbc.Card([html.H2(f"{meta.get('score',0)}%", className="text-primary fw-bold"), html.Small("Conformidade Global")], body=True, className="text-center shadow-sm border-0"), md=4),
            dbc.Col(dbc.Card([html.H2(str(len(data.get("SECOES", []))), className="text-info fw-bold"), html.Small("Seções Analisadas")], body=True, className="text-center shadow-sm border-0"), md=4),
            dbc.Col(dbc.Card([html.H2(", ".join(meta.get("datas", [])[:2]), className="text-success fw-bold", style={"fontSize": "1.2rem"}), html.Small("Datas ANVISA")], body=True, className="text-center shadow-sm border-0"), md=4),
        ], className="mb-4")

        accordion = []
        for sec in data.get("SECOES", []):
            status = sec.get('status', 'N/A')
            
            icon = "✅"
            header_class = "text-success"
            
            if "DIVERGENTE" in status: 
                icon = "❌"
                header_class = "text-danger"
            elif "FALTANTE" in status:
                icon = "🚨"
                header_class = "text-warning"
            elif "INFORMATIVO" in status:
                icon = "ℹ️"
                header_class = "text-info"

            content = dbc.Row([
                dbc.Col([
                    html.Div("REFERÊNCIA", className="small fw-bold text-primary mb-2"),
                    html.Div(dcc.Markdown(sec.get('ref', ''), dangerously_allow_html=True), style=GLOBAL_STYLES['bula-box'])
                ], md=6),
                dbc.Col([
                    html.Div("BELFAR (Candidata)", className="small fw-bold text-success mb-2"),
                    html.Div(dcc.Markdown(sec.get('bel', ''), dangerously_allow_html=True), style=GLOBAL_STYLES['bula-box'])
                ], md=6)
            ])
            
            accordion.append(dbc.AccordionItem(content, title=f"{icon} {sec['titulo']} — {status}", item_id=sec['titulo']))

        return html.Div([
            html.H4("📊 Resultado da Análise", className="fw-bold mb-4"),
            cards,
            dbc.Accordion(accordion, start_collapsed=False, always_open=True, className="shadow-sm bg-white rounded")
        ], className="animate-fade-in")

    except Exception as e:
        return dbc.Alert(f"Erro na análise: {str(e)}", color="danger")

# Handler para callback de input inexistente na home
app.validation_layout = html.Div([
    upload_box("upload-1",""), upload_box("upload-2",""),
    dcc.Store(id="scenario-store"), dcc.RadioItems(id="radio-tipo-bula"),
    sidebar, build_home_layout()
])

if __name__ == "__main__":
    app.run_server(debug=True)
