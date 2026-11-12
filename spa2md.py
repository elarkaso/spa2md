#!/usr/bin/env python3
"""
spa2md.py - učebnice psaná jako SPA (React…) a schovaná za přihlášením
-> Markdown + obrázky.

Stránky se nejdřív vykreslí v opravdovém Chrome (Playwright), takže JS obsah je vidět.
Přihlášení (Google OAuth) uděláš ručně, skript pak využije tvoji session.

REŽIM A (výchozí) – skript otevře vlastní okno Chrome s trvalým profilem:
    python spa2md.py https://web/ucebnice -o vystup
    -> v okně se přihlas, přejdi na obsah učebnice a v terminálu stiskni Enter.
    Profil se ukládá do ./.browser-profile, příště už přihlášení nebude potřeba.

REŽIM B (nejspolehlivější pro Google OAuth) – připojení k tvému běžnému Chrome:
    1) zavři Chrome a spusť ho takto:
       macOS:   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222 --user-data-dir=$HOME/chrome-debug
       Windows: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\\chrome-debug
       Linux:   google-chrome --remote-debugging-port=9222 --user-data-dir=$HOME/chrome-debug
    2) přihlas se do učebnice
    3) python spa2md.py https://web/ucebnice --cdp http://localhost:9222

Zodpovědné používání:
    Ve výchozím stavu skript respektuje robots.txt, dělá pauzy mezi stránkami
    a nijak neskrývá, že prohlížeč řídí automatizace. Stahuj jen obsah,
    ke kterému máš přístup a právo, a staženou kopii nešiř.

Instalace:  pip install playwright beautifulsoup4 markdownify lxml
            (stačí mít nainstalovaný Google Chrome; jinak: playwright install chromium)
"""
import argparse
import base64
import hashlib
import mimetypes
import os
import re
import sys
import time
import copy
import unicodedata
from collections import deque
from urllib.parse import urljoin, urlparse, unquote
from urllib.robotparser import RobotFileParser
import datetime

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

JUNK = ["script", "style", "noscript", "nav", "header", "footer", "aside",
        "form", "iframe", "button"]
SKIP_EXT = (".pdf", ".zip", ".mp4", ".mp3", ".docx", ".xlsx", ".pptx",
            ".css", ".js", ".ico", ".xml", ".json")

# před sběrem HTML: dotáhne lazy obrázky a zafixuje aktuální src (srcset/lazy-load)
PREP_JS = """
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let h = 0;
  for (let y = 0; y < document.body.scrollHeight + 2000; y += 700) {
    window.scrollTo(0, y); await sleep(60);
    if (y > 200000) break;
  }
  window.scrollTo(0, 0);
  for (const img of document.querySelectorAll('img')) {
    const s = img.currentSrc || img.getAttribute('data-src') || img.src;
    if (s) img.setAttribute('src', s);
  }
  for (const d of document.querySelectorAll('details')) d.open = true;
}
"""

