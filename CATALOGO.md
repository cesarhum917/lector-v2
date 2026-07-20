# Especificación del catálogo

> El motor de RSS es commodity. **El catálogo es el producto.**
> Este documento es la fuente de verdad sobre qué entra, qué no, y por qué.

---

## La promesa

**Feedly:** "No te pierdas nada." → 300 ítems, la culpa es tuya.
**Nosotros:** "Lee menos, entérate igual." → 18 historias, agrupadas, puntuadas.

Todo lo que sigue existe para servir esa promesa. **Si una decisión agrega
fuentes pero no agrega señal, es una mala decisión.**

---

## Los ejes

Feedly organiza solo por tema. Nosotros por **tema × tipo**, y el tipo importa
tanto como el tema. Para la prensa hay un tercer eje: **`financiamiento`**
(quién paga al medio; ver abajo) — nadie más deja filtrar por eso.

Ejemplo real que motivó esto: en IA, los blogs personales (Willison, Mollick,
Clark) van meses adelante de la prensa, que solo cubre lanzamientos. Un usuario
debe poder decir *"quiero IA, pero solo voces y primarias, sin prensa"*.
Feedly no deja expresar eso. Nosotros sí.

### Tipos de fuente

| `tipo` | Qué es | Volumen | Para qué sirve |
|---|---|---|---|
| `medio` | Prensa, agencias | Alto | Cobertura amplia. Ruidoso. |
| `voz` | Blog personal, Substack | Bajo | Profundidad. Sesgo declarado. |
| `primaria` | La fuente original (SENASICA, Banxico, OpenAI) | Bajo | Sin intermediario. Máxima confianza. |
| `longform` | Revista de ensayo/investigación | Muy bajo | Alta señal. Se lee entero. |
| `agregador` | Google News, Longreads | Alto | Red de seguridad y rescate. |
| `podcast` | Audio | Bajo | — |
| `video` | YouTube | Medio | — |
| `alerta` | Una consulta guardada | Variable | Vigila un tema en toda la prensa a la vez. |

### Sobre `alerta`

Una alerta **no es un medio: es una consulta**. El usuario aporta la `query` y
el sistema construye el feed sobre Google News:

```
https://news.google.com/rss/search?q={QUERY_URLENCODED}&hl={hl}&gl={gl}&ceid={ceid}
```

`hl/gl/ceid` salen del campo `region` (`mx` → `hl=es-419&gl=MX&ceid=MX:es-419`).
**No usamos Google Alerts** (google.com/alerts): requiere login y su feed no se
puede construir programáticamente. Google News da lo mismo y sí se puede.

```yaml
- id: alerta_miel_fraude
  nombre: "Miel: adulteración"
  tipo: alerta
  query: 'miel (adulteración OR fraude OR autenticidad)'
  temas: [alimentos]
  idioma: es
  region: mx
  resumir: true
  autor: cesar        # quién la creó (para el pool multiusuario futuro)
  porque: "..."
```

El costo escala con alertas **únicas**, no con usuarios. La ruta de alta sin
servidor (fase posterior): GitHub Issue Form → Action que parsea → PR al catálogo.

---

## Criterios de curaduría

### 1. Utilidad sobre popularidad
La regla que ya aplicamos sin nombrarla. **Reverse Shot sobre Rotten Tomatoes.**
Simon Willison sobre TechCrunch. Si una fuente es popular pero derivativa, fuera.

### 2. Primacía
Prefiere la fuente original sobre quien la reporta. SENASICA antes que la nota
que resume a SENASICA. Cuando exista una `primaria` para un tema, va primero.

### 3. Transparencia de postura, no "objetividad"
**No prometemos neutralidad.** Casi todo medio se cree objetivo, y en temas
políticos no hay árbitro neutral: decir "estas son las objetivas" es tomar una
postura editorial disfrazada de neutralidad.

En su lugar: **declaramos la postura** en el campo `postura` y el usuario decide.
Es más honesto y más defendible.

### 4. Diversidad dentro de la categoría
Ningún paquete debe traer cinco medios de la misma línea editorial. Esto protege
al usuario mejor que prometerle objetividad.
**Regla dura:** todo paquete de tema político/nacional debe incluir al menos dos
`postura` distintas.

### 5. Toda fuente justifica su lugar
El campo `porque` es **obligatorio**. Una línea: qué aporta esta fuente que
ninguna otra del catálogo aporta. Si no puedes escribirla, la fuente no entra.

### 6. Más fuentes ≠ mejor
La tentación va a ser inflar el catálogo para competir con Feedly. **Resístela.**
Cada fuente nueva tiene que ganarse el lugar contra las que ya están.

---

## Esquema de una fuente

