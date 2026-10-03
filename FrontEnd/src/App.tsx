/**
 * ============================================================================
 * MODULE: App.tsx — UI Orchestration + Screen Components
 * ============================================================================
 * PURPOSE
 *   This file owns the demo flow state and renders the five product areas:
 *     1. MandateSetup          — user writes an instruction, edits limits, activates
 *     2. ShoppingWorkspace     — agent shows candidates + recommendation
 *     3. AuthorizationScreen   — Transaction + Policy = ALLOW/DENY (the key moment)
 *     4. ResultScreen          — success / blocked / cancelled receipt
 *     5. AuditLog              — plain-language history + expandable technical detail
 *
 *   The root <App /> component is the ORCHESTRATOR: every user decision flows
 *   through its handler functions (activateMandate, propose, evaluate, checkout,
 *   revoke). Those handlers are EXACTLY where "user decisions" would be sent to
 *   your backend — each one already calls a CommerceGateway method or appends an
 *   audit event. See BACKEND_INTEGRATION.md §5 for the mapping table.
 *
 * BACKEND CONNECTION
 *   All backend access goes through ONE import below:
 *       import { commerceGateway } from './services/mockGateway';
 *   Swap it for './services/httpGateway' when your API is ready. The screens
 *   and handlers below do not change.
 * ============================================================================
 */

import { useState } from 'react';
import { AlertTriangle, ArrowRight, Bot, Check, CheckCircle2, ChevronDown, CircleDollarSign, Clock3, FileClock, LockKeyhole, RotateCcw, ShieldCheck, ShoppingBag, Sparkles, X, XCircle } from 'lucide-react';
import { catalog } from './data/catalog';
import { scenarios } from './data/scenarios';
import type { AuditEvent, AuthorizationResult, Mandate, Product, ScenarioId, Transaction, TransactionStatus } from './domain/types';
import type { CommerceGateway } from './services/contracts';
import { MockCommerceGateway } from './services/mockGateway';

/** Currency formatter for HKD display (no decimals in this demo). */
const fmt = (n: number) => new Intl.NumberFormat('en-HK', { style: 'currency', currency: 'HKD', maximumFractionDigits: 0 }).format(n);
const stamp = () => new Date().toISOString();
const makeId = (prefix: string) => `${prefix}-${Date.now().toString(36)}`;

/** The five navigable areas of the product, in flow order. */
type StepId = 'mandate' | 'shop' | 'authorize' | 'result' | 'audit';
const steps: { id: StepId; label: string; icon: typeof ShieldCheck }[] = [
  { id: 'mandate', label: 'Mandate', icon: ShieldCheck }, { id: 'shop', label: 'Agent shop', icon: Bot },
  { id: 'authorize', label: 'Authorize', icon: LockKeyhole }, { id: 'result', label: 'Result', icon: CheckCircle2 }, { id: 'audit', label: 'Audit log', icon: FileClock }
];

/**
 * App — root orchestrator.
 * Holds all flow state (mandate, selection, transaction, authorization, audit
 * events) and defines the handlers that move the demo between states.
 * USER-DECISION → BACKEND touchpoints are marked with [BACKEND-SEND].
 */
