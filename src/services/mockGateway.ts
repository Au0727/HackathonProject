/**
 * ============================================================================
 * MODULE: services/mockGateway.ts — Dummy Data Adapter + Deterministic Policy Demo
 * ============================================================================
 * PURPOSE
 *   Stand-in for the real backend so the frontend is fully demoable today.
 *   Two things live here:
 *     1. `evaluatePolicy()` — a real, deterministic, testable authorization
 *        engine (this logic later moves to your BACKEND; keep it out of the UI).
 *     2. `MockCommerceGateway` / `MemoryAuditRepository` — async dummy
 *        implementations of the interfaces in services/contracts.ts.
 *
 * WHERE YOUR BACKEND DATA REPLACES THIS
 *   - Product list   → comes from GET /api/catalog instead of data/catalog.ts
 *   - Mandate parse  → comes from POST /api/mandates/interpret (your LLM endpoint)
 *   - Authorization  → comes from POST /api/authorization/evaluate (server-side engine)
 *   - Payment steps  → come from your simulated payment endpoints
 *   See BACKEND_INTEGRATION.md for the request/response JSON for each.
 * ============================================================================
 */

import { catalog } from '../data/catalog';
import type { AuditEvent, AuthorizationResult, Mandate, RuleCheck, Transaction } from '../domain/types';
import type { AuditRepository, CommerceGateway } from './contracts';

/** Small artificial delay so the UI's loading states are visible in demos. */
const wait = (ms = 220) => new Promise((resolve) => setTimeout(resolve, ms));
const money = (value: number) => `HK$${value.toFixed(0)}`;

/**
 * evaluatePolicy — THE deterministic authorization engine (prototype copy).
 *
 * Given a Mandate + Transaction, it evaluates each rule and returns an
 * AuthorizationResult with:
 *   - decision: ALLOW / DENY / ASK
 *   - reason:   exact plain-language explanation
 *   - failedRules / ruleChecks: recorded evidence for the audit log
 *
 * NOTE FOR BACKEND: this function is intentionally pure (no UI, no globals,
 * injectable `now`) so the same logic — and the same tests in
 * mockGateway.test.ts — can be ported to your server 1:1.
 * The golden rule: evaluate transaction.total, never just the product price.
 */
