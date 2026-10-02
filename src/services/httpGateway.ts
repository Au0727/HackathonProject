/**
 * ============================================================================
 * MODULE: services/httpGateway.ts — REAL Backend Adapter (scaffold)
 * ============================================================================
 * PURPOSE
 *   Drop-in replacement for services/mockGateway.ts. Implement each method with
 *   your real API endpoint here; then switch the import in App.tsx:
 *
 *     // src/App.tsx
 *     - import { commerceGateway } from './services/mockGateway';
 *     + import { commerceGateway } from './services/httpGateway';
 *
 *   Nothing else in the UI changes.
 *
 * STATUS: TEMPLATE. The fetch calls are written out; adjust paths/headers to
 * match your API. It is NOT imported by the app yet, so it cannot break the build.
 *
 * REQUEST/RESPONSE SHAPES: see src/domain/types.ts and BACKEND_INTEGRATION.md.
 * ============================================================================
 */

import type { AuditEvent, AuthorizationResult, Mandate, Product, Transaction } from '../domain/types';
import type { AuditRepository, CommerceGateway } from './contracts';

/** Base URL from a browser-safe env var (see .env.example). Never put secrets here. */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3000';

/** Small helper: POST JSON, throw a readable error on non-2xx. */
async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

/**
 * HttpCommerceGateway — talks to your real backend.
 * Each method maps to one endpoint (see BACKEND_INTEGRATION.md §1).
 */
export class HttpCommerceGateway implements CommerceGateway {
  /** GET /api/catalog → Product[] */
  async getCatalog(): Promise<Product[]> {
    const res = await fetch(`${BASE_URL}/api/catalog`);
    if (!res.ok) throw new Error('Catalog request failed');
    return (await res.json()) as Product[];
  }

  /** POST /api/mandates/interpret → Mandate. Your server calls the LLM + validates. */
  async interpretMandate(instruction: string): Promise<Mandate> {
    return postJson<Mandate>('/api/mandates/interpret', { instruction });
  }

  /** POST /api/authorization/evaluate → AuthorizationResult (deterministic, server-side). */
  async authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult> {
    return postJson<AuthorizationResult>('/api/authorization/evaluate', { mandate, transaction });
  }

  /** POST /api/transactions/:id/payment/start → Transaction (status PAYMENT_PENDING). */
  async startPayment(transaction: Transaction): Promise<Transaction> {
    return postJson<Transaction>(`/api/transactions/${transaction.id}/payment/start`, transaction);
  }

  /**
   * POST /api/transactions/:id/payment/complete → Transaction (COMPLETED | CANCELLED).
   * The server must re-check expiry + revocation atomically here.
   */
  async completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction> {
    return postJson<Transaction>(`/api/transactions/${transaction.id}/payment/complete`, { transaction, mandate });
  }
}

/** HttpAuditRepository — persists audit events on your backend. */
export class HttpAuditRepository implements AuditRepository {
  /** GET /api/audit → AuditEvent[] */
  async list(): Promise<AuditEvent[]> {
    const res = await fetch(`${BASE_URL}/api/audit`);
    if (!res.ok) throw new Error('Audit request failed');
    return (await res.json()) as AuditEvent[];
  }
  /** POST /api/audit → append one event (backend-owned store). */
  async append(event: AuditEvent): Promise<void> {
    await postJson<unknown>('/api/audit', event);
  }
  /** DELETE /api/audit → clear (dev/demo only). */
  async clear(): Promise<void> {
    await fetch(`${BASE_URL}/api/audit`, { method: 'DELETE' });
  }
}

/**
 * COMPOSITION ROOT for the real backend.
 * In App.tsx, replace the mock import with:
 *   export const commerceGateway = new HttpCommerceGateway();
 *   export const auditRepository = new HttpAuditRepository();
 */
export const commerceGateway: CommerceGateway = new HttpCommerceGateway();
export const auditRepository: AuditRepository = new HttpAuditRepository();