function App() {
  const [scenarioId, setScenarioId] = useState<ScenarioId>('allowed');
  const scenario = scenarios.find((s) => s.id === scenarioId)!;
  const [step, setStep] = useState<StepId>('mandate');
  const [instruction, setInstruction] = useState(scenario.request);
  const [mandate, setMandate] = useState<Mandate>({ ...scenario.mandate });
  const [selectedId, setSelectedId] = useState(scenario.productId);
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [authorization, setAuthorization] = useState<AuthorizationResult | null>(null);
  const [audits, setAudits] = useState<AuditEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);
  const selected = catalog.find((p) => p.id === selectedId)!;
  const finalTotal = selected.price + selected.shipping;

  /**
   * The backend gateway, seeded with the active scenario's mandate as defaults.
   * interpretMandate(input) merges these defaults (expiry, allowed merchants,
   * categories) with what the interpreter extracts from the user's text.
   * [BACKEND-SEND]: swap MockCommerceGateway for HttpCommerceGateway to go live.
   */
  const commerceGateway: CommerceGateway = new MockCommerceGateway(scenario.mandate);

  /**
   * Records one audit event. [BACKEND-SEND]: in production this becomes
   * auditRepository.append(event) so the server owns the audit trail.
   */
  const appendAudit = (eventType: string, actor: AuditEvent['actor'], summary: string, data: Record<string, unknown> = {}, transactionId?: string) => {
    setAudits((prev) => [{ id: makeId('audit'), transactionId, timestamp: stamp(), eventType, actor, summary, data }, ...prev]);
  };

  /** Loads a demo scenario and resets all flow state. */
  const loadScenario = (id: ScenarioId) => {
    const next = scenarios.find((s) => s.id === id)!;
    setScenarioId(id); setInstruction(next.request); setMandate({ ...next.mandate }); setSelectedId(next.productId);
    setTransaction(null); setAuthorization(null); setAudits([]); setInterpretError(null); setStep('mandate');
  };

  /**
   * Step 1 → 2. [BACKEND-SEND → LLM MODULE]
   * When the user clicks "Activate mandate", this handler bundles the two
   * things the LLM module needs —
   *     instruction : the natural-language text from the Screen 1 textarea
   *     priceLimit  : the "Maximum per purchase" value the user typed
   * into a MandateInterpretationInput and sends it through the gateway:
   *
   *     mock today : MockCommerceGateway.interpretMandate  (local parser)
   *     real later : POST /api/mandates/interpret          (LLM → validated Mandate)
   *
   * The returned structured Mandate replaces the editable policy fields, an
   * audit event records the interpretation, and the flow advances to the
   * agent workspace. Errors keep the user on Screen 1 with a readable message.
   */
  const activateMandate = async () => {
    setBusy(true);
    setInterpretError(null);
    try {
      const parsed = await commerceGateway.interpretMandate({ instruction, priceLimit: mandate.maxPerTransaction });
      setMandate(parsed);
      appendAudit('MANDATE_INTERPRETED', 'AGENT', `The agent interpreted your instruction into a ${fmt(parsed.maxPerTransaction ?? 0)} spending mandate.`, { input: { instruction, priceLimit: mandate.maxPerTransaction }, mandate: parsed });
      setStep('shop');
    } catch (err) {
      setInterpretError(err instanceof Error ? err.message : 'The agent could not interpret that instruction. Please try rephrasing it.');
    } finally {
      setBusy(false);
    }
  };

  /**
   * Step 2 → 3. Builds the Transaction proposal (subtotal + shipping = final total).
   * [BACKEND-SEND]: in production, POST this proposal to your transactions endpoint
   * so the server re-prices it from trusted data before authorization.
   */
  const propose = () => {
    const tx: Transaction = { id: makeId('txn'), productId: selected.id, merchantId: selected.merchantId, subtotal: selected.price, shipping: selected.shipping, total: finalTotal, currency: selected.currency, status: 'PROPOSED', createdAt: stamp() };
    setTransaction(tx);
    appendAudit('PRODUCT_SELECTED', 'AGENT', `Agent proposed ${selected.name} from ${selected.merchantName}.`, { productId: selected.id, untrustedContentIgnored: selected.id === 'mouse-untrusted' }, tx.id);
    appendAudit('TRANSACTION_PROPOSED', 'AGENT', `A ${fmt(finalTotal)} transaction was proposed for policy evaluation.`, { transaction: tx }, tx.id);
    setStep('authorize');
  };

  /**
   * Runs deterministic authorization. [BACKEND-SEND]: POST /api/authorization/evaluate
   * with { mandate, transaction } → AuthorizationResult. The UI only displays
   * the recorded decision; it never computes ALLOW/DENY itself.
   */
  const evaluate = async () => {
    if (!transaction) return;
    setBusy(true);
    const result = await commerceGateway.authorize(mandate, transaction);
    const nextStatus: TransactionStatus = result.decision === 'DENY' ? 'DENIED' : 'AUTHORIZED';
    setAuthorization(result); setTransaction({ ...transaction, status: nextStatus });
    appendAudit('POLICY_EVALUATED', 'POLICY_ENGINE', result.reason, { decision: result.decision, failedRules: result.failedRules, ruleChecks: result.ruleChecks, policyVersion: '2026.1' }, transaction.id);
    setBusy(false);
  };

  /**
   * Starts the simulated payment (PAYMENT_PENDING). [BACKEND-SEND]:
   * POST /api/transactions/:id/payment/start. In the 'revocation' scenario the
   * flow deliberately PAUSES here so the user can press "Revoke authorization".
   */
  const checkout = async () => {
    if (!transaction) return;
    setBusy(true);
    const pending = await commerceGateway.startPayment({ ...transaction, status: 'CHECKOUT' });
    setTransaction(pending); appendAudit('PAYMENT_PENDING', 'PAYMENT_SIMULATOR', 'Simulated payment is pending. No real money has moved.', { status: pending.status }, pending.id);
    setBusy(false);
    if (scenarioId !== 'revocation') await completePayment(pending, mandate);
  };

  /**
   * Completes (or cancels) the payment. [BACKEND-SEND]:
   * POST /api/transactions/:id/payment/complete — the server MUST re-check the
   * mandate atomically here so a mid-checkout revocation cannot complete.
   */
  const completePayment = async (tx = transaction, currentMandate = mandate) => {
    if (!tx) return;
    setBusy(true);
    const completed = await commerceGateway.completePayment(tx, currentMandate);
    setTransaction(completed);
    appendAudit(completed.status === 'COMPLETED' ? 'PAYMENT_COMPLETED' : 'TRANSACTION_CANCELLED', 'PAYMENT_SIMULATOR', completed.status === 'COMPLETED' ? 'Simulated payment completed successfully.' : 'Transaction cancelled before completion.', { status: completed.status, simulated: true }, completed.id);
    setBusy(false); setStep('result');
  };

  /**
   * USER REVOCATION — the critical safety decision. [BACKEND-SEND]:
   * PATCH /api/mandates/:id/revoke (sets revokedAt server-side), THEN the
   * pending payment is re-authorized and cancelled. Order matters: revoke
   * first, complete never.
   */
  const revoke = async () => {
    if (!transaction) return;
    const revoked = { ...mandate, revokedAt: stamp() };
    setMandate(revoked);
    appendAudit('AUTHORIZATION_REVOKED', 'USER', 'You revoked authority while payment was pending.', { revokedAt: revoked.revokedAt }, transaction.id);
    const result = await commerceGateway.authorize(revoked, transaction);
    setAuthorization(result);
    await completePayment(transaction, revoked);
  };

  return <div className="app-shell">
    <Header />
    <main className="main">
      <DemoBar active={scenarioId} onSelect={loadScenario} />
      <StepNav current={step} onChange={setStep} />
      {step === 'mandate' && <MandateSetup instruction={instruction} setInstruction={setInstruction} mandate={mandate} setMandate={setMandate} busy={busy} error={interpretError} onContinue={activateMandate} />}
      {step === 'shop' && <ShoppingWorkspace instruction={instruction} mandate={mandate} selectedId={selectedId} setSelectedId={setSelectedId} onPropose={propose} />}
      {step === 'authorize' && transaction && <AuthorizationScreen product={selected} transaction={transaction} mandate={mandate} result={authorization} busy={busy} onEvaluate={evaluate} onCheckout={checkout} onRevoke={revoke} onResult={() => setStep('result')} />}
      {step === 'result' && <ResultScreen transaction={transaction} product={selected} authorization={authorization} onAudit={() => setStep('audit')} onReset={() => loadScenario(scenarioId)} />}
      {step === 'audit' && <AuditLog events={audits} />}
    </main>
  </div>;
}

