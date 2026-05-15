"""
TARA Scratchpad Parser
Converts natural language text into structured transaction previews.
No external AI APIs required — fully rule-based.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ── Filipino month names ─────────────────────────────────────────────
FILIPINO_MONTHS = {
    'enero': 1, 'pebrero': 2, 'marso': 3, 'abril': 4,
    'mayo': 5, 'hunyo': 6, 'hulyo': 7, 'agosto': 8,
    'setyembre': 9, 'oktubre': 10, 'nobyembre': 11, 'disyembre': 12
}

ENGLISH_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

# ── Transaction type keywords ─────────────────────────────────────────
SALE_KEYWORDS = [
    'sold', 'nagbenta', 'benta', 'binenta', 'nabenta',
    'sale', 'sales', 'binebenta', 'nagbebenta'
]

EXPENSE_KEYWORDS = [
    'bayad', 'nagbayad', 'binayaran', 'binayad', 'gastos',
    'gumastos', 'nagastos', 'binili', 'bumili', 'bumibili',
    'bought', 'purchased', 'spent', 'paid for', 'binayaran ng',
    'nagbayad ng'
]

PAYMENT_RECEIVED_KEYWORDS = [
    'nagbayad', 'bayad', 'paid', 'nagbayad si', 'payment from',
    'bayad ni', 'nagpadala', 'nagsend', 'sent', 'gcash from',
    'maya from', 'gcash galing', 'maya galing'
]

# ── Category mapping (Filipino + English keywords) ────────────────────
CATEGORY_MAP = {
    'kuryente': 'Utilities', 'electricity': 'Utilities', 'ilaw': 'Utilities',
    'tubig': 'Utilities', 'water': 'Utilities',
    'internet': 'Utilities', 'wifi': 'Utilities', 'pldt': 'Utilities',
    'upa': 'Rent', 'rent': 'Rent', 'arkila': 'Rent',
    'supplies': 'Supplies', 'gamit': 'Supplies', 'kagamitan': 'Supplies',
    'palengke': 'Supplies', 'grocery': 'Supplies',
    'sahod': 'Salaries', 'sweldo': 'Salaries', 'salary': 'Salaries',
    'gasolina': 'Transportation', 'gas': 'Transportation', 'diesel': 'Transportation',
    'pamasahe': 'Transportation', 'fare': 'Transportation', 'commute': 'Transportation',
    'pagkain': 'Meals', 'food': 'Meals', 'kain': 'Meals', 'lunch': 'Meals',
    'load': 'Communication', 'cellphone': 'Communication', 'phone': 'Communication',
    'repair': 'Repairs', 'kumpuni': 'Repairs', 'pagawa': 'Repairs',
    'gamot': 'Medical', 'medicine': 'Medical', 'ospital': 'Medical',
}


def parse_date(text: str) -> datetime:
    """
    Extract date from text. Handles:
    - 'May 4', 'Mayo 4'
    - 'kahapon' → yesterday
    - 'ngayon' → today
    - Defaults to today if nothing found.
    """
    text_lower = text.lower()

    # Relative dates
    if 'kahapon' in text_lower or 'yesterday' in text_lower:
        return datetime.now() - timedelta(days=1)
    if 'ngayon' in text_lower or 'today' in text_lower:
        return datetime.now()

    # English: "May 4" or "May 4, 2026"
    for month_name, month_num in ENGLISH_MONTHS.items():
        pattern = rf'{month_name}\s+(\d{{1,2}})'
        match = re.search(pattern, text_lower)
        if match:
            day = int(match.group(1))
            year = datetime.now().year
            # Also check for year
            year_match = re.search(r'(\d{4})', text)
            if year_match:
                year = int(year_match.group(1))
            return datetime(year, month_num, day)

    # Filipino: "Mayo 4" or "Mayo 4, 2026"
    for month_name, month_num in FILIPINO_MONTHS.items():
        pattern = rf'{month_name}\s+(\d{{1,2}})'
        match = re.search(pattern, text_lower)
        if match:
            day = int(match.group(1))
            year = datetime.now().year
            year_match = re.search(r'(\d{4})', text)
            if year_match:
                year = int(year_match.group(1))
            return datetime(year, month_num, day)

    return datetime.now()


def extract_amounts(text: str) -> List[Tuple[float, int, int]]:
    """
    Find all monetary amounts with their positions.
    Returns list of (amount, start_pos, end_pos).
    Handles: '800', '₱800', 'P800', 'php 800', '800 pesos'
    """
    amounts = []

    # Pattern: optional currency symbol + number (possibly with commas)
    # ₱1,200 | P800 | php 500 | 350 pesos | 1k | 2.5k
    patterns = [
        (r'(?:₱|P|PHP|Php|php)\s*([\d,]+(?:\.\d{1,2})?)', 1),  # ₱800, P800, php 800
        (r'([\d,]+(?:\.\d{1,2})?)\s*(?:pesos|piso)', 1),          # 800 pesos
        (r'(\d+(?:\.\d+)?)\s*(k|K)', 1),                           # 2k, 1.5K → multiply by 1000
    ]

    for pattern, group_idx in patterns:
        for match in re.finditer(pattern, text):
            amount_str = match.group(group_idx).replace(',', '')
            amount = float(amount_str)

            # Handle 'k' suffix
            if match.lastindex and match.lastindex >= 2:
                suffix = match.group(2).lower() if match.lastindex >= 2 else ''
                if suffix == 'k':
                    amount *= 1000

            amounts.append((amount, match.start(), match.end()))

    # Bare numbers near transaction keywords (fallback)
    # Find numbers not already captured
    bare_numbers = re.finditer(r'(?<!\w)(\d{2,4})(?!\w)', text)
    for match in bare_numbers:
        num = int(match.group(1))
        # Check if this position was already captured
        already_captured = any(
            match.start() >= cap_start and match.end() <= cap_end
            for _, cap_start, cap_end in amounts
        )
        if not already_captured and 10 <= num <= 999999:
            amounts.append((float(num), match.start(), match.end()))

    return amounts


def extract_items(text: str) -> List[Dict]:
    """
    Parse patterns like:
    '5 lattes 800 each'
    '3 cookies 150 each and 2 brownies 200 each'
    Returns list of {product, quantity, unit_price, total}
    """
    items = []
    text_lower = text.lower()

    # Pattern: [quantity] [product] [price] each
    # Captures: "5 lattes 800 each"
    pattern = r'(\d+)\s+([a-zA-ZÀ-ÿ\s]+?)\s+(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:each|isa|bawat|per piece|per piraso)'
    matches = re.finditer(pattern, text_lower)

    for match in matches:
        qty = int(match.group(1))
        product = match.group(2).strip()
        price = float(match.group(3).replace(',', ''))
        items.append({
            'product': product,
            'quantity': qty,
            'unit_price': price,
            'total': qty * price
        })

    return items


def detect_transaction_type(text: str) -> str:
    """
    Returns one of: 'sale', 'expense', 'payment_received', 'unknown'
    """
    text_lower = text.lower()

    # Check sale first (sold + items pattern is strong signal)
    if any(kw in text_lower for kw in SALE_KEYWORDS):
        return 'sale'

    # Payment received
    if any(kw in text_lower for kw in PAYMENT_RECEIVED_KEYWORDS):
        return 'payment_received'

    # Expense
    if any(kw in text_lower for kw in EXPENSE_KEYWORDS):
        return 'expense'

    return 'unknown'


def detect_category(text: str) -> Optional[str]:
    """Map keywords to expense/income categories."""
    text_lower = text.lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in text_lower:
            return category
    return None


def detect_payment_method(text: str) -> Optional[str]:
    """Detect payment method from text."""
    text_lower = text.lower()
    if 'gcash' in text_lower:
        return 'GCash'
    if 'maya' in text_lower:
        return 'Maya'
    if 'cash' in text_lower or 'pera' in text_lower:
        return 'Cash'
    if 'bank' in text_lower or 'bangko' in text_lower:
        return 'Bank Transfer'
    return None


def extract_person(text: str, txn_type: str) -> Optional[str]:
    """
    Extract person name for payment_received or AR-related entries.
    Patterns: 'si Juan', 'from Juan', 'ni Maria', 'Aling Rosa'
    """
    text_lower = text.lower()

    patterns = [
        r'(?:from|galing|kay)\s+([A-ZÀ-ÿ][a-zÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zÀ-ÿ]+)?)',
        r'(?:si|ni)\s+([A-ZÀ-ÿ][a-zÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zÀ-ÿ]+)?)',
        r'([A-ZÀ-ÿ][a-zÀ-ÿ]+\s+[A-ZÀ-ÿ][a-zÀ-ÿ]+)\s+(?:paid|nagbayad|nagsend|sent)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def parse(text: str) -> Dict:
    """
    Main entry point. Takes freeform text, returns structured transaction preview.

    Returns:
    {
        'success': True/False,
        'transaction_type': 'sale'|'expense'|'payment_received'|'unknown',
        'date': datetime,
        'items': [...],          # For sales
        'total_amount': float,
        'category': str,         # For expenses
        'payment_method': str,
        'person': str,           # Customer/payee name
        'description': str,      # Cleaned description
        'confidence': float,     # 0.0 - 1.0
        'breakdown': str,        # Human-readable explanation
    }
    """
    if not text or len(text.strip()) < 3:
        return {'success': False, 'error': 'Text too short', 'confidence': 0.0}

    result = {
        'success': True,
        'transaction_type': 'unknown',
        'date': parse_date(text),
        'items': [],
        'total_amount': 0.0,
        'category': None,
        'payment_method': None,
        'person': None,
        'description': text.strip(),
        'confidence': 0.0,
        'breakdown': '',
    }

    # Detect transaction type
    txn_type = detect_transaction_type(text)
    result['transaction_type'] = txn_type

    # Extract amounts
    amounts = extract_amounts(text)

    # Extract items (for sales)
    items = extract_items(text)

    if items:
        # This is likely a sale with items
        result['transaction_type'] = 'sale'
        result['items'] = items
        result['total_amount'] = sum(item['total'] for item in items)
        result['confidence'] = 0.9
        result['breakdown'] = f"Sale of {len(items)} item type(s), total ₱{result['total_amount']:,.2f}"
    elif amounts:
        # Use the largest amount as the transaction total
        # (first amount is usually the main one with currency symbol)
        main_amount = amounts[0][0]
        result['total_amount'] = main_amount

        if txn_type == 'sale':
            result['items'] = [{
                'product': 'Item',
                'quantity': 1,
                'unit_price': main_amount,
                'total': main_amount
            }]
            result['breakdown'] = f"Single sale, ₱{main_amount:,.2f}"

        elif txn_type == 'expense':
            result['category'] = detect_category(text)
            result['payment_method'] = detect_payment_method(text) or 'Cash'
            result['breakdown'] = f"Expense: {result['category'] or 'Uncategorized'}, ₱{main_amount:,.2f}"
            result['confidence'] = 0.75 if result['category'] else 0.5

        elif txn_type == 'payment_received':
            result['person'] = extract_person(text, txn_type)
            result['payment_method'] = detect_payment_method(text) or 'Cash'
            result['breakdown'] = f"Payment received"
            if result['person']:
                result['breakdown'] += f" from {result['person']}"
            result['breakdown'] += f", ₱{main_amount:,.2f}"
            result['confidence'] = 0.8 if result['person'] else 0.6

        else:
            # Unknown type but has amount — guess expense
            result['transaction_type'] = 'expense'
            result['category'] = detect_category(text)
            result['payment_method'] = detect_payment_method(text) or 'Cash'
            result['breakdown'] = f"Likely expense: {result['category'] or 'Uncategorized'}, ₱{main_amount:,.2f}"
            result['confidence'] = 0.3
    else:
        result['confidence'] = 0.0
        result['success'] = False
        result['error'] = 'No transaction amount detected. Try including a number like "800" or "₱800".'

    # Detect payment method if not already set
    if not result['payment_method']:
        result['payment_method'] = detect_payment_method(text)

    # Detect person if not already set
    if not result['person']:
        result['person'] = extract_person(text, txn_type)

    return result