# označí diagramy (SVG, canvas, draw.io…, HTML "kreslené" bloky) a obrázky v CSS pozadí
MARK_JS = """
(extraSel) => {
  const out = [];
  const marked = new Set();
  const big = (el, w=120, h=60) => { const r = el.getBoundingClientRect(); return r.width >= w && r.height >= h; };
  const inside = el => { for (let p = el; p; p = p.parentElement) if (marked.has(p)) return true; return false; };
  const caption = el => {
    let n = el.nextElementSibling, k = 0;
    for (let p = el; !n && p && k < 4; p = p.parentElement, k++) n = p.nextElementSibling;
    const t = n ? (n.innerText || '').trim().split('\\n')[0] : '';
    return /^(diagram|obr|obrázek|figure|fig|schéma|image|tabulka)\\b/i.test(t) ? t.slice(0, 150) : '';
  };
  const mark = el => {
    if (!el || inside(el)) return;
    for (const m of [...marked]) if (el.contains(m)) { marked.delete(m); }
    marked.add(el);
  };
  // 1) diagram-like třídy a vlastní selektor
  const cls = '[class*=diagram i],[class*=drawio i],[class*=mxgraph i],[class*=plantuml i],[class*=mermaid i],[class*=chart i],[class*=imaging i]';
  for (const el of document.querySelectorAll(cls + (extraSel ? ',' + extraSel : ''))) if (big(el)) mark(el);
  // 2) svg a canvas
  for (const el of document.querySelectorAll('svg, canvas')) {
    if (el.parentElement && el.parentElement.closest('svg')) continue;
    if (big(el)) mark(el);
  }
  // 3) HTML "kreslené" diagramy: dlouhé řady stejného znaku (0000…, ────, ....)
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    if (!/(.)\\1{25,}/.test(walker.currentNode.nodeValue)) continue;
    if (walker.currentNode.parentElement.closest('pre, code, script, style, noscript, template')) continue;
    if (!walker.currentNode.parentElement.getClientRects().length) continue;
    let el = walker.currentNode.parentElement;
    const clean = e => (e.innerText || '').replace(/(.)\\1{10,}/g, '').replace(/\\s+/g, ' ').trim().length;
    while (el.parentElement && el.parentElement !== document.body) {
      const r = el.getBoundingClientRect();
      if (r.height >= 150 && r.width >= 200) break;
      const p = el.parentElement;
      // nestoupat do rodiče, který obsahuje běžný text (odstavce) nebo kód
      if (clean(p) - clean(el) > 120 || p.querySelector('pre[data-md-code], p')) break;
      el = p;
    }
    const r = el.getBoundingClientRect();
    if (r.height <= 2000) mark(el);
  }
  // 4) obrázky přes CSS background-image
  for (const el of document.querySelectorAll('body *')) {
    if (inside(el) || el.tagName === 'IMG') continue;
    const bg = getComputedStyle(el).backgroundImage;
    const m = bg && bg.match(/url\\(["']?(.*?)["']?\\)/);
    if (m && big(el, 80, 60) && !(el.innerText || '').trim()) {
      const img = document.createElement('img');
      img.src = m[1]; img.alt = el.getAttribute('aria-label') || el.title || '';
      el.replaceWith(img);
    }
  }
  let i = 0;
  for (const el of marked) {
    el.setAttribute('data-md-shot', String(i));
    out.push({ id: i, alt: caption(el) || (el.getAttribute('aria-label') || '') });
    i++;
  }
  return out;
}
"""

REPLACE_SHOTS_JS = """
(items) => {
  for (const it of items) {
    const el = document.querySelector('[data-md-shot="' + it.id + '"]');
    if (!el) continue;
    const img = document.createElement('img');
    img.setAttribute('src', 'md-shot:' + it.file);
    img.setAttribute('alt', it.alt || 'diagram');
    el.replaceWith(img);
  }
}
"""

# zachytí obsah code snippetů: kliknutím na "copy" tlačítko (zachycený clipboard)
# nebo přes API editorů (CodeMirror 5/6, Monaco, Ace); blok nahradí <pre><code>
CODE_PREP_JS = """
() => {
  window.__mdCopied = null;
  if (!window.__mdHooked) {
    window.__mdHooked = true;
    try {
      const cb = navigator.clipboard || {};
      const orig = cb.writeText ? cb.writeText.bind(cb) : null;
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: Object.assign(Object.create(cb), {
        writeText: t => { window.__mdCopied = t; return Promise.resolve(); },
        write: async items => {
          try { for (const it of items) for (const ty of it.types) if (ty === 'text/plain')
            window.__mdCopied = await (await it.getType(ty)).text(); } catch (e) {}
        },
        readText: () => Promise.resolve(window.__mdCopied || ''),
      })});
    } catch (e) {}
    const origExec = document.execCommand.bind(document);
    document.execCommand = function (cmd, ...rest) {
      if (String(cmd).toLowerCase() === 'copy') {
        let v = document.getSelection().toString();
        const ae = document.activeElement;
        if (!v && ae && 'value' in ae) v = ae.value.substring(ae.selectionStart || 0, ae.selectionEnd || 0) || ae.value;
        if (!v) { const tas = document.querySelectorAll('textarea'); if (tas.length) v = tas[tas.length - 1].value; }
        if (v) window.__mdCopied = v;
        return true;
      }
      return origExec(cmd, ...rest);
    };
    document.addEventListener('copy', e => {
      const sel = document.getSelection().toString();
      if (sel) window.__mdCopied = sel;
      const ta = document.activeElement;
      if (!sel && ta && 'value' in ta) window.__mdCopied = ta.value;
    }, true);
  }
  const btnRe = /copy|kop[ií]r|clipboard|schr[aá]nk/i;
  const isBtn = el => {
    const r = el.getBoundingClientRect();
    if (!r.width || r.width > 120 || r.height > 80) return false;
    const attrs = [el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('data-tooltip'),
                   el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className,
                   el.getAttribute('data-testid'), (el.innerText || '').trim().slice(0, 20)].join(' ');
    const icon = el.querySelector('[class*=copy i], [class*=clipboard i]');
    return btnRe.test(attrs) || !!icon;
  };
  const cands = [...document.querySelectorAll('button, [role=button], a, span, div, i')]
    .filter(isBtn)
    .filter((el, _, all) => !all.some(o => o !== el && o.contains(el) && isBtn(o)) || el.tagName === 'BUTTON');
  // nejvnější klikací kandidát; odstraní ty, co obsahují jiného kandidáta
  const btns = cands.filter(el => !cands.some(o => o !== el && el.contains(o)));
  let n = 0;
  for (let i = 0; i < btns.length; i++) btns[i].setAttribute('data-md-copy', String(i));
  return btns.length;
}
"""

