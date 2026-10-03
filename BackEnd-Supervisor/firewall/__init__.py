"""Financial Firewall - deterministic purchase authorization.

Public API::

    from firewall import FinancialFirewall, FirewallRequest

    firewall = FinancialFirewall()
    decision = firewall.evaluate_purchase_plans(request)

The shopping agent proposes ranked purchase plans. The firewall decides whether
one of them is financially authorized. A language model is never the
authorization authority.
"""

from .authorization_engine import (
    AuthorizationEngine,
    ConfirmationProvider,
    FinancialFirewall,
    FirewallRequest,
    UnknownAskError,
)
from .audit import AuditService
from .blacklist import BlacklistError, BlacklistStore
from .models import (
    AuthorizationContext,
    FirewallAuditEvent,
    FirewallDecision,
    MerchantRisk,
    MerchantRiskProvider,
    PlanDecisionSummary,
    PlanEvaluation,
    PurchasePlan,
    RuleEvaluation,
    UserAuthorization,
    UserConfirmationResponse,
)
from .money import HKD_ZERO, Money, MoneyError
from .rating import calculate_merchant_rating, risk_level_for
from .rule_engine import RuleEngine
from .transaction import (
    InvalidTransitionError,
    Transaction,
    TransactionError,
    UnauthorizedTransactionError,
)
from .types import (
    AskReason,
    Currency,
    DecisionStatus,
    RiskLevel,
    RuleCode,
    RuleSeverity,
    TransactionState,
    UserConfirmation,
)
from .validation import (
    AuthorizationValidationError,
    PlanSetError,
    validate_plan,
    validate_user_authorization,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "AuthorizationEngine",
    "FinancialFirewall",
    "FirewallRequest",
    "ConfirmationProvider",
    "UnknownAskError",
    "RuleEngine",
    "AuditService",
    "BlacklistStore",
    "BlacklistError",
    "Money",
    "MoneyError",
    "HKD_ZERO",
    "AuthorizationContext",
    "UserAuthorization",
    "PurchasePlan",
    "MerchantRisk",
    "MerchantRiskProvider",
    "RuleEvaluation",
    "PlanEvaluation",
    "PlanDecisionSummary",
    "FirewallDecision",
    "FirewallAuditEvent",
    "UserConfirmationResponse",
    "Currency",
    "DecisionStatus",
    "RuleCode",
    "RuleSeverity",
    "RiskLevel",
    "AskReason",
    "TransactionState",
    "UserConfirmation",
    "calculate_merchant_rating",
    "risk_level_for",
    "AuthorizationValidationError",
    "PlanSetError",
    "validate_plan",
    "validate_user_authorization",
    "Transaction",
    "TransactionError",
    "InvalidTransitionError",
    "UnauthorizedTransactionError",
]
