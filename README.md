# Rohlík × Košík – čistá verze 19

Sledování vybraných výrobků a značek z veřejných stránek Rohlíku a Košíku pro preferované PSČ **149 00**. Automatizovaný sběr nenahrazuje potvrzení lokálních cen přímo u obchodníků. **Nezaručuje úplné pokrytí ani získání všech produktových obrázků.**

## Složení
- `monitor.py`, `catalog_scan.py` – prohledávání viditelného veřejného sortimentu, akční záloha a uchování ověřených cen.
- `config.json` – pravidla a priority.
- `docs/index.html` – mobilní produktové karty a desktopový přehled.
- `.github/workflows/prices.yml` – automatická kontrola 3× denně a GitHub Pages.
- `tests/` – offline regresní testy.
- `docs/data/` – pouze prázdný startovní report; **historická data z předchozího projektu nejsou součástí ZIPu**.

## Nejprve otestovat

1. Vytvořit **nový veřejný repozitář** (např. `rohlik-kosik-monitor-clean`) a z rozbaleného ZIPu nahrát **obsah složky** do rootu včetně skryté `.github`.
2. GitHub: Settings → Pages → Source: **GitHub Actions**.
3. Actions → Rohlík Košík – scan and publish → Run workflow (větev main).
4. Zkontrolovat zelené testy a **reálná čísla a stav zdrojů**, ne jen barvu běhu.
5. Ověřit online URL: `https://UZIVATEL.github.io/NAZEV-REPOZITARE/`.
6. **Ponechat starý projekt**, dokud nebude nový dashboard fungovat. Teprve pak upravit odkaz v ChatGPT Free a rozhodnout o migraci historie.

Čistá verze automaticky nepřebírá staré reporty; první úspěšné kontroly vytvoří vlastní historii. Ceny a obrázky mohou být neúplné, zejména při omezení vyhledávání e-shopem.
