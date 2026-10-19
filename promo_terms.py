"""Public promotion conditions from the SAME product card or confirmed detail page.

No inferred dates, no assumed memberships and no quantity inferred from pack
size (e.g. 3x50g is a package, not a minimum shopping quantity).
"""
from __future__ import annotations

import re

# An explicit time limit only. Keep day/month as printed when no year is shown.
DATE_RE = re.compile(
    r"(?<!\w)(?:(?:akce|sleva|platnost|nabídka)\s+(?:plat[ií]\s+)?)?"
    r"(?:plat[ií]\s+)?do\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?(?:\s*(20\d{2}))?(?!\d)",
    re.I,
)
MIN_QTY_RES = (
    re.compile(r"(?<!\w)od\s+(\d{1,2})\s*(?:ks|kus[uů]|balen[ií])\b", re.I),
    re.compile(r"p[řr]i\s+(?:n[aá]kupu|koupi)\s+(?:(?:alespo[nň]|min(?:im[aá]ln[eě]|\.)?)\s+)?(\d{1,2})\s*(?:ks|kus[uů]|balen[ií])\b", re.I),
    re.compile(r"(?<!\d)(\d{1,2})\s*(?:a|nebo)\s*v[ií]ce\s*(?:ks|kus[uů]|balen[ií])\b", re.I),
)
BUY_PLUS = re.compile(r"(?<!\d)([1-9]\d?)\s*\+\s*([1-9]\d?)\s*(?:zdarma|gratis)\b", re.I)
MEMBERSHIP = re.compile(r"(?<!\w)(?:s\s+(?:kartou|aplikac[ií])\s+(?:lidl\s*plus|kaufland\s*card|billa\s*klub|albert)|(?:jen|pouze)\s+(?:s\s+kartou|v\s+aplikaci|pro\s+[čc]leny)|klubov[aá]\s+cena|lidl\s*plus|kaufland\s*card|billa\s*klub)\b", re.I)
PERSONAL = re.compile(r"\b(?:pro\s+v[aá]s|personalizovan[aá]\s+(?:sleva|cena|nab[ií]dka))\b", re.I)
STOCKS = re.compile(r"\bdo\s+vyprod[aá]n[ií]\s+z[aá]sob\b", re.I)
OTHER_MULTIBUY = re.compile(r"\b(?:multikup|kup\s+v[ií]ce|mno[zž]stevn[ií]\s+(?:sleva|akce))\b", re.I)


def extract_promotion(text: str) -> dict:
    """Return only terms *explicitly present* in trusted product-level text."""
    if not isinstance(text, str):
        text = ''
    text = re.sub(r'\s+', ' ', text.replace('\u00a0', ' ')).strip()[:2100]
    until = ''
    m = DATE_RE.search(text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = m.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                # Validate impossible dates without inventing an absent year.
                import datetime
                datetime.date(int(year) if year else 2024, month, day)
                until = f'{day}. {month}.' + (f' {year}' if year else '')
            except ValueError:
                pass
    labels = []
    qty = None
    bundle = BUY_PLUS.search(text)
    if bundle:
        buy, extra = int(bundle.group(1)), int(bundle.group(2))
        labels.append(f'{buy}+{extra} zdarma')
        qty = buy + extra
    else:
        for rx in MIN_QTY_RES:
            minimum = rx.search(text)
            if minimum:
                n = int(minimum.group(1))
                if 2 <= n <= 99:
                    qty = n
                    labels.append(f'Od {n} ks')
                    break
        if qty is None and OTHER_MULTIBUY.search(text):
            labels.append('Množstevní akce – podmínky ověřit')
    if MEMBERSHIP.search(text):
        labels.append('Klubová cena / karta')
    if PERSONAL.search(text):
        labels.append('Individuální nabídka „pro vás“')
    if STOCKS.search(text):
        labels.append('Do vyprodání zásob')
    return {
        'promo_until': until,
        'promo_condition': '; '.join(dict.fromkeys(labels)),
        'promo_min_qty': qty,
    }


def is_conditional(item) -> bool:
    """Do not compare conditional prices with plain public prices."""
    if isinstance(item, dict):
        condition = item.get('promo_condition') or ''
        qty = item.get('promo_min_qty')
        terms = item.get('terms') or ''
    else:
        condition = getattr(item, 'promo_condition', '')
        qty = getattr(item, 'promo_min_qty', None)
        terms = getattr(item, 'terms', '')
    return bool(condition or (qty is not None and qty >= 2) or 'množstevní' in terms)