CODE_EXTRACT_JS = """
(i) => {
  const btn = document.querySelector('[data-md-copy="' + i + '"]');
  const text = window.__mdCopied;
  window.__mdCopied = null;
  if (!btn || !text || !text.trim()) return false;
  const first = text.split('\\n').map(s => s.trim()).find(s => s) || '';
  const mono = e => /mono|courier|consolas|menlo/i.test(getComputedStyle(e).fontFamily);
  const codeSel = 'pre, code, textarea, [class*=code i], [class*=editor i], [class*=highlight i], [class*=snippet i]';
  const codeLike = e => e.matches(codeSel) || mono(e);
  const hasCode = b => [...b.querySelectorAll('*')].some(e => !btn.contains(e) && !e.contains(btn) && codeLike(e) && (e.innerText || '').trim());
  let box = btn.parentElement;
  while (box && box !== document.body && !hasCode(box)) box = box.parentElement;
  if (!box || box === document.body) return false;
  const prose = b => b.querySelector('p, h1, h2, h3, h4, h5, h6, li') ||
    (b.innerText || '').length > 1.5 * text.length + 300;
  if (prose(box)) {
    // obal je moc velký: vezmi největší kódový prvek v něm, který neobsahuje prózu
    const inner = [...box.querySelectorAll(codeSel + ', div, span')]
      .filter(e => codeLike(e) && !prose(e) && !e.contains(btn) && (e.innerText || '').trim())
      .filter((e, _, all) => !all.some(o => o !== e && o.contains(e)));
    if (!inner.length) return false;
    inner.sort((x, y) => (y.innerText || '').length - (x.innerText || '').length);
    box = inner[0];
    btn.remove();
  }
  const cls = (box.outerHTML.match(/(?:language|lang|mode)-([a-z0-9+#]+)/i) || [])[1] || '';
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  if (cls) code.className = 'language-' + cls.toLowerCase();
  code.textContent = text.replace(/\\n$/, '');
  pre.appendChild(code);
  pre.setAttribute('data-md-code', '1');
  box.replaceWith(pre);
  return true;
}
"""

