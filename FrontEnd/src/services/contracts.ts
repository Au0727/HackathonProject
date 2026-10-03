/**
 * ============================================================================
 * MODULE: services/contracts.ts — Backend Integration Interfaces
 * ============================================================================
 * PURPOSE
 *   This file is THE integration seam between the frontend and your backend.
 *   The UI (App.tsx) only calls these interfaces — it never talks to mock data
 *   or HTTP directly. That means you can swap the mock adapter for your real
 *   backend by changing ONE import, without touching any screen.
 *
 * HOW TO CONNECT YOUR BACKEND (summary; full guide in BACKEND_INTEGRATION.md)
 *   1. Create `src/services/httpGateway.ts` implementing `CommerceGateway`
 *      with fetch() calls to your API endpoints.
 *   2. In `App.tsx`, change:
 *        import { commerceGateway } from './services/mockGateway';
 *      to:
 *        import { commerceGateway } from './services/httpGateway';
 *   3. Keep the request/response JSON in the shapes from domain/types.ts.
 *
 * EACH METHOD maps 1:1 to a suggested backend endpoint (see comments below).
 * ============================================================================
 */

import type { AuditEvent, AuthorizationResult, Mandate, MandateInterpretationInput, Product, Transaction } from '../domain/types';

export type ShoppingSearchResult = {
  products: Product[];
  securityRejections: number;
  stopReason?: string;
};

/**
 * CommerceGateway — every operation the UI needs from the "backend".
 * Method names mirror the product flow:
 *   catalog → mandate interpretation → authorization → payment start → payment completion
 */
export interface CommerceGateway {
  /**
   * Get the controlled product catalog.
   *   Backend: GET /api/catalog          → Product[]
   *   Current: returns the local dummy file src/data/catalog.ts
   */
  getCatalog(): Promise<Product[]>;

  /**
   * Send the user's natural-language instruction + price limit to your LLM
   * pipeline and receive a validated, structured Mandate back.
   *
   * This is called from `activateMandate()` in App.tsx when the user clicks
   * the "Activate mandate" button.
   *
   *   Backend: POST /api/mandates/interpret
   *     request  body: { "instruction": string, "priceLimit": number }
   *     response body: Mandate (the LLM proposes; your server validates)
   *
   *   Security: the LLM output must be validated server-side against a schema;
   *   it is a PROPOSAL, never spending authority by itself.
   */
  interpretMandate(input: MandateInterpretationInput): Promise<Mandate>;

  /**
   * Ask the DETERMINISTIC policy engine to evaluate a proposed transaction
   * against the mandate. This is the core of the product.
   *   Backend: POST /api/authorization/evaluate
   *     request  body: { "mandate": Mandate, "transaction": Transaction }
   *     response body: AuthorizationResult (decision + per-rule checks)
   *   The engine evaluates transaction.total (price + shipping), NOT just price.
   */
  authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult>;

  /**
   * Move an authorized transaction into PAYMENT_PENDING on the simulated
   * payment rail. This is where the "revoke during checkout" scenario pauses.
   *   Backend: POST /api/transactions/:id/payment/start   → Transaction (status=PAYMENT_PENDING)
   *   Use an idempotency key server-side so retries don't double-charge (even simulated).
   */
  startPayment(transaction: Transaction): Promise<Transaction>;

  /**
   * Complete the pending payment. CRITICAL: the server must re-evaluate the
   * mandate (expiry + revocation) immediately before completing — this is how
   * "user revokes during checkout" reliably becomes CANCELLED instead of COMPLETED.
   *   Backend: POST /api/transactions/:id/payment/complete → Transaction (COMPLETED | CANCELLED)
   */
  completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction>;
}

/**
 * AuditRepository — append-only record of every important decision.
 * In the prototype, events live in React state; for production, your backend
 * should own this store so audit records are tamper-evident and survive refresh.
 *   Backend: GET /api/audit → AuditEvent[] ; POST /api/audit → append server-side
 */
export interface AuditRepository {
  list(): Promise<AuditEvent[]>;
  append(event: AuditEvent): Promise<void>;
  clear(): Promise<void>;
}
