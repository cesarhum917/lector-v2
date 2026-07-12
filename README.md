# Lector v2

Lector de noticias multiusuario, estático y sin servidor. Un pipeline en Python
ingesta un **catálogo curado** de fuentes (RSS, YouTube, podcasts), las procesa
con Claude y publica un `datos.json`. El frontend (`index.html`) es una página
estática que carga ese JSON y **filtra en el navegador**: cada persona elige
paquetes, filtra por tema y por tipo, y oculta fuentes; esa selección vive solo
en su `localStorage`.

> El motor de RSS es commodity. **El catálogo es el producto.**
> Qué entra, qué no y por qué: ver [CATALOGO.md](CATALOGO.md).

```
catalogo.yaml ──► lector.py ──► lector.db (dedup) ──► Claude (Haiku) ──► datos.json
                                                                             │
                                         index.html (estático) ◄────────────┘
                                         + preferencias del usuario (localStorage)
```

Claves del diseño:

- **Sin login, sin base de datos, sin servidor.** Corre entero en GitHub Pages.
- **El costo de API escala con las fuentes, no con los usuarios.** Cada artículo
  pasa por Claude una sola vez (el dedup en SQLite lo garantiza).
- **Dos ejes: tema × tipo.** Un usuario puede pedir "IA, pero solo voces y
  primarias, sin prensa". El tipo importa tanto como el tema.
- **Postura declarada, no "objetividad".** Los medios políticos llevan su línea
  editorial visible en cada nota.
- **Los paquetes son consultas, no listas.** Un paquete = `temas × tipos` sobre
  el catálogo; cuando entra una fuente nueva que cumple la consulta, aparece
  sola a quien eligió ese paquete.
- La puntuación es **importancia periodística general por tema**, no relevancia
  personal: el mismo score le sirve a todos los lectores.
- `localStorage` guarda **solo preferencias** (`lector.prefs`): paquetes
  elegidos y fuentes ocultas. Los datos siempre vienen de `datos.json`.

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
  "schema": 2,
  "generado": "2026-07-12T12:00:00+00:00",
  "dias": 3,
  "temas":    [{ "id": "ia", "nombre": "Inteligencia Artificial", "color": "#7aa2f7" }],
  "tipos":    [{ "id": "voz", "nombre": "Voces" }],           // medio|voz|primaria|longform|agregador|podcast|video
  "paquetes": [{ "id": "ia_sin_ruido", "nombre": "IA sin ruido",
                 "descripcion": "…", "temas": ["ia"], "tipos": ["voz","primaria"] }],
  "fuentes": [{
    "id": "simon_willison", "nombre": "Simon Willison",
    "dominio": "simonwillison.net",
    "temas": ["ia"], "tipo": "voz",          // los dos ejes
    "idioma": "en", "region": "global",
    "postura": null,                          // declarada solo donde aplica
    "resumida": true,                         // ¿pasa por Claude?
    "porque": "Prueba las herramientas antes que nadie…"
  }],
  "articulos": [{
    "id": "a1b2c3d4",             // hash de la URL normalizada
    "fuente": "simon_willison",   // id en el catálogo (temas/tipo se resuelven ahí)
    "medio": "Simon Willison",    // etiqueta visible (en agregadores, el medio real)
    "dominio": "simonwillison.net",
    "tipo": "voz",
    "titulo": "…", "url": "https://…",
    "resumen": "…", "etiqueta": "agentes",   // solo fuentes resumidas
    "relevancia": 7,              // importancia periodística 0-10, por tema
    "cluster": "banxico-tasa",    // mismo cluster = la misma noticia
    "publicado": "2026-07-11T18:03:00+00:00",
    "imagen": "https://…",        // opcional
    "duracion": 2040              // opcional, segundos (podcasts)
  }]
}
```

Los artículos van **planos, sin agrupar**: el frontend agrupa por `cluster`
después de aplicar los filtros del usuario (si ocultas la fuente del artículo
líder, el líder cambia). Los `id` de fuentes y paquetes son estables: no los
renombres, porque las preferencias guardadas en los navegadores apuntan a ellos.

### Leer datos.json programáticamente

```bash
curl -s https://TU-DOMINIO/datos.json | jq '.articulos[0]'
```

```python
import requests
d = requests.get("https://TU-DOMINIO/datos.json").json()
voces = {f["id"] for f in d["fuentes"] if f["tipo"] == "voz"}
ia_sin_ruido = [a for a in d["articulos"] if a["fuente"] in voces]
```

```javascript
const d = await (await fetch("https://TU-DOMINIO/datos.json")).json();
const top = d.articulos.filter(a => a.relevancia >= 8);
```

## Agregar una fuente al catálogo

**Primero lee [CATALOGO.md](CATALOGO.md).** El campo `porque` es obligatorio:
si no puedes escribir qué aporta que ninguna otra fuente aporte, no entra.

```yaml
- id: revista_nueva            # slug estable: NO cambiarlo después
  nombre: "Revista Nueva"
  sitio: "https://revistanueva.com"   # el feed se autodescubre
  temas: [ideas]
  tipo: longform
  idioma: es
  volumen: bajo
  resumir: false
  porque: "Qué aporta que nadie más del catálogo aporta."
```

Si el autodiscovery falla, `python diagnostico.py "Revista Nueva"` caza el feed
y te imprime el `feed:` listo para pegar. Como el paquete es una consulta, la
fuente nueva entra sola a todos los usuarios cuyo paquete la cubra.

## Publicar (GitHub Pages)

1. Sube el repo a GitHub (puede ser público: no hay secretos en el código).
2. Settings → Secrets and variables → Actions → New secret:
   `ANTHROPIC_API_KEY` con tu llave.
3. Settings → Pages → Source: `Deploy from a branch` → `main` / `root`.
4. El workflow (`.github/workflows/lector.yml`) corre cada mañana y commitea
   `datos.json` + `lector.db`. También puedes dispararlo a mano desde Actions.

### Dominio propio

1. Settings → Pages → Custom domain (crea el archivo `CNAME` por ti).
2. En tu DNS agrega un registro `CNAME` de ese subdominio hacia
   `<tu-usuario>.github.io`.
3. Activa "Enforce HTTPS" cuando el certificado esté listo.

## Costo

- `MODELO` está fijo en **Haiku** por costo ($1/$5 por MTok). No lo cambies.
- El dedup evita pagar dos veces por el mismo artículo.
- Las fuentes con `resumir: false` (longform, podcasts) nunca tocan la API.
- **Independiente del número de usuarios**: ellos solo descargan un JSON estático.

## Fase 2 (no construida aún)

Que los usuarios propongan/agreguen fuentes desde la web requiere un backend y
queda para después. El diseño ya lo contempla: el catálogo de `datos.json`
(fuentes con ids estables, paquetes como consultas, `schema` versionado) puede
crecer desde otro origen sin tocar el frontend.
