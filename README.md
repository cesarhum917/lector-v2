# Lector v2

Lector de noticias multiusuario, estático y sin servidor. Un pipeline en Python
ingesta un pool compartido de fuentes (RSS, YouTube, podcasts), las procesa con
Claude y publica un `datos.json`. El frontend (`index.html`) es una página
estática que carga ese JSON y **filtra en el navegador**: cada persona elige
sus secciones y oculta fuentes, y esa selección vive solo en su `localStorage`.

```
fuentes.yaml ──► lector.py ──► lector.db (dedup) ──► Claude (Haiku) ──► datos.json
                                                                            │
                                        index.html (estático) ◄────────────┘
                                        + preferencias del usuario (localStorage)
```

Claves del diseño:

- **Sin login, sin base de datos, sin servidor.** Corre entero en GitHub Pages.
- **El costo de API escala con las fuentes, no con los usuarios.** Cada artículo
  pasa por Claude una sola vez (el dedup en SQLite lo garantiza); agregar
  lectores cuesta $0.
- **La puntuación es importancia periodística general por sección**, no
  relevancia personal: el mismo score le sirve a todos los lectores.
- `localStorage` guarda **solo preferencias** (`lector.prefs`): secciones
  elegidas y fuentes ocultas. Los datos siempre vienen de `datos.json`.

## Correr en local

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."

python lector.py                 # corrida completa
python lector.py --sin-claude    # sin API: gratis, para probar fuentes
python lector.py --solo-export   # solo regenerar datos.json desde la base
python lector.py --dias 3        # cuántos días exportar
```

Para ver el frontend, sírvelo (el `fetch` de `datos.json` no funciona con `file://`):

```bash
python -m http.server 8000       # -> http://localhost:8000
```

## Estructura de datos.json

```jsonc
{
  "schema": 1,
  "generado": "2026-07-12T12:00:00+00:00",
  "dias": 3,
  "secciones": [{
    "id": "ia", "nombre": "Inteligencia Artificial", "orden": 5,
    "resumida": true,
    "defaults": { "min_relevancia": 4, "max_por_fuente": 5 },
    "fuentes": [{ "id": "simon-willison", "nombre": "Simon Willison",
                  "dominio": "simonwillison.net", "tipo": "rss" }]
  }],
  "articulos": [{
    "id": "a1b2c3d4",           // hash de la URL normalizada
    "seccion": "ia",
    "fuente": "simon-willison", // id de la fuente CONFIGURADA (para ocultarla)
    "medio": "Simon Willison",  // etiqueta visible (en Google News, el medio real)
    "dominio": "simonwillison.net",
    "tipo": "rss",              // rss | youtube | podcast
    "titulo": "…", "url": "https://…",
    "resumen": "…", "etiqueta": "agentes",   // solo en secciones resumidas
    "relevancia": 7,            // importancia periodística 0-10
    "cluster": "banxico-tasa",  // artículos con el mismo cluster son la misma noticia
    "publicado": "2026-07-11T18:03:00+00:00",
    "imagen": "https://…",      // opcional (thumbnails de YouTube, etc.)
    "duracion": 2040            // opcional, segundos (podcasts)
  }]
}
```

Los artículos van **planos, sin agrupar**: el frontend agrupa por `cluster`
después de aplicar los filtros del usuario (si ocultas la fuente del artículo
líder, el líder cambia). Los `id` de fuentes son estables: no los renombres,
porque las preferencias guardadas en los navegadores apuntan a ellos.

### Leer datos.json programáticamente

```bash
curl -s https://TU-DOMINIO/datos.json | jq '.articulos[0]'
```

```python
import requests
datos = requests.get("https://TU-DOMINIO/datos.json").json()
ia = [a for a in datos["articulos"] if a["seccion"] == "ia"]
```

```javascript
const datos = await (await fetch("https://TU-DOMINIO/datos.json")).json();
const top = datos.articulos.filter(a => a.relevancia >= 8);
```

## Agregar una fuente al pool

Edita `fuentes.yaml` (o corre `python admin.py` para hacerlo con interfaz).
Basta la URL del **sitio**; el script autodescubre el feed:

```yaml
- id: revista-nueva          # slug estable: NO cambiarlo después
  nombre: Revista Nueva
  url: https://revistanueva.com
```

Si el autodiscovery falla, `python diagnostico.py "Revista Nueva"` caza el feed
y te imprime el YAML listo. Para podcasts pega el RSS en `feed:` con
`tipo: podcast`; para YouTube basta la URL del canal.

## Ajustes por sección

| campo | efecto |
|---|---|
| `resumir: true` | Claude resume, agrupa duplicados y puntúa importancia. |
| `resumir: false` | Se lista tal cual (long-form, cine, libros, podcasts). Nunca toca la API. |
| `min_relevancia` | Default de corte que aplica el frontend. |
| `max_por_fuente` | Tope de notas por medio, aplicado en el frontend. |

## Publicar (GitHub Pages)

1. Sube el repo a GitHub (puede ser público: no hay secretos en el código).
2. Settings → Secrets and variables → Actions → New secret:
   `ANTHROPIC_API_KEY` con tu llave.
3. Settings → Pages → Source: `Deploy from a branch` → `main` / `root`.
4. El workflow (`.github/workflows/lector.yml`) corre cada mañana y commitea
   `datos.json` + `lector.db`. También puedes dispararlo a mano desde Actions.

### Dominio propio

1. Crea el archivo `CNAME` en la raíz con tu dominio (una sola línea, p. ej.
   `lector.midominio.com`) — o configúralo en Settings → Pages → Custom domain,
   que crea el CNAME por ti.
2. En tu DNS agrega un registro `CNAME` de ese subdominio hacia
   `<tu-usuario>.github.io`.
3. Activa "Enforce HTTPS" cuando el certificado esté listo.

## Costo

- `MODELO` está fijo en **Haiku** por costo ($1/$5 por MTok). No lo cambies.
- El dedup evita pagar dos veces por el mismo artículo.
- Las secciones con `resumir: false` nunca tocan la API.
- Con ~60 fuentes: en el orden de $1–3 USD/mes. **Independiente del número de
  usuarios**: ellos solo descargan un JSON estático.

## Fase 2 (no construida aún)

Que los usuarios propongan/agreguen fuentes desde la web requiere un backend y
queda para después. El diseño ya lo contempla: el catálogo de `datos.json`
(secciones + fuentes con ids estables y `schema` versionado) puede crecer desde
otro origen sin tocar el frontend.
