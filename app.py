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

app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.MINTY, "https://use.fontawesome.com/releases/v6.4.0/css/all.css"],
    title="Validador Belfar",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ----------------- ESTILOS -----------------
COLOR_PRIMARY = "#20c997"
STYLES = {
    'upload_box': {
        'borderWidth': '2px', 'borderStyle': 'dashed', 'borderRadius': '15px',
        'borderColor': '#dee2e6', 'backgroundColor': '#f8f9fa',
        'padding': '20px', 'textAlign': 'center', 'cursor': 'pointer',
        'minHeight': '160px', 'display': 'flex', 'flexDirection': 'column', 
        'justifyContent': 'center', 'alignItems': 'center',
        'transition': 'all 0.2s ease-in-out'
    },
    'bula_box': {
        'height': '400px', 'overflowY': 'auto', 'border': '1px solid #e9ecef',
        'borderRadius': '8px', 'padding': '25px', 'backgroundColor': '#ffffff',
        'fontFamily': '"Georgia", serif', 'fontSize': '15px', 'lineHeight': '1.7',
        'color': '#212529'
    }
}

# ----------------- CONSTANTES -----------------
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
def get_model():
    try:
        genai.configure(api_key=FIXED_API_KEY)
        return genai.GenerativeModel('models/gemini-1.5-flash')
    except: return None

def process_file(contents, filename):
    if not contents: return None
    try:
        _, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        
        if filename.lower().endswith('.docx'):
            doc = docx.Document(io.BytesIO(decoded))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
        elif filename.lower().endswith('.pdf'):
            doc = fitz.open(stream=decoded, filetype="pdf")
            images = []
            # OTIMIZAÇÃO: 8 páginas max e qualidade média para não travar
            for i in range(min(8, len(doc))):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                images.append(Image.open(img_byte_arr))
            return {"type": "images", "data": images}
    except Exception as e:
        return None
    return None

def clean_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"): text = text[4:]
    return text

# ----------------- COMPONENTES VISUAIS -----------------

def build_upload_area(id_upload, id_store_name, id_clear, label):
    """Cria área de upload com botão de remover (X)"""
    return html.Div([
        html.H6([html.I(className="far fa-file-alt me-2 text-muted"), label], className="fw-bold mb-2"),
        html.Div([
            dcc.Upload(
                id=id_upload,
                children=html.Div([
                    # Estado Vazio
                    html.Div([
                        html.I(className="fas fa-cloud-arrow-up fa-3x text-muted mb-2"),
                        html.H6("Arraste ou Clique", className="text-muted small fw-bold")
                    ], id=f"{id_upload}-empty"),
                    # Estado Preenchido
                    html.Div([
                        html.I(className="fas fa-check-circle fa-3x text-success mb-2"),
                        html.H6(id=id_store_name, className="text-success small fw-bold text-break")
                    ], id=f"{id_upload}-filled", style={"display": "none"})
                ]),
                style=STYLES['upload_box'],
                multiple=False
            ),
            # Botão X
            html.Button(
                html.I(className="fas fa-times"),
                id=id_clear,
                className="btn btn-sm btn-danger position-absolute top-0 end-0 m-2 rounded-circle shadow-sm",
                style={"display": "none", "width": "30px", "height": "30px", "padding": "0"},
                title="Remover arquivo"
            )
        ], className="position-relative")
    ])

# ----------------- LAYOUTS -----------------

sidebar = html.Div([
    html.Div([
        html.I(className="fas fa-shield-alt fa-2x text-primary me-2"),
        html.Span("Validador", className="h3 fw-bold align-middle", style={"color": "#2c3e50"})
    ], className="text-center py-4 border-bottom"),
    
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home w-25"), "Início"], href="/", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-pills w-25"), "Ref x Belfar"], href="/ref-bel", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-file-contract w-25"), "Conferência MKT"], href="/mkt", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-print w-25"), "Gráfica x Arte"], href="/graf", active="exact", className="py-3 fw-bold"),
    ], vertical=True, pills=True, className="px-3 py-4"),
], style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "260px", "backgroundColor": "#fff", "borderRight": "1px solid #dee2e6", "zIndex": 100})

