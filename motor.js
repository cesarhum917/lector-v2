/*
 * motor.js — Motor de seleccion del Lector.
 *
 * Logica pura, sin DOM: la usa index.html en el navegador y la prueba
 * test_motor.js en Node. Cualquier regla de filtrado/orden/agrupado del
 * muro vive AQUI, no en el HTML, para que la regresion tenga donde morder.
 *
 * REGLAS DURAS (fase 1 de TAREAS.md — el bug que ocultaba media app):
 *   1. min_relevancia SOLO filtra articulos de fuentes resumidas.
 *      Los de resumir:false (longform, podcasts, cine, libros) SIEMPRE pasan.
 *   2. Los articulos sin puntaje no se hunden: flotan neutrales (score 5)
 *      y entre si se ordenan por fecha, reciente primero.
 *   3. El tope por medio solo aplica a fuentes resumidas: long-form y
 *      podcasts publican poco y un tope agresivo no tiene sentido.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Motor = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MIN_RELEVANCIA = 4;   // corte de ruido para fuentes resumidas (0-4 = ruido)
  const MAX_POR_MEDIO = 5;    // tope de notas por medio dentro de un tema (solo resumidas)

  // score: los resumidos usan su importancia; los no resumidos flotan a 5.
  const score = (a, f) => f.resumida ? (a.relevancia || 0) : 5;

  /*
   * Selecciona y agrupa los articulos de un tema.
   *   articulos:  array plano (datos.json)
   *   fuentes:    Map id -> fuente (catalogo)
   *   temaId:     tema a mostrar
   *   activas:    Set de ids de fuentes activas (paquetes - ocultas)
   *   temasOn:    Set de ids de temas visibles (para el modo exclusivo)
   *   filtroTipo: id de tipo o null
   *   exclusivo:  true en la vista "Todo": el articulo aparece solo bajo el
   *               primer tema activo de su fuente, para no duplicarse
   * Devuelve: array de grupos (clusters); cada grupo trae el lider primero.
   */
  function gruposDeTema({ articulos, fuentes, temaId, activas, temasOn,
                          filtroTipo = null, exclusivo = false }) {
    const arts = articulos.filter(a => {
      const f = fuentes.get(a.fuente);
      if (!f || !activas.has(f.id)) return false;
      if (!f.temas.includes(temaId)) return false;
      if (filtroTipo && f.tipo !== filtroTipo) return false;
      // Regla 1: el corte de relevancia NUNCA toca a los no resumidos.
      if (f.resumida && (a.relevancia || 0) < MIN_RELEVANCIA) return false;
      if (exclusivo) {
        const primero = f.temas.find(t => temasOn.has(t));
        if (primero !== temaId) return false;
      }
      return true;
    });

    // Duplicados: el lider se decide AQUI, despues de filtrar, porque puede
    // cambiar si el usuario oculto la fuente del lider.
    const porCluster = {};
    for (const a of arts) (porCluster[a.cluster] ??= []).push(a);
    const sc = a => score(a, fuentes.get(a.fuente));
    let grupos = Object.values(porCluster);
    for (const g of grupos)
      g.sort((x, y) => sc(y) - sc(x)
        || String(y.publicado).localeCompare(String(x.publicado)));
    // Regla 2: sin puntaje = score neutral 5; a igual score decide la fecha.
    grupos.sort((a, b) => sc(b[0]) - sc(a[0])
      || String(b[0].publicado).localeCompare(String(a[0].publicado)));

    // Regla 3: tope por medio solo para fuentes resumidas.
    const vistos = {};
    return grupos.filter(g => {
      const f = fuentes.get(g[0].fuente);
      if (!f.resumida) return true;
      const k = g[0].medio || g[0].fuente;
      vistos[k] = (vistos[k] || 0) + 1;
      return vistos[k] <= MAX_POR_MEDIO;
    });
  }

  return { MIN_RELEVANCIA, MAX_POR_MEDIO, score, gruposDeTema };
});