/** Sticky top bar: product brand + the persistent "no real money" badge. */
function Header() { return <header className="header"><div className="brand"><div className="brand-mark"><ShieldCheck size={21}/></div><div><strong>Guardrail</strong><span>Agentic commerce</span></div></div><div className="prototype-badge"><span/> Prototype · no real money</div></header>; }

/** Demo Mode bar — judge-facing one-click scenario switcher, rendered from data/scenarios.ts. */
function DemoBar({ active, onSelect }: { active: ScenarioId; onSelect: (id: ScenarioId) => void }) { return <section className="demo-bar"><div className="demo-copy"><span className="eyebrow"><Sparkles size={14}/> Demo mode</span><p>Switch scenarios to test each guardrail instantly.</p></div><div className="scenario-pills">{scenarios.map((s, i) => <button key={s.id} className={active === s.id ? 'active' : ''} onClick={() => onSelect(s.id)}><span>{i + 1}</span>{s.shortTitle}</button>)}</div></section>; }

/** Horizontal step indicator; steps are clickable for free navigation. */
function StepNav({ current, onChange }: { current: StepId; onChange: (id: StepId) => void }) { const index = steps.findIndex(s => s.id === current); return <nav className="step-nav" aria-label="Purchase flow">{steps.map((s, i) => { const Icon=s.icon; return <button key={s.id} className={`${s.id === current ? 'current' : ''} ${i < index ? 'done' : ''}`} onClick={() => onChange(s.id)}><span className="step-icon">{i < index ? <Check size={15}/> : <Icon size={15}/>}</span><span>{s.label}</span></button>})}</nav>; }