export function evaluatePolicy(mandate: Mandate, transaction: Transaction, now = new Date()): AuthorizationResult {
  const checks: RuleCheck[] = [];
  const add = (id: string, label: string, passed: boolean, detail: string) => checks.push({ id, label, passed, detail });
  const merchantAllowed = !mandate.allowedMerchants?.length || mandate.allowedMerchants.includes(transaction.merchantId);
  const product = catalog.find((item) => item.id === transaction.productId);
  const categoryAllowed = !mandate.allowedCategories?.length || (!!product && mandate.allowedCategories.includes(product.category));
  const amountAllowed = mandate.maxPerTransaction === undefined || transaction.total <= mandate.maxPerTransaction;
  const active = new Date(mandate.expiresAt).getTime() > now.getTime();
  const notRevoked = !mandate.revokedAt;
  const dailyAllowed = mandate.maxDailySpend === undefined || transaction.total <= mandate.maxDailySpend;

  // Recorded per-rule results — these power the ✓/✕ list in the UI and the audit trail.
  add('MAX_PER_TRANSACTION', 'Final total', amountAllowed, amountAllowed ? `${money(transaction.total)} is within the ${money(mandate.maxPerTransaction ?? transaction.total)} limit.` : `${money(transaction.total)} exceeds the ${money(mandate.maxPerTransaction!)} limit.`);
  add('DAILY_SPEND', 'Daily spend', dailyAllowed, dailyAllowed ? 'This purchase fits within today’s delegated spend.' : 'This purchase exceeds today’s remaining delegated spend.');
  add('MERCHANT', 'Approved merchant', merchantAllowed, merchantAllowed ? 'Merchant is on your approved list.' : 'Merchant is not on your approved list.');
  add('CATEGORY', 'Approved category', categoryAllowed, categoryAllowed ? 'Product category is permitted.' : 'Product category is outside the mandate.');
  add('EXPIRY', 'Mandate active', active, active ? 'Authorization has not expired.' : `Authorization expired on ${new Date(mandate.expiresAt).toLocaleDateString('en-HK')}.`);
  add('REVOCATION', 'Not revoked', notRevoked, notRevoked ? 'Authorization remains active.' : 'You revoked this authorization.');

  const failed = checks.filter((check) => !check.passed);
  let decision: AuthorizationResult['decision'] = failed.length ? 'DENY' : 'ALLOW';
  let reason = 'Every deterministic policy rule passed. This transaction may proceed to simulated payment.';
  // Denial reasons are precise and ordered so the FIRST broken rule explains the denial.
  if (!amountAllowed) reason = `Final transaction total ${money(transaction.total)} exceeds the authorized per-transaction limit of ${money(mandate.maxPerTransaction!)}.`;
  else if (!active) reason = 'This spending mandate has expired and can no longer authorize a purchase.';
  else if (!notRevoked) reason = 'The user revoked this authorization before payment completed.';
  else if (!merchantAllowed) reason = 'The selected merchant is not approved by this spending mandate.';
  else if (!categoryAllowed) reason = 'The selected product category is not approved by this spending mandate.';
  else if (!dailyAllowed) reason = 'This purchase would exceed the delegated daily spending limit.';
  else if (mandate.requiresConfirmationAbove !== undefined && transaction.total > mandate.requiresConfirmationAbove) {
    decision = 'ASK';
    reason = `This purchase is allowed but requires confirmation above ${money(mandate.requiresConfirmationAbove)}.`;
  }

  return { decision, reason, failedRules: failed.map((check) => check.id), evaluatedAt: now.toISOString(), mandateId: mandate.id, ruleChecks: checks };
}

/**
 * MockCommerceGateway — async dummy backend implementing CommerceGateway.
 * Each method mirrors a real endpoint (see contracts.ts). Delays simulate latency.
 */
class MockCommerceGateway implements CommerceGateway {
  /** Dummy: local catalog. Real: GET /api/catalog */
  async getCatalog() { await wait(); return catalog; }
  /** Dummy: throws — scenarios ship pre-parsed mandates. Real: POST /api/mandates/interpret (LLM → validated Mandate) */
  async interpretMandate(_instruction: string): Promise<Mandate> { await wait(350); throw new Error('The prototype loads parsed mandates from demo scenarios. Connect POST /api/mandates/interpret here.'); }
  /** Dummy: local evaluatePolicy. Real: POST /api/authorization/evaluate */
  async authorize(mandate: Mandate, transaction: Transaction) { await wait(); return evaluatePolicy(mandate, transaction); }
  /** Dummy: instant transition. Real: POST /api/transactions/:id/payment/start */
  async startPayment(transaction: Transaction) { await wait(350); return { ...transaction, status: 'PAYMENT_PENDING' as const }; }
  /** Dummy: revoked mandate → CANCELLED. Real: server re-checks mandate atomically before completing. */
  async completePayment(transaction: Transaction, mandate: Mandate) { await wait(500); return { ...transaction, status: mandate.revokedAt ? 'CANCELLED' as const : 'COMPLETED' as const }; }
}

/**
 * MemoryAuditRepository — in-memory audit store for the prototype.
 * Real: your backend owns the append-only audit store (see AuditRepository in contracts.ts).
 */
class MemoryAuditRepository implements AuditRepository {
  private events: AuditEvent[] = [];
  async list() { return [...this.events]; }
  async append(event: AuditEvent) { this.events = [event, ...this.events]; }
  async clear() { this.events = []; }
}

/**
 * COMPOSITION ROOT — these are the instances App.tsx imports.
 * To connect the real backend, export an HttpCommerceGateway here instead
 * (or re-point the import in App.tsx). Nothing else in the UI changes.
 */
export const commerceGateway: CommerceGateway = new MockCommerceGateway();
export const auditRepository: AuditRepository = new MemoryAuditRepository();
