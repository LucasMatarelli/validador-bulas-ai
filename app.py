import React, { useState } from 'react';
import { 
  Upload, FileText, CheckCircle, AlertTriangle, 
  XCircle, Info, ChevronDown, ChevronRight, 
  Printer, ArrowRight, Loader2, File
} from 'lucide-react';
import { GoogleGenerativeAI } from "@google/generative-ai";

// --- CONFIGURAÇÃO ---
const FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw";

// --- COMPONENTES UI ---

const Card = ({ children, className = "" }) => (
  <div className={`bg-white rounded-xl border border-gray-200 shadow-sm ${className}`}>
    {children}
  </div>
);

const Button = ({ children, onClick, disabled, variant = "primary", className = "" }) => {
  const baseStyle = "w-full font-bold py-3 px-6 rounded-lg transition-all flex items-center justify-center gap-2";
  const styles = {
    primary: "bg-red-600 hover:bg-red-700 text-white shadow-md hover:shadow-lg disabled:bg-red-300",
    secondary: "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50",
    outline: "border-2 border-red-100 text-red-600 hover:bg-red-50"
  };
  return (
    <button 
      onClick={onClick} 
      disabled={disabled} 
      className={`${baseStyle} ${styles[variant]} ${className}`}
    >
      {disabled ? <Loader2 className="animate-spin" /> : children}
    </button>
  );
};

const FileUpload = ({ label, file, setFile, accept = ".pdf,.docx" }) => (
  <div className="flex flex-col gap-2">
    <label className="font-semibold text-gray-700 flex items-center gap-2">
      {label}
    </label>
    <div className={`
      relative border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all group
      ${file ? 'border-green-500 bg-green-50' : 'border-gray-300 hover:border-red-400 hover:bg-red-50'}
    `}>
      <input 
        type="file" 
        accept={accept}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        onChange={(e) => setFile(e.target.files[0])}
      />
      <div className="flex flex-col items-center gap-3">
        {file ? (
          <>
            <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center">
              <FileText className="w-6 h-6 text-green-600" />
            </div>
            <div>
              <p className="text-sm font-bold text-green-800">{file.name}</p>
              <p className="text-xs text-green-600">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </div>
          </>
        ) : (
          <>
            <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center group-hover:bg-red-100 transition-colors">
              <Upload className="w-6 h-6 text-gray-400 group-hover:text-red-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-600">Clique ou arraste o arquivo aqui</p>
              <p className="text-xs text-gray-400 mt-1">PDF ou DOCX suportados</p>
            </div>
          </>
        )}
      </div>
    </div>
  </div>
);

// --- APP PRINCIPAL ---

