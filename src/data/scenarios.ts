/**
 * ============================================================================
 * MODULE: data/scenarios.ts — One-Click Demo Scenarios for Judges
 * ============================================================================
 * PURPOSE
 *   Each entry fully describes one repeatable exhibition scenario: the user's
 *   natural-language request, a PRE-PARSED Mandate (this stands in for LLM
 *   output until POST /api/mandates/interpret exists), and the product to
 *   propose. The Demo Mode bar in the UI loads these fixtures.
 *
 * HOW TO ADD A NEW SCENARIO
 *   1. Add the id to `ScenarioId` in domain/types.ts.
 *   2. Add an entry below with request + mandate + productId.
 *   The Demo Mode bar renders automatically from this array.
 *
 * NOTE ON THE LLM: in the real system the mandate is produced by your LLM
 * endpoint from `request`; here it is hard-coded so demos are deterministic.
 * ============================================================================
 */

import type { DemoScenario, Mandate } from '../domain/types';

const future = '2027-12-31T23:59:59.000Z';
/** Shared baseline: HK$300/purchase, HK$600/day, accessories only, two approved merchants. */
const base: Mandate = {
  id: 'mandate-demo-001',
  maxPerTransaction: 300,
  maxDailySpend: 600,
  allowedCategories: ['Computer Accessories'],
  allowedMerchants: ['campus-tech', 'student-store'],
  expiresAt: future
};

export const scenarios: DemoScenario[] = [
  // A — Allowed: HK$219 + HK$20 = HK$239 ≤ HK$300, approved merchant → ALLOW → COMPLETED
  { id: 'allowed', title: 'Allowed purchase', shortTitle: 'Allowed', description: 'A trusted product stays within the final-total limit.', request: 'Buy me a quiet wireless mouse for university. Spend at most HK$300 and only use approved merchants.', mandate: { ...base, id: 'mandate-allowed' }, productId: 'mouse-quiet' },
  // B — Over budget: HK$280 + HK$30 shipping = HK$310 > HK$300 → DENY (final total rule)
  { id: 'over_budget', title: 'Blocked by final total', shortTitle: 'Over budget', description: 'HK$280 + HK$30 shipping exceeds the HK$300 cap.', request: 'Buy me an ergonomic wireless mouse under HK$300.', mandate: { ...base, id: 'mandate-over-budget' }, productId: 'mouse-pro' },
  // C — Expired: amount is fine, but expiresAt is in the past → DENY (expiry rule)
  { id: 'expired', title: 'Expired mandate', shortTitle: 'Expired', description: 'The amount is valid, but the authority has expired.', request: 'Use my existing university supplies mandate to buy a mouse.', mandate: { ...base, id: 'mandate-expired', expiresAt: '2025-01-01T00:00:00.000Z' }, productId: 'mouse-basic' },
  // D — Revocation: payment pauses in PAYMENT_PENDING; user revokes → CANCELLED
  { id: 'revocation', title: 'Revoke during payment', shortTitle: 'Revocation', description: 'Payment pauses so the user can revoke authority.', request: 'Buy the recommended wireless mouse, but let me retain revocation control.', mandate: { ...base, id: 'mandate-revocation' }, productId: 'mouse-quiet' },
  // E — Malicious content: unapproved merchant + injection text → DENY (merchant rule)
  { id: 'malicious', title: 'Untrusted product content', shortTitle: 'Prompt injection', description: 'A malicious listing cannot override the mandate.', request: 'Find a university mouse, but only from an approved merchant.', mandate: { ...base, id: 'mandate-malicious' }, productId: 'mouse-untrusted' }
];
