import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, ArrowUpRight, Check, ChevronRight, CircleAlert, FileCode2, FileText, GitBranch, LoaderCircle, Play, Radar, ShieldCheck, Terminal, TestTube2 } from "lucide-react";
import "./styles.css";
import "./approval.css";
import "./report.css";
import "./verification.css";

const API = `${(import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "") || ""}/api`;
type PlanItem = { task: string; files: string[]; reason: string; risk: string };
type Result = { request: string; impact_message: string; analysis_duration: number; affected_files: string[]; affected_components: string[]; affected_apis: string[]; database_components: string[]; dependencies: string[]; tests: string[]; security_risks: string[]; confidence: number; confidence_label: string; plan: PlanItem[]; evidence: { files: string[]; symbols: { name: string; kind: string; file: string; line: number }[] } };
type Verification = { status: string; reason?: string | null; framework: string | null; passed: number | null; failed: number | null; skipped: number | null; errors: number | null; total: number | null; duration: number | null; tests_discovered: number; command: string[][]; working_directory: string; output?: string; stdout?: string; stderr?: string; return_code?: number | null };
type ImplementationResult = { status: string; message: string; pre_commit_sha?: string | null; diff?: string | null; verification?: Verification | null; rolled_back?: boolean; files_changed?: string[]; allowed_files?: string[]; limitation?: string | null; patch_data?: { file: string; unified_diff: string }[] };
type StoredAnalysis = { id: string; repository_path: string; result: Result; verification?: Verification };
const countLabel = (value: number | null | undefined) => value == null ? "Unavailable" : String(value);