/**
 * SCREEN 1 — Mandate Setup.
 * Left: natural-language instruction textarea (this text is what gets sent to
 * your LLM endpoint via commerceGateway.interpretMandate when the button is
 * clicked — see activateMandate in App.tsx).
 * Right: editable structured mandate fields (limits, category, expiry) that
 * the deterministic policy engine enforces.
 * `busy` shows the interpreting state on the button; `error` shows any failure
 * from the interpreter so the user can rephrase and retry.
 */
function MandateSetup({ instruction, setInstruction, mandate, setMandate, busy, error, onContinue }: { instruction: string; setInstruction: (v:string)=>void; mandate: Mandate; setMandate:(m:Mandate)=>void; busy: boolean; error: string|null; onContinue:()=>void }) { return <section className="screen"><div className="screen-heading"><span className="step-kicker">Step 1 · Set the boundary</span><h1>Delegate a purchase,<br/><em>not your control.</em></h1><p>Tell your shopping agent what you need. A structured spending mandate keeps every purchase inside your rules.</p></div><div className="two-col">
  <div className="card instruction-card"><div className="card-title"><div className="icon-box purple"><Bot size={19}/></div><div><h2>Your instruction</h2><p>Use natural language — the agent handles the rest.</p></div></div><label className="sr-only" htmlFor="instruction">Shopping instruction</label><textarea id="instruction" value={instruction} onChange={e=>setInstruction(e.target.value)} /><div className="trust-note"><LockKeyhole size={16}/><span><strong>The agent can interpret.</strong> It cannot authorize spending.</span></div></div>
  <div className="card policy-card"><div className="card-title"><div className="icon-box green"><ShieldCheck size={19}/></div><div><h2>Enforceable mandate</h2><p>These rules are checked by deterministic code.</p></div><span className={`status-chip ${mandate.revokedAt ? 'red' : 'green'}`}>{mandate.revokedAt ? 'Revoked' : 'Ready'}</span></div><div className="field-grid"><label><span>Maximum per purchase</span><div className="input-prefix"><b>HK$</b><input type="number" value={mandate.maxPerTransaction ?? ''} onChange={e=>setMandate({...mandate,maxPerTransaction:Number(e.target.value)})}/></div></label><label><span>Daily spending limit</span><div className="input-prefix"><b>HK$</b><input type="number" value={mandate.maxDailySpend ?? ''} onChange={e=>setMandate({...mandate,maxDailySpend:Number(e.target.value)})}/></div></label><label><span>Allowed category</span><div className="select-like">{mandate.allowedCategories?.[0]}<ChevronDown size={15}/></div></label><label><span>Expires</span><input type="date" value={mandate.expiresAt.slice(0,10)} onChange={e=>setMandate({...mandate,expiresAt:`${e.target.value}T23:59:59.000Z`})}/></label></div><div className="merchant-row"><span>Approved merchants</span><div><span className="tag">Campus Tech <X size={12}/></span><span className="tag">Student Store <X size={12}/></span></div></div>{error&&<div className="error-note"><AlertTriangle size={15}/><span>{error}</span></div>}<button className="primary wide" disabled={busy} onClick={onContinue}>{busy?'Interpreting…':'Activate mandate'} <ArrowRight size={17}/></button></div>
</div></section>; }

