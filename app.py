import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update
import dash_bootstrap_components as dbc
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import io
import base64
import json
from PIL import Image

# ----------------- CONFIGURAÇÃO -----------------
FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw"

# Inicializa o App
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.MINTY, "https://use.fontawesome.com/releases/v6.4.0/css/all.css"],
    title="Validador Belfar",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

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
            for i in range(min(10, len(doc))):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                images.append(Image.open(img_byte_arr))
            return {"type": "images", "data": images}
    except Exception as e:
        print(f"Erro: {e}")
        return None
    return None

# ----------------- COMPONENTES VISUAIS -----------------
def upload_box(id_name, label):
    return dbc.Card([
        dbc.CardBody([
            html.H6(label, className="fw-bold text-dark mb-3"),
            dcc.Upload(
                id=id_name,
                children=html.Div([
                    html.I(className="fas fa-cloud-upload-alt fa-2x text-primary mb-2"),
                    html.Div(["Arraste ou ", html.Span("Clique", className="fw-bold text-primary")])
                ]),
                style={
                    'width': '100%', 'height': '120px', 'lineHeight': '30px',
                    'borderWidth': '2px', 'borderStyle': 'dashed', 'borderRadius': '10px',
                    'textAlign': 'center', 'borderColor': '#ced4da', 'backgroundColor': '#f8f9fa',
                    'cursor': 'pointer', 'padding': '25px', 'transition': 'all 0.3s'
                },
                multiple=False
            ),
            html.Div(id=f"{id_name}-filename", className="mt-2 small text-success fw-bold text-center")
        ])
    ], className="mb-3 shadow-sm border-0")

def feature_card(title, desc, icon, color, link_id):
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Div(html.I(className=f"fas {icon} fa-lg text-{color}"), className=f"bg-{color}-subtle p-3 rounded-3 me-3"),
                html.H5(title, className="card-title fw-bold mb-0")
            ], className="d-flex align-items-center mb-3"),
            html.P(desc, className="card-text text-muted small"),
            dbc.Button("Acessar Ferramenta", id=link_id, color=color, outline=True, size="sm", className="mt-3 w-100 fw-bold")
        ])
    ], className="h-100 shadow-sm border-0 hover-shadow")

# ----------------- BARRA LATERAL -----------------
sidebar = html.Div([
    # Torna o título clicável para voltar ao Home
    dcc.Link([
        html.Div([
            html.I(className="fas fa-file-medical fa-2x text-primary me-2"),
            html.Span("Validador Belfar", className="h4 fw-bold align-middle text-dark text-decoration-none")
        ], className="text-center py-4 border-bottom hover-bg-light")
    ], href="/", className="text-decoration-none"),
    
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home me-3"), "Página Inicial"], href="/", active="exact", className="py-3"),
        dbc.NavLink([html.I(className="fas fa-check-double me-3"), "Ref x Belfar"], href="/ref-bel", active="exact", className="py-3"),
        dbc.NavLink([html.I(className="fas fa-tasks me-3"), "Conferência MKT"], href="/mkt", active="exact", className="py-3"),
        dbc.NavLink([html.I(className="fas fa-print me-3"), "Gráfica x Arte"], href="/graf", active="exact", className="py-3"),
    ], vertical=True, pills=True, className="px-3 py-4"),
    
    html.Div([
        dbc.Alert([html.I(className="fas fa-wifi me-2"), "API Conectada"], color="success", className="small m-0 py-2 text-center")
    ], className="mt-auto p-3")
], style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "260px", "backgroundColor": "#fff", "borderRight": "1px solid #dee2e6", "zIndex": 100})

content_style = {"marginLeft": "260px", "padding": "2rem", "backgroundColor": "#f8f9fa", "minHeight": "100vh"}

# ----------------- LAYOUTS DINÂMICOS -----------------

def build_home_layout():
    """Gera o layout da home dinamicamente para resetar os botões."""
    return html.Div([
        html.Div([
            html.H1([html.I(className="fas fa-microscope text-primary me-3"), "Validador Inteligente"], className="fw-bold mb-3"),
            html.P("Bem-vindo à central de auditoria de documentos.", className="text-muted lead mb-4"),
            dbc.Alert([
                html.I(className="fas fa-info-circle me-2"), 
                html.B("Como começar: "), "Selecione uma ferramenta abaixo ou no menu lateral."
            ], color="info", className="mb-5 border-start border-5 border-info bg-info-subtle"),
            
            html.H4("Ferramentas Disponíveis:", className="fw-bold mb-4"),
            dbc.Row([
                dbc.Col(feature_card("1. Ref x Belfar", "Comparação de texto técnico e posologia.", "fa-pills", "primary", "btn-home-ref"), md=4),
                dbc.Col(feature_card("2. Conferência MKT", "Checklist de itens obrigatórios (Logos, SAC).", "fa-list-check", "warning", "btn-home-mkt"), md=4),
                dbc.Col(feature_card("3. Gráfica x Arte", "Validação visual para pré-impressão.", "fa-eye", "danger", "btn-home-graf"), md=4),
            ]),
        ], className="animate-fade-in")
    ])

