# Návod pro úplné začátečníky

Tenhle návod tě provede od čistého počítače až k učebnici staženou do Markdownu. Nepředpokládá žádné zkušenosti s programováním. Zabere asi 15 minut.

Příkazy z návodu se píšou do **terminálu**:
- **macOS:** `Cmd + mezerník` → napiš `Terminál` → Enter.
- **Linux:** obvykle `Ctrl + Alt + T`.
- **Windows:** viz [sekce pro Windows](#windows) na konci.

Řádky v šedých blocích zkopíruj do terminálu a potvrď Enterem. Text za `#` je jen poznámka, ten psát nemusíš.

---

## Krok 1: Nainstaluj potřebné programy

Budeš potřebovat tři věci:

| Program | Na co | Jak zjistit, jestli ho máš |
|---|---|---|
| **Python 3.9+** | Jazyk, ve kterém je skript napsaný | `python3 --version` |
| **Git** | Stažení repozitáře | `git --version` |
| **Google Chrome** | Prohlížeč, který skript ovládá | Najdi ho v Aplikacích |

Pokud příkaz vypíše číslo verze (např. `Python 3.12.4`), program máš. Pokud vypíše `command not found`, nainstaluj ho:

**macOS.** Nejjednodušší je přes [Homebrew](https://brew.sh). Na jeho stránce zkopíruj instalační příkaz a vlož ho do terminálu. Potom:
```bash
brew install python git
```
Chrome stáhni z [google.com/chrome](https://www.google.com/chrome/).

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y python3 python3-venv git
```

> Chrome je doporučený, ale ne nutný. Když chybí, instalační skript stáhne Chromium. S ním ale může mít potíže přihlášení přes Google.

## Krok 2: Stáhni si skript

```bash
cd ~                                               # přesun do domovské složky
git clone https://github.com/<uzivatel>/spa2md.git # stažení repozitáře
cd spa2md                                          # vstup do jeho složky
```

`<uzivatel>/spa2md` nahraď skutečnou adresou repozitáře.

## Krok 3: Nainstaluj závislosti

```bash
./install.sh
```

Co se stane:
1. Vytvoří se složka `.venv`. Je to **virtuální prostředí**, oddělená krabička pro knihovny tohoto projektu, aby se nemíchaly se zbytkem počítače.
2. Do ní se nainstalují knihovny `playwright`, `beautifulsoup4`, `markdownify` a `lxml`.
3. Ověří se, že máš Chrome. Pokud ne, stáhne se Chromium.

Na konci by mělo být napsáno `balíčky OK` a `Hotovo`.

> **`permission denied`?** Spusť nejdřív `chmod +x install.sh` a pak znovu `./install.sh`.

## Krok 4: Aktivuj prostředí

```bash
source .venv/bin/activate
```

Na začátku řádku v terminálu se objeví `(.venv)`. To znamená, že prostředí je aktivní.

> ⚠️ **Tenhle krok opakuj pokaždé, když otevřeš nový terminál.** Bez něj Python knihovny nenajde (chyba `ModuleNotFoundError`).

## Krok 5: Najdi adresu první stránky

V prohlížeči otevři učebnici na **první stránce nebo obsahu**. Zkopíruj adresu z adresního řádku, například:

```
https://web.cz/kniha/page?code=home
```

Skript bude stahovat všechny stránky z téhož webu, které leží ve stejné „složce" jako tahle (vše do poslední `/`). V příkladu tedy vše pod `https://web.cz/kniha/`, ale ne třeba `https://web.cz/kniha-stara/`.

> ⚖️ Stahuj jen materiály, ke kterým máš přístup a právo, a staženou kopii nikomu nešiř. Je jen pro tvoji osobní potřebu.

## Krok 6: Zkušební běh

Nejdřív stáhni jen 3 stránky, ať vidíš, jestli výsledek dává smysl:

```bash
python spa2md.py 'https://web.cz/kniha/page?code=home' -o test --max-pages 3
```

> **Adresu vždycky dávej do jednoduchých uvozovek `'…'`.** Znaky `?` a `&` mají v terminálu zvláštní význam. Bez uvozovek by se adresa pokazila.

1. Otevře se nové okno Chrome.
2. **Pokud je web za přihlášením, přihlas se** v tom okně (třeba přes Google) a dojdi na první stránku knihy.
3. Vrať se do terminálu a stiskni **Enter**.
4. Skript vypisuje, co dělá:
   ```
   [1] https://web.cz/kniha/page?code=home
     kód: 2
     diagramy: 1
   [2] ...
   Hotovo: 3 stránek, 5 obrázků -> test/
   ```

Přihlášení se uloží, takže příště už se přihlašovat nemusíš.

## Krok 7: Zkontroluj výsledek

Otevři složku `test`:
```bash
open test          # macOS
xdg-open test      # Linux
```

Soubory `.md` otevři v editoru, který umí zobrazit Markdown: [VS Code](https://code.visualstudio.com/) (náhled přes `Cmd/Ctrl + Shift + V`), [Obsidian](https://obsidian.md/) nebo [Typora](https://typora.io/).

**Zkontroluj:**
- ✅ Je tam text kapitoly, ne menu?
- ✅ Zobrazují se obrázky?
- ✅ Je kód v šedých blocích?

Jestli je všechno v pořádku, pokračuj krokem 9. Jinak krok 8.

## Krok 8: Když výsledek není dobrý

**V souborech je místo obsahu menu nebo je obsah useknutý.** Zjisti, kde na stránce obsah leží:

```bash
python spa2md.py 'https://web.cz/kniha/page?code=home' -o test --inspect
```

Výpis ukáže řádky jako:
```
  --selector "div.lesson-content"   [...]  text:4210 znaků
      Úvod Tato kapitola popisuje...
```

Vyber ten, jehož ukázka textu odpovídá skutečnému obsahu kapitoly, a přidej ho do příkazu:

```bash
python spa2md.py '…' -o test --max-pages 3 --selector "div.lesson-content"
```

> Pokud selektor vypadá jako náhodný hash (`div#4a0f6b80…`), **nepoužívej ho**. Na každé stránce bude jiný. V takovém případě bývá automatika (bez `--selector`) lepší volba.

**V textu zůstává nějaký otravný kus (hlavička, banner).** Klikni na něj na webu pravým tlačítkem → *Prozkoumat*. Podívej se, jakou má třídu (`class="..."`), a vyhoď ho:
```bash
... --remove ".page-header" --remove ".cookie-banner"
```

**Stránka se nestihne načíst a chybí kusy textu.** Prodluž čekání:
```bash
... --settle 3
```

Další případy najdeš v tabulce [Řešení problémů v README](../README.md#řešení-problémů).

## Krok 9: Stáhni celou knihu

Stejný příkaz jako ve zkušebním běhu, jen bez `--max-pages` a do jiné složky:

```bash
python spa2md.py 'https://web.cz/kniha/page?code=home' -o kniha
```

U velké knihy to potrvá. Počítej zhruba 2 až 5 sekund na stránku. Skript mezi stránkami schválně dělá pauzy, aby server nezatěžoval. Nezkracuj je. Hotovou knihu najdeš ve složce `kniha`:
- `index.md`: obsah s odkazy na kapitoly,
- `kniha.md`: všechno v jednom souboru (dobré na hledání nebo převod do PDF),
- `001_….md`, `002_….md`: jednotlivé kapitoly,
- `images/`: obrázky.

Hotovo! 🎉

---

## Časté chyby

| Hláška | Co s tím |
|---|---|
| `command not found: python` | Použij `python3`, nebo jsi zapomněl `source .venv/bin/activate`. |
| `ModuleNotFoundError: No module named 'playwright'` | Neaktivoval jsi prostředí (krok 4). |
| `zsh: no matches found: https://…?code=…` | Chybí uvozovky kolem adresy. |
| `400 Bad Request` | V adrese je navíc `\` nebo jiný znak. Zkopíruj ji znovu a dej do `'…'`. |
| Google: „Tento prohlížeč nebo aplikace nemusí být bezpečné" | Použij režim `--cdp`, popsaný v [README](../README.md#když-google-odmítne-přihlášení). |
| Stáhla se jen 1 stránka | Startovní adresa je moc „hluboko". Zkus adresu obsahu knihy, nebo nastav `--scope 'https://web.cz/kniha/'`. |
| „robots.txt tohoto webu … zakazuje" | Web nechce být automaticky procházen. U vlastních studijních materiálů můžeš vědomě přidat `--ignore-robots`. |
| `Error with Permissions-Policy header…` | Neškodné varování, ignoruj. |

## Windows

Skript na Windows funguje, jen `install.sh` je pro macOS/Linux. Instalace ručně v **PowerShellu**:

```powershell
# Python z https://www.python.org/downloads/ – při instalaci zaškrtni „Add python.exe to PATH"
# Git z https://git-scm.com/download/win
git clone https://github.com/<uzivatel>/spa2md.git
cd spa2md
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium   # jen pokud nemáš Google Chrome
python spa2md.py "https://web.cz/kniha/page?code=home" -o test --max-pages 3
```

> Pokud PowerShell odmítne spustit `Activate.ps1`, napiš jednou `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
> Na Windows dávej adresu do **dvojitých** uvozovek `"…"`.
