#!/usr/bin/env python3
"""
lector.py — Lector de noticias (v2, esquema catalogo)
=====================================================
Pipeline:  catalogo.yaml -> autodiscovery RSS -> fetch -> SQLite (dedup)
           -> Claude (resumen + agrupacion + importancia) -> datos.json

El catalogo ES el producto (ver CATALOGO.md): fuentes planas con
temas (1+), tipo (medio|voz|primaria|longform|agregador|podcast|video)
y postura declarada. Los paquetes de onboarding son CONSULTAS sobre el
catalogo (temas x tipos), no listas fijas: se exportan tal cual y el
frontend los resuelve en el navegador.

El frontend (index.html) es estatico, carga datos.json y filtra por tema
y por tipo segun las preferencias de cada usuario (localStorage).
El costo de API escala con el numero de fuentes, nunca con el de usuarios.

Uso:
    python lector.py                # corrida normal
    python lector.py --sin-claude   # sin llamar a la API (gratis, para probar)
    python lector.py --dias 3       # cuantos dias exportar a datos.json
    python lector.py --solo-export  # solo regenerar datos.json desde la base

Requiere:  export ANTHROPIC_API_KEY="sk-ant-..."
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# CONFIGURACION
# ----------------------------------------------------------------------
DB_PATH = "lector.db"
CATALOGO_PATH = "catalogo.yaml"
SALIDA_JSON = "datos.json"

MODELO = "claude-haiku-4-5-20251001"   # el mas barato ($1/$5 por MTok). NO cambiar: es por costo.
MAX_ITEMS_POR_LOTE = 25                # items por llamada a la API
UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9,*/*;q=0.8",
}

# Etiquetas visibles de los tipos de fuente (ver CATALOGO.md)
TIPOS = [
    {"id": "medio", "nombre": "Prensa"},
    {"id": "voz", "nombre": "Voces"},
    {"id": "primaria", "nombre": "Primarias"},
    {"id": "longform", "nombre": "Long-form"},
    {"id": "agregador", "nombre": "Agregadores"},
    {"id": "podcast", "nombre": "Podcasts"},
    {"id": "video", "nombre": "Video"},
    {"id": "alerta", "nombre": "Alertas"},
]

# Parametros de Google News por region (para tipo: alerta).
# NO usamos Google Alerts: requiere login y su feed no se puede construir
# programaticamente. Google News da lo mismo y si se puede.
REGIONES_GN = {
    "mx": ("es-419", "MX", "MX:es-419"),
    "latam": ("es-419", "MX", "MX:es-419"),
    "us": ("en-US", "US", "US:en"),
    "es": ("es", "ES", "ES:es"),
}


def feed_de_alerta(fuente: dict) -> str:
    """Una alerta es una consulta guardada: el usuario aporta la query y
    el sistema construye el feed de Google News."""
    region = fuente.get("region")
    if region not in REGIONES_GN:
        # sin region clara, decide el idioma
        region = "mx" if fuente.get("idioma", "es") == "es" else "us"
    hl, gl, ceid = REGIONES_GN[region]
    q = quote(fuente["query"], safe="")
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


# ----------------------------------------------------------------------
# BASE DE DATOS
# ----------------------------------------------------------------------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS articulos (
            id           TEXT PRIMARY KEY,   -- hash de la url
            fuente_id    TEXT,               -- id de la fuente en catalogo.yaml
            fuente       TEXT,               -- medio visible (en agregadores, el medio real)
            tema         TEXT,               -- tema principal (temas[0] de la fuente): para lotes de Claude
            tipo         TEXT,               -- tipo de la fuente (medio|voz|...)
            resumible    INTEGER DEFAULT 0,  -- copia del resumir de la fuente al ingerir
            titulo       TEXT,
            url          TEXT,
            extracto     TEXT,
            publicado    TEXT,               -- ISO 8601
            visto        TEXT,               -- cuando lo capturamos
            resumen      TEXT,               -- generado por Claude
            etiqueta     TEXT,
            relevancia   INTEGER DEFAULT 0,  -- importancia periodistica 0-10 (por tema)
            cluster      TEXT,               -- id del grupo de duplicados
            dominio      TEXT,               -- para el icono de la fuente
            imagen       TEXT,               -- thumbnail si el feed la trae
            duracion     INTEGER,            -- segundos (podcasts)
            procesado    INTEGER DEFAULT 0
        )
    """)
    # Migracion suave si la base viene del esquema anterior (secciones)
    cols = [r[1] for r in con.execute("PRAGMA table_info(articulos)")]
    for col, tipo_sql in [("tema", "TEXT"), ("resumible", "INTEGER DEFAULT 0")]:
        if col not in cols:
            con.execute(f"ALTER TABLE articulos ADD COLUMN {col} {tipo_sql}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pub ON articulos(publicado)")
    # memoria de recomendaciones musicales (para no repetir)
    con.execute("""
        CREATE TABLE IF NOT EXISTS recs_musica (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha       TEXT,      -- YYYY-MM-DD
            categoria   TEXT,      -- album | dj_set | cancion
            nueva       INTEGER,   -- 1 = novedad, 0 = catalogo
            artista     TEXT,
            titulo      TEXT,
            anio        TEXT,
            porque      TEXT,
            plataformas TEXT       -- JSON array
        )
    """)
    con.commit()
    return con


