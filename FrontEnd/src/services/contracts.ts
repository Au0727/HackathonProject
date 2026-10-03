/**
 * ============================================================================
 * MODULE: services/contracts.ts — Backend Integration Interfaces
 * ============================================================================
 * PURPOSE
 *   This file is THE integration seam between the frontend and your backend.
 *   The UI (App.tsx) calls these service contracts. The active implementation
 *   is httpGateway.ts; mockGateway.ts remains available to isolated tests.
 *
 * HOW TO CONNECT YOUR BACKEND (summary; full guide in BACKEND_INTEGRATION.md)
 *   Keep request and response JSON aligned with domain/types.ts and the
 *   endpoint contracts documented in BACKEND_INTEGRATION.md.
 *
 * EACH METHOD maps 1:1 to a suggested backend endpoint (see comments below).
 * ============================================================================
 */

import type { AuditEvent, AuthorizationResult, Mandate, MandateInterpretationInput, Product, Transaction } from '../domain/types';

/**
 * CommerceGateway — every operation the UI needs from the "backend".
 * Method names mirror the product flow:
 *   catalog → mandate interpretation/search → authorization → simulated payment
 */
export interface CommerceGateway {
  /**
   * Get the controlled product catalog.
   *   Backend: GET /api/catalog          → Product[]
   *   Active implementation: GET /api/catalog through httpGateway.ts.
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
   *     request body: { "prompt": string }
   *     response: StructuredIntent, mapped to a frontend Mandate by httpGateway
   *
   *   Security: the LLM output must be validated server-side against a schema;
   *   it is a PROPOSAL, never spending authority by itself.
   */
  interpretMandate(input: MandateInterpretationInput): Promise<Mandate>;

  /**
   * Search the configured inventory under the interpreted mandate.
   *   Backend: POST /api/shopping/search
   *     body: { intent, mandate, max_results }
   *   Returned options have passed the agent and supervisor pipeline.
   */
  search(mandate: Mandate, maxResults?: number): Promise<Product[]>;

  /**
   * Ask the DETERMINISTIC policy engine to evaluate a proposed transaction
   * against the mandate. This is the core of the product.
   *   Backend: POST /api/authorization/evaluate
   *     request  body: { "mandate": Mandate, "transaction": Transaction }
   *   response body: AuthorizationResult (decision + per-rule checks).
   *   The integrated HTTP API maps unsupported supervisor ASK to DENY.
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
 *   Backend: GET/POST/DELETE /api/audit/logs
 */
export interface AuditRepository {
  list(): Promise<AuditEvent[]>;
  append(event: AuditEvent): Promise<void>;
  clear(): Promise<void>;
}
