#!/usr/bin/env node
/*
 * test_motor.js — Regresion del bug que ocultaba media app (fase 1, TAREAS.md).
 *
 *   node test_motor.js
 *
 * Falla (exit 1) si un articulo de fuente resumir:false vuelve a ser
 * filtrado por relevancia, hundido al fondo, o recortado por el tope
 * por medio. Corre tambien en CI antes de generar datos.
 */
'use strict';
const Motor = require('./motor.js');

let fallas = 0;
function ok(cond, nombre) {
  console.log(`${cond ? 'OK ' : 'FALLA'}  ${nombre}`);
  if (!cond) fallas++;
}

// ---------- fixtures: un tema con una fuente resumida y una longform
const fuentes = new Map([
  ['prensa_x', { id: 'prensa_x', temas: ['cine'], tipo: 'medio', resumida: true }],
  ['revista_y', { id: 'revista_y', temas: ['cine'], tipo: 'longform', resumida: false }],
  ['podcast_z', { id: 'podcast_z', temas: ['cine'], tipo: 'podcast', resumida: false }],
]);
const art = (id, fuente, relevancia, publicado, extra = {}) =>
  ({ id, fuente, medio: fuente, relevancia, cluster: id,
     publicado: `2026-07-${String(publicado).padStart(2, '0')}T12:00:00+00:00`, ...extra });

const base = { fuentes, temaId: 'cine', activas: new Set(fuentes.keys()),
               temasOn: new Set(['cine']) };
const lideres = arts => Motor.gruposDeTema({ ...base, articulos: arts }).map(g => g[0].id);

// ---------- 1. EL BUG: resumir:false con relevancia 0 JAMAS se filtra
{
  const arts = [art('lf1', 'revista_y', 0, 10), art('pod1', 'podcast_z', 0, 9)];
  const ids = lideres(arts);
  ok(ids.includes('lf1') && ids.includes('pod1'),
     'un articulo resumir:false con relevancia 0 siempre aparece');
}

// ---------- 2. el corte SI aplica a fuentes resumidas (ruido fuera)
{
  const arts = [art('ruido', 'prensa_x', Motor.MIN_RELEVANCIA - 1, 10),
                art('util', 'prensa_x', Motor.MIN_RELEVANCIA, 10)];
  const ids = lideres(arts);
  ok(!ids.includes('ruido') && ids.includes('util'),
     `una nota resumida con relevancia < ${Motor.MIN_RELEVANCIA} se filtra; con ${Motor.MIN_RELEVANCIA} pasa`);
}

// ---------- 3. sin puntaje = orden por fecha, no hasta abajo
{
  const arts = [
    art('vieja_alta', 'prensa_x', 9, 1),     // scored alto pero viejo
    art('lf_fresca', 'revista_y', 0, 12),    // sin puntaje, reciente
    art('lf_vieja', 'revista_y', 0, 3),      // sin puntaje, vieja
    art('nota_4', 'prensa_x', 4, 11),        // scored bajo el neutral (5)
  ];
  const ids = lideres(arts);
  ok(ids.indexOf('lf_fresca') < ids.indexOf('lf_vieja'),
     'entre articulos sin puntaje manda la fecha (reciente primero)');
  ok(ids.indexOf('lf_fresca') < ids.indexOf('nota_4'),
     'un articulo sin puntaje no queda debajo de una nota de relevancia baja');
  ok(ids[0] === 'vieja_alta',
     'una nota de relevancia alta si va por encima de los sin puntaje');
}

// ---------- 4. el tope por medio NO recorta a los resumir:false
{
  const muchos = [];
  for (let i = 1; i <= Motor.MAX_POR_MEDIO + 3; i++)
    muchos.push(art(`lf${i}`, 'revista_y', 0, i));
  for (let i = 1; i <= Motor.MAX_POR_MEDIO + 3; i++)
    muchos.push(art(`np${i}`, 'prensa_x', 6, i));
  const ids = lideres(muchos);
  ok(ids.filter(id => id.startsWith('lf')).length === Motor.MAX_POR_MEDIO + 3,
     'el tope por medio no recorta fuentes resumir:false (publican poco)');
  ok(ids.filter(id => id.startsWith('np')).length === Motor.MAX_POR_MEDIO,
     `el tope por medio (${Motor.MAX_POR_MEDIO}) si aplica a fuentes resumidas`);
}

// ---------- 5. el cluster agrupa y el lider no resumido no muere por relevancia
{
  const arts = [
    art('a', 'prensa_x', 7, 10, { cluster: 'misma-noticia' }),
    art('b', 'revista_y', 0, 11, { cluster: 'misma-noticia' }),
  ];
  const grupos = Motor.gruposDeTema({ ...base, articulos: arts });
  ok(grupos.length === 1 && grupos[0].length === 2,
     'los duplicados del mismo cluster se agrupan en una sola historia');
}

console.log(fallas ? `\n${fallas} prueba(s) fallaron` : '\nTodo verde');
process.exit(fallas ? 1 : 0);