/**
 * SCREEN 2 — Agent Shopping Workspace.
 * Shows the instruction the agent is working on, candidate products with
 * price + shipping + final total, and a proposal bar. The agent recommends;
 * the mandate boundary chip stays visible so the user keeps context.
 */
function ShoppingWorkspace({ instruction, mandate, selectedId, setSelectedId, onPropose }: { instruction:string; mandate:Mandate; selectedId:string; setSelectedId:(id:string)=>void; onPropose:()=>void }) { const candidates = catalog.filter(p => p.category === 'Computer Accessories').slice(0, scenarioProductCount(selectedId)); const picked = catalog.find(p=>p.id===selectedId)!; return <section className="screen"><div className="screen-heading row-heading"><div><span className="step-kicker">Step 2 · Agent workspace</span><h1>Your agent found <em>options.</em></h1><p>It can compare and recommend. Your mandate still decides what can be purchased.</p></div><div className="boundary-card"><ShieldCheck size={19}/><div><strong>{fmt(mandate.maxPerTransaction ?? 0)} boundary active</strong><span>{mandate.allowedMerchants?.length} approved merchants · {mandate.allowedCategories?.[0]}</span></div></div></div><div className="agent-thinking"><div className="bot-dot"><Bot size={20}/></div><div><span>Agent request</span><p>“{instruction}”</p></div><span className="status-chip purple">Recommendation ready</span></div><div className="product-grid">{candidates.map((p, i)=><ProductCard key={p.id} product={p} selected={p.id===selectedId} recommended={i===0 && selectedId!=='mouse-untrusted'} onSelect={()=>setSelectedId(p.id)}/>)}</div>{selectedId==='mouse-untrusted' && <div className="warning-banner"><AlertTriangle size={19}/><div><strong>Untrusted content isolated</strong><p>The product description contains instructions. They are treated as data and cannot change the mandate.</p></div></div>}<div className="proposal-bar"><div><span>Agent proposes</span><strong>{picked.name}</strong><small>{picked.merchantName} · {fmt(picked.price)} + {fmt(picked.shipping)} shipping</small></div><div className="proposal-total"><span>Estimated total</span><strong>{fmt(picked.price+picked.shipping)}</strong></div><button className="primary" onClick={onPropose}>Propose purchase <ArrowRight size={17}/></button></div></section>; }

/** How many products each scenario shows (keeps the grid tidy per demo). */
const scenarioProductCount = (id:string) => id==='mouse-untrusted' ? 6 : id==='mouse-pro' ? 2 : 3;

/** One selectable product card: merchant, rating, description, price breakdown, final total. */
function ProductCard({ product, selected, recommended, onSelect }: {product:Product; selected:boolean; recommended:boolean; onSelect:()=>void}) { return <button className={`product-card ${selected?'selected':''}`} onClick={onSelect}><div className="product-art"><MouseArt/><span className="merchant-badge">{product.merchantName}</span>{recommended&&<span className="recommend-badge"><Sparkles size={12}/> Best fit</span>}</div><div className="product-info"><div className="rating">★ {product.rating}</div><h3>{product.name}</h3><p>{product.description}</p><div className="price-row"><strong>{fmt(product.price)}</strong><span>+ {fmt(product.shipping)} shipping</span></div><div className="final-line"><span>Final total</span><b>{fmt(product.price+product.shipping)}</b></div></div></button>; }

/** Pure-CSS mouse illustration (avoids binary image assets). */
function MouseArt(){return <div className="mouse-art"><div className="mouse-wheel"/><div className="mouse-line"/></div>}

/**
 * SCREEN 3 — Authorization / Checkout: the key visual moment.
 * Three panels: Transaction (bill + final total) + Policy (limit comparison +
 * ✓/✕ rule checks) = Decision (DecisionPanel). The decision comes from
 * recorded AuthorizationResult data, never from generated prose.
 */
