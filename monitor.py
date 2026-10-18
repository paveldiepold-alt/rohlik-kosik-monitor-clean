#!/usr/bin/env python3
"""Rohlík × Košík – public sale-page price watch (unofficial).

No credentials. Reads visible public listing cards with Playwright. Does NOT
claim catalog completeness, personalized prices or stock. Failures are surfaced.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import hashlib
import io
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
DATA = ROOT / "docs" / "data"
PRODUCT_URLS = {
    "Rohlík": re.compile(r"^/\d{5,}(?:-[a-z0-9-]+)?/?$", re.I),
    "Košík": re.compile(r"^/p\d+(?:-[a-z0-9-]+)?/?$", re.I),
}
PRICE_DECIMAL = re.compile(r"(?<!\d)(\d{1,4})[,.](\d{2})(?!\d)")
PRICE_SPLIT = re.compile(r"(?<!\d)(\d{1,4})[ \u00a0\u202f\n\r]+(\d{2})(?!\d)")
SALE_PCT = re.compile(r"(?<!\w)[−\-]\s*(\d{1,2})\s*%")
SIZE_PATTERN = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|ks)\b", re.I)

@dataclass
class Offer:
    shop: str
    name: str
    url: str
    price: float
    discount_pct: int
    old_price: float | None
    brand: str
    favorite: bool
    quantity: str
    terms: str
    comparable_group: str = ""
    other_shop_price: float | None = None
    other_shop_url: str = ""
    other_shop: str = ""
    category: str = ""
    rule_id: str = ""
    note: str = ""
    # Additional product metadata. Missing values are never guessed.
    image_url: str = ""
    unit_price: float | None = None
    unit_label: str = ""   # Kč/l or Kč/kg, only when pack volume is certain
    detail_source: str = ""   # listing / product page


def normalized(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("×", "x").replace("&", " a ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


# Retailer accessibility labels are UI commands, not product identities.
# Košík can expose an anchor as "Zobrazit detail produktu Hellmann's Majonéza".
UI_TITLE_PREFIXES = (
    re.compile(r"^(?:zobrazit|otev[rř][ií]t|prohl[eé]dnout)\s+detail\s+produktu\s*[:\-–]?\s*", re.I),
    re.compile(r"^(?:zobrazit|otev[rř][ií]t)\s+produkt\s*[:\-–]?\s*", re.I),
)


def clean_product_name(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    value = " ".join(raw.replace("\u00a0", " ").split()).strip()
    for pat in UI_TITLE_PREFIXES:
        value = pat.sub("", value, count=1).strip()
    return value


# Only plain RAW cuts of meat are eligible. Matching a keyword such as
# "krůtí prsa" inside a jerky/can/ready meal must not create a notification.
# Do not assume every processed product discloses its treatment in its title:
# ambiguous listings are omitted where a reliable raw-cut descriptor is absent.
NON_RAW_MEAT = (
    # Pet food and human baby food have been observed as false matches of "kuřecí prsa".
    "applaws", "brit care", "granule", "kapsick*", "pro kocky",
    "pro psy", "kocici", "psim", "krmivo", "cat kitten", "dog adult",
    "pamlsk*", "zradlo", "konzerva pro psy", "konzerva pro kocky",
    "just meat", "jerky", "biltong", "snack*", "proteinov*", "tycink*",
    "susen*", "vysusen*", "dehydratovan*", "lyofilizovan*", "fermentovan*",
    "konzerv*", "plechov*", "plechovk*", "sklenic*", "sterilovan*", "zavaren*",
    "hotov*", "predvar*", "vareny", "varene", "varena", "dusen*", "pecen*",
    "grilovan*", "smazen*", "sote", "sous vide", "trhane maso",
    "uzen*", "uzene", "uzena", "uzenin*", "sunka", "parky", "parek",
    "klobas*", "salam*", "pastik*", "pomazank*", "masova smes", "ragu",
    "omack*", "polevk*", "na smetane", "burger", "hamburger", "sendvic*", "baget*",
    "salat", "salaty", "wrap", "pizza", "rizoto", "testovin*", "ravioli",
    "nugget*", "obalovan*", "strouhank*", "sekan*", "mlete*", "mleta*",
    "masovy vyrobek", "marinovan*", "marinad*", "nakladan*", "ochucen*", "gyros", "kebab",
    "korenen*", "kořeněn*", "pepr*", "pepr", "peprem", "soleny", "solene",
    "solena", "s soli", "soli", "s korenim", "s bylinkami", "bylinkov*",
    "cesnekov*", "grilovaci", "bbq", "teriyaki", "pikantni", "paprikov*",
)

# In raw cuts, simple titles like "Kuřecí prsní řízky bez kosti" and
# "Vepřová krkovice plátky" are okay, but marketing names alone aren't.
RAW_MEAT_CUT_TERMS = (
    "prsni riz*", "kureci prs*", "kruti prs*", "kureci riz*", "kruti riz*",
    "kureci stehn*", "kruti stehn*", "kureci palick*", "stehenni riz*",
    "veprova krkovic*", "krkovice vepr*", "krkovic*",
    "veprova panenk*", "panenka vepr*",
    "hovezi svickov*", "svickova hovezi", "svickova prava", "svickova falesna",
)


def is_raw_meat_name(name: str) -> bool:
    """Only raw *chicken* breast/thigh cuts, pork neck/tenderloin, beef tenderloin.

    A user's updated shopping list removed all turkey. Search terms may have
    descriptive words between chicken and thighs: e.g. 'Kuřecí vykostěná
    stehna'. Reject cooked, seasoned and otherwise processed meat first.
    """
    n = normalized(clean_product_name(name))
    if any(term_matches(n, bad) for bad in NON_RAW_MEAT):
        return False
    # Poultry is chicken ONLY, including reordered / descriptively expanded titles.
    # 'Krůtí' is deliberately excluded even when there are chicken-like words.
    chicken = (term_matches(n, 'kureci') and not term_matches(n, 'kruti')
               and any(term_matches(n, cut) for cut in (
                   'prsni riz*', 'prsa', 'prsou', 'prsick*', 'stehn*', 'palick*',
                   'rizky', 'rizku', 'rizky')))
    # Krkovice and panenka are names of pork cuts; processed versions are
    # blocked by NON_RAW_MEAT above.
    pork = (term_matches(n, 'krkovic*') or
            (term_matches(n, 'panenk*') and any(term_matches(n, w) for w in
                                                ('veprova', 'veprove', 'veprovy', 'veprove'))))
    # A 'falešná svíčková' is a different cut; exclude it specifically.
    beef = (term_matches(n, 'svickov*') and not term_matches(n, 'falesn*')
            and (term_matches(n, 'hovezi') or term_matches(n, 'prava')))
    return bool(chicken or pork or beef)


def scrub_historical_meat(config: dict) -> int:
    """Remove meat false positives from archival snapshots (idempotent)."""
    history = DATA / "history"
    removed_total = 0
    for path in sorted(history.glob("*.json")) if history.exists() else []:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        offers = snapshot.get("offers")
        if not isinstance(offers, list):
            continue
        kept = [o for o in offers if o.get("category") != "Maso" or is_raw_meat_name(o.get("name", ""))]
        if len(offers) != len(kept):
            snapshot["offers"] = kept
            urls = {o.get("url") for o in kept}
            snapshot["changes"] = [x for x in snapshot.get("changes", []) if x.get("url") in urls]
            snapshot["raw_meat_filter_repaired"] = True
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            removed_total += len(offers) - len(kept)
    return removed_total


def brand_of(name: str, brands: list[dict]) -> str:
    # Anchored: avoids matching brand names inside unrelated words.
    check = " " + normalized(name) + " "
    for b in brands:
        for alias in b["aliases"]:
            key = normalized(alias)
            if key and (" " + key + " ") in check:
                return b["name"]
    return ""



def term_matches(n: str, expression: str) -> bool:
    """Case-/diacritic-insensitive full word/phrase, with terminal * prefix notation.

    This avoids accidental 'Axe' matches in unrelated words and allows Czech
    grammatical variants like šunk* / paprik* without unrestricted substrings.
    """
    prefix = expression.endswith("*")
    term = normalized(expression[:-1] if prefix else expression)
    if not term:
        return False
    if prefix:
        return re.search(r"(?<![a-z0-9])"+re.escape(term)+r"[a-z0-9]*", n) is not None
    return " " + term + " " in " " + n + " "



# These groups contain only unprocessed, fresh whole fruit and vegetables.
# Matching "banana" or "raspberry" anywhere in a title is NOT enough:
# that would incorrectly classify yogurt, supplements, beverages and snacks.
FRESH_PRODUCE_WORDS = {
    "W037": ("avokado", "avokada"),
    "W038": ("banan", "banany", "bananu"),
    "W039": ("boruvka", "boruvky", "boruvek"),
    "W040": ("malina", "maliny", "malin"),
    "W041": ("citron", "citrony", "citronu"),
    "W042": ("hrozny", "hroznu", "hroznove vino", "hroznoveho vina"),
    "W043": ("okurka", "okurky", "okurek", "okurku"),
    "W044": ("rajce", "rajcata", "rajcat"),
    "W045": ("rajce", "rajcata", "rajcat"),
    "W046": ("mrkev", "mrkve", "mrkvicka", "mrkvicky", "karotka", "karotky", "karotek"),
    "W047": ("paprika", "papriky", "papriku", "paprik"),
}

# Legitimate descriptors before the commodity, such as "BIO mrkev",
# "České čerstvé borůvky" or "Chiquita banány". This deliberately errs
# on the side of omitting ambiguous listings rather than false alerts.
FRESH_PRODUCE_PREFIX = frozenset("""
    bio cerstve cerstva cerstvy cerstvych cerstvi ceske ceska cesky
    ceskych farmarske farmarska farmarsky farmarskych vyberove vyberova
    premium organic eko lokalni velke male sladke sladka sladka
    spanelske spanelska italske italska belgicke peruanske
    chiquita bonita dole del monte farm fresh nature cherry mini
    koktejlova koktejlove baby volne balene balena baleny
