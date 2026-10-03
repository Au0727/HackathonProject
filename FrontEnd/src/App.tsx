/**
 * ============================================================================
 * MODULE: App.tsx — UI Orchestration + Screen Components
 * ============================================================================
 * PURPOSE
 *   This file owns the demo flow state and renders mandate, agent shop, result,
 *   and audit views. Authorization runs inline when the user confirms.
 *
 *   The root <App /> component is the ORCHESTRATOR: every user decision flows
 *   through its handler functions (activateMandate, confirmPurchase). Those
 *   handlers are where "user decisions" are sent to
 *   your backend — each one already calls a CommerceGateway method or appends an
 *   audit event. See BACKEND_INTEGRATION.md §5 for the mapping table.
 *
 * BACKEND CONNECTION
 *   The HTTP gateway is the only backend integration surface. Search results,
 *   authorization, simulated payment, and audit records are obtained through
 *   the Python API; presentation and flow state remain in this component.
 * ============================================================================
 */

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowRight, Bot, Check, CheckCircle2, ChevronDown, CircleDollarSign, FileClock, LockKeyhole, RotateCcw, ShieldCheck, ShoppingBag, Sparkles, XCircle } from 'lucide-react';
import { catalog } from './data/catalog';
import { scenarios } from './data/scenarios';
import type { AuditEvent, AuthorizationResult, Mandate, Product, ScenarioId, Transaction } from './domain/types';
import { auditRepository, HttpCommerceGateway } from './services/httpGateway';

/** Currency formatter for HKD display (no decimals in this demo). */
const fmt = (n: number) => new Intl.NumberFormat('en-HK', { style: 'currency', currency: 'HKD', maximumFractionDigits: 0 }).format(n);
const stamp = () => new Date().toISOString();
const makeId = (prefix: string) => `${prefix}-${Date.now().toString(36)}`;