def hash_url(url: str) -> str:
    # Normaliza para que ?utm_source=... no cuente como articulo distinto
    limpia = re.sub(r"[?&](utm_[^=]+|fbclid|gclid)=[^&]*", "", url)
    limpia = limpia.rstrip("?&/")
    return hashlib.sha256(limpia.encode()).hexdigest()[:16]


# ----------------------------------------------------------------------
# AUTODESCUBRIMIENTO DE FEEDS
# ----------------------------------------------------------------------
CACHE_FEEDS = {}


def descubrir_feed(url_sitio: str) -> str | None:
    """Busca el <link rel=alternate type=application/rss+xml> del sitio.
    Asi en catalogo.yaml basta el 'sitio', nunca la URL del RSS."""
    if url_sitio in CACHE_FEEDS:
        return CACHE_FEEDS[url_sitio]

    # Caso especial: canales de YouTube exponen RSS via channel_id
    if "youtube.com" in url_sitio:
        feed = _feed_youtube(url_sitio)
        CACHE_FEEDS[url_sitio] = feed
        return feed

    try:
        r = requests.get(url_sitio, headers=UA, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for tipo in ["application/rss+xml", "application/atom+xml", "application/feed+json"]:
            link = soup.find("link", rel=lambda v: v and "alternate" in v, type=tipo)
            if link and link.get("href"):
                feed = urljoin(url_sitio, link["href"])
                CACHE_FEEDS[url_sitio] = feed
                return feed
    except Exception as e:
        print(f"    ! autodiscovery fallo en {url_sitio}: {e}")

    # Plan B: convenciones comunes (WordPress, Substack, Ghost, Industry Dive...)
    sufijos = ["/feed/", "/feed", "/rss", "/rss.xml", "/index.xml", "/atom.xml",
               "/feeds/news/", "/feed.xml", "/?feed=rss2", "/rss/"]
    base = url_sitio.rstrip("/")
    p = urlparse(url_sitio)
    raiz = f"{p.scheme}://{p.netloc}"
    candidatos = [base + s for s in sufijos]
    if raiz != base:
        candidatos += [raiz + s for s in sufijos]

    for prueba in candidatos:
        try:
            r = requests.get(prueba, headers=UA, timeout=10, allow_redirects=True)
            if not r.ok:
                continue
            cabeza = r.text[:800].lower()
            if "<rss" in cabeza or "<feed" in cabeza or "<?xml" in cabeza:
                d = feedparser.parse(r.content)
                if d.entries:
                    CACHE_FEEDS[url_sitio] = prueba
                    return prueba
        except Exception:
            continue

    CACHE_FEEDS[url_sitio] = None
    return None


def _feed_youtube(url: str) -> str | None:
    """Todo canal de YouTube tiene RSS, pero requiere el channel_id.
    OJO: el primer "channelId" del HTML puede ser de un canal recomendado,
    no del canal de la pagina. El canonical y externalId si son propios."""
    try:
        r = requests.get(url, headers=UA, timeout=15)
        m = (re.search(r'rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', r.text)
             or re.search(r'"externalId":"(UC[\w-]{22})"', r.text)
             or re.search(r'"channelId":"(UC[\w-]{22})"', r.text))
        if m:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
    except Exception as e:
        print(f"    ! youtube fallo: {e}")
    return None


# ----------------------------------------------------------------------
# INGESTA
# ----------------------------------------------------------------------
def dominio_de(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def limpiar_html(texto: str, limite: int = 400) -> str:
    if not texto:
        return ""
    txt = BeautifulSoup(texto, "html.parser").get_text(" ", strip=True)
    return txt[:limite]


def fecha_de(entry) -> str:
    for campo in ("published_parsed", "updated_parsed"):
        t = getattr(entry, campo, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def imagen_de(entry) -> str:
    for m in (entry.get("media_thumbnail") or []):
        if m.get("url"):
            return m["url"]
    for m in (entry.get("media_content") or []):
        if m.get("url") and (str(m.get("type", "")).startswith("image")
                             or m.get("medium") in (None, "image")):
            return m["url"]
    img = entry.get("image")
    if isinstance(img, dict) and img.get("href"):
        return img["href"]
    return ""


def duracion_de(entry) -> int | None:
    """itunes:duration puede venir como segundos o como HH:MM:SS."""
    d = entry.get("itunes_duration")
    if not d:
        return None
    d = str(d).strip()
    try:
        if ":" in d:
            s = 0
            for parte in d.split(":"):
                s = s * 60 + int(parte)
            return s
        return int(float(d))
    except ValueError:
        return None


def ingestar(con, config) -> int:
    nuevos = 0
    ahora = datetime.now(timezone.utc).isoformat()

    for fuente in config["fuentes"]:
        nombre = fuente["nombre"]
        fid = fuente["id"]
        tema = fuente["temas"][0]        # tema principal: define el lote de Claude
        tipo = fuente["tipo"]
        resumible = 1 if fuente.get("resumir") else 0
        feed_url = fuente.get("feed")

        if not feed_url and tipo == "alerta":
            feed_url = feed_de_alerta(fuente)
        if not feed_url:
            feed_url = descubrir_feed(fuente["sitio"])
            if not feed_url:
                print(f"  x {nombre}: sin feed (revisar a mano)")
                continue

        try:
            d = feedparser.parse(feed_url, request_headers=UA)
        except Exception as e:
            print(f"  x {nombre}: {e}")
            continue

        if not d.entries:
            print(f"  x {nombre}: feed vacio")
            continue

        tope = fuente.get("max", 30)
        cuenta = 0
        for e in d.entries[:tope]:
            url = e.get("link")
            if not url:
                continue
            aid = hash_url(url)
            extracto = limpiar_html(e.get("summary", "") or e.get("description", ""))

            # Agregadores (Google News): el medio real viene en <source>. Lo
            # usamos como etiqueta visible y para el favicon, pero fuente_id
            # sigue apuntando a la fuente del catalogo (para poder ocultarla).
            titulo = e.get("title", "(sin titulo)")
            medio, dominio = nombre, dominio_de(url)
            src = e.get("source")
            if src and getattr(src, "get", None):
                if src.get("title"):
                    medio = src["title"]
                if src.get("href"):
                    dominio = dominio_de(src["href"])
                # Google News repite " - Medio" al final del titulo
                titulo = re.sub(r"\s+-\s+[^-]+$", "", titulo).strip() or titulo

            try:
                con.execute(
                    "INSERT INTO articulos (id, fuente_id, fuente, tema, tipo, resumible, "
                    "titulo, url, extracto, publicado, visto, dominio, imagen, duracion) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, fid, medio, tema, tipo, resumible, titulo, url, extracto,
                     fecha_de(e), ahora, dominio, imagen_de(e), duracion_de(e)),
                )
                cuenta += 1
                nuevos += 1
            except sqlite3.IntegrityError:
                pass  # ya lo teniamos: dedup gratis, sin gastar API

        print(f"  + {nombre}: {cuenta} nuevos")
        con.commit()

    return nuevos


# ----------------------------------------------------------------------
# CAPA CLAUDE: resumen, agrupacion de duplicados, importancia
# ----------------------------------------------------------------------
# La puntuacion es IMPORTANCIA PERIODISTICA GENERAL por tema, no relevancia
# contra un perfil personal. El lector es multiusuario: cada quien filtra en
# el navegador, pero el score debe servirle a todos.
PROMPT = """Eres el editor de un lector de noticias. Los siguientes {n} articulos
pertenecen al tema "{tema}". Para cada uno:
1. "resumen": una frase en espanol, informativa y concreta (max 25 palabras).
   Nada de "el articulo habla de". Di el hecho.
2. "etiqueta": una palabra clave.
3. "importancia": 0-10 con criterio periodistico general para lectores que
   siguen este tema. 8-10 = noticia mayor, desarrollo significativo o de
   impacto amplio. 5-7 = util para quien sigue el tema. 0-4 = ruido, refrito,
   nota menor o contenido promocional.
4. "cluster": si varios articulos cuentan LA MISMA noticia, dales el mismo
   identificador corto (ej. "banxico-tasa"). Si es unico, usa su propio id.

Responde SOLO con un array JSON. Sin markdown, sin explicaciones:
[{{"id":"...","resumen":"...","etiqueta":"...","importancia":7,"cluster":"..."}}]

ARTICULOS:
{articulos}"""


def procesar_con_claude(con, config, activo=True, marcar_sin_api=False):
    nombres = {t["id"]: t["nombre"] for t in config["temas"]}

    pendientes = con.execute(
        "SELECT id, tema, fuente, titulo, extracto FROM articulos "
        "WHERE procesado = 0 AND resumible = 1").fetchall()

    if not pendientes:
        print("\nNada nuevo que procesar con Claude.")
    else:
        print(f"\nProcesando {len(pendientes)} articulos con Claude...")

    if not activo and pendientes:
        if marcar_sin_api:
            print("  (--sin-claude: se marcan como procesados sin llamar a la API)")
            con.executemany("UPDATE articulos SET procesado=1, relevancia=5, cluster=id "
                            "WHERE id=?", [(p[0],) for p in pendientes])
            con.commit()
        else:
            # Falta la API key pero NO fue intencional: se dejan pendientes
            # para que la proxima corrida (ya con key) si los resuma.
            print("  ! Sin API key: quedan pendientes y se reintentan en la proxima corrida.")
        pendientes = []

    if pendientes:
        from anthropic import Anthropic
        client = Anthropic()

        # Lotes por tema: el criterio de importancia es tematico, y los
        # clusters de duplicados solo tienen sentido dentro de un tema.
        por_tema = {}
        for p in pendientes:
            por_tema.setdefault(p[1], []).append(p)

        for tid, filas in por_tema.items():
            for i in range(0, len(filas), MAX_ITEMS_POR_LOTE):
                lote = filas[i:i + MAX_ITEMS_POR_LOTE]
                listado = "\n".join(
                    f'- id:{r[0]} | fuente:{r[2]} | titulo:{r[3]} | extracto:{(r[4] or "")[:200]}'
                    for r in lote
                )
                try:
                    msg = client.messages.create(
                        model=MODELO,
                        max_tokens=4000,
                        messages=[{"role": "user", "content": PROMPT.format(
                            tema=nombres.get(tid, tid), n=len(lote), articulos=listado)}],
                    )
                    texto = msg.content[0].text.strip()
                    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
                    datos = json.loads(texto)

                    for d in datos:
                        con.execute(
                            "UPDATE articulos SET resumen=?, etiqueta=?, relevancia=?, "
                            "cluster=?, procesado=1 WHERE id=?",
                            (d.get("resumen", ""), d.get("etiqueta", ""),
                             int(d.get("importancia", 5)), d.get("cluster", d["id"]), d["id"]),
                        )
                    con.commit()
                    print(f"  [{tid}] lote {i // MAX_ITEMS_POR_LOTE + 1}: {len(datos)} listos")
                    time.sleep(1)

                except Exception as e:
                    print(f"  ! error en lote [{tid}]: {e}")
                    # No los marcamos: se reintentan en la siguiente corrida
                    continue

    # Lo que no se resume (longform, podcasts...) queda listo tal cual
    con.execute("UPDATE articulos SET procesado=1, cluster=id "
                "WHERE procesado=0 AND resumible=0")
    con.commit()


# ----------------------------------------------------------------------
# MUSICA: recomendaciones diarias a la medida del grupo
# ----------------------------------------------------------------------
# A diferencia del resto del lector (RSS), la seccion de musica es
# GENERATIVA: una llamada diaria a Claude con el perfil de gustos del
# grupo (musica-gustos.yaml, destilado de su tabla de calificaciones)
# produce 6 recomendaciones: album, dj set y cancion, cada una en
# version novedad y version catalogo. La tabla recs_musica evita
# repetir recomendaciones. Costo: 1 llamada/dia.
GUSTOS_PATH = "musica-gustos.yaml"

PROMPT_MUSICA = """Eres el curador musical de un grupo de tres amigos de Mexico.
Su perfil, destilado de {n_obras} obras que calificaron de 0 a 10:

SINTESIS: {sintesis}

LO MAS GUSTADO (artista — obra [formato, promedio]):
{top}

LO QUE NO LES GUSTO:
{bajo}

Hoy es {hoy}. Genera EXACTAMENTE 6 recomendaciones:
- 2 con "categoria":"album"  (una "nueva":true = lanzada en los ultimos ~3 meses; una "nueva":false = catalogo/clasico)
- 2 con "categoria":"dj_set" (uno reciente, uno de archivo; SOLO sets reales y grabados: Boiler Room, HOR, NTS, Dekmantel, Trommel, Mixmag, Tiny Desk, etc.)
- 2 con "categoria":"cancion" (una nueva, una de catalogo)

Reglas:
1. Nada que ya este en su historial ni en YA RECOMENDADO.
2. "porque" conecta con SU gusto concreto (max 18 palabras, en espanol).
3. Si no estas seguro de que algo exista tal cual, elige otra cosa segura.
4. Variedad dentro de su perfil: no des 6 cosas del mismo genero.
5. "plataformas": donde realmente se encuentra, de esta lista:
   Spotify, Apple Music, YouTube, Bandcamp, SoundCloud, Mixcloud, NTS.
   (Los DJ sets suelen vivir en YouTube/SoundCloud/Mixcloud, no en Spotify.)

YA RECOMENDADO (no repetir):
{previas}

Responde SOLO con el array JSON, sin markdown:
[{{"categoria":"album","nueva":true,"artista":"...","titulo":"...","anio":"2026","porque":"...","plataformas":["Spotify","Bandcamp"]}}]"""


def recomendar_musica(con, activo=True):
    if not os.path.exists(GUSTOS_PATH):
        return
    hoy = datetime.now(timezone.utc).date().isoformat()
    if con.execute("SELECT COUNT(*) FROM recs_musica WHERE fecha=?", (hoy,)).fetchone()[0]:
        print("\nMusica: las recomendaciones de hoy ya existen.")
        return
    if not activo:
        print("\nMusica: sin API key, se conservan las recomendaciones previas.")
        return

    with open(GUSTOS_PATH, encoding="utf-8") as f:
        gustos = yaml.safe_load(f)
    previas = con.execute(
        "SELECT artista, titulo FROM recs_musica ORDER BY id DESC LIMIT 90").fetchall()

    fmt = lambda d: f'- {d["artista"]} — {d["obra"]} [{d["formato"]}, {d["promedio"]}]'
    prompt = PROMPT_MUSICA.format(
        n_obras=len(gustos["muy_gustado"]) + len(gustos["no_gustado"]),
        sintesis=gustos["sintesis"],
        top="\n".join(fmt(d) for d in gustos["muy_gustado"]),
        bajo="\n".join(fmt(d) for d in gustos["no_gustado"]),
        hoy=hoy,
        previas="\n".join(f"- {a} — {t}" for a, t in previas) or "- (nada aun)",
    )

    from anthropic import Anthropic
    try:
        msg = Anthropic().messages.create(
            model=MODELO, max_tokens=1500,
            messages=[{"role": "user", "content": prompt}])
        texto = re.sub(r"^```(?:json)?|```$", "", msg.content[0].text.strip(), flags=re.M).strip()
        recs = json.loads(texto)
        assert isinstance(recs, list) and len(recs) >= 4
    except Exception as e:
        print(f"\nMusica: fallo la generacion ({e}); se conservan las previas.")
        return

    for r in recs[:6]:
        con.execute(
            "INSERT INTO recs_musica (fecha, categoria, nueva, artista, titulo, anio, porque, plataformas) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (hoy, r.get("categoria", "cancion"), 1 if r.get("nueva") else 0,
             r.get("artista", ""), r.get("titulo", ""), str(r.get("anio", "")),
             r.get("porque", ""), json.dumps(r.get("plataformas", []), ensure_ascii=False)))
    con.commit()
    print(f"\nMusica: {len(recs[:6])} recomendaciones nuevas para hoy.")


# ----------------------------------------------------------------------
# EXPORTAR datos.json (catalogo completo + articulos planos)
# ----------------------------------------------------------------------
DIAS_SIN_RESUMIR = 14   # ventana larga para resumir:false: longform y podcasts
                        # publican poco (a veces semanal); con la ventana corta
                        # desaparecen del sitio la mayoria de los dias


def exportar_json(con, config, dias=3):
    ahora = datetime.now(timezone.utc)
    corte = (ahora - timedelta(days=dias)).isoformat()
    corte_largo = (ahora - timedelta(days=max(dias, DIAS_SIN_RESUMIR))).isoformat()

    fuentes = []
    for f in config["fuentes"]:
        ficha = {
            "id": f["id"],
            "nombre": f["nombre"],
            "dominio": dominio_de(f.get("sitio") or f.get("feed") or "")
                       or ("news.google.com" if f["tipo"] == "alerta" else ""),
            "temas": f["temas"],
            "tipo": f["tipo"],
            "idioma": f.get("idioma"),
            "region": f.get("region", "global"),
            "postura": f.get("postura"),
            "financiamiento": f.get("financiamiento"),
            # esencial: entra a los paquetes de onboarding; el resto del
            # catalogo queda para explorar (frontend futuro)
            "esencial": bool(f.get("esencial")),
            "peso": f.get("peso", 1),
            "resumida": bool(f.get("resumir")),
            "porque": f.get("porque", ""),
        }
        if f["tipo"] == "alerta":
            # la consulta es visible: una alerta ES su query, y el pool
            # multiusuario futuro necesita saber quien la creo
            ficha["query"] = f["query"]
            if f.get("autor"):
                ficha["autor"] = f["autor"]
        fuentes.append(ficha)
    ids_catalogo = {f["id"] for f in fuentes}

    filas = con.execute(
        "SELECT id, fuente_id, fuente, dominio, tipo, titulo, url, resumen, "
        "etiqueta, relevancia, cluster, publicado, imagen, duracion, resumible "
        "FROM articulos WHERE publicado > ? AND procesado = 1 "
        "ORDER BY publicado DESC", (corte_largo,)).fetchall()

    articulos = []
    for r in filas:
        if r[1] not in ids_catalogo:
            continue  # fuente retirada del catalogo (o del esquema anterior)
        if r[14] and r[11] <= corte:
            continue  # resumibles: solo la ventana corta; la larga es para longform/podcasts
        a = {
            "id": r[0],
            "fuente": r[1],
            "medio": r[2] or "",
            "dominio": r[3] or "",
            "tipo": r[4] or "medio",
            "titulo": r[5] or "(sin titulo)",
            "url": r[6],
            "relevancia": r[9] if r[9] is not None else 0,
            "cluster": r[10] or r[0],
            "publicado": r[11],
        }
        if r[7]:
            a["resumen"] = r[7]
        if r[8]:
            a["etiqueta"] = r[8]
        if r[12]:
            a["imagen"] = r[12]
        if r[13]:
            a["duracion"] = r[13]
        articulos.append(a)

    datos = {
        "schema": 2,
        "generado": ahora.isoformat(),
        "dias": dias,
        "dias_sin_resumir": max(dias, DIAS_SIN_RESUMIR),
        "temas": config["temas"],
        "tipos": TIPOS,
        # definiciones del eje financiamiento (quien paga a cada medio);
        # el frontend las muestra al tocar la etiqueta
        "financiamientos": config.get("financiamiento", []),
        # Un paquete es una CONSULTA sobre el catalogo (temas x tipos):
        # el frontend lo resuelve en el navegador, asi las fuentes nuevas
        # entran solas a quien eligio el paquete.
        "paquetes": config.get("paquetes", []),
        "fuentes": fuentes,
        "articulos": articulos,
    }

    # recomendaciones musicales del dia mas reciente que exista
    ult = con.execute("SELECT MAX(fecha) FROM recs_musica").fetchone()[0]
    if ult:
        filas_m = con.execute(
            "SELECT categoria, nueva, artista, titulo, anio, porque, plataformas "
            "FROM recs_musica WHERE fecha=? ORDER BY categoria, nueva DESC", (ult,)).fetchall()
        datos["musica"] = {"generado": ult, "recs": [
            {"categoria": r[0], "nueva": bool(r[1]), "artista": r[2], "titulo": r[3],
             "anio": r[4], "porque": r[5], "plataformas": json.loads(r[6] or "[]")}
            for r in filas_m]}
    with open(SALIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    kb = os.path.getsize(SALIDA_JSON) // 1024
    print(f"\n-> {SALIDA_JSON} listo: {len(articulos)} articulos, "
          f"{len(fuentes)} fuentes, {len(datos['temas'])} temas, "
          f"{len(datos['paquetes'])} paquetes, {kb} KB, ultimos {dias} dias.")


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-claude", action="store_true", help="no llamar a la API")
    ap.add_argument("--dias", type=int, default=3, help="dias a exportar en datos.json")
    ap.add_argument("--solo-export", action="store_true", help="solo regenerar datos.json")
    args = ap.parse_args()

    with open(CATALOGO_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    con = init_db()

    if not args.solo_export:
        n = ingestar(con, config)
        print(f"\n{n} articulos nuevos.")
        usar_claude = not args.sin_claude and os.environ.get("ANTHROPIC_API_KEY")
        if not args.sin_claude and not usar_claude:
            print("! Falta ANTHROPIC_API_KEY.")
        procesar_con_claude(con, config, activo=bool(usar_claude),
                            marcar_sin_api=args.sin_claude)
        recomendar_musica(con, activo=bool(usar_claude))

    exportar_json(con, config, dias=args.dias)
    con.close()


if __name__ == "__main__":
    main()