def build_home_layout():
    """Layout da Página Inicial (Home)"""
    return dbc.Container([
        html.Div(className="text-center py-5 animate-fade-in", children=[
            html.I(className="fas fa-microscope text-primary fa-4x mb-3"),
            html.H1("Validador Inteligente", className="display-4 fw-bold text-dark"),
            html.P("Selecione uma ferramenta abaixo para começar a auditoria.", className="lead text-muted mb-5"),
            
            dbc.Row([
                dbc.Col(dbc.Card([dbc.CardBody([html.H4("Ref x Belfar", className="fw-bold"), dbc.Button("Acessar", href="/ref-bel", color="success", outline=True, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4"), md=4),
                dbc.Col(dbc.Card([dbc.CardBody([html.H4("Conferência MKT", className="fw-bold"), dbc.Button("Acessar", href="/mkt", color="warning", outline=True, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4"), md=4),
                dbc.Col(dbc.Card([dbc.CardBody([html.H4("Gráfica x Arte", className="fw-bold"), dbc.Button("Acessar", href="/graf", color="danger", outline=True, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4"), md=4),
            ])
        ])
    ])

def build_tool_page(title, subtitle, scenario_id):
    """Layout Genérico das Ferramentas"""
    options_div = html.Div()
    if scenario_id == "1":
        options_div = dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label("Tipo de Bula:", className="fw-bold mt-2 text-end"), width=4),
                    dbc.Col(
                        dbc.RadioItems(
                            options=[
                                {"label": "Paciente", "value": "PACIENTE"},
                                {"label": "Profissional", "value": "PROFISSIONAL"},
                            ],
                            value="PACIENTE",
                            id="radio-tipo-bula",
                            inline=True,
                            className="btn-group-radio",
                            inputClassName="btn-check",
                            labelClassName="btn btn-outline-success px-4 rounded-pill fw-bold",
                            labelCheckedClassName="active"
                        ), width=8
                    )
                ], className="justify-content-center")
            ])
        ], className="mb-4 shadow-sm border-0 rounded-4 bg-white")

    return dbc.Container([
        html.Div([
            html.H2(title, className="fw-bold mb-2", style={"color": "#2c3e50"}),
            html.P(subtitle, className="text-muted"),
        ], className="mb-4 border-bottom pb-3"),
        
        options_div,
        
        dbc.Row([
            dbc.Col(build_upload_area("upload-1", "name-1", "clear-1", "Documento Referência / Padrão"), md=6, className="mb-4"),
            dbc.Col(build_upload_area("upload-2", "name-2", "clear-2", "Documento Belfar / Candidato"), md=6, className="mb-4"),
        ]),
        
        dbc.Button(
            [html.I(className="fas fa-rocket me-2"), "INICIAR AUDITORIA COMPLETA"],
            id="btn-run",
            color="primary",
            size="lg",
            className="w-100 py-3 fw-bold shadow hover-scale mb-5",
            style={"borderRadius": "10px"}
        ),
        
        dcc.Loading(id="loading", type="dot", color=COLOR_PRIMARY, children=html.Div(id="output-results")),
        dcc.Store(id="scenario-store", data=scenario_id)
    ], fluid=True)

# ----------------- APP PRINCIPAL -----------------
app.layout = html.Div([
    dcc.Location(id="url", refresh="callback-nav"), 
    sidebar,
    html.Div(id="page-content", style={"marginLeft": "260px", "padding": "3rem", "backgroundColor": "#f8f9fa", "minHeight": "100vh"})
])

# ----------------- CALLBACKS -----------------

@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page(pathname):
    if pathname == "/ref-bel": return build_tool_page("Ref x Belfar", "Comparação técnica de conteúdo.", "1")
    elif pathname == "/mkt": return build_tool_page("Conferência MKT", "Validação de itens obrigatórios.", "2")
    elif pathname == "/graf": return build_tool_page("Gráfica x Arte", "Comparação visual de pré-impressão.", "3")
    return build_home_layout()

def manage_upload_state(contents, filename, n_clear):
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update, no_update, no_update
    trig_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if 'clear' in trig_id: # Se clicou no X
        return None, "", {"display": "block"}, {"display": "none"}, {"display": "none"}
    
    if contents: # Se fez upload
        return contents, filename, {"display": "none"}, {"display": "block"}, {"display": "block"}
        
    return no_update, no_update, no_update, no_update, no_update

@app.callback(
    [Output("upload-1", "contents"), Output("name-1", "children"),
     Output("upload-1-empty", "style"), Output("upload-1-filled", "style"), Output("clear-1", "style")],
    [Input("upload-1", "contents"), Input("clear-1", "n_clicks")],
    [State("upload-1", "filename")]
)
def update_u1(c, n_clear, n): return manage_upload_state(c, n, n_clear)

@app.callback(
    [Output("upload-2", "contents"), Output("name-2", "children"),
     Output("upload-2-empty", "style"), Output("upload-2-filled", "style"), Output("clear-2", "style")],
    [Input("upload-2", "contents"), Input("clear-2", "n_clicks")],
    [State("upload-2", "filename")]
)
def update_u2(c, n_clear, n): return manage_upload_state(c, n, n_clear)

@app.callback(
    Output("output-results", "children"),
    Input("btn-run", "n_clicks"),
    [State("upload-1", "contents"), State("upload-1", "filename"),
     State("upload-2", "contents"), State("upload-2", "filename"),
     State("scenario-store", "data"), State("radio-tipo-bula", "value")]
)
def run_analysis(n_clicks, c1, n1, c2, n2, scenario, tipo_bula):
    if not n_clicks: return no_update
    if not c1 and not c2: return dbc.Alert("⚠️ Faça o upload dos arquivos!", color="warning")

    try:
        model = get_model()
        if not model: return dbc.Alert("Erro API.", color="danger")

        # Processamento
        d1 = process_file(c1, n1) if c1 else None
        d2 = process_file(c2, n2) if c2 else None
        
        payload = []
        if d1: payload.append("--- REF ---"); payload.extend([d1['data']] if d1['type']=='text' else d1['data'])
        if d2: payload.append("--- ALVO ---"); payload.extend([d2['data']] if d2['type']=='text' else d2['data'])

        # Lógica Seções
        lista = SECOES_PACIENTE
        nome_tipo = "Paciente"
        
        if scenario == "1":
            if tipo_bula == "PROFISSIONAL":
                lista = SECOES_PROFISSIONAL
                nome_tipo = "Profissional"
        
        secoes_str = "\n".join([f"- {s}" for s in lista])
        nao_comparar_str = ", ".join(SECOES_NAO_COMPARAR)

        prompt = f"""
        Atue como Auditor de Qualidade Farmacêutica.
        Analise os documentos (Ref vs Alvo).
        
        TAREFA: Extraia o texto COMPLETO de cada seção.
        LISTA ({nome_tipo}):
        {secoes_str}
        
        REGRAS DE FORMATAÇÃO (Retorne texto com estas tags HTML):
        1. Divergências de sentido: <mark style='background-color: #fff3cd; color: #856404; padding: 2px 4px; border: 1px solid #ffeeba;'>texto</mark>
           (IGNORE divergências nas seções: {nao_comparar_str}).
        2. Erros de Português: <mark style='background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545;'>erro</mark>
        3. Datas ANVISA: <mark style='background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold;'>dd/mm/aaaa</mark>
        
        SAÍDA JSON:
        {{
            "METADADOS": {{ "score": 90, "datas": ["..."] }},
            "SECOES": [
                {{ "titulo": "NOME SEÇÃO", "ref": "texto...", "bel": "texto...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" | "INFORMATIVO" }}
            ]
        }}
        """
        
        res = model.generate_content([prompt] + payload)
        data = json.loads(clean_json(res.text))
        
        meta = data.get("METADADOS", {})
        
        cards = dbc.Row([
            dbc.Col(dbc.Card([html.H2(f"{meta.get('score',0)}%", className="text-success fw-bold"), "Conformidade"], body=True, className="text-center shadow-sm"), md=4),
            dbc.Col(dbc.Card([html.H2(str(len(data.get("SECOES", []))), className="text-primary fw-bold"), "Seções"], body=True, className="text-center shadow-sm"), md=4),
            dbc.Col(dbc.Card([html.H2(", ".join(meta.get("datas", [])[:2]) or "-", className="text-info fw-bold", style={"fontSize":"1rem"}), "Datas"], body=True, className="text-center shadow-sm"), md=4),
        ], className="mb-4")

        items = []
        for sec in data.get("SECOES", []):
            icon = "✅"
            if "DIVERGENTE" in sec['status']: icon = "❌"
            elif "FALTANTE" in sec['status']: icon = "🚨"
            
            content = dbc.Row([
                dbc.Col([html.Strong("Referência", className="text-primary"), html.Div(dcc.Markdown(sec.get('ref',''), dangerously_allow_html=True), style=STYLES['bula_box'])], md=6),
                dbc.Col([html.Strong("Belfar", className="text-success"), html.Div(dcc.Markdown(sec.get('bel',''), dangerously_allow_html=True), style=STYLES['bula_box'])], md=6)
            ])
            items.append(dbc.AccordionItem(content, title=f"{icon} {sec['titulo']} — {sec['status']}"))

        return html.Div([cards, dbc.Accordion(items, start_collapsed=False, always_open=True)])

    except Exception as e:
        return dbc.Alert(f"Erro: {e}", color="danger")

# Handler final (inclui todos os inputs possíveis para não quebrar callbacks)
app.validation_layout = html.Div([
    build_upload_area("upload-1","","clear-1",""), 
    build_upload_area("upload-2","","clear-2",""),
    dcc.Store(id="scenario-store"), dcc.RadioItems(id="radio-tipo-bula"),
    sidebar, build_home_layout(), build_tool_page("","", "1")
])

if __name__ == "__main__":
    app.run_server(debug=True)