function AuthorizationScreen({ product, transaction, mandate, result, busy, onEvaluate, onCheckout, onRevoke, onResult }: {product:Product;transaction:Transaction;mandate:Mandate;result:AuthorizationResult|null;busy:boolean;onEvaluate:()=>void;onCheckout:()=>void;onRevoke:()=>void;onResult:()=>void}) { const pending=transaction.status==='PAYMENT_PENDING'; return <section className="screen"><div className="screen-heading centered"><span className="step-kicker">Step 3 · Deterministic authorization</span><h1>Transaction <span>+</span> Policy</h1><p>The policy engine—not the AI—makes the final, reproducible spending decision.</p></div><div className="equation-layout"><div className="card checkout-card"><div className="card-title"><div className="icon-box blue"><ShoppingBag size={19}/></div><div><h2>Transaction</h2><p>{transaction.id}</p></div></div><div className="mini-product"><MouseArt/><div><strong>{product.name}</strong><span>{product.merchantName}</span></div></div><div className="bill"><div><span>Subtotal</span><b>{fmt(transaction.subtotal)}</b></div><div><span>Shipping</span><b>{fmt(transaction.shipping)}</b></div><div className="total"><span>Final total</span><strong>{fmt(transaction.total)}</strong></div></div><div className="simulated-label"><CircleDollarSign size={16}/> SIMULATED CHECKOUT · no real charge</div></div><div className="operator">+</div><div className="card rules-card"><div className="card-title"><div className="icon-box green"><ShieldCheck size={19}/></div><div><h2>Your policy</h2><p>Policy version 2026.1</p></div></div><div className="limit-compare"><div><span>Authorized limit</span><strong>{fmt(mandate.maxPerTransaction ?? 0)}</strong></div><div><span>Transaction total</span><strong className={transaction.total>(mandate.maxPerTransaction??Infinity)?'danger':''}>{fmt(transaction.total)}</strong></div></div>{result ? <div className="rule-list">{result.ruleChecks.map(r=><div key={r.id}><span className={r.passed?'pass':'fail'}>{r.passed?<Check size={14}/>:<X size={14}/>}</span><div><strong>{r.label}</strong><small>{r.detail}</small></div></div>)}</div> : <div className="waiting-rules"><LockKeyhole size={26}/><strong>Ready to evaluate</strong><p>Six deterministic rules will run against the final total.</p></div>}</div><div className="operator">=</div><DecisionPanel result={result} busy={busy} pending={pending} onEvaluate={onEvaluate} onCheckout={onCheckout} onRevoke={onRevoke} onResult={onResult}/></div></section>; }

/**
 * The decision column of Screen 3. Four states:
 *   no result → "Run authorization"; DENY → prominent denial + reason;
 *   PAYMENT_PENDING → revoke button; ALLOW → proceed to simulated payment.
 */
function DecisionPanel({result,busy,pending,onEvaluate,onCheckout,onRevoke,onResult}:{result:AuthorizationResult|null;busy:boolean;pending:boolean;onEvaluate:()=>void;onCheckout:()=>void;onRevoke:()=>void;onResult:()=>void}) { if(!result) return <div className="decision-card neutral"><div className="decision-icon"><LockKeyhole/></div><span>Policy engine</span><h2>Awaiting<br/>evaluation</h2><p>Rules are evaluated from recorded data, never generated after the event.</p><button className="primary wide" disabled={busy} onClick={onEvaluate}>{busy?'Evaluating…':'Run authorization'} <ArrowRight size={17}/></button></div>; if(result.decision==='DENY') return <div className="decision-card deny"><div className="decision-icon"><XCircle/></div><span>Decision</span><h2>DENIED</h2><p>{result.reason}</p><button className="secondary wide" onClick={onResult}>View result <ArrowRight size={17}/></button></div>; if(pending) return <div className="decision-card pending"><div className="decision-icon"><Clock3/></div><span>Simulated payment</span><h2>PENDING</h2><p>Authorization passed. Revoke now to prove the transaction cannot complete.</p><button className="danger-button wide" disabled={busy} onClick={onRevoke}>Revoke authorization</button></div>; return <div className="decision-card allow"><div className="decision-icon"><CheckCircle2/></div><span>Decision</span><h2>ALLOWED</h2><p>{result.reason}</p><button className="primary wide" disabled={busy} onClick={onCheckout}>{busy?'Starting…':'Proceed to simulated payment'} <ArrowRight size={17}/></button></div>; }

