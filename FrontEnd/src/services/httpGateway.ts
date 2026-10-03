/**
 * HTTP adapter for the Python Agentic Commerce API.
 *
 * All monetary values are sent as decimal strings. They are converted to the
 * frontend's numeric display model only after a response has been received.
 */

import type { AuditEvent, AuthorizationResult, Mandate, MandateInterpretationInput, Product, Transaction } from '../domain/types';
import type { AuditRepository, CommerceGateway } from './contracts';

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const AUDIT_MONEY_KEYS = new Set([
  'price', 'shipping', 'shipping_fee', 'subtotal', 'tax', 'total',
  'maxpertransaction', 'maxdailyspend', 'requiresconfirmationabove', 'pricelimit',
]);
const AUDIT_AMOUNT_FIELD_MAP: Record<string, 'subtotal' | 'shipping' | 'total'> = {
  price: 'subtotal',
  subtotal: 'subtotal',
  shipping: 'shipping',
  shipping_fee: 'shipping',
  total: 'total',
};
const productMoney = new Map<string, { subtotal: string; shipping: string; total: string }>();

type StructuredIntent = {
  product_keywords: string[];
  max_base_price: string | null;
  max_total_cap: string | null;
  preferred_brands: string[];
  raw_request: string;
  parse_notes: string[];
};

type ApiProduct = Omit<Product, 'price' | 'shipping'> & {
  price: string;
  shipping: string;
};

type AuthorizedReport = {
  results: Array<{
    best_options?: Array<{
      product_id: string;
      product_name: string;
      brand: string;
      description: string;
      price: string;
      shipping_fee: string;
      currency: string;
      merchant_id?: string;
      merchant_name?: string;
    }>;
  }>;
  halts?: Array<{ reason: string }>;
};

type ApiError = { detail?: string | { msg?: string }[] };

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'network request failed';
    throw new Error(`Cannot reach the commerce API at ${BASE_URL}: ${reason}`);
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json() as ApiError;
      if (typeof payload.detail === 'string') detail = payload.detail;
      else if (Array.isArray(payload.detail)) detail = payload.detail.map((item) => item.msg ?? 'Invalid request').join('; ');
    } catch {
      // Preserve the useful HTTP status if the server returned a non-JSON error.
    }
    throw new Error(`Commerce API request failed: ${detail}`);
  }

  return await response.json() as T;
}

function decimalString(value: number | undefined): string {
  if (value === undefined) return '0.00';
  if (!Number.isFinite(value)) throw new Error('Money values must be finite numbers.');
  if (value < 0) throw new Error('Money values cannot be negative.');
  return value.toFixed(2);
}

function decimalCents(value: string): bigint {
  const [whole, fraction = '00'] = value.split('.');
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
}

function moneyFromCents(value: bigint): string {
  const whole = value / 100n;
  const fraction = (value % 100n).toString().padStart(2, '0');
  return `${whole}.${fraction}`;
}

function apiTransaction(transaction: Transaction): Record<string, unknown> {
  const authoritative = productMoney.get(transaction.productId);
  const subtotal = authoritative?.subtotal ?? decimalString(transaction.subtotal);
  const shipping = authoritative?.shipping ?? decimalString(transaction.shipping);
  const tax = transaction.tax === undefined ? undefined : decimalString(transaction.tax);
  const total = authoritative?.total ?? moneyFromCents(
    decimalCents(subtotal) + decimalCents(shipping) + (tax ? decimalCents(tax) : 0n),
  );
  return {
    ...transaction,
    subtotal,
    shipping,
    tax,
    total,
  };
}

function apiMandate(mandate: Mandate): Record<string, unknown> {
  return {
    ...mandate,
    maxPerTransaction: mandate.maxPerTransaction === undefined
      ? undefined
      : decimalString(mandate.maxPerTransaction),
    maxDailySpend: mandate.maxDailySpend === undefined
      ? undefined
      : decimalString(mandate.maxDailySpend),
    requiresConfirmationAbove: mandate.requiresConfirmationAbove === undefined
      ? undefined
      : decimalString(mandate.requiresConfirmationAbove),
  };
}

function stringifyAuditMoney(value: unknown, key = '', amounts?: { subtotal: string; shipping: string; total: string }): unknown {
  const canonicalKey = AUDIT_AMOUNT_FIELD_MAP[key.toLowerCase()];
  const canonicalAmount = canonicalKey && amounts ? amounts[canonicalKey] : undefined;
  if (canonicalAmount !== undefined && AUDIT_MONEY_KEYS.has(key.toLowerCase())) return canonicalAmount;
  if (typeof value === 'number' && AUDIT_MONEY_KEYS.has(key.toLowerCase())) return decimalString(value);
  if (Array.isArray(value)) return value.map((item) => stringifyAuditMoney(item));
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const productId = typeof record.productId === 'string' ? record.productId : '';
    const nestedAmounts = productMoney.get(productId) ?? amounts;
    return Object.fromEntries(
      Object.entries(record).map(([childKey, childValue]) => [
        childKey,
        stringifyAuditMoney(childValue, childKey, nestedAmounts),
      ]),
    );
  }
  return value;
}

