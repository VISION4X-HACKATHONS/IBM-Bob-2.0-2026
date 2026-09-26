import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, ArrowUpRight, Check, ChevronRight, CircleAlert, FileCode2, GitBranch, LoaderCircle, Play, Radar, ShieldCheck, Terminal, TestTube2 } from "lucide-react";
import "./styles.css";
import "./approval.css";

const API = "http://localhost:8001/api";
type PlanItem = { task: string; files: string[]; reason: string; risk: string };
type Result = { request: string; affected_files: string[]; affected_components: string[]; affected_apis: string[]; database_components: string[]; dependencies: string[]; tests: string[]; security_risks: string[]; confidence: number; plan: PlanItem[]; evidence: { files: string[]; symbols: { name: string; kind: string; file: string; line: number }[] } };

function App() {
  const [request, setRequest] = useState("Add phone-number authentication");
  const [result, setResult] = useState<Result | null>(null);
  const [analysisId, setAnalysisId] = useState("");
  const [verification, setVerification] = useState<{ status: string; output: string } | null>(null);
  const [implementation, setImplementation] = useState<{ status: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function analyze() {
    setBusy(true); setError(""); setVerification(null);
    try {
      const response = await fetch(`${API}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request, repository_path: "sample-project" }) });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Analysis failed");
      const data = await response.json(); setAnalysisId(data.id); setResult(data.result);
    } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not reach the API"); }
    finally { setBusy(false); }
  }

  async function verify() {
    setBusy(true); setError("");
    try { const response = await fetch(`${API}/verify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_path: "sample-project" }) }); setVerification(await response.json()); }
    catch { setError("Could not reach the verification API"); } finally { setBusy(false); }
  }

  async function approveImplementation() {
    if (!analysisId) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API}/implement`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis_id: analysisId, approved: true }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message ?? "Approval failed");
      setImplementation(data);
    } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not approve implementation"); }
    finally { setBusy(false); }
  }

  return <main className="shell">
    <header className="topbar"><div className="brand"><div className="brand-mark"><ShieldCheck size={20} /></div><div><strong>CODEGUARDIAN</strong><span>Application Maintenance Intelligence</span></div></div><div className="top-meta"><span className="live-dot" /> LOCAL WORKSPACE <GitBranch size={15} /> main</div></header>
    <section className="hero"><div><p className="eyebrow">CHANGE CONTROL / 01</p><h1>Understand the blast radius<br /><em>before you touch the code.</em></h1><p className="lede">A structured maintenance workflow that turns a change request into evidence, risk, an implementation plan, and verified results.</p></div><div className="hero-stamp"><Radar size={19} /><span>REPOSITORY<br /><b>READY TO SCAN</b></span></div></section>
    <section className="request-bar"><div className="request-label"><span>01</span><div><b>Change request</b><small>Describe the maintenance task</small></div></div><input value={request} onChange={event => setRequest(event.target.value)} /><button className="primary" onClick={analyze} disabled={busy || request.length < 5}>{busy ? <LoaderCircle className="spin" size={17} /> : <Activity size={17} />} Analyze change <ArrowUpRight size={16} /></button></section>
    {error && <div className="error"><CircleAlert size={16} /> {error}</div>}
    <section className="pipeline"><Step label="Repository analysis" done={!!result} /><Step label="Code impact" done={!!result} /><Step label="Test impact" done={!!result} /><Step label="Dependency analysis" done={!!result} /><Step label="Security analysis" done={!!result} /></section>
    {!result ? <div className="empty-state"><Radar size={32} /><h2>Start with a change request</h2><p>CODEGUARDIAN will scan the prepared sample project and surface the connected files, symbols, APIs, tests, dependencies, and security boundaries.</p></div> : <>
      <div className="section-heading"><div><p className="eyebrow">IMPACT MAP / 02</p><h2>Evidence across the repository</h2></div><div className="confidence"><span>CONFIDENCE</span><b>{result.confidence}%</b></div></div>
      <div className="grid-two"><ImpactMap result={result} /><aside className="risk-panel"><div className="panel-head"><span>Risk review</span><CircleAlert size={17} /></div>{result.security_risks.map((risk, index) => <div className="risk" key={risk}><span>R{String(index + 1).padStart(2, "0")}</span><p>{risk}</p></div>)}<div className="evidence-count"><FileCode2 size={16} /><b>{result.evidence.files.length}</b><span>files scanned</span><b>{result.evidence.symbols.length}</b><span>symbols indexed</span></div></aside></div>
      <div className="section-heading lower"><div><p className="eyebrow">IMPLEMENTATION / 03</p><h2>Suggested change sequence</h2></div><div className="heading-actions"><span className="muted">Analysis ID {analysisId.slice(0, 8)}</span><button className="secondary" onClick={approveImplementation} disabled={busy}><Check size={15} /> Approve manifest</button></div></div>
      <div className="plan-list">{result.plan.map((item, index) => <div className="plan-item" key={item.task}><div className="plan-number">0{index + 1}</div><div className="plan-content"><h3>{item.task}</h3><p>{item.reason}</p>{item.files.length > 0 && <div className="file-pills">{item.files.map(file => <code key={file}>{file}</code>)}</div>}</div><span className={`risk-tag ${item.risk}`}>{item.risk}</span><ChevronRight size={18} /></div>)}</div>
      {implementation && <div className="approval-note"><ShieldCheck size={17} /><span><b>Manifest approved.</b> {implementation.message}</span></div>}
      <div className="verification"><div><p className="eyebrow">VERIFICATION / 04</p><h2>Run the regression suite</h2><p>Execute the sample project's real Pytest suite and attach the output to this analysis.</p></div><button className="secondary" onClick={verify} disabled={busy}><Play size={16} /> Run tests</button>{verification && <div className={`test-result ${verification.status}`}><TestTube2 size={19} /><div><b>{verification.status === "passed" ? "Verification passed" : "Verification failed"}</b><pre>{verification.output}</pre></div></div>}</div>
    </>}
    <footer><span>CODEGUARDIAN / LOCAL-FIRST PROTOTYPE</span><span>Evidence before implementation</span></footer>
  </main>
}

function Step({ label, done }: { label: string; done: boolean }) { return <div className="step"><span className={done ? "step-icon done" : "step-icon"}>{done ? <Check size={13} /> : <span />}</span>{label}</div> }
function ImpactMap({ result }: { result: Result }) { const nodes = [{ label: "CHANGE REQUEST", value: "Phone authentication", type: "root" }, { label: "AUTHENTICATION", value: `${result.affected_components.length} symbols`, type: "auth" }, { label: "SURFACES", value: `${result.affected_files.length} files`, type: "surface" }, { label: "VERIFICATION", value: `${result.tests.length} test files`, type: "test" }]; return <div className="impact-map"><div className="map-caption"><GitBranch size={16} /> dependency relationship <span>live evidence</span></div><div className="map-flow">{nodes.map((node, index) => <div className="map-node-wrap" key={node.label}><div className={`map-node ${node.type}`}><small>{node.label}</small><strong>{node.value}</strong></div>{index < nodes.length - 1 && <div className="connector"><span /></div>}</div>)}</div><div className="map-footer"><span><FileCode2 size={15} /> {result.affected_files.length} affected files</span><span><Terminal size={15} /> {result.affected_apis.length} API surfaces</span><span><ShieldCheck size={15} /> {result.dependencies.length} dependencies</span></div></div> }

const container = document.getElementById("root")!;
const rootHost = globalThis as typeof globalThis & { __codeguardianRoot?: ReturnType<typeof createRoot> };
const root = rootHost.__codeguardianRoot ?? createRoot(container);
rootHost.__codeguardianRoot = root;
root.render(<StrictMode><App /></StrictMode>);
