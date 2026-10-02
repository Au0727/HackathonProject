"""Input adapters: upstream report parsing and trusted merchant data."""

from .merchant_catalog import (
    CatalogMerchantRiskProvider,
    MerchantCatalog,
    MerchantCatalogError,
    MerchantRecord,
)
from .shopping_report import (
    INFORMATIONAL_FIELDS,
    MAX_PLANS_PER_REQUEST,
    RequestReport,
    ShoppingReport,
    ShoppingReportAdapter,
    ShoppingReportError,
    UnknownRequestError,
)

__all__ = [
    "MerchantCatalog",
    "MerchantRecord",
    "MerchantCatalogError",
    "CatalogMerchantRiskProvider",
    "ShoppingReportAdapter",
    "ShoppingReport",
    "RequestReport",
    "ShoppingReportError",
    "UnknownRequestError",
    "MAX_PLANS_PER_REQUEST",
    "INFORMATIONAL_FIELDS",
]