type StepId = 'mandate' | 'shop' | 'result' | 'audit';
type ManualOverrides = {
  maxPerTransaction: string;
  maxDailySpend: string;
  allowedCategory: string;
  expiresAt: string;
  allowedMerchants: string;
};
const emptyOverrides = (): ManualOverrides => ({
  maxPerTransaction: '',
  maxDailySpend: '',
  allowedCategory: '',
  expiresAt: '',
  allowedMerchants: '',
});
const blankMandate = (id: string): Mandate => ({ id, expiresAt: '' });
const demoScenarios = scenarios.filter((scenario) => scenario.id !== 'expired' && scenario.id !== 'revocation');
const steps: { id: Exclude<StepId, 'audit'>; label: string; icon: typeof ShieldCheck }[] = [
  { id: 'mandate', label: 'Mandate', icon: ShieldCheck },
  { id: 'shop', label: 'Agent shop', icon: Bot },
  { id: 'result', label: 'Payment / Result', icon: CircleDollarSign },
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
  const [mandate, setMandate] = useState<Mandate>(blankMandate(scenario.mandate.id));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [manualOverrides, setManualOverrides] = useState<ManualOverrides>(emptyOverrides);
  const [selectedId, setSelectedId] = useState(scenario.productId);
  const [products, setProducts] = useState<Product[]>(catalog);
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [authorization, setAuthorization] = useState<AuthorizationResult | null>(null);
  const [audits, setAudits] = useState<AuditEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);
  const [securityWarning, setSecurityWarning] = useState<string | null>(null);
  const activeProductId = products.some((product) => product.id === selectedId)
    ? selectedId
    : products[0]?.id;
  const selected = products.find((product) => product.id === activeProductId);

  /**
   * No scenario policy is passed as an implicit hard constraint.
   */
  const commerceGateway: HttpCommerceGateway = useMemo(
    () => new HttpCommerceGateway(),
    [],
  );

  useEffect(() => {
    let active = true;
    void commerceGateway.getCatalog().then((remoteProducts) => {
      if (!active || remoteProducts.length === 0) return;
      setProducts(remoteProducts);
      setSelectedId((current) =>
        remoteProducts.some((product) => product.id === current) ? current : remoteProducts[0].id,
      );
    }).catch((error: unknown) => {
      if (active) setInterpretError(error instanceof Error ? error.message : 'Could not load the backend catalog.');
    });
    void auditRepository.list().then((events) => {
      if (active) setAudits(events);
    }).catch((error: unknown) => {
      if (active) setInterpretError(error instanceof Error ? error.message : 'Could not load backend audit events.');
    });
    return () => { active = false; };
  }, [commerceGateway]);

  /** Records the event locally and persists it to the backend audit log. */
  const appendAudit = (eventType: string, actor: AuditEvent['actor'], summary: string, data: Record<string, unknown> = {}, transactionId?: string) => {
    const event: AuditEvent = { id: makeId('audit'), transactionId, timestamp: stamp(), eventType, actor, summary, data };
    setAudits((prev) => [event, ...prev]);
    void auditRepository.append(event).catch((error: unknown) => {
      setInterpretError(error instanceof Error ? error.message : 'Could not persist the audit event.');
    });
  };

  /** Loads a demo scenario and resets all flow state. */
  const loadScenario = (id: ScenarioId) => {
    const next = scenarios.find((s) => s.id === id)!;
    setScenarioId(id); setInstruction(next.request); setMandate(blankMandate(next.mandate.id)); setManualOverrides(emptyOverrides()); setAdvancedOpen(false); setSelectedId(next.productId);
    setTransaction(null); setAuthorization(null); setAudits([]); setInterpretError(null); setSecurityWarning(null); setStep('mandate');
  };

  /**
   * Step 1 → 2. [BACKEND-SEND → LLM MODULE]
   * When the user clicks "Activate mandate", this handler bundles the two
   * things the LLM module needs —
   *     instruction : the natural-language text from the Screen 1 textarea
   * Explicit form overrides are applied only when a field has a user-entered
   * value. The prompt remains unchanged even if the controls are later collapsed.
   */
  const activateMandate = async () => {
    setBusy(true);
    setInterpretError(null);
    setSecurityWarning(null);
    try {
      const hasManualOverrides = Object.values(manualOverrides).some((value) => value.trim() !== '');
      const priceLimit = manualOverrides.maxPerTransaction.trim()
        ? Number(manualOverrides.maxPerTransaction)
        : undefined;
      if (priceLimit !== undefined && (!Number.isFinite(priceLimit) || priceLimit < 0)) {
        throw new Error('Maximum per purchase must be a valid non-negative amount.');
      }
      const dailyLimit = manualOverrides.maxDailySpend.trim()
        ? Number(manualOverrides.maxDailySpend)
        : undefined;
      if (dailyLimit !== undefined && (!Number.isFinite(dailyLimit) || dailyLimit < 0)) {
        throw new Error('Daily spending limit must be a valid non-negative amount.');
      }
      const parsed = await commerceGateway.interpretMandate({ instruction, priceLimit });
      const manualMerchants = manualOverrides.allowedMerchants
        .split(',')
        .map((merchant) => merchant.trim())
        .filter(Boolean);
      const nextMandate: Mandate = {
        ...parsed,
        ...(dailyLimit === undefined
          ? {}
          : { maxDailySpend: dailyLimit }
        ),
        ...(manualOverrides.allowedCategory.trim()
          ? { allowedCategories: [manualOverrides.allowedCategory.trim()] }
          : {}),
        ...(manualOverrides.expiresAt
          ? { expiresAt: `${manualOverrides.expiresAt}T23:59:59.000Z` }
          : {}),
        ...(manualMerchants.length ? { allowedMerchants: manualMerchants } : {}),
      };
      setMandate(nextMandate);
      appendAudit('MANDATE_INTERPRETED', 'AGENT', 'The agent interpreted your instruction into a structured mandate.', { input: { instruction, manualOverrides: hasManualOverrides ? manualOverrides : null }, mandate: nextMandate });
      setStep('shop');
      try {
        const searchResult = await commerceGateway.search();
        setProducts(searchResult.products);
        setSelectedId(searchResult.products[0]?.id ?? '');
        if (searchResult.securityRejections > 0) {
          const count = searchResult.securityRejections;
          setSecurityWarning(
            `${count} product listing${count === 1 ? ' was' : 's were'} excluded after a potential AI-manipulation attempt was detected.`,
          );
        }
        if (!searchResult.products.length && searchResult.stopReason) {
          setInterpretError(searchResult.stopReason);
        }
      } catch (error) {
        setProducts([]);
        setSelectedId('');
        setSecurityWarning(null);
        setInterpretError(error instanceof Error ? error.message : 'The shopping pipeline could not return an authorized product.');
      }
    } catch (err) {
      setInterpretError(err instanceof Error ? err.message : 'The agent could not interpret that instruction. Please try rephrasing it.');
      setProducts([]);
      setSelectedId('');
      setStep('shop');
    } finally {
      setBusy(false);
    }
  };

  /** Confirm runs server authorization and the simulated payment loop inline. */
  const confirmPurchase = async () => {
    if (!selected) {
      setInterpretError('No authorized product is available to confirm.');
      return;
    }
    const total = selected.price + selected.shipping;
    const proposed: Transaction = {
      id: makeId('txn'),
      productId: selected.id,
      merchantId: selected.merchantId,
      subtotal: selected.price,
      shipping: selected.shipping,
      total,
      currency: selected.currency,
      status: 'PROPOSED',
      createdAt: stamp(),
    };
    setTransaction(proposed);
    appendAudit('PRODUCT_SELECTED', 'AGENT', `Agent proposed ${selected.name} from ${selected.merchantName}.`, { productId: selected.id, untrustedContentIgnored: selected.id === 'mouse-untrusted' }, proposed.id);
    appendAudit('TRANSACTION_PROPOSED', 'AGENT', `A ${fmt(total)} transaction was proposed for policy evaluation.`, { transaction: proposed }, proposed.id);
    setBusy(true);
    setInterpretError(null);
    try {
      const result = await commerceGateway.authorize(mandate, proposed);
      setAuthorization(result);
      appendAudit('POLICY_EVALUATED', 'POLICY_ENGINE', result.reason, { decision: result.decision, failedRules: result.failedRules, ruleChecks: result.ruleChecks, policyVersion: '2026.1' }, proposed.id);
      if (result.decision !== 'ALLOW') {
        setTransaction({ ...proposed, status: 'DENIED' });
        setInterpretError(result.reason || 'The Financial Firewall did not authorize this purchase.');
        return;
      }
      const pending = await commerceGateway.startPayment({ ...proposed, status: 'CHECKOUT' });
      setTransaction(pending);
      appendAudit('PAYMENT_PENDING', 'PAYMENT_SIMULATOR', 'Simulated payment is pending. No real money has moved.', { status: pending.status }, pending.id);
      const completed = await commerceGateway.completePayment(pending, mandate);
      setTransaction(completed);
      appendAudit(completed.status === 'COMPLETED' ? 'PAYMENT_COMPLETED' : 'TRANSACTION_CANCELLED', 'PAYMENT_SIMULATOR', completed.status === 'COMPLETED' ? 'Simulated payment completed successfully.' : 'Transaction cancelled before completion.', { status: completed.status, simulated: true }, completed.id);
      if (completed.status === 'COMPLETED' || completed.status === 'CANCELLED') setStep('result');
      else setInterpretError('The simulated payment did not complete.');
    } catch (error) {
      setInterpretError(error instanceof Error ? error.message : 'Authorization or simulated payment failed.');
    } finally {
      setBusy(false);
    }
  };

  return <div className="app-shell">
    <Header />
    <main className="main">
      <DemoBar active={scenarioId} onSelect={loadScenario} />
      <StepNav current={step} onChange={setStep} />
      {step === 'mandate' && <MandateSetup instruction={instruction} setInstruction={setInstruction} advancedOpen={advancedOpen} setAdvancedOpen={setAdvancedOpen} manualOverrides={manualOverrides} setManualOverrides={setManualOverrides} busy={busy} error={interpretError} onContinue={activateMandate} />}
      {step === 'shop' && <ShoppingWorkspace products={products} instruction={instruction} mandate={mandate} selectedId={activeProductId ?? ''} setSelectedId={setSelectedId} error={interpretError} securityWarning={securityWarning} busy={busy} onCancel={() => setStep('mandate')} onConfirm={confirmPurchase} />}
      {step === 'result' && <ResultScreen transaction={transaction} product={selected ?? catalog[0]} authorization={authorization} onAudit={() => setStep('audit')} onReset={() => loadScenario(scenarioId)} />}
      {step === 'audit' && <AuditLog events={audits} />}
    </main>
  </div>;
}