""".split())

# Whole fresh produce only: never the fruit-flavoured version of another item,
# juice, sweet, dairy product, ready meal, preserved/dried/frozen produce,
# cosmetics, supplements, etc. Patterns are applied to complete word stems.
NON_FRESH_PRODUCE = (
    "actimel*", "magnesia", "dr max", "vitamin*", "tablet*", "horcik*",
    "dopln*", "probiot*", "napoj*", "limonad*", "dzus*", "nektar*",
    "smoothie", "sirup*", "stavy", "stava", "stavu", "stav", "caj", "caje",
    "jogurt*", "kefir*", "mleko", "mlecny", "mlecna", "mlecne",
    "mozzarella", "syr", "syry", "toast*", "sendvic*", "bageta",
    "dezert*", "pudink*", "krem*", "koktejl", "koktejly", "zmrzlin*",
    "pecivo", "kolac*", "buchta", "bucht*", "rohlik", "tycink*",
    "susen*", "susenk*", "lyofiliz*", "mrazen*", "zmrazen*",
    "chips*", "cokolad*", "polev*", "bonbon*", "cukrovink*", "cereali*",
    "marmelad*", "dzem*", "protlak*", "kecup*", "kase", "kasi",
    "pyre", "presnidavk*", "prichut*", "aroma*", "ochucen*", "esence",
    "ravioli", "testovin*", "rizoto", "pizza", "omack*", "polevk*", "na smetane",
    "hotove jidlo", "hotov*", "pomazank*", "koreni", "mlet*",
    "konzerv*", "sterilovan*", "nakladan*", "zavaren*", "kysel*", "kandovan*", "plnen*",
    "fermentovan*", "grilovan*", "pecen*", "marinovan*", "olej*",
    "protein*", "kapsl*", "sampon*", "kosmetik*", "maska", "gel",
    "cistic*", "mydlo", "vune", "sprej", "doplnek stravy",
)


def is_fresh_produce_name(name: str, rule: dict) -> bool:
    """True only if the main product is fresh whole fruit/vegetables.

    Without a reliable shop-category field, ambiguous offers are omitted.
    Avoid inferring the commodity from an ingredient/flavour anywhere in name.
    """
    if rule.get("category") not in ("Ovoce", "Zelenina"):
        return True
    lexicon = FRESH_PRODUCE_WORDS.get(rule.get("id"), ())
    if not lexicon:
        return False  # Fail closed for new produce rules pending review.
    n = normalized(name)
    if any(term_matches(n, word) for word in NON_FRESH_PRODUCE):
        return False
    tokens = n.split()
    # Require a whole-word produce noun. Banana-flavoured adjectives such as
    # "banánové", "malinový" or "citronová" do not qualify.
    for commodity in lexicon:
        words = commodity.split()
        for i in range(len(tokens) - len(words) + 1):
            if tokens[i:i + len(words)] != words:
                continue
            # All words before the commodity must be known fresh-produce
            # descriptors (not "Actimel Kids ..." or "Dr.Max ...").
            if i <= 5 and all(w in FRESH_PRODUCE_PREFIX for w in tokens[:i]):
                return True
    return False


def scrub_historical_produce(config: dict) -> int:
    """Repair misleading fruit/vegetable entries from pre-v7 daily archives.

    Preserve genuine prices/history, removing only incorrectly classified
    produce rows. This is idempotent, so scheduled runs can invoke it safely.
    """
    history = DATA / "history"
    rules_by_id = {r["id"]: r for r in config.get("watch_rules", [])}
    removed_total = 0
    for path in sorted(history.glob("*.json")) if history.exists() else []:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        offers = snapshot.get("offers")
        if not isinstance(offers, list):
            continue
        kept = []
        for offer in offers:
            if offer.get("category") not in ("Ovoce", "Zelenina"):
                kept.append(offer)
                continue
            rule = rules_by_id.get(offer.get("rule_id", ""))
            if not rule:
                rule = match_rules(offer.get("name", ""), config.get("watch_rules", []))
            if rule and rule.get("category") in ("Ovoce", "Zelenina") and is_fresh_produce_name(offer.get("name", ""), rule):
                kept.append(offer)
        removed = len(offers) - len(kept)
        if removed:
            snapshot["offers"] = kept
            kept_urls = {o["url"] for o in kept}
            snapshot["changes"] = [c for c in snapshot.get("changes", []) if c.get("url") in kept_urls]
            snapshot["produce_filter_repaired"] = True
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            removed_total += removed
    return removed_total


# Beverage rules require bottle-size compliance, not a keyword-only match.
# These constraints refer to the volume of ONE bottle, never the sum of a pack.
# Czech listings often omit the packaging material from the title: for such
# listings, PET is a plausible inference from the retail bottle size, not a
# verified packaging claim. Explicitly non-PET packages are always rejected.
BEVERAGE_SIZES = {
    "Nápoje / limonády": (1.0, None),   # PET bottle of 1 l or more
    "Nápoje / vody": (1.5, 1.5),      # PET bottle of precisely 1.5 l
}
BEVERAGE_VOLUME = re.compile(
    r"(?<![\d.,])(?P<amount>\d{1,4}(?:[.,]\d{1,2})?)\s*"
    r"(?P<unit>ml|mililitr(?:u|y|ů)?|l|litry?|litr(?:u|y|ů)?)\b",
    flags=re.IGNORECASE,
)
# No glass bottles, cans, cartons, bag-in-box or disposable cups.
NON_PET_BEVERAGE_PACKAGE = (
    "sklo", "sklenene*", "sklenena*", "skleneny*",
    "plechovk*", "plechov*", "plech", "cans", "can",
    "tetrapak", "tetra pak", "karton*", "krabic*",
    "bag in box", "sacek", "sack*", "kelimek*", "aluminiov*",
)


def beverage_volume_liters(name: str) -> list[float]:
    """Read capacity per individual bottle (also in e.g. 6x1,5l packs)."""
    volumes = []
    for match in BEVERAGE_VOLUME.finditer(name):
        amount = float(match.group('amount').replace(',', '.'))
        unit = match.group('unit').casefold()
        value = amount / 1000 if unit.startswith(('ml', 'mililitr')) else amount
        if 0 < value <= 10:  # impossible 'bottle sizes' may be other metadata
            volumes.append(value)
    return volumes


def is_allowed_beverage(name: str, rule: dict) -> bool:
    """Reject undersized/oversized or explicitly non-PET beverage packaging."""
    limits = BEVERAGE_SIZES.get(rule.get('category'))
    if not limits:
        return True
    n = normalized(name)
    if any(term_matches(n, expr) for expr in NON_PET_BEVERAGE_PACKAGE):
        return False
    lower, upper = limits
    sizes = beverage_volume_liters(name)
    # Product name must state a recognizable single-bottle size. For multiple
    # capacities in one title, fail closed: '2l + 0.5l' is not a pure 2l pack.
    if not sizes:
        return False
    return all(size >= lower - 0.001 and
               (upper is None or size <= upper + 0.001) for size in sizes)


def scrub_historical_beverages(config: dict) -> int:
    """Remove old water/soda entries that violate the current bottle rules."""
    history = DATA / "history"
    rules_by_id = {r["id"]: r for r in config.get("watch_rules", [])}
    removed_total = 0
    for path in sorted(history.glob("*.json")) if history.exists() else []:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        offers = snapshot.get("offers")
        if not isinstance(offers, list):
            continue
        kept = []
        for offer in offers:
            category = offer.get('category')
            if category not in BEVERAGE_SIZES:
                kept.append(offer)
                continue
            rule = rules_by_id.get(offer.get('rule_id', ''))
            # Even old snapshots without a rule id must meet the bottle size.
            # Category provides the exact requirements in that case.
            check = rule if rule and rule.get('category') == category else {'category': category}
            if is_allowed_beverage(offer.get('name', ''), check):
                kept.append(offer)
        removed = len(offers) - len(kept)
        if removed:
            snapshot['offers'] = kept
            allowed = {o['url'] for o in kept}
            snapshot['changes'] = [c for c in snapshot.get('changes', []) if c.get('url') in allowed]
            snapshot['beverage_pack_filter_repaired'] = True
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
            removed_total += removed
    return removed_total


# Paper-goods watch groups deliberately describe the actual PRODUCT TYPE, not
# any title containing "papír" or "kapesníky". Generic box tissues and kitchen
# paper towels may be ANY brand; Zewa pocket packets require Deluxe.
PAPER_GOODS_TYPES = {
    "zewa_toilet_or_napkins", "zewa_deluxe_pocket",
    "kitchen_paper_towels", "boxed_3ply_tissues",
}


def is_wanted_paper_goods_name(name: str, paper_type: str) -> bool:
    n = normalized(clean_product_name(name))
    has = lambda *phrases: any(term_matches(n, phrase) for phrase in phrases)
    if not n or paper_type not in PAPER_GOODS_TYPES:
        return False
    # These are NOT dry disposable paper hygiene / kitchen rolls.
    if has("vlhcen*", "vlhke", "vlhceny*", "mokr*", "textiln*", "latkov*",
           "mikrovlak*", "had*", "hadr*", "houbick*", "houba", "cistic* ubrousk*",
           "odlicovac*", "dezinfekcn*", "ubrousk* na uklid"):
        return False
    tissue = has("kapesnik*", "facial tissue*", "facial tissues")
    boxed = has("krabic*", "krabick*", "krabicce", "box", "boxu", "boxik*",
                "vytahovac*", "dispenzer*", "krabicov*", "krabicove")
    three_ply = (re.search(r"(?<!\d)3\s*vrstv[a-z]*\b", n) is not None or
                 has("tri vrstve", "tri vrstv*", "three ply", "3 ply"))
    if paper_type == "zewa_toilet_or_napkins":
        return has("zewa") and (
            has("toaletni papir", "toaletni role", "toaletni papi*", "toilet paper")
            or (has("papir*", "papirov*", "servitk*") and has("ubrousk*", "servitk*"))
        )
    if paper_type == "zewa_deluxe_pocket":
        # Brand + Deluxe alone is insufficient: "Deluxe Family" is a 90-ct BOX.
        pocket_variant = has("standard", "original", "10x10", "10 balick*", "balickove")
        return (has("zewa") and tissue and has("deluxe") and pocket_variant
                and not has("family") and not boxed
                and not has("role", "ruli*", "toaletni"))
    if paper_type == "kitchen_paper_towels":
        return (has("papirove uterky", "papirova uterka", "papirove kuchynske uterky",
                    "kuchynske uterky", "kuchynska uterka", "kuchynske papirove role",
                    "kuchynske papirove rucniky", "papirove rucniky",
                    "uterky na roli", "uterky v roli", "wisch weg", "paper towels")
                and not tissue and not has("toaletni", "kapesnik*"))
    if paper_type == "boxed_3ply_tissues":
        # Košík names the known 90-piece "Zewa Deluxe Family" box without
        # spelling out "box" in its listing title; manufacturer/retail listings
        # confirm its pack type. Other ambiguous titles must disclose "box".
        verified_family_box = has("zewa") and has("deluxe family") and three_ply
        return (tissue and three_ply and (boxed or verified_family_box)
                and not has("10x10", "balickove kapesniky"))
    return False


def scrub_historical_paper_goods(config: dict) -> int:
    """Correct previous broad W053 classifications while preserving other products.

    Removes old Zewa paper-goods false positives and recategorizes eligible
    Zewa pocket packets / towels / boxed 3-ply tissues in archived snapshots.
    """
    history = DATA / "history"
    adjusted = 0
    for path in sorted(history.glob("*.json")) if history.exists() else []:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = snapshot.get("offers")
        if not isinstance(rows, list):
            continue
        revised = []
        changed = False
        for item in rows:
            if not isinstance(item, dict):
                revised.append(item)
                continue
            legacy_paper = (item.get("rule_id") in ("W053", "W073", "W074", "W075") or
                            (item.get("category") == "Papír a hygiena" and
                             term_matches(normalized(item.get("name", "")), "zewa")))
            if not legacy_paper:
                revised.append(item)
                continue
            correct = match_rules(item.get("name", ""), config["watch_rules"])
            if not correct or correct.get("paper_type") not in PAPER_GOODS_TYPES:
                changed = True
                adjusted += 1
                continue
            if (item.get("rule_id") != correct["id"] or
                item.get("category") != correct["category"] or not item.get("favorite")):
                item.update(rule_id=correct["id"], category=correct["category"],
                            favorite=True, note=correct.get("note", ""))
                adjusted += 1
                changed = True
            revised.append(item)
        if changed:
            snapshot["offers"] = revised
            allowed_urls = {x.get("url") for x in revised if isinstance(x, dict)}
            snapshot["changes"] = [x for x in snapshot.get("changes", [])
                                   if x.get("url") in allowed_urls]
            snapshot["paper_rules_repaired_v14"] = True
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return adjusted


def match_rules(name: str, rules: list[dict]) -> dict | None:
    n = normalized(name)
    matched = []
    # A name matching a known tracked brand should not be mistaken for a raw
    # vegetable/fruit just because it contains the same word (Jar Citron etc.).
    known_brands = {
        normalized(a) for r in rules for a in r.get('brand_aliases', [])
        if len(normalized(a)) > 3
    }
    has_brand = any(term_matches(n, a) for a in known_brands)
    for r in rules:
        if not r.get("enabled", True):
            continue
        if r.get("brand_aliases") and not any(term_matches(n, alias) for alias in r["brand_aliases"]):
            continue
        if has_brand and not r.get("brand_aliases") and r.get('category') in ('Ovoce', 'Zelenina'):
            continue
        if r.get("category") in ("Ovoce", "Zelenina") and not is_fresh_produce_name(name, r):
            continue
        if r.get("paper_type") and not is_wanted_paper_goods_name(name, r["paper_type"]):
            continue
        if r.get("category") == "Maso":
            if not is_raw_meat_name(name):
                continue
            # A breast fillet must not include bone. "Bez kosti" is acceptable.
            if r.get('id') == 'W001' and re.search(r'\bs kosti\b', n):
                continue
        if r.get("category") in BEVERAGE_SIZES and not is_allowed_beverage(name, r):
            continue
        # W030 is a baking/cooking fat, NOT any product mentioning Omega
        # (Omega-3 supplements, gummy fish, etc.).
        if r.get('id') == 'W030' and not any(term_matches(n, word) for word in
                ('tuk', 'pokrmov*', 'ztuzen*', 'na peceni', 'na vareni')):
            continue
        # Only unflavoured drinking water. "Neperlivá jahoda" is flavoured,
        # even though it contains a permitted carbonation description.
        if r.get('category') == 'Nápoje / vody' and any(term_matches(n, word) for word in
                ('ochucen*','prichut*','jahod*','malin*','hrozn*','broskv*',
                 'boruv*','jablk*','meloun*','mango','lesni ovoce','bezink*',
                 'pomel*','grep*','grapefru*','citron*','limet*','pomeranc*')):
            continue
        if r.get("product_any") and not any(term_matches(n, term) for term in r["product_any"]):
            continue
        if any(term_matches(n, term) for term in r.get("exclude_any", [])):
            continue
        # For ties, more specific rules beat broad general ones.
        specificity = max((len(normalized(t.strip('*'))) for t in r.get('product_any', [])), default=0)
        matched.append((r.get("priority", 2), -int(bool(r.get('brand_aliases'))), -specificity, r))
    return min(matched, key=lambda x: (x[0], x[1], x[2]))[3] if matched else None


def favorite_match(name: str, url: str, favorites: list[dict]) -> bool:
    n = normalized(name)
    for f in favorites:
        if f.get("url") and f["url"].rstrip("/") == url.rstrip("/"):
            return True
        if f.get("keywords") and all(normalized(w) in n for w in f["keywords"]):
            return True
    return False


def parse_price(text: str) -> float | None:
    text = text.replace("\u202f", " ").replace("\u00a0", " ").strip()
    # Price text must be constrained to a price-bearing element or pre-title card prefix.
    matches = [m for rx in (PRICE_DECIMAL, PRICE_SPLIT) if (m := rx.search(text))]
    m = min(matches, key=lambda match: match.start()) if matches else None
    if m:
        val = float(f"{m.group(1)}.{m.group(2)}")
        return round(val, 2) if 0 < val < 100000 else None
    return None


# Retailer listings contain unit prices (e.g. 699,00 Kč/kg) alongside the
# actual sale price (69,90 Kč). Unit prices are NOT payable item prices.
_UNIT_PRICE_TEXT = re.compile(
    r"(?<!\d)(?:\d{1,5}[,.]\d{2}|\d{1,5}[ \u00a0\u202f\n]\d{2})"
    r"\s*(?:Kč|CZK|kc)\s*/\s*(?:kg|l|ml|g|100\s*g|ks|d[aá]vk[auy]?)\b",
    re.I,
)


def parse_item_price(text: str) -> float | None:
    if not isinstance(text, str):
        return None
    value = _UNIT_PRICE_TEXT.sub(" ", text)
    return parse_price(value)


# Some Rohlík listing cards expose the STRUCK-THROUGH old price as the
# apparent current-price element. Before publishing a discount, cross-check
# the two visible prices against the claimed sale percentage.
_CARD_PRICE_WITH_CURRENCY = re.compile(
    r'(?<!\d)(\d{1,5})[,. \u00a0\u202f\n]+(\d{2})\s*(?:Kč|CZK)\b', re.I
)


def price_pair_before_discount(card: str, discount_pct: int) -> tuple[float, float] | None:
    """Find an explicitly visible discounted/original price pair, if unambiguous.

    Ignore unit prices such as '139,90 Kč/kg'. Never estimate a price from
    discount alone. Pair is selected only if its ratio confirms the label.
    """
    m = SALE_PCT.search(card or '')
    if not m:
        return None
    head = _UNIT_PRICE_TEXT.sub(' ', card[:m.start()])
    nums = []
    for found in _CARD_PRICE_WITH_CURRENCY.finditer(head):
        amount = float(f'{found.group(1)}.{found.group(2)}')
        if 0 < amount < 100000 and amount not in nums:
            nums.append(amount)
    valid = []
    for i, left in enumerate(nums):
        for right in nums[i+1:]:
            low, high = sorted((left, right))
            if abs((1-low/high)*100-discount_pct) <= 2.0:
                valid.append((low,high))
    return valid[0] if len(valid)==1 else None


def quantity_of(name: str, context: str) -> str:
    # Prefer product name, which distinguishes multipacks from single units.
    m = SIZE_PATTERN.search(name) or SIZE_PATTERN.search(context[:160])
    return (m.group(1).replace(",", ".") + " " + m.group(2).lower()) if m else ""


def safe_image_url(raw: str, base: str = "") -> str:
    """Only HTTPS product image URL; ignore placeholders and data blobs."""
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        url = urljoin(base, raw.strip())
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or len(url) > 1300:
            return ""
        if parsed.path.lower().endswith((".svg", ".gif")) or any(
            x in parsed.path.lower() for x in ("placeholder", "no-image", "no_image", "default-image", "fallback", "/logo")
        ):
            return ""
        return url
    except ValueError:
        return ""


def precise_pack(text: str) -> str:
    """Find one explicit, defensible capacity/weight; no guesses from product type.

    A near-title snippet (or a product-detail field) must be passed instead of
    arbitrary page text which might contain related products' capacities.
    """
    if not isinstance(text, str):
        return ""
    text = text.replace("\xa0", " ").replace("\u202f", " ")
    # Avoid treating unit prices as the item size: 119,84 Kč/l.
    text = re.sub(r"\d+(?:[.,]\d+)?\s*Kč\s*/\s*(?:l|kg|100\s*g)", "", text, flags=re.I)
    m = SIZE_PATTERN.search(text)
    if not m:
        return ""
    amount = m.group(1).replace(",", ".")
    unit = m.group(2).lower()
    try:
        v = float(amount)
    except ValueError:
        return ""
    if v <= 0 or (unit == "ks" and v > 10000):
        return ""
    return f"{v:g} {unit}".replace(".", ",")


def size_from_listing(name: str, row: dict) -> str:
    """Prefer the name or product-specific size over cart count / price labels."""
    explicit = precise_pack(name)
    if explicit:
        return explicit
    direct = precise_pack(row.get("size", ""))
    if direct:
        return direct
    text = row.get("card", "")
    # Size usually follows product name in the card. Other numbers or sizes
    # elsewhere in multi-product page must never become its packaging size.
    pos = text.casefold().find(name.casefold())
    if pos >= 0:
        tail = text[pos+len(name):pos+len(name)+85]
        return precise_pack(tail.split("\n", 3)[0]) or precise_pack(tail[:35])
    return ""


def quantity_base(quantity: str) -> tuple[float, str] | None:
    """Only SINGLE units; multi-packs cannot use single-bottle denominators."""
    if re.search(r"\d\s*[x×]\s*\d", quantity, flags=re.I):
        return None
    m = SIZE_PATTERN.fullmatch(quantity.strip())
    if not m:
        return None
    amount = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    if unit == "ml": return (amount/1000, "l")
    if unit == "l": return (amount, "l")
    if unit == "g": return (amount/1000, "kg")
    if unit == "kg": return (amount, "kg")
    return None


def set_unit_price(offer: Offer) -> None:
    if not offer.quantity:
        return
    # Do not confuse multi-packs with individual units: include the only
    # reliably known packaging quantity when computing a unit price.
    source = offer.name
    if re.search(r"\d\s*[x×]\s*\d+(?:[,.]\d+)?\s*(?:ml|l|kg|g)\b", source, re.I):
        offer.unit_price, offer.unit_label = None, ""
        return
    sized = quantity_base(offer.quantity)
    if sized:
        number, unit = sized
        if number > 0:
            offer.unit_price = round(offer.price/number, 2)
            offer.unit_label = "Kč/"+unit


def parse_card(shop: str, row: dict, config: dict) -> Offer | None:
    url = row.get("url", "")
    if urlparse(url).netloc not in ("www.rohlik.cz", "rohlik.cz", "www.kosik.cz", "kosik.cz"):
        return None
    if not PRODUCT_URLS[shop].match(urlparse(url).path):
        return None
    name = clean_product_name(row.get("name", ""))
    if len(name) < 4 or len(name) > 180:
        return None
    brand = brand_of(name, config.get("brands", []))
    fav = favorite_match(name, url, config.get("favorites", []))
    matched_rule = match_rules(name, config["watch_rules"]) if config.get("watch_rules") else None
    if config.get("watch_rules") and not matched_rule and not fav:
        return None
    if not config.get("watch_rules") and not brand and not fav:
        return None
    # A watch rule is part of the user's explicitly chosen shopping list.
    # For this project ALL these rules are favorites, including Hellmann's,
    # Leerdammer and Colgate; priority must not depend on prior P2 labels.
    if matched_rule and config.get("monitoring", {}).get("interpret_watch_rules_as_favorites", True):
        fav = True
    elif matched_rule and int(matched_rule.get("priority", 2)) == 1:
        fav = True
    snippet = row.get("card", "")[:850]
    # A visible sale percentage in the same product card is mandatory.
    m = SALE_PCT.search(snippet)
    if not m:
        return None
    discount = int(m.group(1))
    if discount < 1 or discount > 90:
        return None
    threshold = int(config.get("favorite_min_discount_pct", 5)) if fav else int(
        config.get("monitoring", {}).get("brand_min_discount_pct", 15))
    if not config.get("watch_rules") and not fav:
        threshold = next((int(b.get("min_discount_pct", 15)) for b in config["brands"] if b["name"] == brand), 15)
    if discount < threshold:
        return None
    conditional = re.search(r"od\s+(\d+)\s*ks", snippet, re.I)
    terms = f"množstevní akce (od {conditional.group(1)} ks)" if conditional else (
        "množstevní akce (podmínky ověřit)" if re.search(r"multikup|kup v[ií]c", snippet, re.I) else "akce")
    # If the page only exposes the price after a minimum quantity, treat this
    # offer as quantity-conditional, and never compare it as an ordinary price.
    candidate = row.get("current_price", "")
    price = parse_item_price(candidate) if candidate else None
    if price is None:
        # Card begins with price on Košík; Rohlík cards usually place 0 kusů first.
        prefix = snippet.split(name)[0]
        prefix = re.sub(r"\b0\s+kus[uů]\s+v\s+ko[sš][ií]ku\b", "", prefix, flags=re.I)
        price = parse_item_price(prefix)
    if price is None:
        return None  # Never fabricate a price.
    old_price = parse_item_price(row.get("old_price", "")) if row.get("old_price") else None
    # Critical correction: the sale price may be present on the card but the
    # CSS selector found the struck-through original price. The grape offer
    # showed 111,92 Kč / -50 % instead of its actual sale-price pair 55,92.
    verified_pair = price_pair_before_discount(snippet, discount)
    if verified_pair:
        price, old_price = verified_pair
    # Cross-check an explicit old price if available; allow rounding differences.
    if old_price is not None:
        if old_price <= price:
            return None
        # Reject inconsistent cards rather than publish likely misparsed prices.
        observed_discount = (1 - price / old_price) * 100
        if abs(observed_discount - discount) > 7:
            return None
    category = matched_rule.get("category", "") if matched_rule else ""
    label = matched_rule.get("label", "") if matched_rule else ""
    note = matched_rule.get("note", "") if matched_rule else ""
    if category in BEVERAGE_SIZES and not any(term_matches(normalized(name), term) for term in ("pet", "plastov*", "plast", "plastova*")):
        note = (note + " ").strip() + " PET obal je podle velikosti pravděpodobný, ale z názvu neověřený."
    qty = size_from_listing(name, row)
    offer = Offer(shop, name, url, price, discount, old_price, brand or label or "Oblíbené", fav,
                  qty, terms, category=category, rule_id=matched_rule.get("id", "") if matched_rule else "",
                  note=note, image_url=safe_image_url(row.get("image_url", ""), url),
                  detail_source="listing" if qty else "")
    set_unit_price(offer)
    return offer


def classify_rows(shop: str, rows: list[dict], config: dict) -> list[Offer]:
    offers = {}
    for r in rows:
        o = parse_card(shop, r, config)
        if o and (o.url not in offers or (o.favorite and not offers[o.url].favorite)):
            offers[o.url] = o
    return list(offers.values())


# JavaScript executes in page after rendering; deliberately avoids hidden API endpoints.
EXTRACT_JS = r"""() => {
  const hostname = location.hostname;
  const rx = hostname.includes('rohlik') ? /^\/\d{5,}(?:-[\w-]+)?\/?$/i : /^\/p\d+(?:-[\w-]+)?\/?$/i;
  const roots = [...document.querySelectorAll('a[href]')].filter(a => {
    try { const u=new URL(a.href); return u.hostname===hostname && rx.test(u.pathname); }
    catch { return false; }
  });
  const items = [];
  for (const a of roots) {
    let e=a, selected=null;
    for (let i=0;i<7 && e;i++,e=e.parentElement) {
      const t=(e.innerText||'').trim();
      if (t.length>15 && t.length<800 && /[-−]\s*\d{1,2}\s*%/.test(t)) { selected=e; break; }
    }
    if (!selected) continue;
    const card=(selected.innerText||'').trim();
    const cardAnchors=[...selected.querySelectorAll('a[href]')].filter(link=>{
      try{return rx.test(new URL(link.href).pathname);}catch{return false;}
    });
    // Image must belong to THIS anchor: don't use neighbour's image in
    // a broader discount panel with several different products.
    const photo=a.querySelector('img') || (cardAnchors.length===1 ? selected.querySelector('img') : null);
    const imgAlt=(photo?.alt || '').trim();
    let imageUrl='';
    if(photo){
      const candidates=[photo.currentSrc, photo.getAttribute('data-src'), photo.getAttribute('src'),
                        photo.getAttribute('data-original'),
                        (photo.getAttribute('srcset')||'').split(',')[0].trim().split(/\s+/)[0]];
      imageUrl=candidates.find(u=>u && /^https?:|^\//i.test(u)) || '';
    }
    // Some Košík thumbnails are lazy-loaded in <picture><source>, or drawn
    // with background-image on a child of the product anchor (not an <img>).
    // Search THIS product anchor only, never another card's neighbour.
    if(!imageUrl){
      const sources=[...a.querySelectorAll('picture source')];
      const responsive=sources.map(e=>(e.getAttribute('srcset')||e.getAttribute('data-srcset')||'')
           .split(',')[0].trim().split(/\s+/)[0]);
      imageUrl=responsive.find(u=>u && /^https?:|^\//i.test(u))||'';
    }
    if(!imageUrl){
      const nodes=[a,...a.querySelectorAll('div, span, picture')].slice(0,25);
      for(const el of nodes){
        const style=window.getComputedStyle(el).backgroundImage || el.style?.backgroundImage || '';
        const m=style.match(/url\(\s*["']?([^"')]+)["']?\s*\)/i);
        if(m && /^https?:|^\//i.test(m[1])){imageUrl=m[1];break;}
      }
    }
    const title=(a.getAttribute('title')||a.getAttribute('aria-label')||'').trim();
    const raw=(a.innerText||'').trim();
    // Prefer image alt / semantic label. Anchor text may contain price and a
    // different item in a multi-product grid, so never treat it as a title if
    // it contains Kč, discount percentages or basket UI elements.
    const titleCandidate=[imgAlt,title,raw].find(t=>t.length>4 && t.length<180
      && !/(?:Kč|kusů v košíku|[-−]\s*\d{1,2}\s*%)/i.test(t))||'';
    let name=titleCandidate.replace(/^(?:(?:Zobrazit|Otevřít|Prohlédnout)\s+detail\s+produktu|(?:Zobrazit|Otevřít)\s+produkt)\s*[:\-–]?\s*/i, '').trim();
    if (!name) {
      const near=selected.querySelector('a[href="'+a.getAttribute('href')+'"]');
      name=(near?.getAttribute('title')||near?.getAttribute('aria-label')||'').trim();
    }
    if (!name) continue;
    // Where semantic price elements exist, use them; else Python parses card prefix.
    const old=selected.querySelector('del, s, [class*="originalPrice"], [class*="oldPrice"]');
    let current='';
    const priceElt=selected.querySelector('[data-testid*="price"], [class*="currentPrice"], [class*="Price_current"], [class*="salePrice"]');
    if (priceElt) current=(priceElt.innerText||'').trim().slice(0,35);
    items.push({url:a.href,name,card,current_price:current,old_price:(old?.innerText||'').trim(),image_url:imageUrl});
  }
  return items;
}"""


def fetch_shop(shop: str, url: str, max_items: int, *, max_rounds: int = 85) -> tuple[list[dict], str, dict]:
    """Collect visible sale cards; report how incomplete the sample may be.

    Unlike the original nine-scroll-only implementation, this also tries the
    shop's visible 'Načíst další' button. It still cannot guarantee that all
    product listings have been loaded or that every promotion is in this page.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(locale='cs-CZ', timezone_id='Europe/Prague',
                                viewport={'width': 1365, 'height': 1000},
                                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/133.0 Safari/537.36')
        metrics = {'scroll_rounds': 0, 'load_more_clicks': 0, 'sample_is_complete': False,
                   'reason': 'Neověřená úplnost; jen veřejná akční stránka'}
        try:
            resp = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            if resp is None or resp.status >= 400:
                return [], f"HTTP {resp.status if resp else 'bez odpovědi'}", metrics
            page.wait_for_timeout(2000)
            try:
                page.get_by_role('button', name=re.compile('Přijmout|Souhlasím|Povolit vše', re.I)).first.click(timeout=1000)
            except Exception:
                pass
            all_rows: dict[str, dict] = {}
            stagnant = 0
            for iteration in range(max(1, max_rounds)):
                metrics['scroll_rounds'] = iteration + 1
                rows = page.evaluate(EXTRACT_JS)
                before = len(all_rows)
                for row in rows:
                    all_rows[row['url']] = row
                if len(all_rows) >= max_items:
                    metrics['reason'] = f'Zastaveno po limitu {max_items} karet; neúplný vzorek'
                    break
                if len(all_rows) == before:
                    stagnant += 1
                else:
                    stagnant = 0
                # Košík uses 'Načíst další' on large offer lists. Simply
                # scrolling nine times missed many products and brands.
                clicked = False
                for selector in ('button:has-text("Načíst další")',
                                 'a:has-text("Načíst další")',
                                 'button:has-text("Zobrazit další")'):
                    try:
                        control = page.locator(selector).first
                        if control.count() and control.is_visible():
                            control.click(timeout=1250)
                            metrics['load_more_clicks'] += 1
                            clicked = True
                            page.wait_for_timeout(550)
                            break
                    except Exception:
                        pass
                if not clicked:
                    page.evaluate('window.scrollBy(0, Math.max(1600, window.innerHeight*2))')
                    page.wait_for_timeout(500)
                if stagnant >= 10 and not clicked:
                    metrics['reason'] = 'Další nové karty se již nenačítají; úplnost není prokázána'
                    break
            metrics['cards_found'] = len(all_rows)
            if len(all_rows) >= max_items:
                metrics['reason'] = f'Dosažen limit {max_items}; další akce mohou chybět'
            rows = list(all_rows.values())[:max_items]
            return rows, 'ok' if rows else 'Nenalezeny produktové karty / blokování nebo změna HTML', metrics
        finally:
            browser.close()


# Read *visible product detail page* when listing omits packaging or photo.
# Never use a free-text page-wide regex: related items might have other sizes.
DETAIL_JS = r"""() => {
  const h=document.querySelector('main h1') || document.querySelector('h1');
  const heading=(h?.innerText||'').trim();
  const ogTitle=document.querySelector('meta[property="og:title"]')?.content || '';
  const sizePattern=/(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|l|kg|g|ks)\b/i;
  let size='';
  // Restrict packaging to h1 itself, or the FIRST text line directly after
  // its heading in its immediate parent/nearby product heading container.
  if(heading){
    const own=heading.match(sizePattern);
    if(own) size=own[0];
    for(let a=h?.parentElement, depth=0; a && !size && depth<3; a=a.parentElement,depth++){
      const full=(a.innerText||'').trim();
      const at=full.indexOf(heading);
      if(at<0 || at>120) continue;
      const following=full.slice(at+heading.length).trim();
      const first=following.split('\n').map(x=>x.trim()).filter(Boolean).slice(0,2);
      for(const line of first){const m=line.match(/^\s*(?:balen[ií]\s*:?\s*)?(\d+(?:[.,]\d+)?\s*(?:ml|l|kg|g|ks))\b/i);
        if(m){size=m[1];break;}}
    }
  }
  // Prefer schema.org Product image, which often exists even when Košík uses
  // a CSS background or a lazy-loaded responsive <picture> for the hero shot.
  let schemaImage='';
  const schemas=[...document.querySelectorAll('script[type="application/ld+json"]')];
  function flatten(x){if(!x || typeof x!=='object')return [];
    return [...(Array.isArray(x)?x.flatMap(flatten):[x]),...(x['@graph']?flatten(x['@graph']):[])];}
  const simplified=x=>(x||'').toLocaleLowerCase('cs').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  for(const script of schemas){try{const obj=JSON.parse(script.textContent||'');
    for(const product of flatten(obj)){
      const typ=product['@type'];const isProduct=Array.isArray(typ)?typ.includes('Product'):typ==='Product';
      if(!isProduct) continue;
      const schemaName=simplified(product.name||''); const trueName=simplified(heading);
      if(!schemaName || !trueName || !(schemaName.includes(trueName)||trueName.includes(schemaName)))continue;
      const img=product.image; const first=Array.isArray(img)?img[0]:img;
      schemaImage=typeof first==='string'?first:first?.url||first?.contentUrl||'';
      if(schemaImage)break;
    }
  }catch(_e){}if(schemaImage)break;}
  const metaImage=document.querySelector('meta[property="og:image"]')?.content ||
                  document.querySelector('meta[name="twitter:image"]')?.content || '';
  const imgCandidates=[...document.querySelectorAll('main picture img, main img, picture img, img')];
  const relevant=imgCandidates.find(img=>{
    const alt=simplified(img.alt||'').replace(/^zobrazit detail produktu /,'');
    const h=simplified(heading);
    return h && alt && (alt.includes(h)||h.includes(alt)) && alt.length>5;
  });
  const link=document.querySelector('link[rel="image_src"]')?.href || '';
  const resolveImg=img=>img?.currentSrc || img?.getAttribute('data-src') || img?.getAttribute('src') ||
    img?.getAttribute('srcset')?.split(',')[0].trim().split(/\s+/)[0] || '';
  // Candidates come from this product detail; the downloader checks actual
  // image bytes rather than trusting a filename or hotlink.
  const productImages=[...document.querySelectorAll('main picture img, main img, picture img, img')]
    .filter(img => {
      const alt=simplified(img.alt||'');
      const title=simplified(heading);
      const match=alt && title && (alt.includes(title)||title.includes(alt));
      const hero=/product.*(image|photo|gallery)|image.*product/i.test(
        String(img.closest('[data-testid], [class], [id]')?.className||'')+' '+
        String(img.closest('[data-testid]')?.getAttribute('data-testid')||''));
      return match || (hero && img.naturalWidth>120 && img.naturalHeight>100);
    })
    .map(resolveImg).filter(Boolean).slice(0,8);
  const images=[schemaImage,metaImage,resolveImg(relevant),link,...productImages].filter(Boolean);
  return {heading, og_title:ogTitle, size, image_url:images[0]||'', image_candidates:[...new Set(images)]};
}"""


def detail_belongs_to_offer(heading: str, offer_name: str) -> bool:
    """Guard against redirect to generic landing pages and wrong variants."""
    a, b = normalized(clean_product_name(heading)), normalized(clean_product_name(offer_name))
    # A product title may add/remove "Original" or a pack suffix, so check
    # meaningful product tokens instead of exact string equality.
    wa = set(a.split()); wb = set(b.split());
    return bool(wa and wb and len(wa & wb) >= max(1, min(2, len(wb))))


def apply_detail(offer: Offer, detail: dict) -> None:
    """Attach only metadata that is provably from the right product page."""
    if not isinstance(detail, dict):
        return
    if not detail_belongs_to_offer(detail.get("heading", ""), offer.name):
        return
    size = precise_pack(detail.get("size", ""))
    if size:
        offer.quantity = size
        offer.detail_source = "detail page"
    if not offer.image_url:
        offer.image_url = safe_image_url(detail.get("image_url", ""), offer.url)
    set_unit_price(offer)




def _product_photo_path(offer: Offer) -> Path:
    """Stable local asset path keyed by exact product URL, never fuzzy name."""
    slug=hashlib.sha256(offer.url.encode('utf-8')).hexdigest()[:22]
    return DATA / 'images' / f'{slug}.webp'


def cache_product_photo(offer: Offer, page, detail: dict | None = None) -> bool:
    """Store a small VERIFIED product thumbnail inside docs/data/images.

    Browser direct image URLs from shops often fail on GitHub Pages due to
    hotlink rules, expiring CDN signatures or referrer checks. The nightly
    scan downloads/validates an image while on the shop site and creates a
    same-origin WEBP thumbnail. No generic stock or guessed product image.
    Failed image download -> empty image (neutral placeholder in frontend).
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return False
    # Detail redirects or generic category pages must NEVER supply a photo.
    if isinstance(detail,dict) and not detail_belongs_to_offer(detail.get('heading',''), offer.name):
        offer.image_url=''
        return False
    path=_product_photo_path(offer)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Reuse an image only when it belongs to the same EXACT product URL.
    if path.exists() and path.stat().st_size>200:
        try:
            with Image.open(path) as im:
                im.verify()
            offer.image_url='data/images/'+path.name
            return True
        except (OSError,ValueError,UnidentifiedImageError):
            path.unlink(missing_ok=True)
    candidates=[]
    if isinstance(detail,dict):
        candidates+=detail.get('image_candidates',[]) or []
        candidates.append(detail.get('image_url',''))
    candidates.append(offer.image_url)
    seen=set()
    for raw in candidates:
        url=safe_image_url(raw,offer.url)
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            response=page.request.get(url,headers={'Referer': offer.url,'Accept':'image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8'},timeout=6500)
            if not response.ok:
                continue
            mime=response.headers.get('content-type','').split(';')[0].strip().lower()
            if mime not in ('image/jpeg','image/png','image/webp','image/avif'):
                continue
            content=response.body()
            if not 256<len(content)<5_000_000:
                continue
            with Image.open(io.BytesIO(content)) as im:
                if im.width<75 or im.height<75:
                    continue
                # Guard against banners and tiny placeholder icons.
                if max(im.width,im.height)/max(1,min(im.width,im.height))>3.2:
                    continue
                im=im.convert('RGB')
                im.thumbnail((144,160),Image.Resampling.LANCZOS)
                im.save(path,format='WEBP',quality=76,method=4)
            offer.image_url='data/images/'+path.name
            return True
        except Exception:
            # Image failures never stop the price scan.
            continue
    # Image is visibly rendered in the product gallery but CDN download may
    # be denied to the request client. In that case use a verified on-page
    # product image element screenshot as thumbnail; never scrape a random ad.
    try:
        target=page.evaluate(r"""() => {
          const h=document.querySelector('main h1')||document.querySelector('h1');
          if(!h) return false;
          const norm=s=>String(s||'').toLowerCase().normalize('NFD')
            .replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
          const heading=norm(h.innerText);
          const imgs=[...document.querySelectorAll('main img, picture img')];
          for(const img of imgs){
            if(!img.complete || img.naturalWidth<90 || img.naturalHeight<90)continue;
            const r=img.getBoundingClientRect();
            if(r.width<65||r.height<65||r.top>1200)continue;
            const alt=norm(img.alt);
            const classNames=(img.closest('[class], [data-testid]')?.className||'')+' '+
              (img.closest('[data-testid]')?.getAttribute('data-testid')||'');
            const isNamed=alt && (alt.includes(heading)||heading.includes(alt));
            const isHero=/product.{0,16}(image|photo|gallery)|gallery.{0,12}(image|product)/i.test(classNames);
            if(isNamed || isHero){img.setAttribute('data-rk-photo','1');return true;}
          }
          return false;
        }""")
        if target:
            thumb=page.locator('img[data-rk-photo="1"]').first.screenshot(timeout=2300)
            with Image.open(io.BytesIO(thumb)) as im:
                if im.width>=65 and im.height>=65:
                    im=im.convert('RGB');im.thumbnail((144,160),Image.Resampling.LANCZOS)
                    im.save(path,format='WEBP',quality=76,method=4)
                    offer.image_url='data/images/'+path.name
                    return True
    except Exception:
        pass
    # Košík sometimes paints its hero picture as a CSS background or a
    # <picture> wrapper, rather than a plain <img>. Screenshot only a strong
    # image/gallery candidate on the EXACT product detail page. Avoid carousels
    # and cross-sells outside the main product section.
    try:
        chosen=page.evaluate(r"""() => {
          const h=document.querySelector('main h1') || document.querySelector('h1');
          const main=document.querySelector('main');
          if(!h || !main) return false;
          const title=h.getBoundingClientRect();
          const nodes=[...main.querySelectorAll('picture, [class*="gallery"], [class*="Gallery"], [class*="productImage"], [class*="ProductImage"], [style*="background-image"]')];
          const viable=[];
          for(const el of nodes){
            const r=el.getBoundingClientRect();
            if(r.width<135 || r.height<125 || r.width>1050 || r.height>900 || r.top < -15 || r.top>1000) continue;
            if(r.left>title.left+40 || r.bottom<title.top-380 || r.top>title.bottom+320) continue;
            const type=(String(el.className||'')+' '+String(el.id||'')).toLowerCase();
            const bg=getComputedStyle(el).backgroundImage;
            const imageLike=bg && bg!=='none' || el.querySelector('img, source') || /gallery|product.?image|product.?photo/.test(type);
            if(!imageLike)continue;
            let score=(r.width*r.height)/2000 - Math.abs(r.top-title.top)/8;
            if(/gallery|product.?image/.test(type))score+=75;
            if(r.right<=title.left+40)score+=35;
            viable.push({el,score});
          }
          viable.sort((a,b)=>b.score-a.score);
          if(!viable.length)return false;
          viable[0].el.setAttribute('data-rk-css-photo','1');
          return true;
        }""")
        if chosen:
            thumb=page.locator('[data-rk-css-photo="1"]').first.screenshot(timeout=3400)
            from PIL import ImageStat
            with Image.open(io.BytesIO(thumb)) as im:
                im=im.convert('RGB')
                std=ImageStat.Stat(im.resize((30,30))).stddev
                # Reject plain white/grey boxes and empty skeleton loaders.
                if im.width>=135 and im.height>=125 and max(std)>15:
                    im.thumbnail((144,160),Image.Resampling.LANCZOS)
                    im.save(path,format='WEBP',quality=76,method=4)
                    offer.image_url='data/images/'+path.name
                    return True
    except Exception:
        pass
    # An uncacheable remote URL is not a working thumbnail on Pages.
    # Expose a neutral icon rather than broken image or a wrong product.
    offer.image_url=''
    return False


def scrub_historical_favorites(cfg: dict) -> int:
    """Re-tag stored archival offers according to the full selected watchlist.

    Does not change prices, discounts or dates. A previous snapshot may have
    assigned selected brands to P2, even though they are all user favorites.
    """
    updated=0
    history=DATA/'history'
    if not history.exists():
        return updated
    for path in history.glob('*.json'):
        try:
            doc=json.loads(path.read_text(encoding='utf-8'))
            changed=False
            for offer in doc.get('offers',[]):
                match=match_rules(clean_product_name(offer.get('name','')),cfg.get('watch_rules',[]))
                if match and not offer.get('favorite'):
                    offer['favorite']=True
                    changed=True;updated+=1
            if changed:
                path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        except (ValueError, OSError):
            continue
    return updated


def enrich_from_product_pages(offers: list[Offer], cfg: dict) -> dict:
    """Best-effort pack sizes and picture URLs, never blocking the entire scan.

    Browser detail requests are capped. If a shop blocks access, preserve
    verified listing data and leave uncertain fields blank. Price is NEVER
    changed from its sale-card value during enrichment.
    """
    max_pages = max(0, min(65, int(cfg.get("detail_max_per_run", 40))))
    candidates = [o for o in offers if not o.quantity or not (o.image_url.startswith('data/images/'))]
    candidates.sort(key=lambda o: (not o.favorite, bool(o.quantity), bool(o.image_url)))
    count=0; filled=0; errors=0; photos=0
    if not candidates or not max_pages:
        return {"visited": 0, "filled": 0, "errors": 0, "photos_cached": 0}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, args=["--no-sandbox"])
        page=browser.new_page(locale="cs-CZ", timezone_id="Europe/Prague", viewport={"width":1280,"height":920})
        try:
            for offer in candidates[:max_pages]:
                count+=1
                try:
                    resp=page.goto(offer.url, wait_until="domcontentloaded", timeout=13500)
                    if not resp or resp.status >= 400:
                        offer.image_url=''
                        errors+=1;continue
                    page.wait_for_timeout(1000)
                    before=(offer.quantity,offer.image_url)
                    detail=page.evaluate(DETAIL_JS)
                    apply_detail(offer,detail)
                    if cache_product_photo(offer,page,detail): photos+=1
                    if before != (offer.quantity, offer.image_url):filled+=1
                except Exception:
                    offer.image_url=''
                    errors+=1
        finally:
            browser.close()
    return {"visited":count,"filled":filled,"errors":errors,"photos_cached":photos}


def comparison_key(name: str, quantity: str) -> str:
    """Conservative match; manual aliases override automatically."""
    n = normalized(name)
    # Normalizing ampersands and punctuation is okay; do not conflate 'zero' or packs.
    return f"{n} | {normalized(quantity)}"


def add_comparisons(offers: list[Offer], pairs: list[dict]) -> None:
    manual = {}
    for pair in pairs:
        key = pair.get("id") or "manual"
        for url in (pair.get("rohlik_url"), pair.get("kosik_url")):
            if url:
                manual[url.rstrip("/")] = "manual:" + key
    for o in offers:
        o.comparable_group = manual.get(o.url.rstrip("/"), "auto:" + comparison_key(o.name, o.quantity))
    groups = defaultdict(list)
    for o in offers:
        groups[o.comparable_group].append(o)
    for group in groups.values():
        shops = {o.shop for o in group}
        if len(group) != 2 or len(shops) != 2:
            continue  # Never compare ambiguous or non-identical items.
        a, b = group
        if a.quantity and b.quantity:
            sa, sb = quantity_base(a.quantity), quantity_base(b.quantity)
            if sa and sb and (sa[1] != sb[1] or abs(sa[0] - sb[0]) > 0.00001):
                continue  # Never compare different pack sizes (e.g. 405 vs 625 ml).
            if (not sa or not sb) and normalized(a.quantity) != normalized(b.quantity):
                continue
        elif a.quantity != b.quantity:
            continue
        # Auto-matching same generic title without an explicit volume is unsafe.
        if a.comparable_group.startswith('auto:') and not a.quantity:
            continue
        if a.terms != b.terms:
            continue  # Conditional prices not equivalent to ordinary discounts.
        a.other_shop_price, a.other_shop_url, a.other_shop = b.price, b.url, b.shop
        b.other_shop_price, b.other_shop_url, b.other_shop = a.price, a.url, a.shop


def demo_rows():
    return {
        "Rohlík": [
            dict(name="LE&CO Šunka od kosti 100 g", url="https://www.rohlik.cz/1234567-sunka", card="0 kusů v košíku\n34,90 Kč 44,90 Kč -22 % do 20.10. LE&CO Šunka od kosti 100 g", current_price="34,90 Kč", old_price="44,90 Kč"),
            dict(name="Coca-Cola Original 2 l", url="https://www.rohlik.cz/1234568-cola", card="0 kusů v košíku\n39,90 Kč 49,90 Kč -20 % Coca-Cola Original 2 l", current_price="39,90 Kč", old_price="49,90 Kč")
        ],
        "Košík": [
            dict(name="Coca-Cola Original 2 l", url="https://www.kosik.cz/p12345-cola", card="36 90 49,90 -26 % do 20.10. Coca-Cola Original 2 l", current_price="36,90 Kč", old_price="49,90 Kč"),
            dict(name="Aquila První voda 6x1,5 l", url="https://www.kosik.cz/p12346-aquila", card="89 90 119,90 -25 % do 20.10. Aquila První voda 6x1,5 l", current_price="89,90 Kč", old_price="119,90 Kč")
        ]
    }


def read_previous() -> dict:
    p = DATA / "latest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def compare_changes(current: list[Offer], previous: dict) -> list[dict]:
    old_by_url = {x["url"]: x for x in previous.get("offers", [])}
    changes = []
    for offer in current:
        prior = old_by_url.get(offer.url)
        if not prior or prior.get("price") is None:
            changes.append({"url": offer.url, "kind": "newly_observed", "price": offer.price})
        elif offer.price < float(prior["price"]) - 0.005:
            changes.append({"url": offer.url, "kind": "price_dropped", "price": offer.price,
                            "previous_price": prior["price"]})
    return changes


def build_report(snapshot: dict) -> str:
    offers = [Offer(**x) for x in snapshot["offers"]]
    offers.sort(key=lambda o: (not o.favorite, -o.discount_pct, o.brand, o.name))
    lines = [f"ROHLÍK × KOŠÍK | {snapshot['date']} | poslední kontrola: {snapshot['checked_at']}",
             "VEŘEJNÉ VYHLEDÁVÁNÍ NAPŘÍČ SORTIMENTEM – pouze skutečně nalezené položky, nikoli úplný katalog." if snapshot.get('catalog_coverage') else "VEŘEJNÉ AKCE – pouze položky skutečně nalezené při kontrole, nikoli kompletní katalog.",
             f"Doručovací oblast: PSČ {snapshot.get('delivery', {}).get('postal_code', 'neuvedeno')} (referenční požadavek, nikoli automaticky ověřená lokální cena).",
             "Bez potvrzené volby oblasti v e-shopu: ceny a dostupnost se mohou lišit podle doručovací adresy / členství.",
             "STAV ZDROJŮ: " + "; ".join(f"{s}: {v['status']} ({v['cards']} karet)" for s, v in snapshot["sources"].items()),
             f"Nalezeno {len(offers)} sledovaných zlevněných položek; nově zaznamenané / zlevněné: {len(snapshot['changes'])}.",
             "OBLÍBENÉ PRODUKTY A ZNAČKY (všechna zadaná pravidla = oblíbené):"]
    if snapshot.get('catalog_coverage'):
        cov=snapshot['catalog_coverage']
        lines.append(f"KATALOG: {len(snapshot.get('catalog',[]))} nalezených výrobků (včetně nezlevněných); 24h pokrytí vyhledávacích dotazů {cov['queries_responded_24h']}/{cov['queries_planned']} a nákupních pravidel {cov['watch_rules_with_search_24h']}/{cov['watch_rules_total']}. Neznamená úplný katalog.")
    if not offers:
        lines.append("Žádná ověřená nabídka v dostupném vzorku; neznamená to, že žádná sleva neexistuje.")
    for o in offers[:80]:
        comp = f" | druhý obchod: {o.other_shop} {o.other_shop_price:.2f} Kč" if o.other_shop_price is not None else " | bez ověřeného páru"
        lines.append(f"{'★ ' if o.favorite else ''}{o.category or o.brand} | {o.shop} | {o.name}" + (f" | balení: {o.quantity}" if o.quantity else " | balení: neuvedeno") + f" | {o.price:.2f} Kč | -{o.discount_pct}% | {o.terms}{comp} | {o.url}" + (f" | POZN.: {o.note}" if o.note else ""))
    if len(offers) > 80:
        lines.append(f"Dalších {len(offers) - 80} položek pouze na webovém dashboardu.")
    lines.extend(["Zdroje:"] + [f"{k}: {v}" for k, v in snapshot["source_urls"].items()])
    if snapshot.get("demo"):
        lines.insert(0, "*** DEMO DATA – NESKUTEČNÉ CENY ***")
    return "\n".join(lines) + "\n"


def write_snapshot(snapshot: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "history").mkdir(exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    (DATA / "latest.json").write_text(payload, encoding="utf-8")
    (DATA / "history" / (snapshot["date"] + ".json")).write_text(payload, encoding="utf-8")
    (DATA / "report.txt").write_text(build_report(snapshot), encoding="utf-8")
    # Basic static HTML usable as text input to ChatGPT; escape all external data.
    (ROOT / "docs" / "report.html").write_text(
        '<!doctype html><html lang="cs"><meta charset="utf-8"><title>Denní cenový report</title>'
        '<meta name="robots" content="noindex"><body><h1>Rohlík × Košík – denní report</h1><pre>'
        + html.escape(build_report(snapshot)) + '</pre></body></html>', encoding="utf-8")
    index = DATA / "index.json"
    try:
        dates = json.loads(index.read_text(encoding="utf-8")) if index.exists() else []
    except ValueError:
        dates = []
    dates = sorted(set(dates + [snapshot["date"]]), reverse=True)[:120]
    index.write_text(json.dumps(dates, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="Generate synthetic demo results (NOT real prices)")
    ap.add_argument("--legacy-sales-only", action="store_true", help="Run old sales-page-only collector (emergency fallback)")
    ap.add_argument("--config", type=Path, default=CONFIG)
    args = ap.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if cfg.get('catalog_search', {}).get('enabled', False) and not args.demo and not args.legacy_sales_only:
        # Incremental public storefront searches across EVERY watch-rule group.
        # Sales are detected among all observed matching products, not just
        # products featured in a special promotions collection.
        from catalog_scan import run_catalog_monitor
        return run_catalog_monitor(cfg, sys.modules[__name__])
    now = dt.datetime.now(ZoneInfo(cfg.get("timezone", "Europe/Prague")))
    rows_by_shop = demo_rows() if args.demo else {}
    statuses = {}
    for shop, url in cfg["sources"].items():
        if not args.demo:
            try:
                rows, status, collection_meta = fetch_shop(
                    shop, url, int(cfg.get('max_items_per_store', 3500)),
                    max_rounds=int(cfg.get('max_scroll_rounds', 85)))
            except Exception as exc:
                rows, status, collection_meta = [], f"CHYBA: {type(exc).__name__}: {str(exc)[:150]}", {}
            rows_by_shop[shop] = rows
        else:
            status = "DEMO – syntetická data"
            rows = rows_by_shop[shop]
            collection_meta = {'reason': 'DEMO'}
        statuses[shop] = {'status': status, 'cards': len(rows), **collection_meta}
    previous = read_previous()
    offers = []
    for shop, rows in rows_by_shop.items():
        offers.extend(classify_rows(shop, rows, cfg))
    # Product cards often omit capacity from the short title (e.g. 625 ml
    # Hellmann's Mayonnaise). Read the detail page for offers lacking size/photo.
    enrich_status = {"visited": 0, "filled": 0, "errors": 0}
    if not args.demo and offers:
        try:
            enrich_status = enrich_from_product_pages(offers, cfg)
        except Exception as exc:
            enrich_status["note"] = f"Detail pages unavailable: {type(exc).__name__}"
    # Repair historical false positives as well, so past days do not keep
    # listing juice/yogurt/sweets as fresh fruit or vegetables.
    if not args.demo:
        scrub_historical_produce(cfg)
        scrub_historical_beverages(cfg)
        scrub_historical_meat(cfg)
        scrub_historical_favorites(cfg)
        scrub_historical_paper_goods(cfg)
    add_comparisons(offers, cfg.get("canonical_pairs", []))
    offers.sort(key=lambda o: (not o.favorite, -o.discount_pct, o.brand, o.name))
    snapshot = {"date": now.date().isoformat(), "checked_at": now.isoformat(timespec="minutes"),
                "sources": statuses, "source_urls": cfg["sources"], "product_details": enrich_status,
                "delivery": cfg.get("delivery", {}), "postcode_specific_prices_verified": False,
                "offers": [asdict(o) for o in offers],
                "changes": compare_changes(offers, previous),
                "demo": args.demo,
                "disclaimer": "Veřejný NEÚPLNÝ vzorek; ne úplný katalog; PSČ je zadáno pouze jako preference (neověřené lokální ceny a dostupnost); množstevní slevy podmíněné."}
    write_snapshot(snapshot)
    print(f"{snapshot['checked_at']} | {len(offers)} nabídek | {statuses}")
    # Exit nonzero if ALL sources fail; do NOT present this as 'no sales'.
    return 0 if args.demo or any(v["status"] == "ok" for v in statuses.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
