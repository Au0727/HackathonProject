"""
Flask Backend Example — Complete Starter Code

This is a WORKING example showing how to implement all 5 endpoints
the frontend expects. Copy this and adapt it for your LLM and policy logic.

Run:
  pip install flask flask-cors python-dotenv
  python backend.py
  
Then frontend will connect to http://localhost:3000
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import uuid
from typing import Dict, List, Any

app = Flask(__name__)
CORS(app)  # Allow frontend to call backend from different origin

# ============================================================================
# MOCK DATA (replace with database queries in production)
# ============================================================================

CATALOG = [
    {
        "id": "mouse-quiet",
        "name": "QuietClick Wireless Mouse",
        "category": "Computer Accessories",
        "merchantId": "campus-tech",
        "merchantName": "Campus Tech",
        "price": 219,
        "shipping": 20,
        "currency": "HKD",
        "rating": 4.8,
        "description": "Silent clicks, Bluetooth and USB receiver.",
        "source": "Observed 2026-09-15",
        "observedAt": "2026-09-15T09:00:00.000Z"
    },
    {
        "id": "keyboard-pro",
        "name": "MechanicalPro Keyboard",
        "category": "Computer Accessories",
        "merchantId": "student-store",
        "merchantName": "Student Store",
        "price": 580,
        "shipping": 30,
        "currency": "HKD",
        "rating": 4.6,
        "description": "RGB backlit, mechanical switches.",
        "source": "Observed 2026-09-15",
        "observedAt": "2026-09-15T09:00:00.000Z"
    }
]

# Store transactions and mandates in memory (use DB in production)
transactions: Dict[str, Dict] = {}
mandates: Dict[str, Dict] = {}
audit_events: List[Dict] = []

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_id(prefix: str) -> str:
    """Generate a unique ID with a prefix."""
    return f"{prefix}-{str(uuid.uuid4())[:8]}"

def current_timestamp() -> str:
    """ISO 8601 timestamp."""
    return datetime.utcnow().isoformat() + 'Z'

def log_audit(
    transaction_id: str = None,
    event_type: str = "UNKNOWN",
    actor: str = "POLICY_ENGINE",
    summary: str = "",
    data: Dict = None
) -> Dict:
    """Record an audit event."""
    event = {
        "id": generate_id("audit"),
        "transactionId": transaction_id,
        "timestamp": current_timestamp(),
        "eventType": event_type,
        "actor": actor,
        "summary": summary,
        "data": data or {}
    }
    audit_events.append(event)
    print(f"[AUDIT] {actor}: {summary}")
    return event

# ============================================================================
# ENDPOINT 1: GET /api/catalog
# ============================================================================

@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    """
    Return the controlled product catalog.
    
    Response: Product[]
    """
    print("[GET] /api/catalog")
    return jsonify(CATALOG), 200

# ============================================================================
# ENDPOINT 2: POST /api/mandates/interpret
# ============================================================================

def mock_llm_interpret(instruction: str, price_limit: float) -> Dict[str, Any]:
    """
    MOCK LLM: Parse natural language into mandate structure.
    
    In production, call your real LLM here (OpenAI, Claude, etc).
    Make sure to constrain the output to a JSON schema matching Mandate type.
    """
    instruction_lower = instruction.lower()
    
    # Naive keyword matching (replace with real LLM)
    categories = []
    if any(word in instruction_lower for word in ["mouse", "keyboard", "monitor"]):
        categories.append("Computer Accessories")
    if any(word in instruction_lower for word in ["book", "pen", "paper"]):
        categories.append("Stationery")
    
    merchants = []
    if "campus" in instruction_lower:
        merchants.append("campus-tech")
    if "student" in instruction_lower:
        merchants.append("student-store")
    
    # Default: allow all if not specified
    if not merchants:
        merchants = ["campus-tech", "student-store"]
    if not categories:
        categories = ["Computer Accessories", "Stationery"]
    
    return {
        "categories": categories,
        "merchants": merchants,
    }

@app.route('/api/mandates/interpret', methods=['POST'])
def interpret_mandate():
    """
    Convert user's natural-language instruction to a structured Mandate.
    
    Request body:
    {
      "instruction": string,    // e.g. "Buy me a quiet mouse under HK$300"
      "priceLimit": number      // e.g. 300
    }
    
    Response: Mandate (JSON)
    {
      "id": string,
      "maxPerTransaction": number,
      "allowedCategories": string[],
      "allowedMerchants": string[],
      "expiresAt": string (ISO 8601)
    }
    """
    print("[POST] /api/mandates/interpret")
    
    # Step 1: Extract request body
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is empty"}), 400
    
    instruction = data.get('instruction', '').strip()
    price_limit = data.get('priceLimit')
    
    # Step 2: Validate inputs
    if not instruction:
        return jsonify({"error": "instruction is required"}), 400
    
    if price_limit is None:
        return jsonify({"error": "priceLimit is required"}), 400
    
    try:
        price_limit = float(price_limit)
        if price_limit <= 0:
            raise ValueError("must be positive")
    except (ValueError, TypeError):
        return jsonify({"error": "priceLimit must be a positive number"}), 400
    
    # Step 3: Call LLM to interpret
    print(f"  Interpreting: '{instruction}' with limit HK${price_limit}")
    parsed = mock_llm_interpret(instruction, price_limit)
    
    # Step 4: Build response
    mandate_id = generate_id("mandate")
    response = {
        "id": mandate_id,
        "maxPerTransaction": price_limit,
        "maxDailySpend": price_limit * 2,  # arbitrary
        "allowedCategories": parsed["categories"],
        "allowedMerchants": parsed["merchants"],
        "expiresAt": (datetime.utcnow() + timedelta(days=365)).isoformat() + 'Z'
    }
    
    # Step 5: Store and return
    mandates[mandate_id] = response
    print(f"  ✓ Created mandate {mandate_id}")
    log_audit(
        event_type="MANDATE_INTERPRETED",
        actor="AGENT",
        summary=f"Interpreted user instruction into mandate {mandate_id}",
        data={"instruction": instruction, "mandateId": mandate_id}
    )
    
    return jsonify(response), 200

# ============================================================================
# ENDPOINT 3: POST /api/authorization/evaluate
# ============================================================================

def evaluate_policy(mandate: Dict, transaction: Dict) -> Dict[str, Any]:
    """
    DETERMINISTIC policy engine.
    
    This is the core logic: given a mandate and a transaction,
    decide ALLOW or DENY. The decision is based on rules, not LLM.
    
    Rules:
      1. Expiry: mandate must not be expired
      2. Revocation: mandate must not be revoked
      3. Max per transaction: total must not exceed maxPerTransaction
      4. Category: product must be in allowedCategories
      5. Merchant: product must be in allowedMerchants
    """
    failed_rules = []
    rule_checks = []
    
    # Rule 1: Expiry
    expiry = mandate.get('expiresAt', '')
    is_expired = datetime.fromisoformat(expiry.rstrip('Z')) < datetime.utcnow()
    if is_expired:
        failed_rules.append('EXPIRED')
    rule_checks.append({
        "id": "EXPIRED",
        "label": "Not expired",
        "passed": not is_expired,
        "detail": f"Expires {expiry}"
    })
    
    # Rule 2: Revocation
    is_revoked = 'revokedAt' in mandate and mandate['revokedAt']
    if is_revoked:
        failed_rules.append('REVOKED')
    rule_checks.append({
        "id": "REVOKED",
        "label": "Not revoked",
        "passed": not is_revoked,
        "detail": f"Revoked at {mandate.get('revokedAt', 'N/A')}"
    })
    
    # Rule 3: Max per transaction
    total = transaction.get('total', 0)
    max_txn = mandate.get('maxPerTransaction')
    passes_max = max_txn is None or total <= max_txn
    if not passes_max:
        failed_rules.append('MAX_PER_TRANSACTION')
    rule_checks.append({
        "id": "MAX_PER_TRANSACTION",
        "label": "Final total",
        "passed": passes_max,
        "detail": f"HK${total} vs limit HK${max_txn}" if max_txn else "No limit"
    })
    
    # Rule 4: Category
    # (In real system, look up product's category from catalog)
    category = "Computer Accessories"  # mock
    allowed_cats = mandate.get('allowedCategories', [])
    passes_category = not allowed_cats or category in allowed_cats
    if not passes_category:
        failed_rules.append('CATEGORY')
    rule_checks.append({
        "id": "CATEGORY",
        "label": "Approved category",
        "passed": passes_category,
        "detail": f"Category '{category}'"
    })
    
    # Rule 5: Merchant
    merchant = transaction.get('merchantId', '')
    allowed_merchants = mandate.get('allowedMerchants', [])
    passes_merchant = not allowed_merchants or merchant in allowed_merchants
    if not passes_merchant:
        failed_rules.append('MERCHANT')
    rule_checks.append({
        "id": "MERCHANT",
        "label": "Approved merchant",
        "passed": passes_merchant,
        "detail": f"Merchant '{merchant}'"
    })
    
    # Decision
    decision = 'ALLOW' if not failed_rules else 'DENY'
    
    if decision == 'ALLOW':
        reason = "All policy checks passed. Transaction is authorized."
    else:
        reason = f"Policy check failed on: {', '.join(failed_rules)}"
    
    return {
        "decision": decision,
        "reason": reason,
        "failedRules": failed_rules,
        "evaluatedAt": current_timestamp(),
        "mandateId": mandate.get('id'),
        "ruleChecks": rule_checks
    }

@app.route('/api/authorization/evaluate', methods=['POST'])
def authorize():
    """
    Evaluate a transaction against a mandate using deterministic policy rules.
    
    Request body:
    {
      "mandate": Mandate,
      "transaction": Transaction
    }
    
    Response: AuthorizationResult
    {
      "decision": "ALLOW" | "DENY",
      "reason": string,
      "failedRules": string[],
      "evaluatedAt": string (ISO 8601),
      "mandateId": string,
      "ruleChecks": RuleCheck[]
    }
    """
    print("[POST] /api/authorization/evaluate")
    
    data = request.get_json()
    mandate = data.get('mandate', {})
    transaction = data.get('transaction', {})
    
    print(f"  Mandate: {mandate.get('id')}")
    print(f"  Transaction: {transaction.get('id')} (total: HK${transaction.get('total')})")
    
    # Evaluate policy
    result = evaluate_policy(mandate, transaction)
    
    # Log the decision
    log_audit(
        transaction_id=transaction.get('id'),
        event_type="POLICY_EVALUATED",
        actor="POLICY_ENGINE",
        summary=f"Authorization {result['decision']}: {result['reason']}",
        data=result
    )
    
    print(f"  ✓ Decision: {result['decision']}")
    return jsonify(result), 200

# ============================================================================
# ENDPOINT 4: POST /api/transactions/:id/payment/start
# ============================================================================

@app.route('/api/transactions/<txn_id>/payment/start', methods=['POST'])
def start_payment(txn_id):
    """
    Move transaction from AUTHORIZED to PAYMENT_PENDING.
    This is where the simulated payment rail takes over.
    
    In production:
      - Use idempotency keys to prevent double-charging
      - Lock the transaction in the DB
      - Initiate payment processing
    
    Request body: Transaction
    Response: Transaction (status='PAYMENT_PENDING')
    """
    print(f"[POST] /api/transactions/{txn_id}/payment/start")
    
    data = request.get_json()
    transaction = dict(data)  # copy
    transaction['status'] = 'PAYMENT_PENDING'
    transaction['updatedAt'] = current_timestamp()
    
    # Store for later lookup
    transactions[txn_id] = transaction
    
    log_audit(
        transaction_id=txn_id,
        event_type="PAYMENT_INITIATED",
        actor="PAYMENT_SIMULATOR",
        summary=f"Transaction moved to PAYMENT_PENDING",
        data={"txnId": txn_id}
    )
    
    print(f"  ✓ Status: PAYMENT_PENDING")
    return jsonify(transaction), 200

# ============================================================================
# ENDPOINT 5: POST /api/transactions/:id/payment/complete
# ============================================================================

@app.route('/api/transactions/<txn_id>/payment/complete', methods=['POST'])
def complete_payment(txn_id):
    """
    Complete payment: PAYMENT_PENDING → COMPLETED or CANCELLED.
    
    CRITICAL: Before completing, re-check the mandate for:
      - Expiry (has the mandate expired?)
      - Revocation (did the user revoke during checkout?)
    
    If either is true, transition to CANCELLED instead of COMPLETED.
    This must be atomic (same DB transaction) so a race is impossible.
    
    Request body: { "transaction": Transaction, "mandate": Mandate }
    Response: Transaction (status='COMPLETED' or 'CANCELLED')
    """
    print(f"[POST] /api/transactions/{txn_id}/payment/complete")
    
    data = request.get_json()
    transaction = dict(data.get('transaction', {}))
    mandate = data.get('mandate', {})
    
    # Re-check mandate
    is_expired = datetime.fromisoformat(mandate.get('expiresAt', '').rstrip('Z')) < datetime.utcnow()
    is_revoked = 'revokedAt' in mandate and mandate['revokedAt']
    
    if is_expired or is_revoked:
        # Cancel the transaction
        transaction['status'] = 'CANCELLED'
        reason = "Mandate was revoked during payment" if is_revoked else "Mandate expired during payment"
        log_audit(
            transaction_id=txn_id,
            event_type="PAYMENT_CANCELLED",
            actor="POLICY_ENGINE",
            summary=reason,
            data={"txnId": txn_id, "reason": reason}
        )
        print(f"  ✓ Status: CANCELLED ({reason})")
    else:
        # Complete the transaction
        transaction['status'] = 'COMPLETED'
        log_audit(
            transaction_id=txn_id,
            event_type="PAYMENT_COMPLETED",
            actor="PAYMENT_SIMULATOR",
            summary="Payment completed successfully",
            data={"txnId": txn_id}
        )
        print(f"  ✓ Status: COMPLETED")
    
    transaction['updatedAt'] = current_timestamp()
    transactions[txn_id] = transaction
    
    return jsonify(transaction), 200

# ============================================================================
# BONUS ENDPOINT: GET /api/audit
# ============================================================================

@app.route('/api/audit', methods=['GET'])
def get_audit():
    """
    Return all recorded audit events.
    In production, paginate and filter by date/actor.
    """
    print("[GET] /api/audit")
    return jsonify(audit_events), 200

@app.route('/api/audit', methods=['DELETE'])
def clear_audit():
    """
    Clear all audit events (dev/testing only).
    """
    print("[DELETE] /api/audit")
    audit_events.clear()
    return jsonify({"cleared": True}), 200

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    print(f"[ERROR] {error}")
    return jsonify({"error": "Internal server error"}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          GUARDRAIL BACKEND — Flask Development Server         ║
╚═══════════════════════════════════════════════════════════════╝

Endpoints:
  GET  /api/catalog
  POST /api/mandates/interpret
  POST /api/authorization/evaluate
  POST /api/transactions/<id>/payment/start
  POST /api/transactions/<id>/payment/complete
  GET  /api/audit
  DELETE /api/audit

Frontend URL: http://localhost:5173
Backend URL: http://localhost:3000
CORS: Enabled (all origins)

Starting server...
    """)
    
    app.run(
        host='0.0.0.0',
        port=3000,
        debug=True,
        use_reloader=True
    )