/** Sticky top bar: product brand + the persistent "no real money" badge. */
function Header() { return <header className="header"><div className="brand"><div className="brand-mark"><ShieldCheck size={21}/></div><div><strong>Guardrail</strong><span>Agentic commerce</span></div></div><div className="prototype-badge"><span/> Prototype · no real money</div></header>; }

/** Demo Mode bar — judge-facing one-click scenario switcher, rendered from data/scenarios.ts. */
function DemoBar({ active, onSelect }: { active: ScenarioId; onSelect: (id: ScenarioId) => void }) { return <section className="demo-bar"><div className="demo-copy"><span className="eyebrow"><Sparkles size={14}/> Demo mode</span><p>Switch scenarios to test each guardrail instantly.</p></div><div className="scenario-pills">{demoScenarios.map((s, i) => <button key={s.id} className={active === s.id ? 'active' : ''} onClick={() => onSelect(s.id)}><span>{i + 1}</span>{s.shortTitle}</button>)}</div></section>; }

/** Three visible stages; the audit view is linked from the receipt only. */
function StepNav({ current, onChange }: { current: StepId; onChange: (id: StepId) => void }) {
  const visibleStep = current === 'audit' ? 'result' : current;
  const index = steps.findIndex((step) => step.id === visibleStep);
  return <nav className="step-nav" aria-label="Purchase flow">
    {steps.map((step, stepIndex) => {
      const Icon = step.icon;
      return <button key={step.id} className={`${step.id === visibleStep ? 'current' : ''} ${stepIndex < index ? 'done' : ''}`} disabled={stepIndex > index} onClick={() => onChange(step.id)}>
        <span className="step-icon">{stepIndex < index ? <Check size={15}/> : <Icon size={15}/>}</span>
        <span>{step.label}</span>
      </button>;
    })}
  </nav>;
}