function mandateFromIntent(
  intent: StructuredIntent,
  input: MandateInterpretationInput,
  defaults: Partial<Mandate>,
): Mandate {
  const caps = [
    input.priceLimit === undefined ? undefined : decimalString(input.priceLimit),
    intent.max_total_cap ?? undefined,
    intent.max_base_price ?? undefined,
  ].filter((value): value is string => value !== undefined);
  const limit = caps.length
    ? Number(caps.reduce((lowest, cap) => decimalCents(cap) < decimalCents(lowest) ? cap : lowest))
    : undefined;
  return {
    id: defaults.id ?? `mandate-${crypto.randomUUID()}`,
    maxPerTransaction: limit,
    maxDailySpend: defaults.maxDailySpend,
    allowedCategories: defaults.allowedCategories,
    allowedMerchants: defaults.allowedMerchants,
    requiresConfirmationAbove: defaults.requiresConfirmationAbove,
    expiresAt: defaults.expiresAt ?? '',
    revokedAt: defaults.revokedAt,
  };
}

export class HttpCommerceGateway implements CommerceGateway {
  private lastIntent: StructuredIntent | null = null;

  constructor(private readonly defaults: Partial<Mandate> = {}) {}

  async getCatalog(): Promise<Product[]> {
    const products = await requestJson<ApiProduct[]>('/api/catalog');
    return products.map((product) => {
      const subtotal = product.price;
      const shipping = product.shipping;
      productMoney.set(product.id, {
        subtotal,
        shipping,
        total: moneyFromCents(decimalCents(subtotal) + decimalCents(shipping)),
      });
      return { ...product, price: Number(subtotal), shipping: Number(shipping) };
    });
  }

  async interpretMandate(input: MandateInterpretationInput): Promise<Mandate> {
    const intent = await requestJson<StructuredIntent>('/api/mandates/interpret', {
      method: 'POST',
      body: JSON.stringify({ prompt: input.instruction }),
    });
    const caps = [
      input.priceLimit === undefined ? undefined : decimalString(input.priceLimit),
      intent.max_total_cap ?? undefined,
      intent.max_base_price ?? undefined,
    ].filter((value): value is string => value !== undefined);
    if (caps.length) {
      intent.max_total_cap = caps.reduce(
        (lowest, cap) => decimalCents(cap) < decimalCents(lowest) ? cap : lowest,
      );
      if (input.priceLimit !== undefined) {
        intent.parse_notes.push(
          `Applied the lower of the parsed cap and the UI per-purchase total limit (${intent.max_total_cap}).`,
        );
      }
    }
    this.lastIntent = intent;
    return mandateFromIntent(intent, input, this.defaults);
  }

  async search(maxResults = 10): Promise<Product[]> {
    if (!this.lastIntent) throw new Error('Interpret a mandate before searching the catalog.');
    const report = await requestJson<AuthorizedReport>('/api/shopping/search', {
      method: 'POST',
      body: JSON.stringify({ intent: this.lastIntent, max_results: maxResults }),
    });
    const options = report.results.flatMap((result) => result.best_options ?? []);
    if (options.length === 0) {
      const reason = report.halts?.[0]?.reason ?? 'The pipeline did not return an authorized product.';
      throw new Error(reason);
    }
    return options.map((option) => {
      productMoney.set(option.product_id, {
        subtotal: option.price,
        shipping: option.shipping_fee,
        total: moneyFromCents(decimalCents(option.price) + decimalCents(option.shipping_fee)),
      });
      return {
        id: option.product_id,
        name: option.product_name,
        category: 'Computer Accessories',
        merchantId: option.merchant_id ?? '',
        merchantName: option.merchant_name ?? option.brand,
        price: Number(option.price),
        shipping: Number(option.shipping_fee),
        currency: option.currency,
        rating: 0,
        description: option.description,
        source: 'Agentic Commerce pipeline',
      };
    });
  }

  async authorize(mandate: Mandate, transaction: Transaction): Promise<AuthorizationResult> {
    return requestJson<AuthorizationResult>('/api/authorization/evaluate', {
      method: 'POST',
      body: JSON.stringify({
        mandate: apiMandate(mandate),
        transaction: apiTransaction(transaction),
      }),
    });
  }

  async revokeMandate(mandate: Mandate): Promise<void> {
    if (!mandate.revokedAt) throw new Error('A revocation timestamp is required.');
    await requestJson(`/api/mandates/${encodeURIComponent(mandate.id)}/revoke`, {
      method: 'PATCH',
      body: JSON.stringify({ revokedAt: mandate.revokedAt }),
    });
  }

  async startPayment(transaction: Transaction): Promise<Transaction> {
    return requestJson<Transaction>(
      `/api/transactions/${encodeURIComponent(transaction.id)}/payment/start`,
      { method: 'POST', body: JSON.stringify(apiTransaction(transaction)) },
    );
  }

  async completePayment(transaction: Transaction, mandate: Mandate): Promise<Transaction> {
    return requestJson<Transaction>(
      `/api/transactions/${encodeURIComponent(transaction.id)}/payment/complete`,
      {
        method: 'POST',
        body: JSON.stringify({
          transaction: apiTransaction(transaction),
          mandate: apiMandate(mandate),
        }),
      },
    );
  }
}

export class HttpAuditRepository implements AuditRepository {
  async list(): Promise<AuditEvent[]> {
    return requestJson<AuditEvent[]>('/api/audit/logs');
  }

  async append(event: AuditEvent): Promise<void> {
    await requestJson('/api/audit/logs', {
      method: 'POST',
      body: JSON.stringify(stringifyAuditMoney(event)),
    });
  }

  async clear(): Promise<void> {
    await requestJson('/api/audit/logs', { method: 'DELETE' });
  }
}

export const commerceGateway: CommerceGateway = new HttpCommerceGateway();
export const auditRepository: AuditRepository = new HttpAuditRepository();