```yaml
- id: simon_willison              # slug único y estable
  nombre: "Simon Willison"
  feed: "https://simonwillison.net/atom/everything/"
  sitio: "https://simonwillison.net"     # para el favicon
  temas: [ia]                     # 1+ temas (un feed puede servir a varios)
  tipo: voz                       # medio | voz | primaria | longform | agregador | podcast | video | alerta
  idioma: en                      # en | es
  region: global                  # global | mx | latam | es | us
  volumen: medio                  # bajo (<5/sem) | medio (5-30) | alto (>30/día)
  postura: null                   # solo si aplica; ver abajo
  financiamiento: null            # quién paga; ver abajo. Obligatorio en tipo medio
  esencial: true                  # ¿entra a los paquetes de onboarding? ver abajo
  resumir: true                   # ¿pasa por Claude? (false = long-form, se lee entero)
  max: 15                         # tope de ingesta por corrida
  porque: "Va meses adelante de la prensa; prueba las herramientas antes que nadie."
```

### Sobre `postura`
Solo se llena en temas donde la línea editorial cambia lo que lees
(política, economía). En cine, libros o IA se deja `null`.

Valores para México: `izquierda`, `centro-izquierda`, `centro`,
`centro-derecha`, `derecha`, `oficialista`, `critica-gobierno`, `independiente`.

**Es una etiqueta descriptiva, no un juicio de calidad.** Un medio con postura
declarada puede ser excelente. El punto es que el usuario lo sepa.

### Sobre `financiamiento`

Es la respuesta honesta a "quiero medios objetivos". **No existe el medio
"independiente" en abstracto: existe el medio independiente RESPECTO A un poder
concreto.** La pregunta útil no es "¿es objetivo?" sino *"¿quién le paga, y a
quién NO puede criticar por eso?"*

El ejemplo que lo explica todo: DW está financiada por el gobierno **alemán**.
No es "independiente" en absoluto. Pero NO está capturada por el gobierno
mexicano ni el estadounidense — por eso puede decir de México lo que la prensa
local normaliza. Drop Site vive de sus lectores: no depende de anunciantes ni
de acceso oficial. **Los dos sirven al mismo propósito por caminos opuestos.**
La independencia es relacional, no absoluta; por eso el campo no se llama
"independiente" (sería mentira), sino `financiamiento`, y el usuario decide.

| `financiamiento` | Qué significa |
|---|---|
| `lectores` | No depende de anunciantes ni de acceso oficial. El sesgo es editorial, no comercial. |
| `publico_extranjero` | Financiado por OTRO estado. Capturado por un poder que a ti no te afecta. Útil justo por eso. |
| `fundacion` | Sin presión comercial. Revisar la agenda del donante. |
| `anuncios` | Presión comercial. Difícil que critique a sus anunciantes. |
| `estatal_local` | Capturado respecto a lo que más te importa. Úsalo como fuente primaria, no como crítica. |
| `corporativo` | Depende del dueño. Puede ser bueno, pero nunca criticará a su matriz. |

Se llena **siempre en `tipo: medio`**; en voces, primarias o long-form solo
cuando aporte (una `primaria` ya declara su interés por definición). Las
definiciones viven en `catalogo.yaml` y se exportan a `datos.json` para que el
frontend las muestre al tocar la etiqueta.

### Sobre `esencial`

El catálogo completo es demasiado para un recién llegado. `esencial: true`
marca el subconjunto (~50) que **entra a los paquetes de onboarding**; el resto
(`esencial: false`) no se borra: queda en el catálogo, disponible al explorar
temas manualmente (frontend futuro). La regla de poda no cambia — una fuente
mala se corta, no se degrada a `esencial: false`.

Excepción: los paquetes de **formato** ("Escuchar", "Ver") llevan
`todo_el_catalogo: true` y resuelven sin filtrar por esencial — son la puerta
de entrada a ese formato, no una selección temática.

---

## Paquetes de arranque (onboarding)

Feedly te recibe con un buscador vacío. La mayoría no sabe qué buscar y se va.

Nosotros recibimos con **paquetes curados con opinión**. Tres clics:

1. **¿Qué temas?** (multi-select)
2. **¿Qué dieta?** → *Solo lo esencial* (primarias + voces, bajo volumen) ·
   *Equilibrada* (+ medios) · *Todo* (+ agregadores)
3. **Listo.** Refinar después, no antes.

```yaml
paquetes:
  - id: esencial_ia
    nombre: "IA sin ruido"
    descripcion: "Las voces que van adelante de la prensa. Cero notas de lanzamiento."
    temas: [ia]
    tipos: [voz, primaria]
```

El paquete es **una consulta sobre el catálogo**, no una lista fija. Así, cuando
agregues una `voz` nueva de IA, entra sola a todos los que eligieron ese paquete.

---

## Qué NO hacer

- No agregar una fuente "porque es famosa".
- No prometer objetividad. Declarar postura y financiamiento.
- No dejar que el catálogo crezca sin poda. Revisar cada trimestre:
  ¿qué fuentes nadie lee? ¿cuáles solo generan ruido? Fuera.
- No mezclar `longform` con `medio` en el mismo muro: el ruido entierra la señal.