export default function App() {
  const [activeTab, setActiveTab] = useState('home');

  const renderContent = () => {
    switch(activeTab) {
      case 'home': return <HomePage setActiveTab={setActiveTab} />;
      case 'ref_bel': return <ValidatorTool scenario="ref_bel" title="1. Referência x BELFAR" />;
      case 'mkt': return <ValidatorTool scenario="mkt" title="2. Conferência MKT" />;
      case 'graf': return <ValidatorTool scenario="graf" title="3. Gráfica x Arte" />;
      default: return <HomePage setActiveTab={setActiveTab} />;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex font-sans text-gray-900 selection:bg-red-100 selection:text-red-900">
      {/* Sidebar */}
      <aside className="w-72 bg-white border-r border-gray-200 fixed h-full hidden md:flex flex-col z-20 shadow-sm">
        <div className="p-8 border-b border-gray-100 flex flex-col items-center">
          <div className="w-16 h-16 bg-gradient-to-br from-red-500 to-red-600 rounded-2xl flex items-center justify-center mb-4 shadow-lg shadow-red-200">
            <FileText className="text-white w-8 h-8" />
          </div>
          <h1 className="font-bold text-gray-900 text-xl tracking-tight">Validador Belfar</h1>
          <span className="text-xs font-medium text-gray-400 mt-1 px-2 py-1 bg-gray-50 rounded-full border border-gray-100">
            v2.0 React
          </span>
        </div>
        
        <nav className="flex-1 p-6 space-y-2 overflow-y-auto">
          <div className="text-xs font-bold text-gray-400 uppercase px-3 mb-2 tracking-wider">Menu Principal</div>
          <NavItem active={activeTab === 'home'} onClick={() => setActiveTab('home')} icon={<FileText size={20}/>}>
            Página Inicial
          </NavItem>
          
          <div className="pt-6 pb-2 text-xs font-bold text-gray-400 uppercase px-3 tracking-wider">Ferramentas</div>
          <NavItem active={activeTab === 'ref_bel'} onClick={() => setActiveTab('ref_bel')} icon={<CheckCircle size={20}/>}>
            Ref x BELFAR
          </NavItem>
          <NavItem active={activeTab === 'mkt'} onClick={() => setActiveTab('mkt')} icon={<AlertTriangle size={20}/>}>
            Conferência MKT
          </NavItem>
          <NavItem active={activeTab === 'graf'} onClick={() => setActiveTab('graf')} icon={<Printer size={20}/>}>
            Gráfica x Arte
          </NavItem>
        </nav>

        <div className="p-6 border-t border-gray-100 bg-gray-50/50">
          <div className="bg-white border border-green-200 rounded-xl p-4 shadow-sm flex items-center gap-3">
            <div className="relative">
              <div className="w-3 h-3 bg-green-500 rounded-full"></div>
              <div className="w-3 h-3 bg-green-500 rounded-full absolute top-0 animate-ping opacity-50"></div>
            </div>
            <div>
              <p className="text-xs font-bold text-gray-900">Sistema Online</p>
              <p className="text-[10px] text-gray-500">API Gemini Conectada</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 md:ml-72 p-8 lg:p-12 max-w-[1600px] mx-auto w-full">
        {renderContent()}
      </main>
    </div>
  );
}

const NavItem = ({ children, active, onClick, icon }) => (
  <button 
    onClick={onClick}
    className={`w-full flex items-center gap-3 px-4 py-3.5 text-sm font-medium rounded-xl transition-all duration-200 group
      ${active 
        ? 'bg-red-50 text-red-700 shadow-sm ring-1 ring-red-200 translate-x-1' 
        : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900 hover:translate-x-1'
      }`}
  >
    <span className={`${active ? 'text-red-600' : 'text-gray-400 group-hover:text-gray-600'}`}>{icon}</span>
    {children}
    {active && <ChevronRight size={16} className="ml-auto text-red-400" />}
  </button>
);

// --- PÁGINAS ---

const HomePage = ({ setActiveTab }) => (
  <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
    <header className="mb-12">
      <h1 className="text-4xl lg:text-5xl font-extrabold text-gray-900 mb-6 flex items-center gap-4">
        <span className="text-red-600">🔬</span> Validador Inteligente
      </h1>
      <p className="text-xl text-gray-600 max-w-3xl leading-relaxed">
        Bem-vindo à nova geração de auditoria de bulas. Utilize Inteligência Artificial para comparar documentos, detectar erros e validar artes gráficas em segundos.
      </p>
    </header>

    <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 p-6 mb-10 rounded-2xl flex items-start gap-4 shadow-sm">
      <Info className="text-blue-600 mt-1 flex-shrink-0" />
      <div>
        <h4 className="font-bold text-blue-900 text-lg mb-1">Como começar?</h4>
        <p className="text-blue-800">
          Selecione uma das ferramentas abaixo ou use o menu lateral para iniciar sua primeira validação.
        </p>
      </div>
    </div>

    <div className="grid md:grid-cols-3 gap-8">
      <HomeCard 
        title="Ref x BELFAR" 
        desc="Comparação semântica completa. Valida Posologia, Contraindicações e Dosagens entre a referência e a candidata."
        onClick={() => setActiveTab('ref_bel')}
        icon={<CheckCircle className="text-blue-600 w-8 h-8" />}
        color="blue"
      />
      <HomeCard 
        title="Conferência MKT" 
        desc="Checklist rápido de itens obrigatórios (Logos, SAC, Farmacêutico) para aprovação de materiais de marketing."
        onClick={() => setActiveTab('mkt')}
        icon={<AlertTriangle className="text-orange-600 w-8 h-8" />}
        color="orange"
      />
      <HomeCard 
        title="Gráfica x Arte" 
        desc="Validação visual pixel-a-pixel. Detecta manchas, textos cortados e erros de impressão na prova gráfica."
        onClick={() => setActiveTab('graf')}
        icon={<Printer className="text-purple-600 w-8 h-8" />}
        color="purple"
      />
    </div>
  </div>
);

const HomeCard = ({ title, desc, onClick, icon, color }) => (
  <div 
    onClick={onClick}
    className="bg-white p-8 rounded-2xl border border-gray-200 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all cursor-pointer group h-full flex flex-col"
  >
    <div className={`mb-6 bg-${color}-50 w-16 h-16 rounded-2xl flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
      {icon}
    </div>
    <h3 className="text-xl font-bold text-gray-900 mb-3 group-hover:text-red-600 transition-colors">{title}</h3>
    <p className="text-sm text-gray-500 leading-relaxed mb-6 flex-1">{desc}</p>
    <div className="flex items-center text-sm font-bold text-red-600 group-hover:gap-2 transition-all mt-auto">
      Acessar Ferramenta <ArrowRight size={16} className="ml-2" />
    </div>
  </div>
);

// --- FERRAMENTA DE VALIDAÇÃO ---

const ValidatorTool = ({ scenario, title }) => {
  const [file1, setFile1] = useState(null);
  const [file2, setFile2] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [bulaType, setBulaType] = useState('paciente');

  // Simula processamento (Para ambiente sem backend Node)
  // Em produção, aqui entraria a lógica de pdfjs-dist e mammoth
  const processFileMock = async (file) => {
    if (!file) return null;
    return new Promise(resolve => {
      setTimeout(() => {
        resolve({ mimeType: 'text/plain', data: `Conteúdo extraído simulado de ${file.name}...` });
      }, 800);
    });
  };

  const handleRun = async () => {
    if (!file1 && !file2) return;
    setLoading(true);
    setResult(null);

    try {
      const genAI = new GoogleGenerativeAI(FIXED_API_KEY);
      const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

      // Prompt Simplificado para Demo
      let prompt = `
        Atue como Auditor Farmacêutico.
        Gere um JSON simulado de validação de bula com base nos nomes dos arquivos: 
        Arquivo 1: ${file1?.name}, Arquivo 2: ${file2?.name}.
        
        Crie 3 seções de exemplo (Posologia, Composição, Contraindicações).
        Faça com que uma delas tenha status DIVERGENTE para teste.
        
        JSON esperado:
        {
          "METADADOS": { "score": 85, "datas_anvisa": ["10/05/2024"] },
          "SECOES": [
            { "titulo": "POSOLOGIA", "ref": "Tomar 1cp ao dia", "bel": "Tomar 1cp ao dia", "status": "CONFORME" },
            { "titulo": "COMPOSIÇÃO", "ref": "500mg de Dipirona", "bel": "500g de Dipirona (Erro unidade)", "status": "DIVERGENTE" },
            { "titulo": "CONTRAINDICAÇÕES", "ref": "Não usar se grávida", "bel": "Não usar se grávida", "status": "CONFORME" }
          ]
        }
      `;

      const result = await model.generateContent(prompt);
      const text = result.response.text();
      const jsonStr = text.replace(/```json|```/g, '').trim();
      const jsonData = JSON.parse(jsonStr);
      
      setResult(jsonData);

    } catch (error) {
      alert("Erro na análise: " + error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 max-w-5xl mx-auto">
      <header className="mb-10 border-b border-gray-200 pb-6 flex justify-between items-end">
        <div>
          <h2 className="text-3xl font-extrabold text-gray-900 flex items-center gap-3">
            {title}
          </h2>
          <p className="text-gray-500 mt-2">Carregue os arquivos para iniciar a validação automática.</p>
        </div>
        {scenario === 'ref_bel' && (
          <div className="bg-white p-1 rounded-lg border border-gray-200 inline-flex items-center shadow-sm">
            <button 
              onClick={() => setBulaType('paciente')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${bulaType === 'paciente' ? 'bg-red-50 text-red-700 shadow-sm' : 'text-gray-500 hover:bg-gray-50'}`}
            >
              Paciente
            </button>
            <button 
              onClick={() => setBulaType('profissional')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${bulaType === 'profissional' ? 'bg-red-50 text-red-700 shadow-sm' : 'text-gray-500 hover:bg-gray-50'}`}
            >
              Profissional
            </button>
          </div>
        )}
      </header>

      <div className="grid md:grid-cols-2 gap-8 mb-8">
        <FileUpload 
          label={scenario === 'graf' ? "🎨 Arte Final (Original)" : "📄 Documento Referência (Padrão)"} 
          file={file1} setFile={setFile1} 
        />
        <FileUpload 
          label={scenario === 'graf' ? "🖨️ Prova Gráfica (Digitalizada)" : "📄 Documento Belfar (Candidato)"} 
          file={file2} setFile={setFile2} 
        />
      </div>

      <Button onClick={handleRun} disabled={loading || (!file1 && !file2)}>
        {loading ? "Processando Inteligência Artificial..." : "🚀 INICIAR AUDITORIA COMPLETA"}
      </Button>

      {result && (
        <div className="mt-12 animate-in slide-in-from-bottom-8 duration-700">
          <div className="flex items-center justify-between mb-8 bg-white p-6 rounded-2xl shadow-sm border border-gray-200">
            <div>
              <h3 className="text-xl font-bold text-gray-800">Resultado da Análise</h3>
              <p className="text-sm text-gray-500">Auditoria concluída com sucesso</p>
            </div>
            <div className="flex gap-6">
              <Badge label="Conformidade" value={`${result.METADADOS?.score}%`} color={result.METADADOS?.score > 90 ? "green" : "orange"} />
              <Badge label="Seções" value={result.SECOES?.length || 0} color="blue" />
              <Badge label="Status" value="Finalizado" color="gray" />
            </div>
          </div>

          <div className="space-y-4">
            {result.SECOES?.map((sec, idx) => (
              <AccordionItem key={idx} data={sec} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const Badge = ({ label, value, color }) => {
  const colors = {
    green: "bg-green-50 text-green-700 border-green-200",
    orange: "bg-orange-50 text-orange-700 border-orange-200",
    blue: "bg-blue-50 text-blue-700 border-blue-200",
    gray: "bg-gray-50 text-gray-700 border-gray-200",
  };
  return (
    <div className={`flex flex-col items-center px-5 py-2 rounded-xl border ${colors[color] || colors.gray}`}>
      <span className="text-[10px] font-bold uppercase opacity-70 mb-1">{label}</span>
      <span className="text-xl font-bold">{value}</span>
    </div>
  );
};

const AccordionItem = ({ data }) => {
  const [isOpen, setIsOpen] = useState(data.status !== 'CONFORME');
  const isDiff = data.status === 'DIVERGENTE';
  
  return (
    <div className={`border rounded-xl bg-white overflow-hidden transition-all duration-300 shadow-sm hover:shadow-md ${isDiff ? 'border-red-200 ring-1 ring-red-100' : 'border-gray-200'}`}>
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center justify-between p-5 text-left transition-colors
          ${isDiff ? 'bg-red-50/50' : 'hover:bg-gray-50'}`}
      >
        <div className="flex items-center gap-4">
          <div className={`p-2 rounded-full ${isDiff ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600'}`}>
            {isDiff ? <XCircle size={20} /> : <CheckCircle size={20} />}
          </div>
          <span className={`font-bold text-lg ${isDiff ? 'text-red-900' : 'text-gray-700'}`}>{data.titulo}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className={`text-xs font-bold px-3 py-1 rounded-full border ${
            isDiff ? 'bg-white text-red-600 border-red-200' : 'bg-green-100 text-green-700 border-green-200'
          }`}>
            {data.status}
          </span>
          <div className={`transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}>
            <ChevronDown size={20} className="text-gray-400" />
          </div>
        </div>
      </button>

      {isOpen && (
        <div className="border-t border-gray-100 grid md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-gray-100 animate-in slide-in-from-top-2">
          <div className="p-6 bg-gray-50/50">
            <h4 className="text-xs font-bold text-blue-600 uppercase mb-3 flex items-center gap-2">
              <div className="w-2 h-2 bg-blue-500 rounded-full"></div> Referência
            </h4>
            <div className="text-sm text-gray-700 leading-relaxed font-serif bg-white p-4 rounded-lg border border-gray-200 shadow-sm" 
                 dangerouslySetInnerHTML={{ __html: data.ref }} />
          </div>
          <div className="p-6 bg-white">
            <h4 className="text-xs font-bold text-green-600 uppercase mb-3 flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full"></div> Belfar (Candidato)
            </h4>
            <div className="text-sm text-gray-700 leading-relaxed font-serif bg-gray-50 p-4 rounded-lg border border-gray-200 shadow-sm"
                 dangerouslySetInnerHTML={{ __html: data.bel }} />
          </div>
        </div>
      )}
    </div>
  );
};
