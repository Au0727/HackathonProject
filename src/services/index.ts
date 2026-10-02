/**
 * ============================================================================
 * MODULE: services/index.ts — Composition Root (optional switch point)
 * ============================================================================
 * PURPOSE
 *   One place to choose between the mock adapter and the real HTTP adapter,
 *   driven by an env flag. Import from here if you prefer not to edit App.tsx:
 *
 *     import { commerceGateway, auditRepository } from './services';
 *
 *   Set VITE_USE_MOCKS=false in .env to switch to the real backend.
 *
 *   This file is a convenience; App.tsx currently imports mockGateway directly,
 *   so nothing changes until you opt in.
 * ============================================================================
 */

import type { AuditRepository, CommerceGateway } from './contracts';
import { commerceGateway as mockCommerce, auditRepository as mockAudit } from './mockGateway';
import { commerceGateway as httpCommerce, auditRepository as httpAudit } from './httpGateway';

const useMocks = import.meta.env.VITE_USE_MOCKS !== 'false';

/** Backend gateway: mock by default, real HTTP when VITE_USE_MOCKS=false. */
export const commerceGateway: CommerceGateway = useMocks ? mockCommerce : httpCommerce;

/** Audit repository: in-memory by default, backend-owned when VITE_USE_MOCKS=false. */
export const auditRepository: AuditRepository = useMocks ? mockAudit : httpAudit;
