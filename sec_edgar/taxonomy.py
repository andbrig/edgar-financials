"""Standard financial-statement line items mapped to US-GAAP XBRL tags.

Each metric lists candidate tags in priority order; the parser uses the first
tag that has data for a given frame. Units are USD except per-share items.
"""
from __future__ import annotations

# metric -> dict(label, statement, period, unit, tags)
METRICS: dict[str, dict] = {
    # ---------------- Income statement (duration) ----------------
    "revenue": dict(label="Revenue", statement="income", period="duration", unit="USD", tags=[
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ]),
    "cogs": dict(label="Cost of Revenue", statement="income", period="duration", unit="USD", tags=[
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfRevenue",
    ]),
    "gross_profit": dict(label="Gross Profit", statement="income", period="duration", unit="USD", tags=[
        "GrossProfit",
    ]),
    "rd": dict(label="R&D Expense", statement="income", period="duration", unit="USD", tags=[
        "ResearchAndDevelopmentExpense",
    ]),
    "sga": dict(label="SG&A Expense", statement="income", period="duration", unit="USD", tags=[
        "SellingGeneralAndAdministrativeExpense",
    ]),
    "operating_income": dict(label="Operating Income", statement="income", period="duration", unit="USD", tags=[
        "OperatingIncomeLoss",
    ]),
    "interest_expense": dict(label="Interest Expense", statement="income", period="duration", unit="USD", tags=[
        "InterestExpense",
        "InterestCostsIncurred",
    ]),
    "income_tax": dict(label="Income Tax Expense", statement="income", period="duration", unit="USD", tags=[
        "IncomeTaxExpenseBenefit",
    ]),
    "net_income": dict(label="Net Income", statement="income", period="duration", unit="USD", tags=[
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ]),
    "eps_basic": dict(label="EPS (Basic)", statement="income", period="duration", unit="USD/shares", tags=[
        "EarningsPerShareBasic",
    ]),
    "eps_diluted": dict(label="EPS (Diluted)", statement="income", period="duration", unit="USD/shares", tags=[
        "EarningsPerShareDiluted",
    ]),
    "shares_basic": dict(label="Weighted Avg Shares (Basic)", statement="income", period="duration", unit="shares", tags=[
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ]),
    "shares_diluted": dict(label="Weighted Avg Shares (Diluted)", statement="income", period="duration", unit="shares", tags=[
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ]),
    # ---------------- Balance sheet (instant) ----------------
    "assets": dict(label="Total Assets", statement="balance", period="instant", unit="USD", tags=[
        "Assets",
    ]),
    "current_assets": dict(label="Current Assets", statement="balance", period="instant", unit="USD", tags=[
        "AssetsCurrent",
    ]),
    "cash": dict(label="Cash & Equivalents", statement="balance", period="instant", unit="USD", tags=[
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalentsAtCarryingValueIncludingRestrictedCash",
    ]),
    "inventory": dict(label="Inventory", statement="balance", period="instant", unit="USD", tags=[
        "InventoryNet",
        "InventoryFinishedGoodsNetOfReserves",
    ]),
    "liabilities": dict(label="Total Liabilities", statement="balance", period="instant", unit="USD", tags=[
        "Liabilities",
    ]),
    "current_liabilities": dict(label="Current Liabilities", statement="balance", period="instant", unit="USD", tags=[
        "LiabilitiesCurrent",
    ]),
    "long_term_debt": dict(label="Long-Term Debt", statement="balance", period="instant", unit="USD", tags=[
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ]),
    "equity": dict(label="Total Equity", statement="balance", period="instant", unit="USD", tags=[
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ]),
    "retained_earnings": dict(label="Retained Earnings", statement="balance", period="instant", unit="USD", tags=[
        "RetainedEarningsAccumulatedDeficit",
    ]),
    # ---------------- Cash flow (duration) ----------------
    "cfo": dict(label="Operating Cash Flow", statement="cashflow", period="duration", unit="USD", tags=[
        "NetCashProvidedByUsedInOperatingActivities",
    ]),
    "cfi": dict(label="Investing Cash Flow", statement="cashflow", period="duration", unit="USD", tags=[
        "NetCashProvidedByUsedInInvestingActivities",
    ]),
    "cff": dict(label="Financing Cash Flow", statement="cashflow", period="duration", unit="USD", tags=[
        "NetCashProvidedByUsedInFinancingActivities",
    ]),
    "capex": dict(label="Capital Expenditures", statement="cashflow", period="duration", unit="USD", tags=[
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ]),
    "dividends": dict(label="Dividends Paid", statement="cashflow", period="duration", unit="USD", tags=[
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ]),
    "buybacks": dict(label="Share Buybacks", statement="cashflow", period="duration", unit="USD", tags=[
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ]),
}

TAXONOMIES = ("us-gaap", "dei")

# Ratios computed from base metrics (functions of metric->value dict)
def compute_ratios(m: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    rev, ni = m.get("revenue"), m.get("net_income")
    gp = m.get("gross_profit")
    eq, assets, liab = m.get("equity"), m.get("assets"), m.get("liabilities")
    ca, cl = m.get("current_assets"), m.get("current_liabilities")
    ltd = m.get("long_term_debt")
    if rev:
        if gp is not None:
            out["gross_margin"] = gp / rev
        if ni is not None:
            out["net_margin"] = ni / rev
    if ni and eq:
        out["roe"] = ni / eq
    if ni and assets:
        out["roa"] = ni / assets
    if liab is not None and eq:
        out["debt_to_equity"] = liab / eq
    if ca and cl:
        out["current_ratio"] = ca / cl
    if ltd is not None and eq:
        out["ltd_to_equity"] = ltd / eq
    return out

RATIO_LABELS = {
    "gross_margin": "Gross Margin",
    "net_margin": "Net Margin",
    "roe": "ROE",
    "roa": "ROA",
    "debt_to_equity": "Debt / Equity",
    "current_ratio": "Current Ratio",
    "ltd_to_equity": "LT Debt / Equity",
}