function App() {
  const [request, setRequest] = useState("Add phone-number authentication");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [analysisId, setAnalysisId] = useState("");
  const [verification, setVerification] = useState<Verification | null>(null);
  const [gitState, setGitState] = useState<{ clean: boolean; status: string[]; diff_stat: string[] } | null>(null);
  const [implementation, setImplementation] = useState<ImplementationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [implementationStage, setImplementationStage] = useState("");

  useEffect(() => {
    const savedId = window.localStorage.getItem("codeguardian.analysisId");
    if (!savedId) return;
    fetch(`${API}/analysis/${savedId}`).then(async response => {
      if (!response.ok) throw new Error("Saved analysis is unavailable.");
      const data = await response.json() as StoredAnalysis;
      setAnalysisId(data.id); setRepositoryPath(data.repository_path); setRequest(data.result.request); setResult(data.result); setVerification(data.verification ?? null);
    }).catch(exception => setError(exception instanceof Error ? exception.message : "Could not reload the saved analysis"));
  }, []);

  async function analyze() {
    setBusy(true); setError(""); setVerification(null); setGitState(null); setImplementation(null); setResult(null);
    try {
      const response = await fetch(`${API}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request, repository_path: repositoryPath }) });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Analysis failed");
      const data = await response.json(); setAnalysisId(data.id); setResult(data.result); window.localStorage.setItem("codeguardian.analysisId", data.id);
    } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not reach the API"); }
    finally { setBusy(false); }
  }

  async function verify() {
    setBusy(true); setError("");
    try { const response = await fetch(`${API}/verify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_path: repositoryPath, analysis_id: analysisId }) }); const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Verification request failed"); setVerification(data); const gitResponse = await fetch(`${API}/git/status?repository_path=${encodeURIComponent(repositoryPath)}`); if (gitResponse.ok) setGitState(await gitResponse.json()); }
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

  async function generateAndImplement() {
    if (!analysisId) return;
    setBusy(true); setError("");
    setImplementationStage("Generating code...");
    try {
      const response = await fetch(`${API}/implement`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis_id: analysisId, approved: true, generate_patch: true }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message ?? "Implementation generation failed");
      setImplementation(data);
      setImplementationStage(data.rolled_back ? "Implementation rolled back because verification failed." : "Implementation complete");
      setVerification(data.verification ?? null);
    } catch (exception) {
      const message = exception instanceof Error ? exception.message : "Generation failed";
      setError(message);
      setImplementationStage(message);
    } finally { setBusy(false); }
  }

  return <main className="shell">
    <header className="topbar"><div className="brand"><div className="brand-mark"><ShieldCheck size={20} /></div><div><strong>CODEGUARDIAN</strong><span>Application Maintenance Intelligence</span></div></div><div className="top-meta"><span className="live-dot" /> CLOUD DEPLOYMENT</div></header>
    <section className="hero"><div><p className="eyebrow">CHANGE CONTROL / 01</p><h1>Understand the blast radius<br /><em>before you touch the code.</em></h1><p className="lede">A structured maintenance workflow that turns a change request into evidence, risk, an implementation plan, and verified results.</p></div><div className="hero-stamp"><Radar size={19} /><span>REPOSITORY<br /><b>AWAITING PATH</b></span></div></section>
    <section className="request-bar"><div className="request-label"><span>01</span><div><b>Change request</b><small>Describe the maintenance task</small></div></div><input value={request} onChange={event => setRequest(event.target.value)} /><div className="request-label"><span>02</span><div><b>Repository path</b><small>Provide an actual repository to scan</small></div></div><input value={repositoryPath} onChange={event => setRepositoryPath(event.target.value)} placeholder="https://github.com/owner/repo  or  local/path (local dev only)" /><button className="primary" onClick={analyze} disabled={busy || request.length < 5 || repositoryPath.trim().length === 0}>{busy ? <LoaderCircle className="spin" size={17} /> : <Activity size={17} />} Analyze change <ArrowUpRight size={16} /></button></section>
    {error && <div className="error"><CircleAlert size={16} /> {error}</div>}
    <section className="pipeline"><Step label="Repository analysis" done={!!result} /><Step label="Code impact" done={!!result} /><Step label="Test impact" done={!!result} /><Step label="Dependency analysis" done={!!result} /><Step label="Security analysis" done={!!result} /></section>
    {!result ? <div className="empty-state"><Radar size={32} /><h2>Start with a change request</h2><p>Enter a repository path to scan its files, APIs, dependencies, tests, database evidence, and security findings.</p></div> : <>
      <div className="section-heading"><div><p className="eyebrow">IMPACT MAP / 02</p><h2>Evidence across the repository</h2></div><div className="confidence"><span>{result.confidence_label.toUpperCase()}</span><b>{result.confidence}%</b></div></div>
      <div className="grid-two"><ImpactMap result={result} /><aside className="risk-panel"><div className="panel-head"><span>Existing security findings</span><CircleAlert size={17} /></div>{result.security_risks.length ? result.security_risks.map((risk, index) => <div className="risk" key={risk}><span>R{String(index + 1).padStart(2, "0")}</span><p>{risk}</p></div>) : <p className="muted">No confirmed security vulnerability discovered.</p>}<div className="evidence-count"><FileCode2 size={16} /><b>{result.evidence.files.length}</b><span>files scanned</span><b>{result.evidence.symbols.length}</b><span>symbols indexed</span></div></aside></div>
      <div className="section-heading lower"><div><p className="eyebrow">IMPLEMENTATION / 03</p><h2>Suggested change sequence</h2></div><div className="heading-actions"><span className="muted">Analysis ID {analysisId.slice(0, 8)}</span><button className="secondary" onClick={approveImplementation} disabled={busy || implementation?.status === "approved_manifest"}><Check size={15} /> {implementation?.status === "approved_manifest" ? "Manifest approved" : "Approve manifest"}</button><button className="primary" onClick={generateAndImplement} disabled={busy || !analysisId}><LoaderCircle className={busy ? "spin" : ""} size={15} /> Generate &amp; Implement</button></div></div>
      <div className="plan-list">{result.plan.map((item, index) => <div className="plan-item" key={item.task}><div className="plan-number">0{index + 1}</div><div className="plan-content"><h3>{item.task}</h3><p>{item.reason}</p>{item.files.length > 0 && <div className="file-pills">{item.files.map(file => <code key={file}>{file}</code>)}</div>}</div><span className={`risk-tag ${item.risk}`}>{item.risk}</span><ChevronRight size={18} /></div>)}</div>
      {implementation && <div className="approval-note"><ShieldCheck size={17} /><span><b>{implementationStage || "Approval recorded."}</b> {implementation.message}{implementation.rolled_back ? " Implementation rolled back because verification failed." : ""}</span></div>}
      <div className="verification"><div><p className="eyebrow">VERIFICATION / 04</p><h2>Run the regression suite</h2><p>Execute the repository’s discovered test suite and attach the captured result.</p></div><button className="secondary" onClick={verify} disabled={busy}><Play size={16} /> Run tests</button>{verification && <div className={`test-result ${verification.status.toLowerCase()}`}><TestTube2 size={19} /><div><b>{verification.status.replace(/_/g, " ")}</b><p>{verification.reason}</p><div className="verification-counts">{[["Framework", verification.framework], ["Passed", verification.passed], ["Failed", verification.failed], ["Skipped", verification.skipped], ["Errors", verification.errors], ["Total", verification.total], ["Discovered files", verification.tests_discovered], ["Duration (s)", verification.duration]].map(([label, value]) => <span key={String(label)}><small>{label}</small><b>{countLabel(value as number | null)}</b></span>)}</div><small>Working directory: {verification.working_directory}</small><small>Command: {verification.command.flat().join(" ") || "Not executed"}</small><pre>{verification.output ?? verification.stderr ?? verification.stdout ?? verification.reason ?? ""}</pre></div></div>}</div>
      <section className="final-report"><div className="report-title"><FileText size={19} /><div><p className="eyebrow">FINAL REPORT / 05</p><h2>Change verification report</h2></div><span className={`report-status ${verification?.status === "TESTS_PASSED" ? "verified" : "pending"}`}>{verification?.status.replace(/_/g, " ") ?? "PENDING VERIFICATION"}</span></div><div className="report-grid"><div><small>REQUESTED CHANGE</small><b>{result.request}</b></div><div><small>FILES AFFECTED</small><b>{result.affected_files.length}</b></div><div><small>COMPONENTS</small><b>{result.affected_components.length}</b></div><div><small>TEST RESULT</small><b>{verification?.status.replace(/_/g, " ") ?? "Not run"}</b></div><div><small>WORKTREE</small><b>{gitState ? (gitState.clean ? "Clean" : `${gitState.status.length} changes`) : "Not checked"}</b></div></div></section>
    </>}
    <footer><span>CODEGUARDIAN / LOCAL-FIRST PROTOTYPE</span><span>Evidence before implementation</span></footer>
  </main>
}

