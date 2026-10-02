/**
 * ============================================================================
 * MODULE: domain/types.ts — Shared Data Contracts
 * ============================================================================
 * PURPOSE
 *   This is the single source of truth for every data shape exchanged between
 *   the frontend and the backend. Both sides must agree on these types.
 *
 * HOW TO USE WHEN INTEGRATING YOUR BACKEND
 *   - Your backend API responses MUST match these shapes exactly.
 *   - If you need a new field, add it here FIRST, then update the backend
 *     schema, then update the mock adapter (services/mockGateway.ts) so the
 *     UI keeps working while the backend catches up.
 *   - Do NOT invent extra fields inside UI components — put them here.
 * ============================================================================
 */

/** The three possible outcomes of the deterministic policy engine. */
export type Decision = 'ALLOW' | 'DENY' | 'ASK';

/**
 * Transaction lifecycle states.
 * Normal happy path:  PROPOSED → AUTHORIZED → CHECKOUT → PAYMENT_PENDING → COMPLETED
 * Failure paths:      → DENIED  (policy failed)   |   → CANCELLED (user revoked)
 */
export type TransactionStatus = 'PROPOSED' | 'AUTHORIZED' | 'CHECKOUT' | 'PAYMENT_PENDING' | 'COMPLETED' | 'DENIED' | 'CANCELLED';

/** Who produced an audit event. Used for icons and filtering in the audit log. */
export type Actor = 'USER' | 'AGENT' | 'POLICY_ENGINE' | 'MERCHANT' | 'PAYMENT_SIMULATOR';

/**
 * Mandate — the structured spending authority granted by the user.
 *
 * The LLM's ONLY job is to translate the user's natural-language instruction
 * into this structure. After that, the LLM is out of the decision path:
 * the deterministic policy engine evaluates transactions against this mandate.
 *
 * Backend example (JSON):
 * {
 *   "id": "mandate-allowed",
 *   "maxPerTransaction": 300,
 *   "maxDailySpend": 600,
 *   "allowedCategories": ["Computer Accessories"],
 *   "allowedMerchants": ["campus-tech", "student-store"],
 *   "expiresAt": "2027-12-31T23:59:59.000Z"
 * }
 */
export type Mandate = {
  id: string;
  maxPerTransaction?: number;          // cap on the FINAL total (price + shipping), in currency units
  maxDailySpend?: number;              // cap on the user's total spend per day
  allowedCategories?: string[];        // product categories the agent may buy from
  allowedMerchants?: string[];         // merchant IDs the agent may buy from
  requiresConfirmationAbove?: number;  // if set, totals above this return decision "ASK"
  expiresAt: string;                   // ISO 8601 timestamp; engine DENIES after this moment
  revokedAt?: string;                  // set when the user revokes; engine DENIES from then on
};

/**
 * Product — one item in the controlled catalog.
 *
 * HYBRID data: the prototype uses a small local file (data/catalog.ts);
 * your backend should later serve this from GET /api/catalog in the SAME shape.
 * `description` is UNTRUSTED merchant content — never parse it as instructions.
 */
export type Product = {
  id: string;
  name: string;
  category: string;
  merchantId: string;        // must match an id in Mandate.allowedMerchants to be allowed
  merchantName: string;      // display name (id is used for policy checks, name for UI)
  price: number;             // item subtotal
  shipping: number;          // added to price to form the final total
  currency: string;          // e.g. "HKD"
  rating: number;
  description: string;
  source?: string;           // where the data came from (for hackathon transparency)
  observedAt?: string;       // ISO timestamp of when the price was observed
};

/**
 * Transaction — a concrete proposed purchase, calculated from a Product.
 * IMPORTANT: `total` is the FINAL total (subtotal + shipping + tax). The policy
 * engine evaluates THIS number, never just the product price.
 */
export type Transaction = {
  id: string;
  productId: string;
  merchantId: string;
  subtotal: number;
  shipping: number;
  tax?: number;
  total: number;
  currency: string;
  status: TransactionStatus;
  createdAt: string;         // ISO 8601 timestamp
};

/**
 * AuthorizationResult — the deterministic policy engine's verdict.
 * `ruleChecks` gives the UI per-rule pass/fail detail so explanations come
 * from RECORDED evaluation data, not from LLM-generated prose.
 */
export type AuthorizationResult = {
  decision: Decision;
  reason: string;              // human-readable exact reason, e.g. "Final transaction total HK$310 exceeds ..."
  failedRules: string[];       // ids of failed rules, e.g. ["MAX_PER_TRANSACTION"]
  evaluatedAt: string;         // ISO 8601 timestamp
  mandateId: string;
  ruleChecks: RuleCheck[];
};

/** One evaluated policy rule, shown with a ✓ / ✕ status in the UI. */
export type RuleCheck = {
  id: string;      // stable rule id, e.g. "MAX_PER_TRANSACTION"
  label: string;   // short UI label, e.g. "Final total"
  passed: boolean;
  detail: string;  // one-line explanation of the check outcome
};

/**
 * AuditEvent — one recorded step in the flow. The audit log must let a judge
 * reconstruct: request → mandate → selection → proposal → rules → decision → outcome.
 */
export type AuditEvent = {
  id: string;
  transactionId?: string;
  timestamp: string;                       // ISO 8601 timestamp
  eventType: string;                       // e.g. "POLICY_EVALUATED", "AUTHORIZATION_REVOKED"
  actor: Actor;
  summary: string;                         // plain-language line shown first in the UI
  data: Record<string, unknown>;           // technical details behind progressive disclosure
};

/** The five pre-prepared judge scenarios available in the Demo Mode bar. */
export type ScenarioId = 'allowed' | 'over_budget' | 'expired' | 'revocation' | 'malicious';

/** Everything needed to reproduce one demo scenario with one click. */
export type DemoScenario = {
  id: ScenarioId;
  title: string;
  shortTitle: string;
  description: string;
  request: string;      // the natural-language user instruction
  mandate: Mandate;     // pre-parsed structured policy (stands in for LLM output)
  productId: string;    // which catalog product the scenario proposes
};