/**
 * SCREEN 1 — Mandate Setup.
 * Left: natural-language instruction textarea (this text is what gets sent to
 * your LLM endpoint via commerceGateway.interpretMandate when the button is
 * clicked — see activateMandate in App.tsx).
 * Optional overrides stay collapsed and empty until the user enters them.
 * `busy` shows the interpreting state on the button; `error` shows any failure
 * from the interpreter so the user can rephrase and retry.
 */
function MandateSetup({ instruction, setInstruction, advancedOpen, setAdvancedOpen, manualOverrides, setManualOverrides, busy, error, onContinue }: {
  instruction: string;
  setInstruction: (value: string) => void;
  advancedOpen: boolean;
  setAdvancedOpen: (open: boolean) => void;
  manualOverrides: ManualOverrides;
  setManualOverrides: (value: ManualOverrides) => void;
  busy: boolean;
  error: string | null;
  onContinue: () => void;
}) {
  const updateOverride = (key: keyof ManualOverrides, value: string) =>
    setManualOverrides({ ...manualOverrides, [key]: value });
  return <section className="screen">
    <div className="screen-heading">
      <span className="step-kicker">Step 1 · Describe what you need</span>
      <h1>Delegate a purchase,<br/><em>not your control.</em></h1>
      <p>Describe the item and any budget in your request. You can optionally add enforceable limits below.</p>
    </div>
    <div className="card instruction-card">
      <div className="card-title"><div className="icon-box purple"><Bot size={19}/></div><div><h2>Your instruction</h2><p>DeepSeek interprets your request when available; a local deterministic parser is the fallback.</p></div></div>
      <label className="sr-only" htmlFor="instruction">Shopping instruction</label>
      <textarea id="instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} />
      <div className="trust-note"><LockKeyhole size={16}/><span><strong>The agent can interpret and recommend.</strong> The Financial Firewall makes the deterministic spending decision.</span></div>
    </div>
    <details className="advanced-controls" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
      <summary><span><ShieldCheck size={18}/> Advanced Controls</span><small>Optional manual constraints override the AI-extracted mandate</small><ChevronDown size={18}/></summary>
      <div className="advanced-body card">
        <p>Leave a field blank to apply no additional constraint for it.</p>
        <div className="field-grid">
          <label><span>Maximum per purchase (HKD)</span><input type="number" min="0" step="0.01" value={manualOverrides.maxPerTransaction} onChange={(event) => updateOverride('maxPerTransaction', event.target.value)} placeholder="No manual cap"/></label>
          <label><span>Daily spending limit (HKD)</span><input type="number" min="0" step="0.01" value={manualOverrides.maxDailySpend} onChange={(event) => updateOverride('maxDailySpend', event.target.value)} placeholder="No daily cap"/></label>
          <label><span>Allowed category</span><input value={manualOverrides.allowedCategory} onChange={(event) => updateOverride('allowedCategory', event.target.value)} placeholder="Any category"/></label>
          <label><span>Expires on (optional)</span><input type="date" value={manualOverrides.expiresAt} onChange={(event) => updateOverride('expiresAt', event.target.value)}/></label>
        </div>
        <label className="manual-merchants"><span>Approved merchants (comma-separated IDs)</span><input value={manualOverrides.allowedMerchants} onChange={(event) => updateOverride('allowedMerchants', event.target.value)} placeholder="Leave blank to allow any merchant"/></label>
      </div>
    </details>
    {error && <div className="error-note" role="alert"><AlertTriangle size={15}/><span>{error}</span></div>}
    <button className="primary wide" disabled={busy || !instruction.trim()} onClick={onContinue}>
      {busy ? 'Interpreting and searching…' : 'Find matching products'} <ArrowRight size={17}/>
    </button>
  </section>;
}