function Step({ label, done }: { label: string; done: boolean }) { return <div className="step"><span className={done ? "step-icon done" : "step-icon"}>{done ? <Check size={13} /> : <span />}</span>{label}</div> }
function ImpactMap({ result }: { result: Result }) { const nodes = [{ label: "CHANGE REQUEST", value: result.request, type: "root" }, { label: "CODE IMPACT", value: `${result.affected_components.length} symbols`, type: "auth" }, { label: "API SURFACES", value: `${result.affected_apis.length} routes`, type: "surface" }, { label: "DATABASE", value: `${result.database_components.length} components`, type: "surface" }, { label: "TEST IMPACT", value: `${result.tests.length} test files`, type: "test" }]; return <div className="impact-map"><div className="map-caption"><GitBranch size={16} /> repository evidence <span>{result.impact_message}</span></div><div className="map-flow">{nodes.map((node, index) => <div className="map-node-wrap" key={node.label}><div className={`map-node ${node.type}`}><small>{node.label}</small><strong>{node.value}</strong></div>{index < nodes.length - 1 && <div className="connector"><span /></div>}</div>)}</div><EvidenceList label="Affected files" values={result.affected_files} /><EvidenceList label="API routes" values={result.affected_apis} /><EvidenceList label="Dependencies" values={result.dependencies} /><EvidenceList label="Database components" values={result.database_components} /><div className="map-footer"><span><FileCode2 size={15} /> {result.affected_files.length} affected files</span><span><Terminal size={15} /> {result.dependencies.length} dependencies</span><span><ShieldCheck size={15} /> {result.security_risks.length} security findings</span><span>Analysis {result.analysis_duration}s</span></div></div> }
function EvidenceList({ label, values }: { label: string; values: string[] }) { return <div className="evidence-list"><small>{label}</small>{values.length ? values.map(value => <code key={value}>{value}</code>) : <span>None discovered</span>}</div> }

const container = document.getElementById("root")!;
const rootHost = globalThis as typeof globalThis & { __codeguardianRoot?: ReturnType<typeof createRoot> };
const root = rootHost.__codeguardianRoot ?? createRoot(container);
rootHost.__codeguardianRoot = root;
root.render(<StrictMode><App /></StrictMode>);
