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

## Los dos ejes

Feedly organiza solo por tema. Nosotros por **tema × tipo**, y el tipo importa
tanto como el tema.

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
  tipo: voz                       # medio | voz | primaria | longform | agregador | podcast | video
  idioma: en                      # en | es
  region: global                  # global | mx | latam | es | us
  volumen: medio                  # bajo (<5/sem) | medio (5-30) | alto (>30/día)
  postura: null                   # solo si aplica; ver abajo
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
- No prometer objetividad. Declarar postura.
- No dejar que el catálogo crezca sin poda. Revisar cada trimestre:
  ¿qué fuentes nadie lee? ¿cuáles solo generan ruido? Fuera.
- No mezclar `longform` con `medio` en el mismo muro: el ruido entierra la señal.
