"""Prueba del vigilante contra una tienda VTEX y un servidor ntfy simulados.
Ejecuta:  python test_watcher.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

STORE = {"products": [], "home_links": ""}
SENT = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html"):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path
        host = f"http://127.0.0.1:{self.server.server_port}"
        if p.startswith("/api/catalog_system/pub/products/search"):
            self._send(json.dumps([dict(x, link=host + x["link"]) for x in STORE["products"]]), "application/json")
        elif p.startswith("/api/io/_v/api/intelligent-search"):
            self._send(json.dumps({"products": STORE["products"]}), "application/json")
        elif p == "/sitemap.xml":
            self._send("<sitemapindex><sitemap><loc>%s/sitemap/product-0.xml</loc></sitemap></sitemapindex>" % host)
        elif p.startswith("/sitemap/"):
            locs = "".join(f"<url><loc>{host}{x['link']}</loc></url>" for x in STORE["products"])
            self._send(f"<urlset>{locs}<url><loc>{host}/maquillaje</loc></url></urlset>")
        else:
            self._send(
                "<html><a href='/maquillaje'>Maquillaje</a>"
                "<a href='/servicio-al-cliente#selected=terminos-calendario-2026'>Términos Calendario 2026</a>"
                + STORE["home_links"] + "</html>")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        SENT.append(json.loads(self.rfile.read(n)))
        self._send("{}", "application/json")


def product(name, slug, qty):
    return {"productName": name, "link": f"/{slug}/p",
            "items": [{"sellers": [{"commertialOffer": {"AvailableQuantity": qty, "IsAvailable": qty > 0, "Price": 189900}}]}]}


def run(state, extra=()):
    env = dict(os.environ, TRENDY_BASE=f"http://127.0.0.1:{PORT}", NTFY_SERVER=f"http://127.0.0.1:{PORT}",
               NTFY_TOPIC="test-topic", STATE_FILE=state, REPEAT_MINUTES="30")
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "watcher.py"), *extra],
                       env=env, capture_output=True, text=True, timeout=60)
    return r


srv = HTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
state = os.path.join(tempfile.mkdtemp(), "state.json")
fails = []


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        fails.append(label)


# 1. Tienda normal: el enlace de "Términos Calendario" no debe disparar nada
run(state)
check("1. sin calendario -> 0 notificaciones (heartbeat aparte)", [m for m in SENT if m["priority"] >= 3] == [])

# 2. Aparece un banner en el home
SENT.clear()
STORE["home_links"] = "<a href='/calendario-adviento-2026'><img alt='Calendario de Adviento Trendy'></a>"
run(state)
m = [x for x in SENT if x["priority"] >= 3]
check("2. banner nuevo -> 1 notificación 'posible lanzamiento'", len(m) == 1 and "Posible" in m[0]["title"])
check("2b. el click lleva al enlace", m and m[0]["click"].endswith("/calendario-adviento-2026"))

# 3. Mismo banner otra vez: no repite
SENT.clear()
run(state)
check("3. mismo banner -> no repite", [x for x in SENT if x["priority"] >= 3] == [])

# 4. Producto publicado pero sin stock
SENT.clear()
STORE["products"] = [product("Calendario De Adviento Trendy 2026", "calendario-de-adviento-trendy-2026", 0)]
run(state)
m = [x for x in SENT if x["priority"] >= 3]
check("4. producto sin stock -> 1 aviso 'apareció'", len(m) == 1 and "Apareció" in m[0]["title"])

# 5. Producto pasa a disponible
SENT.clear()
STORE["products"] = [product("Calendario De Adviento Trendy 2026", "calendario-de-adviento-trendy-2026", 40)]
run(state)
m = [x for x in SENT if x["priority"] >= 3]
check("5. disponible -> aviso urgente (prioridad 5) con enlace de compra",
      len(m) == 1 and m[0]["priority"] == 5 and m[0]["click"].endswith("/calendario-de-adviento-trendy-2026/p")
      and m[0]["actions"][0]["label"] == "Comprar ahora")
check("5b. mensaje con precio", m and "189.900" in m[0]["message"])

# 6. Inmediatamente después: no spamea
SENT.clear()
run(state)
check("6. repetición inmediata -> silencio", [x for x in SENT if x["priority"] >= 3] == [])

# 7. Pasan 31 min: repite recordatorio
st = json.load(open(state))
for k, v in st["seen"].items():
    v["last_alert"] -= 31 * 60
json.dump(st, open(state, "w"))
SENT.clear()
run(state)
m = [x for x in SENT if x["priority"] >= 3]
check("7. a los 31 min -> recordatorio 'Sigue disponible'", len(m) == 1 and "Sigue disponible" in m[0]["title"])

# 8. Prueba manual
SENT.clear()
r = run(state, ["--test"])
check("8. --test envía notificación", r.returncode == 0 and SENT and "Prueba" in SENT[0]["title"])

print("\nRESULTADO:", "TODO OK" if not fails else f"{len(fails)} fallos")
sys.exit(1 if fails else 0)