CODE_EDITORS_JS = """
() => {
  let n = 0;
  const repl = (el, text, lang) => {
    if (!el || !el.isConnected || text == null) return;
    const pre = document.createElement('pre'), code = document.createElement('code');
    if (lang) code.className = 'language-' + String(lang).toLowerCase();
    code.textContent = text; pre.appendChild(code); pre.setAttribute('data-md-code', '1');
    el.replaceWith(pre); n++;
  };
  try { if (window.monaco) for (const ed of monaco.editor.getEditors())
    repl(ed.getDomNode(), ed.getValue(), ed.getModel() && ed.getModel().getLanguageId()); } catch (e) {}
  for (const el of document.querySelectorAll('.CodeMirror')) try {
    repl(el, el.CodeMirror.getValue(), el.CodeMirror.getOption('mode')); } catch (e) {}
  for (const el of document.querySelectorAll('.cm-editor')) try {
    const v = el.querySelector('.cm-content').cmView.view; repl(el, v.state.doc.toString(), ''); } catch (e) {
    const lines = [...el.querySelectorAll('.cm-line')].map(l => l.innerText); if (lines.length) repl(el, lines.join('\\n'), ''); }
  for (const el of document.querySelectorAll('.ace_editor')) try {
    repl(el, (el.env && el.env.editor ? el.env.editor : ace.edit(el)).getValue(), ''); } catch (e) {}
  // obecná záloha: sloupec čísel 1..N vedle sloupce s kódem
  for (const g of [...document.querySelectorAll('div, ol, ul, td, span')]) {
    if (!g.isConnected || g.closest('pre')) continue;
    const t = (g.innerText || '').trim();
    if (!/^1\\s*\\n\\s*2(\\s*\\n\\s*\\d+)*$/.test(t)) continue;
    const nums = t.split(/\\s*\\n\\s*/).map(Number);
    if (!nums.every((v, k) => v === k + 1)) continue;
    let box = g.parentElement, codeEl = null;
    for (let k = 0; k < 3 && box && !codeEl; k++, box = box.parentElement)
      for (const c of box.children)
        if (!c.contains(g) && /mono|courier|consolas|menlo/i.test(getComputedStyle(c).fontFamily + getComputedStyle(c.querySelector('*') || c).fontFamily)
            && (c.innerText || '').trim()) { codeEl = c; break; }
    if (!codeEl) continue;
    box = codeEl.parentElement;
    const lines = codeEl.children.length >= nums.length * 0.8
      ? [...codeEl.children].map(l => l.innerText.replace(/\\n$/, ''))
      : (codeEl.innerText || '').split('\\n');
    const text = lines.map(l => l.replace(/\\u00a0/g, ' ').replace(/\\s+$/, '')).join('\\n').replace(/\\n+$/, '');
    repl(box, text, '');
  }
  // čísla řádků v obyčejných <pre>
  for (const g of document.querySelectorAll('pre [class*=line-number i], pre [class*=gutter i], pre .linenos, pre .hljs-ln-numbers'))
    g.remove();
  return n;
}
"""


def load_robots(ctx, start):
    """Načte robots.txt webu (přes stejnou session). Při chybě vrací None = bez omezení."""
    pu = urlparse(start)
    url = f"{pu.scheme}://{pu.netloc}/robots.txt"
    try:
        r = ctx.request.get(url, timeout=15000)
        if r.status in (401, 403):
            rp = RobotFileParser(); rp.disallow_all = True; return rp
        if not r.ok:
            return None
        rp = RobotFileParser()
        rp.parse(r.text().splitlines())
        return rp
    except Exception:
        return None


def norm(url):
    """Odstraní #fragment, kromě hash-routingu (#/cesta)."""
    base, _, frag = url.partition("#")
    if frag.startswith(("/", "!/")):
        return url.rstrip("/")
    return base.rstrip("/") if urlparse(base).path not in ("", "/") else base


def slug_for(url, base):
    p = urlparse(url)
    path = unquote(p.path)
    bp = urlparse(base).path
    rel = path[len(bp):] if path.startswith(bp) else path
    if p.fragment.startswith(("/", "!/")):
        rel = rel.rstrip("/") + "/" + p.fragment.lstrip("!/#")
    rel = rel.strip("/") or "index"
    rel = re.sub(r"\.(html?|php|aspx?)$", "", rel, flags=re.I)
    if p.query:
        rel += "_" + hashlib.md5(p.query.encode()).hexdigest()[:6]
    rel = re.sub(r"[^\w\-./]+", "_", rel).strip("/") or "index"
    return rel + ".md"


class Conv(MarkdownConverter):
    def convert_img(self, el, text, parent_tags=None, **kw):
        alt = (el.get("alt") or "").replace("\n", " ").strip()
        return f"\n\n![{alt}]({el.get('src') or ''})\n\n"


def guess_lang(code):
    t = code.strip()
    if not t:
        return ""
    lines = [l for l in t.splitlines() if l.strip() and not l.strip().startswith("#")]
    if t[0] in "{[":
        try:
            import json; json.loads(t); return "json"
        except Exception:
            pass
    if re.match(r"(FROM|ARG)\s+\S", t):
        return "dockerfile"
    if re.match(r"^(\$ |sudo |apt |npm |pip |docker |kubectl |git |curl |cd |export |#!/bin/(ba)?sh)", t):
        return "bash"
    if re.search(r"^\s*(def |import |from \w+ import )", t, re.M) and ";" not in t:
        return "python"
    if re.search(r"\b(const|let|function|=>|require\(|import .* from)", t):
        return "javascript"
    if re.search(r"^\s*(SELECT|INSERT|CREATE|UPDATE|DELETE)\b", t, re.I | re.M):
        return "sql"
    if lines and sum(bool(re.match(r"\s*(- )?[\w.\-\"']+:(\s|$)", l)) or l.strip().startswith("- ")
                     for l in lines) >= 0.7 * len(lines):
        return "yaml"
    return ""


