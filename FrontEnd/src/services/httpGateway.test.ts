/**
 * Contract tests for the active HTTP adapter. These verify the serialized
 * frontend-to-API shapes without requiring a running backend.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpCommerceGateway } from './httpGateway';

const intent = {
  product_keywords: ['mouse'],
  max_base_price: '200.00',
  max_total_cap: null,
  preferred_brands: [],
  raw_request: 'Find me a mouse below HK$200 before shipping.',
  parse_notes: [],
};

describe('HttpCommerceGateway mandate transfer', () => {
  afterEach(() => vi.restoreAllMocks());

  it('keeps a base-price cap separate from the final-total mandate limit', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(intent), { status: 200 }),
    );
    const gateway = new HttpCommerceGateway({
      id: 'mandate-test',
      expiresAt: '2027-12-31T23:59:59.000Z',
    });

    const mandate = await gateway.interpretMandate({
      instruction: intent.raw_request,
    });

    expect(mandate.maxPerTransaction).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/mandates/interpret'),
      expect.objectContaining({
        body: JSON.stringify({ prompt: intent.raw_request }),
      }),
    );
  });

  it('sends the structured intent and full mandate to search', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(intent), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        results: [{
          best_options: [{
            product_id: 'WM-001',
            product_name: 'Test wireless mouse',
            brand: 'Example',
            description: 'Test item',
            price: '100.00',
            shipping_fee: '10.00',
            currency: 'HKD',
            merchant_id: 'merchant-001',
            merchant_name: 'Trusted merchant',
          }],
        }],
      }), { status: 200 }));
    const gateway = new HttpCommerceGateway({
      id: 'mandate-test',
      expiresAt: '2027-12-31T23:59:59.000Z',
    });
    const interpreted = await gateway.interpretMandate({
      instruction: intent.raw_request,
      priceLimit: 500,
    });
    const mandate = {
      ...interpreted,
      maxDailySpend: 750,
      allowedCategories: ['Computer Accessories'],
      allowedMerchants: ['merchant-001'],
    };

    const products = await gateway.search(mandate, 5);

    expect(products[0]).toMatchObject({
      id: 'WM-001',
      merchantId: 'merchant-001',
      price: 100,
      shipping: 10,
    });
    const searchBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(searchBody).toMatchObject({
      intent: {
        max_base_price: '200.00',
        max_total_cap: '500.00',
      },
      mandate: {
        maxPerTransaction: '500.00',
        maxDailySpend: '750.00',
        allowedCategories: ['Computer Accessories'],
        allowedMerchants: ['merchant-001'],
      },
      max_results: 5,
    });
  });
});
