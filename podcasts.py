#!/usr/bin/env python3
"""
podcasts.py — Resuelve el feed RSS de un podcast a partir de su nombre.

POR QUÉ EXISTE
El RSS de un podcast NO vive en su sitio web: vive en Libsyn, Transistor,
Megaphone, Acast, Spreaker... Por eso el autodescubrimiento nunca lo encuentra.

CÓMO
Usa la API de búsqueda de Apple Podcasts (iTunes Search).
Es gratuita, pública y NO requiere llave ni registro — a diferencia de
Podcast Index, que exige credenciales y firmar cada petición.
Apple devuelve el campo `feedUrl`, que es exactamente lo que necesitamos.

USO
    python podcasts.py                      # resuelve la lista de abajo
    python podcasts.py "Acquired"           # busca uno suelto
    python podcasts.py --pais MX "El Hilo"  # busca en el catálogo mexicano

Imprime el YAML listo para pegar en catalogo.yaml.
"""

import argparse
import sys
import time
from urllib.parse import urlencode

import requests

API = "https://itunes.apple.com/search"

# Los podcasts a resolver. (nombre_para_buscar, id, temas, idioma, pais)
LISTA = [
    # --- Español ---
    ("Radio Ambulante",            "pod_radio_ambulante",  ["ideas", "internacional"], "es", "MX"),
    ("El Hilo",                    "pod_el_hilo",          ["internacional", "mexico"], "es", "MX"),
    ("Las Raras",                  "pod_las_raras",        ["ideas"],                  "es", "MX"),
    ("Hablemos, escritoras",       "pod_hablemos",         ["libros"],                 "es", "MX"),
    ("Un Libro Una Hora",          "pod_libro_una_hora",   ["libros"],                 "es", "ES"),
    ("Nexos",                      "pod_nexos",            ["mexico", "ideas"],        "es", "MX"),
    ("Así como suena",             "pod_asi_como_suena",   ["mexico"],                 "es", "MX"),
    ("La Corriente del Golfo",     "pod_corriente_golfo",  ["mexico", "ideas"],        "es", "MX"),

    # --- Inglés ---
    ("Acquired",                   "pod_acquired",         ["negocios"],               "en", "US"),
    ("Conversations with Tyler",   "pod_cwt",              ["ideas", "negocios"],      "en", "US"),
    ("Dwarkesh Podcast",           "pod_dwarkesh",         ["ia", "ideas"],            "en", "US"),
    ("Latent Space",               "pod_latent_space",     ["ia"],                     "en", "US"),
    ("The Intercept Briefing",     "pod_intercept",        ["internacional"],          "en", "US"),
    ("The Film Comment Podcast",   "pod_film_comment",     ["cine"],                   "en", "US"),
    ("The LRB Podcast",            "pod_lrb",              ["libros", "ideas"],        "en", "US"),
    ("Serious Sellers Podcast",    "pod_serious_sellers",  ["negocios"],               "en", "US"),
    ("Search Engine",              "pod_search_engine",    ["ideas"],                  "en", "US"),
    ("The Rest Is History",        "pod_rest_history",     ["ideas"],                  "en", "US"),
]


def buscar(termino: str, pais: str = "US", n: int = 5):
    """Busca en Apple Podcasts. Devuelve lista de (nombre, feed, artista, n_eps)."""
    url = f"{API}?{urlencode({'term': termino, 'media': 'podcast', 'country': pais, 'limit': n})}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        datos = r.json().get("results", [])
    except Exception as e:
        print(f"    ! error: {e}", file=sys.stderr)
        return []

    salida = []
    for d in datos:
        feed = d.get("feedUrl")
        if feed:
            salida.append((
                d.get("collectionName", "?"),
                feed,
                d.get("artistName", "?"),
                d.get("trackCount", 0),
            ))
    return salida


def verificar(feed: str) -> int:
    """Confirma que el feed responde y trae episodios."""
    try:
        import feedparser
        d = feedparser.parse(feed)
        return len(d.entries)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("termino", nargs="*", help="nombre del podcast (si se omite, usa LISTA)")
    ap.add_argument("--pais", default="US", help="catálogo: US, MX, ES, AR...")
    ap.add_argument("--todos", action="store_true", help="muestra todas las coincidencias")
    args = ap.parse_args()

    # Modo: buscar uno suelto
    if args.termino:
        term = " ".join(args.termino)
        print(f"\nBuscando '{term}' en el catálogo {args.pais}...\n")
        for nombre, feed, artista, eps in buscar(term, args.pais):
            print(f"  {nombre}  —  {artista}  ({eps} eps)")
            print(f"    feed: {feed}\n")
        return

    # Modo: resolver la LISTA completa
    resueltos, fallidos = [], []

    for nombre, pid, temas, idioma, pais in LISTA:
        print(f"> {nombre} ({pais})")
        res = buscar(nombre, pais)
        if not res:
            print("    -- no encontrado")
            fallidos.append((nombre, pid))
            time.sleep(0.4)
            continue

        # Nos quedamos con la primera coincidencia; si --todos, las mostramos
        if args.todos:
            for n, f, a, e in res:
                print(f"    · {n} — {a} ({e} eps)\n      {f}")

        n, feed, artista, eps = res[0]
        n_ent = verificar(feed)
        estado = f"{n_ent} entradas" if n_ent else "FEED VACÍO — revisar"
        print(f"    OK  {n} — {artista}")
        print(f"        {feed}   [{estado}]")
        resueltos.append((pid, n, feed, temas, idioma, pais, artista))
        time.sleep(0.4)

    # --- Salida en YAML ---
    print("\n" + "=" * 62)
    print("PEGA ESTO EN catalogo.yaml")
    print("=" * 62)
    for pid, nombre, feed, temas, idioma, pais, artista in resueltos:
        region = {"MX": "mx", "ES": "es", "US": "us", "AR": "latam"}.get(pais, "global")
        print(f"""
  - id: {pid}
    nombre: "{nombre}"
    feed: "{feed}"
    temas: [{", ".join(temas)}]
    tipo: podcast
    idioma: {idioma}
    region: {region}
    volumen: bajo
    resumir: false
    porque: "TODO — escribe qué aporta este podcast que ningún otro aporta."\
""")

    if fallidos:
        print("\n" + "=" * 62)
        print("NO ENCONTRADOS (buscar a mano)")
        print("=" * 62)
        for nombre, pid in fallidos:
            print(f"  - {nombre}  ({pid})")

    print(f"\n{len(resueltos)} resueltos · {len(fallidos)} fallidos")
    print("\nRECUERDA: el campo 'porque' es obligatorio (CATALOGO.md).")
    print("Si no puedes escribir qué aporta, la fuente no entra.")


if __name__ == "__main__":
    main()