/**
 * SCREEN 4 — Transaction Result.
 * Success (COMPLETED), blocked (DENIED), or cancelled (CANCELLED) hero +
 * receipt grid. Always carries the SIMULATED PAYMENT badge.
 */
function ResultScreen({transaction,product,authorization,onAudit,onReset}:{transaction:Transaction|null;product:Product;authorization:AuthorizationResult|null;onAudit:()=>void;onReset:()=>void}) { const state=transaction?.status; const success=state==='COMPLETED'; const cancelled=state==='CANCELLED'; return <section className="screen result-screen"><div className={`result-hero ${success?'success':cancelled?'cancelled':'blocked'}`}><div className="result-icon">{success?<CheckCircle2/>:cancelled?<AlertTriangle/>:<XCircle/>}</div><span className="step-kicker">Step 4 · Transaction result</span><h1>{success?'Purchase completed':cancelled?'Authorization revoked':'Purchase blocked'}</h1><p>{success?'Your agent completed the simulated purchase within every boundary.':cancelled?'The payment was stopped before completion. No money was transferred.':authorization?.reason ?? 'Run authorization to see a transaction result.'}</p><span className="simulated-pill">SIMULATED PAYMENT · NO REAL MONEY</span></div>{transaction&&<div className="receipt card"><div><span>Transaction ID</span><strong>{transaction.id}</strong></div><div><span>Product</span><strong>{product.name}</strong></div><div><span>Merchant</span><strong>{product.merchantName}</strong></div><div><span>Final amount</span><strong>{fmt(transaction.total)}</strong></div><div><span>Status</span><strong className={`state-text ${state?.toLowerCase()}`}>{state}</strong></div></div>}<div className="result-actions"><button className="primary" onClick={onAudit}>View audit trail <ArrowRight size={17}/></button><button className="secondary" onClick={onReset}><RotateCcw size={16}/> Replay scenario</button></div></section>; }

/**
 * SCREEN 5 — Audit Log.
 * Plain-language summary per event first; raw recorded data (mandate, rule
 * checks, timestamps, policy version) behind a <details> disclosure.
 * [BACKEND-SEND]: in production these events come from GET /api/audit.
 */
function AuditLog({events}:{events:AuditEvent[]}) { return <section className="screen"><div className="screen-heading row-heading"><div><span className="step-kicker">Step 5 · Verifiable history</span><h1>Every decision,<br/><em>accounted for.</em></h1><p>Plain-language summaries first. Exact recorded inputs are available below.</p></div><div className="audit-count"><FileClock/><strong>{events.length}</strong><span>recorded events</span></div></div>{events.length===0?<div className="empty-state card"><FileClock/><h2>No events yet</h2><p>Activate a mandate and run a scenario to create an audit trail.</p></div>:<div className="timeline">{events.map((e,i)=><details className="audit-event" key={e.id} open={i===0}><summary><div className={`timeline-dot actor-${e.actor.toLowerCase()}`}>{actorIcon(e.actor)}</div><div className="audit-main"><div><span className="actor-label">{e.actor.replaceAll('_',' ')}</span><time>{new Date(e.timestamp).toLocaleTimeString('en-HK',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time></div><h3>{e.summary}</h3><small>{e.eventType.replaceAll('_',' ')}</small></div><ChevronDown size={18}/></summary><div className="technical"><span>Technical details · recorded, not generated</span><pre>{JSON.stringify(e.data,null,2)}</pre></div></details>)}</div>}</section>; }

/** Picks the icon shown in the audit timeline for each actor type. */
function actorIcon(actor:AuditEvent['actor']){if(actor==='USER')return <ShieldCheck/>;if(actor==='AGENT')return <Bot/>;if(actor==='POLICY_ENGINE')return <LockKeyhole/>;return <CircleDollarSign/>}
export default App;
