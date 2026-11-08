#!/usr/bin/env python3
"""
Vigilante del Calendario de Adviento de Trendy (maquillajetrendyshop.com, tienda VTEX).

Revisa tres fuentes públicas de la tienda:
  1. Catálogo VTEX (búsqueda "calendario" / "adviento")  -> producto + disponibilidad
  2. Sitemap de la tienda                                -> URLs nuevas con esas palabras
  3. Home y Nueva Colección                              -> banners/enlaces nuevos

Cuando detecta algo nuevo envía una notificación push (ntfy) con un enlace directo
a la compra. Si el producto está disponible, repite el aviso hasta MAX_REPEATS veces.

Solo usa la librería estándar de Python 3.9+.

Uso:
  python watcher.py                 # una revisión
  python watcher.py --loop 240 --every 45   # revisa cada 45 s durante 240 s
  python watcher.py --test          # manda una notificación de prueba
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("TRENDY_BASE", "https://www.maquillajetrendyshop.com").rstrip("/")
NTFY = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
STATE_FILE = pathlib.Path(os.environ.get("STATE_FILE", "state.json"))
REPEAT_MINUTES = int(os.environ.get("REPEAT_MINUTES", "30"))
MAX_REPEATS = int(os.environ.get("MAX_REPEATS", "8"))
FAIL_WARN_AFTER = int(os.environ.get("FAIL_WARN_AFTER", "12"))

KW = re.compile(r"calendari|adviento|advent", re.I)
IGNORE = re.compile(r"t[eé]rminos|servicio-al-cliente|pol[ií]tica|privacidad|condiciones", re.I)
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36"
COL = dt.timezone(dt.timedelta(hours=-5))


def log(*a):
    print(dt.datetime.now(COL).strftime("%H:%M:%S"), *a, flush=True)


def http(url, data=None, headers=None, timeout=20, retries=2):
    h = {"User-Agent": UA, "Accept-Language": "es-CO,es;q=0.9"}
    h.update(headers or {})
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
            time.sleep(1 + i)
    log(f"  ! fallo {url[:90]} -> {err}")
    return None


def absolute(link):
    if not link:
        return ""
    if link.startswith("http"):
        return link
    return BASE + (link if link.startswith("/") else "/" + link)


def path_of(url):
    return urllib.parse.urlparse(url).path.rstrip("/") or "/"


# ---------------------------------------------------------------- fuentes
def parse_vtex_products(items):
    out = {}
    for p in items or []:
        name = p.get("productName") or p.get("name") or ""
        link = absolute(p.get("link") or p.get("linkText") and f"/{p['linkText']}/p")
        if not name or not link or not KW.search(name):
            continue
        available = False
        price = None
        for sku in p.get("items", []):
            for s in sku.get("sellers", []):
                offer = s.get("commertialOffer", {})
                if offer.get("IsAvailable") or (offer.get("AvailableQuantity") or 0) > 0:
                    available = True
                    price = offer.get("Price", price)
        out["p:" + path_of(link)] = {
            "kind": "product", "name": name, "url": link,
            "available": available, "price": price,
        }
    return out


def source_catalog():
    """Devuelve (hits, ok)."""
    hits, ok = {}, False
    for q in ("calendario", "adviento", "advent"):
        qq = urllib.parse.quote(q)
        legacy = http(f"{BASE}/api/catalog_system/pub/products/search?ft={qq}&_from=0&_to=49")
        if legacy is not None:
            try:
                hits.update(parse_vtex_products(json.loads(legacy)))
                ok = True
            except json.JSONDecodeError:
                log("  ! respuesta no-JSON del catálogo")
        smart = http(f"{BASE}/api/io/_v/api/intelligent-search/product_search/?query={qq}&count=24&locale=es-CO")
        if smart is not None:
            try:
                for k, v in parse_vtex_products(json.loads(smart).get("products")).items():
                    if k in hits:  # combina disponibilidad
                        v["available"] = v["available"] or hits[k]["available"]
                    hits[k] = v
                ok = True
            except (json.JSONDecodeError, AttributeError):
                pass
    return hits, ok


def source_sitemap():
    hits = {}
    idx = http(f"{BASE}/sitemap.xml")
    if idx is None:
        return hits, False
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", idx)
    subs = [u for u in locs if u.endswith(".xml")][:8]
    pages = [u for u in locs if not u.endswith(".xml")]
    for s in subs:
        body = http(s, timeout=30)
        if body:
            pages += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    for u in pages:
        if KW.search(path_of(u)) and not IGNORE.search(u):
            hits["s:" + path_of(u)] = {"kind": "sitemap", "url": u, "name": path_of(u).strip("/").replace("-", " ")}
    return hits, True


def source_pages():
    hits, ok = {}, False
    for page in ("/", "/nueva-coleccion"):
        html = http(BASE + page)
        if html is None:
            continue
        ok = True
        for m in re.finditer(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.S | re.I):
            href, inner = m.group(1), m.group(2)
            alts = " ".join(re.findall(r"(?:alt|title)=[\"']([^\"']*)[\"']", m.group(0)))
            text = re.sub(r"<[^>]+>", " ", inner)
            hay = f"{href} {alts} {text}"
            if KW.search(hay) and not IGNORE.search(hay):
                url = absolute(href)
                if path_of(url) in ("/", ""):
                    continue
                label = re.sub(r"\s+", " ", (alts or text)).strip()[:80] or path_of(url)
                hits["l:" + path_of(url)] = {"kind": "link", "url": url, "name": label}
    return hits, ok


# ---------------------------------------------------------------- notificaciones
def notify(title, message, click=None, priority=3, tags=None, buy_label="Comprar ahora"):
    if not TOPIC:
        log(f"[sin NTFY_TOPIC] {title} | {message} | {click}")
        return True
    payload = {"topic": TOPIC, "title": title, "message": message,
               "priority": priority, "tags": tags or []}
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": buy_label, "url": click, "clear": True}]
    r = http(NTFY + "/", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return r is not None


# ---------------------------------------------------------------- lógica
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"seen": {}, "fails": 0, "warned": False, "heartbeat": ""}


def save_state(st):
    new = json.dumps(st, indent=2, ensure_ascii=False, sort_keys=True)
    if not STATE_FILE.exists() or STATE_FILE.read_text() != new:
        STATE_FILE.write_text(new)


def rank(h):
    return (h["kind"] == "product" and h.get("available"), h["kind"] == "product", h["kind"] == "link")


def check_once(st):
    now = time.time()
    all_hits, oks = {}, []
    for src in (source_catalog, source_sitemap, source_pages):
        h, ok = src()
        all_hits.update(h)
        oks.append(ok)
    log(f"fuentes OK={sum(oks)}/3 · coincidencias={len(all_hits)}")

    if not any(oks):
        st["fails"] = st.get("fails", 0) + 1
        if st["fails"] >= FAIL_WARN_AFTER and not st.get("warned"):
            notify("⚠️ Vigilante Trendy sin acceso",
                   "No he podido leer la tienda en varias revisiones. Revisa el workflow en GitHub.",
                   priority=3, tags=["warning"])
            st["warned"] = True
        return
    st["fails"], st["warned"] = 0, False

    seen = st.setdefault("seen", {})
    fresh, reasons = [], {}
    for key, h in all_hits.items():
        prev = seen.get(key)
        if prev is None:
            fresh.append(h)
            reasons[key] = "nuevo"
        elif h["kind"] == "product":
            if h["available"] and not prev.get("available"):
                fresh.append(h)
                reasons[key] = "disponible"
            elif (h["available"] and prev.get("alerts", 0) < MAX_REPEATS
                  and now - prev.get("last_alert", 0) >= REPEAT_MINUTES * 60):
                fresh.append(h)
                reasons[key] = "repite"

    if fresh:
        fresh.sort(key=rank, reverse=True)
        top = fresh[0]
        extra = [h["name"] for h in fresh[1:4]]
        avail = top["kind"] == "product" and top["available"]
        if avail:
            repeat = reasons.get("p:" + path_of(top["url"])) == "repite"
            title = "🎄 ¡Sigue disponible! Calendario Trendy" if repeat else "🎄 ¡YA SALIÓ el Calendario de Adviento Trendy!"
            price = f" · ${int(top['price']):,}".replace(",", ".") if top.get("price") else ""
            msg = f"{top['name']}{price}\nDisponible ahora. Toca para comprar."
            prio, tags = 5, ["tada", "rotating_light"]
        elif top["kind"] == "product":
            title, msg = "👀 Apareció el Calendario en la tienda", f"{top['name']}\nAún no se puede comprar; te aviso apenas haya stock."
            prio, tags = 4, ["eyes"]
        else:
            title, msg = "👀 Posible lanzamiento del Calendario", f"{top['name']}\nHay un nuevo enlace en la tienda. Revísalo."
            prio, tags = 4, ["eyes"]
        if extra:
            msg += "\nTambién: " + " · ".join(extra)
        sent = notify(title, msg, click=top["url"], priority=prio, tags=tags,
                      buy_label="Comprar ahora" if avail else "Ver en la tienda")
        log(("ENVIADA" if sent else "FALLÓ envío") + f": {title}")
        if sent:
            for h in fresh:
                key = {"product": "p:", "sitemap": "s:", "link": "l:"}[h["kind"]] + path_of(h["url"])
                rec = seen.get(key, {})
                rec.update({"kind": h["kind"], "name": h["name"], "available": h.get("available", False),
                            "last_alert": now, "alerts": rec.get("alerts", 0) + 1})
                seen[key] = rec
    # si un producto ya visto dejó de estar disponible, lo anotamos (para avisar si vuelve)
    for key, h in all_hits.items():
        if key in seen and key not in reasons and h["kind"] == "product" and not h["available"]:
            seen[key]["available"] = False


def heartbeat(st):
    today = dt.datetime.now(COL)
    d = today.strftime("%Y-%m-%d")
    if st.get("heartbeat") != d and today.hour >= 8:
        if notify("✅ Vigilante Trendy activo",
                  "Sigo revisando la tienda. Te aviso apenas salga el Calendario de Adviento.",
                  priority=1, tags=["white_check_mark"]):
            st["heartbeat"] = d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="segundos totales de bucle")
    ap.add_argument("--every", type=int, default=45, help="segundos entre revisiones")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()

    if a.test:
        ok = notify("🔔 Prueba de Trendy Alerta", "Si ves esto, las notificaciones funcionan. Toca para abrir la tienda.",
                    click=BASE + "/", priority=4, tags=["bell"], buy_label="Abrir tienda")
        sys.exit(0 if ok else 1)

    st = load_state()
    end = time.time() + a.loop
    while True:
        check_once(st)
        heartbeat(st)
        save_state(st)
        if time.time() + a.every >= end:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
