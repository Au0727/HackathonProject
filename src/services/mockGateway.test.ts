/**
 * ============================================================================
 * MODULE: services/mockGateway.test.ts — Authorization Engine Tests
 * ============================================================================
 * PURPOSE
 *   Proves the deterministic policy engine (evaluatePolicy) enforces the
 *   security property: no policy-violating transaction is ever ALLOWED.
 *   These tests need NO LLM and NO network — that is the point.
 *
 * PORT TO BACKEND: copy these cases to your server test suite so the real
 * engine behaves identically. Run with: npm test
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';
import { scenarios } from '../data/scenarios';
import type { Transaction } from '../domain/types';
import { evaluatePolicy, interpretMandateLocally } from './mockGateway';

/** Test helper: build a minimal Transaction with total = subtotal + shipping. */
const tx = (productId: string, merchantId: string, subtotal: number, shipping: number): Transaction => ({
  id: 'test-tx', productId, merchantId, subtotal, shipping, total: subtotal + shipping,
  currency: 'HKD', status: 'PROPOSED', createdAt: '2026-10-02T00:00:00.000Z'
});
/** Fixed "now" so expiry tests are deterministic and never flaky. */
const now = new Date('2026-10-02T00:00:00.000Z');

describe('deterministic authorization', () => {
  it('allows a compliant final total', () => {
    const result = evaluatePolicy(scenarios[0].mandate, tx('mouse-quiet','campus-tech',219,20), now);
    expect(result.decision).toBe('ALLOW');
  });
  it('denies when final total, including shipping, exceeds the cap', () => {
    const result = evaluatePolicy(scenarios[1].mandate, tx('mouse-pro','campus-tech',280,30), now);
    expect(result.decision).toBe('DENY');
    expect(result.failedRules).toContain('MAX_PER_TRANSACTION');
    expect(result.reason).toContain('HK$310');
  });
  it('denies an expired mandate', () => {
    const result = evaluatePolicy(scenarios[2].mandate, tx('mouse-basic','student-store',149,18), now);
    expect(result.failedRules).toContain('EXPIRY');
  });
  it('denies a revoked mandate', () => {
    const mandate = { ...scenarios[0].mandate, revokedAt: now.toISOString() };
    const result = evaluatePolicy(mandate, tx('mouse-quiet','campus-tech',219,20), now);
    expect(result.failedRules).toContain('REVOCATION');
  });
  it('denies an unapproved merchant despite malicious product text', () => {
    const result = evaluatePolicy(scenarios[4].mandate, tx('mouse-untrusted','unknown-market',79,0), now);
    expect(result.failedRules).toContain('MERCHANT');
  });
  it('asks when a confirmation threshold is crossed', () => {
    const mandate = { ...scenarios[0].mandate, requiresConfirmationAbove: 200 };
    expect(evaluatePolicy(mandate, tx('mouse-quiet','campus-tech',219,20), now).decision).toBe('ASK');
  });
});

describe('mandate interpretation (local LLM stand-in)', () => {
  it('prefers the explicit priceLimit the user typed', () => {
    const mandate = interpretMandateLocally({ instruction: 'Buy me a mouse', priceLimit: 300 });
    expect(mandate.maxPerTransaction).toBe(300);
    expect(mandate.maxDailySpend).toBe(600);
  });
  it('extracts a price embedded in the natural-language instruction', () => {
    const mandate = interpretMandateLocally({ instruction: 'Buy me a wireless mouse under HK$250' });
    expect(mandate.maxPerTransaction).toBe(250);
  });
  it('falls back to scenario defaults when neither input nor text gives a limit', () => {
    const mandate = interpretMandateLocally({ instruction: 'Buy me a mouse' }, { maxPerTransaction: 300, allowedMerchants: ['campus-tech'] });
    expect(mandate.maxPerTransaction).toBe(300);
    expect(mandate.allowedMerchants).toEqual(['campus-tech']);
  });
  it('maps product keywords to allowed categories', () => {
    const mandate = interpretMandateLocally({ instruction: 'Buy me headphones for study', priceLimit: 400 });
    expect(mandate.allowedCategories).toContain('Audio');
  });
  it('always produces a valid future expiry and a unique id', () => {
    const mandate = interpretMandateLocally({ instruction: 'Buy me a mouse', priceLimit: 300 });
    expect(new Date(mandate.expiresAt).getTime()).toBeGreaterThan(Date.now());
    expect(mandate.id).toMatch(/^mandate-/);
  });
});