def code_lang(el):
    for e in [el] + el.find_all("code"):
        for c in e.get("class") or []:
            m = re.match(r"(?:language|lang)-(.+)", c)
            if m:
                return {"text/x-yaml": "yaml", "js": "javascript"}.get(m.group(1), m.group(1))
    return guess_lang(el.get_text())


def save_image(ctx, url, img_dir, cache):
    if url in cache:
        return cache[url]
    data, ext = None, None
    try:
        if url.startswith("data:"):
            head, _, payload = url.partition(",")
            mime = head[5:].split(";")[0] or "image/png"
            data = (base64.b64decode(payload) if ";base64" in head
                    else unquote(payload).encode())
            ext = mimetypes.guess_extension(mime) or ".png"
        else:
            r = ctx.request.get(url, timeout=30000)   # sdílí cookies přihlášení
            if r.ok:
                data = r.body()
                ext = os.path.splitext(urlparse(url).path)[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"):
                    ct = r.headers.get("content-type", "").split(";")[0]
                    ext = mimetypes.guess_extension(ct) or ".img"
    except Exception as e:
        print(f"  ! obrázek {url[:80]}: {e}", file=sys.stderr)
    if not data:
        cache[url] = None
        return None
    name = hashlib.md5(url.encode()).hexdigest()[:12] + ext
    os.makedirs(img_dir, exist_ok=True)
    with open(os.path.join(img_dir, name), "wb") as f:
        f.write(data)
    cache[url] = name
    return name


def slugify(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()[:60] or "page"


def strip_common_suffix(titles):
    """'Kapitola - Kniha - uuBookKit' -> 'Kapitola' (odstraní příponu společnou všem stránkám)."""
    parts = [t.split(" - ") for t in titles]
    k = 0
    while (parts and all(len(p) > k + 1 for p in parts)
           and len({p[-1 - k] for p in parts}) == 1):
        k += 1
    return [" - ".join(p[:len(p) - k]) if k else t for p, t in zip(parts, titles)]


def nonlink_len(el):
    total = len(el.get_text(" ", strip=True))
    links = sum(len(l.get_text(" ", strip=True)) for l in el.find_all("a"))
    return max(total - links, 0)


def css_path(el, depth=3):
    def one(e):
        if e.get("id"):
            return f"{e.name}#{e['id']}"
        cls = [c for c in (e.get("class") or []) if re.fullmatch(r"[\w-]+", c)][:2]
        return e.name + "".join("." + c for c in cls)
    chain, cur = [], el
    while cur is not None and cur.name not in (None, "[document]", "html") and len(chain) < depth:
        chain.append(one(cur))
        cur = cur.parent
    return " > ".join(reversed(chain))


BLOCKS = ["div", "main", "article", "section"]


def tightest_containers(soup, share=0.6):
    """Nejhlubší prvky, které drží >= share veškerého textu stránky MIMO odkazy
    (menu je samé odkazy, takže se tím vyřadí)."""
    body = soup.body or soup
    mx = nonlink_len(body)
    if mx < 80:
        return []
    cands = body.find_all(BLOCKS)
    score = {id(e): nonlink_len(e) for e in cands}
    ok = [e for e in cands if score[id(e)] >= share * mx]
    okids = {id(e) for e in ok}
    return [e for e in ok if not any(id(d) in okids for d in e.find_all(BLOCKS))]


def prune_link_blocks(root, min_links=4, density=0.8):
    """Odstraní bloky tvořené skoro jen odkazy (menu, obsah knihy, drobečky)."""
    trial = copy.copy(root)
    bad = []
    for el in trial.find_all(["div", "ul", "ol", "section", "table"]):
        txt = len(el.get_text(" ", strip=True))
        n = len(el.find_all("a"))
        if n >= min_links and txt and (txt - nonlink_len(el)) / txt >= density:
            bad.append(el)
    badids = {id(b) for b in bad}
    for b in bad:
        if not any(id(p) in badids for p in b.parents):
            b.decompose()
    # když by zbyl skoro prázdný obsah, ponech originál
    return trial if len(trial.get_text(" ", strip=True)) >= 200 else root


def pick_content(soup, selector):
    if selector:
        found = soup.select(selector)
        ids = {id(e) for e in found}
        found = [e for e in found if not any(id(p) in ids for p in e.parents)]  # jen nejvyšší shody
        if found:
            w = soup.new_tag("div")
            for el in found:
                w.append(el)
            return w
        print(f"  ! selektor '{selector}' nic nenašel, používám automatiku", file=sys.stderr)
    auto = tightest_containers(soup)
    if auto:
        return auto[0]
    for sel in ("main", "article", "[role=main]", "#content", ".content", "#root", "body"):
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 50:
            return el
    return soup.body or soup


def render(page, url, a, img_dir=None):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    if a.wait_for:
        try:
            page.wait_for_selector(a.wait_for, timeout=15000)
        except PWTimeout:
            print(f"  ! '{a.wait_for}' se neobjevil", file=sys.stderr)
    page.wait_for_timeout(int(a.settle * 1000))
    page.evaluate(PREP_JS)
    page.wait_for_timeout(400)
    if not a.no_code:
        nb = page.evaluate(CODE_PREP_JS)
        got = 0
        for i in range(nb):
            try:
                page.locator(f'[data-md-copy="{i}"]').first.click(timeout=3000)
                page.wait_for_timeout(250)
                got += bool(page.evaluate(CODE_EXTRACT_JS, i))
            except Exception:
                pass
        got += page.evaluate(CODE_EDITORS_JS)
        if got:
            print(f"  kód: {got}")
    if img_dir and not a.no_shots:
        items = page.evaluate(MARK_JS, a.diagram_selector or "")
        done = []
        for it in items:
            name = f"diagram_{hashlib.md5(url.encode()).hexdigest()[:8]}_{it['id']}.png"
            try:
                loc = page.locator(f'[data-md-shot="{it["id"]}"]')
                loc.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(150)
                os.makedirs(img_dir, exist_ok=True)
                loc.screenshot(path=os.path.join(img_dir, name), timeout=15000)
                it["file"] = name
                done.append(it)
            except Exception as e:
                print(f"  ! snímek diagramu {it['id']}: {e}", file=sys.stderr)
        if done:
            page.evaluate(REPLACE_SHOTS_JS, done)
            print(f"  diagramy: {len(done)}")
    return page.url, page.content()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("-o", "--out", default="ucebnice_md")
    ap.add_argument("--cdp", help="připojit se k běžícímu Chrome, např. http://localhost:9222")
    ap.add_argument("--profile", default=".browser-profile", help="adresář trvalého profilu")
    ap.add_argument("--no-login-prompt", action="store_true", help="nečekat na ruční přihlášení")
    ap.add_argument("--scope", help="stahovat jen URL s tímto prefixem (výchozí: adresář start URL)")
    ap.add_argument("--selector", help="CSS selektor kontejneru s obsahem")
    ap.add_argument("--remove", action="append", default=[], help="CSS selektory k odstranění")
    ap.add_argument("--links-selector", default="a[href]",
                    help='odkud brát odkazy na další stránky, např. "nav a[href]" (výchozí: všechny)')
    ap.add_argument("--wait-for", help="CSS selektor, na který se čeká, než se stránka bere za hotovou")
    ap.add_argument("--settle", type=float, default=1.0, help="doba (s) na dorenderování po načtení")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="pauza mezi stránkami v sekundách (výchozí 1, minimum 0.5)")
    ap.add_argument("--max-pages", type=int, default=2000)
    ap.add_argument("--inspect", action="store_true",
                    help="nestahuje knihu; jen vypíše, kde na první stránce leží obsah, a uloží inspect.html")
    ap.add_argument("--keep-link-blocks", action="store_true",
                    help="nemazat bloky složené převážně z odkazů (menu apod.)")
    ap.add_argument("--diagram-selector",
                    help="CSS selektor dalších prvků, které se mají vyfotit jako obrázek")
    ap.add_argument("--no-code", action="store_true", help="neřešit code snippety")
    ap.add_argument("--no-shots", action="store_true", help="nefotit diagramy")
    ap.add_argument("--scale", type=float, default=2, help="ostrost snímků diagramů (device scale factor)")
    ap.add_argument("--stealth", action="store_true",
                    help="skrýt příznaky automatizace v prohlížeči (jen pokud se jinak nepřihlásíš)")
    ap.add_argument("--ignore-robots", action="store_true",
                    help="nerespektovat robots.txt (jen pro obsah, ke kterému máš právo)")
    ap.add_argument("--headless", action="store_true", help="bez okna (jen když už jsi přihlášen v profilu)")
    a = ap.parse_args()

    # zsh při vkládání přidává "\" před ? = & a server pak vrací 400
    a.url = a.url.replace("\\", "").strip()
    a.url = re.sub(r"/book/page/\?", "/book/page?", a.url)
    start = norm(a.url)
    pu = urlparse(start)
    if a.scope:
        scope = a.scope
    else:
        pth = pu.path if pu.path.endswith("/") else pu.path.rsplit("/", 1)[0] + "/"
        scope = f"{pu.scheme}://{pu.netloc}{pth}"
    scope_n = scope.rstrip("/")

    if a.delay < 0.5:
        print("Pozn.: --delay zvýšen na 0.5 s, ať server zbytečně nezatěžuješ.")
        a.delay = 0.5
    print("spa2md: stahuj jen obsah, ke kterému máš přístup a právo, a výsledek nešiř.\n")

    os.makedirs(a.out, exist_ok=True)
    img_dir = os.path.join(a.out, "images")
    img_cache = {}

    with sync_playwright() as p:
        if a.cdp:
            browser = p.chromium.connect_over_cdp(a.cdp)
            ctx = browser.contexts[0]
            page = ctx.new_page()
        else:
            launch = dict(
                user_data_dir=a.profile, headless=a.headless,
                viewport={"width": 1400, "height": 900},
                device_scale_factor=a.scale,
            )
            if a.stealth:
                launch.update(ignore_default_args=["--enable-automation"],
                              args=["--disable-blink-features=AutomationControlled"])
            try:
                ctx = p.chromium.launch_persistent_context(channel="chrome", **launch)
            except Exception:
                print("Google Chrome nenalezen, použiji Chromium z Playwrightu.")
                ctx = p.chromium.launch_persistent_context(**launch)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(start)
            if not a.no_login_prompt:
                input("\n>>> V otevřeném okně se přihlas a otevři učebnici. "
                      "Pak sem stiskni Enter... ")
                if any("accounts.google.com" in pg.url and "rejected" in pg.url for pg in ctx.pages):
                    print("\nGoogle odmítl přihlášení v okně řízeném skriptem.\n"
                          "Řešení (doporučené): přihlas se ve vlastním Chromu a připoj se k němu:\n"
                          "  google-chrome --remote-debugging-port=9222 --user-data-dir=\"$HOME/chrome-debug\"\n"
                          "  python spa2md.py '<url>' --cdp http://localhost:9222\n"
                          "Nebo zkus jednou spustit s --stealth (přihlášení se pak uloží do profilu).")
                    ctx.close()
                    return

        if a.inspect:
            final_url, html = render(page, start, a, img_dir)
            with open(os.path.join(a.out, "inspect.html"), "w", encoding="utf-8") as f:
                f.write(html)
            soup = BeautifulSoup(html, "lxml")
            print(f"\nUložen {a.out}/inspect.html ({len(html)//1024} kB), URL: {final_url}")
            for share in (0.6, 0.3):
                print(f"\nNejhlubší kontejnery s >= {int(share*100)} % textu mimo odkazy:")
                for el in tightest_containers(soup, share)[:8]:
                    prev = el.get_text(" ", strip=True)[:140]
                    print(f"  --selector \"{css_path(el, 1)}\"   [{css_path(el)}]"
                          f"  text:{nonlink_len(el)} znaků\n      {prev}")
            if not a.cdp:
                ctx.close()
            return

        robots = None if a.ignore_robots else load_robots(ctx, start)
        allowed = (lambda u: True) if robots is None else (lambda u: robots.can_fetch("*", u))
        if not allowed(start):
            print("\nrobots.txt tohoto webu automatické procházení této adresy zakazuje.\n"
                  "Pokud je to obsah, ke kterému máš právo (např. vlastní studijní materiály),\n"
                  "můžeš to vědomě obejít přepínačem --ignore-robots.")
            if not a.cdp:
                ctx.close()
            return
        skipped = 0

        # 1) crawl
        queue, seen, rendered, order = deque([start]), {start}, {}, []
        while queue and len(order) < a.max_pages:
            url = queue.popleft()
            print(f"[{len(order)+1}] {url}")
            try:
                final_url, html = render(page, url, a, img_dir)
            except Exception as e:
                print(f"  ! {e}", file=sys.stderr)
                continue
            soup = BeautifulSoup(html, "lxml")
            rendered[url] = (final_url, soup)
            order.append(url)
            for l in soup.select(a.links_selector):
                href = l.get("href")
                if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                nxt = norm(urljoin(final_url, href))
                if (nxt.startswith(scope_n) and nxt not in seen
                        and not nxt.lower().split("#")[0].endswith(SKIP_EXT)):
                    seen.add(nxt)
                    if allowed(nxt):
                        queue.append(nxt)
                    else:
                        skipped += 1
            time.sleep(a.delay)

        raw = [(rendered[u][1].title.get_text(strip=True) if rendered[u][1].title else "")
               for u in order]
        titles = dict(zip(order, strip_common_suffix(raw)))
        slugs = {}
        for i, u in enumerate(order, 1):
            t = titles[u] or slug_for(u, scope_n)[:-3]
            slugs[u] = f"{i:03d}_{slugify(t)}.md"

        # 2) konverze
        book = []
        for url in order:
            final_url, soup = rendered[url]
            title = titles[url] or slugs[url]
            root = pick_content(soup, a.selector)
            for t in root.find_all(JUNK):
                t.decompose()
            for sel in a.remove:
                for t in root.select(sel):
                    t.decompose()
            if not a.keep_link_blocks:
                root = prune_link_blocks(root)

            up = "../" * slugs[url].count("/")
            for img in root.find_all("img"):
                src = img.get("src")
                if not src:
                    continue
                if src.startswith("md-shot:"):
                    img["src"] = f"{up}images/{src[8:]}"
                    continue
                full = src if src.startswith("data:") else urljoin(final_url, src)
                name = save_image(ctx, full, img_dir, img_cache)
                img["src"] = f"{up}images/{name}" if name else full

            for l in root.find_all("a", href=True):
                tgt = norm(urljoin(final_url, l["href"]))
                if tgt in slugs:
                    rel = os.path.relpath(slugs[tgt], os.path.dirname(slugs[url]) or ".")
                    l["href"] = rel.replace(os.sep, "/")
                else:
                    l["href"] = urljoin(final_url, l["href"])

            md = Conv(heading_style="ATX", bullets="-", code_language_callback=code_lang).convert_soup(root)
            parts = re.split(r"(```.*?```)", md, flags=re.S)
            md = "".join(p if p.startswith("```") else re.sub(r"\n{3,}", "\n\n", p)
                         for p in parts).strip() + "\n"
            if not re.search(r"^#{1,3}\s", md[:500], re.M):
                md = f"# {title}\n\n{md}"
            md = f"<!-- zdroj: {url} -->\n\n{md}"
            path = os.path.join(a.out, slugs[url])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            book.append((slugs[url], title, md))

        # 3) index + celá kniha
        notice = (f"> Staženo nástrojem spa2md z {start} dne {datetime.date.today():%d. %m. %Y}.  \n"
                  "> Obsah patří jeho autorům. Kopie je určena jen pro osobní potřebu, nešiř ji.\n\n")
        if skipped:
            print(f"Vynecháno kvůli robots.txt: {skipped} stránek")
        with open(os.path.join(a.out, "index.md"), "w", encoding="utf-8") as f:
            f.write("# Obsah\n\n" + notice)
            for slug, title, _ in book:
                f.write(f"- [{title}]({slug})\n")
        with open(os.path.join(a.out, "kniha.md"), "w", encoding="utf-8") as f:
            f.write(notice)
            for slug, _, md in book:
                f.write(md.replace("../" * slug.count("/") + "images/", "images/") + "\n\n---\n\n")

        if not a.cdp:
            ctx.close()

    n_img = sum(1 for v in img_cache.values() if v)
    print(f"\nHotovo: {len(book)} stránek, {n_img} obrázků -> {a.out}/")


if __name__ == "__main__":
    main()
