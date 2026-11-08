# Trendy Alerta 🎄🔔

Te avisa en el celular **apenas aparezca el Calendario de Adviento** en maquillajetrendyshop.com, con botón para ir directo a comprarlo.

**Cómo funciona**
- `watcher.py` revisa la tienda cada ~45 s (catálogo VTEX, sitemap, banners del home).
- Si hay algo nuevo, manda una notificación push (servicio gratuito **ntfy**) con enlace de compra.
- Si el producto está disponible, te lo repite cada 30 min (hasta 8 veces).
- `docs/` es la app instalable (PWA) con tus avisos y el botón de compra.

Tu tema de ntfy (es como tu contraseña, no lo compartas):

    trendy-adviento-48e6d223b1

---

## Instalación (10 min, una sola vez)

### 1. Recibir avisos en el celular
1. Instala **ntfy** (Play Store / App Store, gratis).
2. Toca **+** → suscríbete al tema `trendy-adviento-48e6d223b1` en el servidor `ntfy.sh`.
3. En el tema: prioridad máxima. En Android: ntfy → sin restricciones de batería.

### 2. Subir el vigilante a GitHub (gratis)
1. Crea un repositorio **público** (ej. `trendy-alerta`) y sube todo el contenido de esta carpeta.
   (Incluye la carpeta oculta `.github`.)
2. **Settings → Secrets and variables → Actions → New repository secret**
   - Nombre: `NTFY_TOPIC`
   - Valor: `trendy-adviento-48e6d223b1`
3. Pestaña **Actions** → "Vigilante Trendy" → **Run workflow**.
4. Abre la ejecución y busca la línea `fuentes OK=3/3`. Si dice `0/3`, la tienda bloqueó a GitHub: avísame.

### 3. Instalar la app
1. **Settings → Pages** → Source: *Deploy from a branch* → rama `main`, carpeta `/docs`.
2. Abre en el celular `https://TU-USUARIO.github.io/trendy-alerta/#t=trendy-adviento-48e6d223b1`
3. Menú del navegador → **Instalar app / Añadir a pantalla de inicio**.
4. Toca **Activar alertas** y luego **Enviar notificación de prueba**.

---

## Prueba rápida desde tu computador
    NTFY_TOPIC=trendy-adviento-48e6d223b1 python watcher.py --test
    python test_watcher.py        # pruebas con una tienda simulada

## Límites que debes conocer
- GitHub ejecuta el cron "cada 5 min" con retrasos ocasionales (a veces 10–15 min). Dentro de cada ejecución se revisa cada 45 s, así que casi siempre el retraso real es de segundos.
- Instagram y TikTok **no** se vigilan: bloquean a los programas automáticos y exigen inicio de sesión. Sigue a @trendyshopbta con las notificaciones del propio Instagram/TikTok activadas como respaldo.
- Si GitHub no tiene actividad en un repo durante 60 días desactiva el cron; el vigilante hace commits cuando detecta cambios, pero revisa que siga activo en diciembre.
- Cada día a las 8 a. m. llega un aviso silencioso "Vigilante activo ✅". Si un día no llega, algo falló.