def build_tool_page(title, subtitle, scenario_id, icon, color):
    options_div = html.Div()
    if scenario_id == "1":
        options_div = dbc.Card([
            dbc.CardBody([
                html.Label("Selecione o Tipo de Bula:", className="fw-bold mb-2 d-block"),
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
                    labelClassName="btn btn-outline-primary me-2 rounded-pill",
                    labelCheckedClassName="active"
                )
            ])
        ], className="mb-4 shadow-sm border-0")

    return html.Div([
        html.Div([
            html.H2([html.I(className=f"fas {icon} text-{color} me-3"), title], className="fw-bold"),
            html.P(subtitle, className="text-muted mb-4"),
        ], className="border-bottom mb-4 pb-2"),
        options_div,
        dbc.Row([
            dbc.Col(upload_box("upload-1", "📄 Documento Referência / Padrão"), md=6),
            dbc.Col(upload_box("upload-2", "📄 Documento Belfar / Candidato"), md=6),
        ]),
        dbc.Button([html.I(className="fas fa-rocket me-2"), "INICIAR AUDITORIA"], 
                   id="btn-run", color=color, size="lg", className="w-100 my-4 shadow fw-bold p-3"),
        dcc.Loading(id="loading", type="dot", color="#0d6efd", children=html.Div(id="output-results")),
        dcc.Store(id="scenario-store", data=scenario_id)
    ])

# ----------------- APP LAYOUT -----------------
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    sidebar,
    html.Div(id="page-content", style=content_style)
])

# ----------------- CALLBACKS -----------------

@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/ref-bel":
        return build_tool_page("Medicamento Ref x BELFAR", "Comparação técnica.", "1", "fa-check-double", "primary")
    elif pathname == "/mkt":
        return build_tool_page("Conferência MKT", "Validação MKT.", "2", "fa-tasks", "warning")
    elif pathname == "/graf":
        return build_tool_page("Gráfica x Arte Vigente", "Validação Visual.", "3", "fa-print", "danger")
    # Retorna uma nova instância da home para evitar estado preso
    return build_home_layout()

@app.callback(Output("url", "pathname"), 
              [Input("btn-home-ref", "n_clicks"), Input("btn-home-mkt", "n_clicks"), Input("btn-home-graf", "n_clicks")])
def home_navigation(b1, b2, b3):
    ctx = callback_context
    if not ctx.triggered: return no_update
    btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if btn_id == "btn-home-ref": return "/ref-bel"
    if btn_id == "btn-home-mkt": return "/mkt"
    if btn_id == "btn-home-graf": return "/graf"
    return no_update

@app.callback(Output("upload-1-filename", "children"), Input("upload-1", "filename"))
def update_f1(name): return f"✅ {name}" if name else ""

@app.callback(Output("upload-2-filename", "children"), Input("upload-2", "filename"))
def update_f2(name): return f"✅ {name}" if name else ""

@app.callback(
    Output("output-results", "children"),
    Input("btn-run", "n_clicks"),
    [State("upload-1", "contents"), State("upload-1", "filename"),
     State("upload-2", "contents"), State("upload-2", "filename"),
     State("scenario-store", "data"), State("radio-tipo-bula", "value")]
)
def run_analysis(n_clicks, c1, n1, c2, n2, scenario, tipo_bula):
    if not n_clicks: return no_update
    if not c1 and not c2: return dbc.Alert("⚠️ Faça upload dos arquivos!", color="warning")

    try:
        model = get_gemini_model()
        if not model: return dbc.Alert("Erro API.", color="danger")

        data1 = process_uploaded_file(c1, n1) if c1 else None
        data2 = process_uploaded_file(c2, n2) if c2 else None
        
        payload = []
        if data1: payload.append(f"--- REF TEXTO ---\n{data1['data']}" if data1['type']=='text' else data1['data'][0] if data1['data'] else "")
        if data1 and data1['type']=='images': payload = data1['data'] + payload 
        
        if data2: 
            if data2['type']=='text': payload.append(f"--- BELFAR TEXTO ---\n{data2['data']}")
            else: payload.extend(data2['data'])

        secoes = "POSOLOGIA, COMPOSIÇÃO"
        if scenario == "1":
            if tipo_bula == "PACIENTE": secoes = "PARA QUE SERVE, COMO USAR, QUANDO NÃO USAR, MALES QUE PODE CAUSAR"
            prompt = f"Atue como Auditor. Compare os documentos. Extraia: {secoes}. Retorne JSON: {{'METADADOS': {{'score': 90, 'datas': []}}, 'SECOES': [{{'titulo': 'X', 'ref': '...', 'bel': '...', 'status': 'CONFORME'}}]}}"
        elif scenario == "2": prompt = "Verifique MKT: VENDA SOB PRESCRIÇÃO, Logo. Retorne JSON."
        else: prompt = "Comparação Visual. Liste defeitos em JSON."

        response = model.generate_content([prompt] + payload)
        txt = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(txt)
        
        items = []
        for sec in data.get("SECOES", []):
            icon = "❌" if "DIVERGENTE" in sec['status'] else "✅"
            content = dbc.Row([
                dbc.Col([html.Strong("Referência"), dcc.Markdown(sec.get('ref', ''), className="border p-2 bg-light")], md=6),
                dbc.Col([html.Strong("Belfar"), dcc.Markdown(sec.get('bel', ''), className="border p-2 bg-white")], md=6)
            ])
            items.append(dbc.AccordionItem(content, title=f"{icon} {sec['titulo']} — {sec['status']}"))

        return html.Div([
            dbc.Row([
                dbc.Col(dbc.Card([html.H3(f"{data['METADADOS'].get('score',0)}%"), "Conformidade"], body=True, className="text-center"), md=4),
            ], className="mb-3"),
            dbc.Accordion(items, start_collapsed=False, always_open=True)
        ])

    except Exception as e:
        return dbc.Alert(f"Erro: {str(e)}", color="danger")

# Corrige inputs faltantes na home
app.validation_layout = html.Div([
    upload_box("upload-1",""), upload_box("upload-2",""),
    dcc.Store(id="scenario-store"), dcc.RadioItems(id="radio-tipo-bula"),
    sidebar, home_layout
])

if __name__ == "__main__":
    app.run_server(debug=True)