/**
 * SCREEN 2 — Agent Shopping Workspace.
 * A dominant primary recommendation sits beside collapsed alternatives.
 */
function ShoppingWorkspace({ products, instruction, mandate, selectedId, setSelectedId, error, securityWarning, busy, onCancel, onConfirm }: {
  products: Product[];
  instruction: string;
  mandate: Mandate;
  selectedId: string;
  setSelectedId: (id: string) => void;
  error: string | null;
  securityWarning: string | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const picked = products.find((product) => product.id === selectedId) ?? products[0];
  const alternatives = products.filter((product) => product.id !== picked?.id);
  return <section className="screen">
    <div className="screen-heading row-heading">
      <div><span className="step-kicker">Step 2 · Agent shop</span><h1>Your agent found <em>options.</em></h1><p>Review the recommendation, then confirm to run policy checks and simulated payment.</p></div>
      <div className="boundary-card"><ShieldCheck size={19}/><div><strong>{mandate.maxPerTransaction === undefined ? 'No purchase cap extracted' : `${fmt(mandate.maxPerTransaction)} purchase cap`}</strong><span>{mandate.allowedMerchants?.length ? `${mandate.allowedMerchants.length} approved merchant(s)` : 'Merchant restrictions: none'}</span></div></div>
    </div>
    <div className="agent-thinking"><div className="bot-dot"><Bot size={20}/></div><div><span>Agent request</span><p>“{instruction}”</p></div><span className="status-chip purple">Recommendation ready</span></div>
    {securityWarning && <div className="security-warning" role="status"><ShieldCheck size={15}/><span>{securityWarning}</span></div>}
    {error && <div className="error-note shop-error" role="alert"><AlertTriangle size={17}/><span>{error}</span></div>}
    {picked ? <>
      <div className="product-layout">
        <article className="primary-product card">
          <div className="primary-overview">
            <div className="primary-art"><MouseArt/><span className="recommend-badge"><Sparkles size={12}/> Agent recommendation</span></div>
            <div className="primary-description"><span className="step-kicker">Primary selection</span><h2>{picked.name}</h2><p>{picked.description}</p>{picked.id === 'mouse-untrusted' && <div className="untrusted-note"><AlertTriangle size={15}/> Product description is untrusted data and cannot modify the mandate.</div>}</div>
          </div>
          <div className="primary-pricing">
            <div><span>Item price</span><strong>{fmt(picked.price)}</strong></div>
            <div><span>Shipping</span><strong>{fmt(picked.shipping)}</strong></div>
            <div className="primary-total"><span>Final total</span><strong>{fmt(picked.price + picked.shipping)}</strong></div>
            <div className="primary-merchant"><span>Merchant</span><strong>{picked.merchantName}</strong><small>{picked.merchantId}</small></div>
          </div>
        </article>
        <aside className="alternative-sidebar">
          <details className="alternative-options">
            <summary>Alternative Options (Click to Expand)<ChevronDown size={17}/></summary>
            {alternatives.length ? <div className="alternative-list">{alternatives.map((product, index) =>
              <button key={product.id} className={`alternative-option ${product.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(product.id)}>
                <span className="alternative-rank">Choice #{index + 2}</span><strong>{product.name}</strong><span>{product.merchantName}</span><b>{fmt(product.price + product.shipping)}</b>
              </button>
            )}</div> : <p className="no-alternatives">No additional authorized options were returned.</p>}
          </details>
        </aside>
      </div>
    </> : <div className="empty-state card"><ShoppingBag/><h2>No selectable product</h2><p>Review the error above or return to revise your request.</p></div>}
    <div className="workflow-actions">
      <button className="cancel-action" onClick={onCancel} disabled={busy}>Cancel</button>
      <button className="confirm-action" onClick={onConfirm} disabled={busy || !picked}>{busy ? 'Checking and processing…' : 'Confirm'} <CheckCircle2 size={18}/></button>
    </div>
  </section>;
}

/** Pure-CSS mouse illustration (avoids binary image assets). */
function MouseArt(){return <div className="mouse-art"><div className="mouse-wheel"/><div className="mouse-line"/></div>}

/**
 * SCREEN 4 — Transaction Result.
 * Success (COMPLETED), blocked (DENIED), or cancelled (CANCELLED) hero +
 * receipt grid. Always carries the SIMULATED PAYMENT badge.
 */
function ResultScreen({transaction,product,authorization,onAudit,onReset}:{transaction:Transaction|null;product:Product;authorization:AuthorizationResult|null;onAudit:()=>void;onReset:()=>void}) {
  const state = transaction?.status;
  const success = state === 'COMPLETED';
  const cancelled = state === 'CANCELLED';
  return <section className="screen result-screen">
    <div className={`result-hero ${success ? 'success' : cancelled ? 'cancelled' : 'blocked'}`}>
      <div className="result-icon">{success ? <CheckCircle2/> : cancelled ? <AlertTriangle/> : <XCircle/>}</div>
      <span className="step-kicker">Step 3 · Payment result</span>
      <h1>{success ? 'Purchase completed' : cancelled ? 'Authorization revoked' : 'Purchase blocked'}</h1>
      <p>{success ? 'Your agent completed the simulated purchase within every boundary.' : cancelled ? 'The payment was stopped before completion. No money was transferred.' : authorization?.reason ?? 'The transaction did not complete.'}</p>
      <span className="simulated-pill">SIMULATED PAYMENT · NO REAL MONEY</span>
    </div>
    {transaction && <div className="receipt card">
      <div><span>Transaction ID</span><strong>{transaction.id}</strong></div>
      <div><span>Product</span><strong>{product.name}</strong></div>
      <div><span>Merchant</span><strong>{product.merchantName}</strong></div>
      <div><span>Final amount</span><strong>{fmt(transaction.total)}</strong></div>
      <div><span>Status</span><strong className={`state-text ${state?.toLowerCase()}`}>{state}</strong></div>
    </div>}
    <div className="result-actions">
      <button className="primary" onClick={onAudit}>View audit trail <ArrowRight size={17}/></button>
      <button className="secondary" onClick={onReset}><RotateCcw size={16}/> Replay scenario</button>
    </div>
  </section>;
}

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
