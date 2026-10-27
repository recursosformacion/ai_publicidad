# Diseño del algoritmo de aprovechamiento de espacios publicitarios

**Estado: propuesta de diseño; no implementado todavía.**  
Objetivo: permitir que la aplicación solicitante reserve un formato concreto o entregue el área real disponible para que `ai_publicidad` seleccione y componga uno, dos o tres anuncios sin desbordar el espacio.

## 1. Decisión principal: selección fija frente a composición automática

La API debe ofrecer dos modos claramente separados. No inferir el modo a partir de que falte un campo ni alterar silenciosamente una petición fija.

### Modo fijo

El cliente identifica un formato (`format_code` o dimensiones) y recibe **una sola creatividad** compatible. Opcionalmente, un consumidor interno autorizado puede imponer una creatividad concreta. Incluso en ese caso se comprueban campaña activa, fechas, estado aprobado, reglas de segmentación, idioma y validez del destino; no se debe permitir que un ID fuerce anuncios pausados, archivados o no dirigidos a esa página.

Si el formato exacto no tiene inventario, se utiliza una creatividad genérica compatible si la política lo permite. Nunca se sustituye un formato fijo por otro tamaño que no cabe.

### Modo de área automática

El cliente indica el rectángulo que realmente ha reservado, y el servicio decide la mejor composición permitida dentro de ese rectángulo. La composición puede contener una creatividad grande, dos pequeñas o tres anuncios pequeños, con un tipo de distribución como `single`, `row`, `column` o `grid`.

La primera versión debe limitar la composición a **tres anuncios**. La decisión de usar menos anuncios debe ser válida: llenar todos los huecos a cualquier precio no es el objetivo.

## 2. Contrato propuesto

Es preferible introducir un endpoint nuevo `POST /api/v1/ads/compose` para no romper el contrato actual de `POST /api/v1/ads/serve`. Ambos deben reutilizar las mismas reglas de selección y validación; `serve` conserva la semántica de una sola creatividad.

Petición automática de ejemplo:

```json
{
  "application": "osap",
  "page": {
    "type": "work_detail",
    "entity_type": "work",
    "entity_id": "12345",
    "language": "es"
  },
  "placement": "content_top",
  "device": "desktop",
  "strategy": {
    "mode": "auto_area",
    "area": {
      "width": 640,
      "height": 320,
      "unit": "css_px"
    },
    "allow_composition": true,
    "max_ads": 3,
    "gap": 12,
    "density": "normal",
    "allow_upscale": false
  }
}
```

Las medidas deben ser **píxeles CSS del contenedor ya reservado**, no el tamaño físico del monitor ni el ancho de todo el viewport. La aplicación conoce mejor el diseño real del contenido; `ai_publicidad` no debe adivinar el ancho de una columna a partir del dispositivo.

Parámetros mínimos:

- `placement`: ubicación física estable (`header`, `sidebar`, `content_top`, `content_inline`, etc.), nunca el nombre de una página o una URL completa.
- `area.width` / `area.height`: límites máximos reales del rectángulo disponible.
- `max_ads`: valor solicitado, limitado por el máximo de la política del espacio y por el máximo global de tres en la primera versión.
- `gap`: separación entre los anuncios, limitada por la política del espacio.
- `density`: `low`, `normal` o `high`. Controla el compromiso entre una creatividad más grande y varias más pequeñas.
- `allow_composition`: permite o prohíbe varias creatividades. Su valor por defecto debe ser `false` en espacios no revisados.
- `allow_upscale`: por defecto `false`; no agrandar creatividades fijas por encima de su tamaño nominal.
- `request_id` o `idempotency_key`: estable para esa instancia de espacio y carga de página, a fin de evitar múltiples entregas si se repite la solicitud por una reconexión o un render de React.

Para el modo fijo:

```json
{
  "application": "osap",
  "page": {
    "type": "work_detail",
    "entity_type": "work",
    "entity_id": "12345",
    "language": "es"
  },
  "placement": "header",
  "device": "desktop",
  "strategy": {
    "mode": "fixed_format",
    "format_code": "leaderboard_728x90"
  }
}
```

Una futura opción `fixed_creative` podría restringir a una creatividad conocida, pero no debe ser la interfaz normal de la web pública: el consumidor debería indicar el espacio o formato y dejar que el servidor seleccione una creatividad elegible.

## 3. Qué debe devolver el servicio

La API debe devolver un **plan de composición declarativo**, no HTML arbitrario como fuente de verdad. Ejemplo esquemático:

```json
{
  "composition_id": "opaque-id",
  "algorithm_version": "1",
  "area": {"width": 640, "height": 320, "unit": "css_px"},
  "layout": {
    "type": "row",
    "gap": 12,
    "width": 612,
    "height": 250
  },
  "items": [
    {
      "slot_index": 0,
      "width": 300,
      "height": 250,
      "ad": {
        "ad_id": 12,
        "impression_id": "opaque-token-a",
        "kind": "house",
        "format": "responsive",
        "title": "OpenMusicRepository",
        "body": "Descubre repertorio y partituras.",
        "image_url": null,
        "alt_text": null,
        "click_url": "https://app.openmusicrepository.com/r/opaque-token-a",
        "ad_format_code": "medium_rectangle_300x250"
      }
    },
    {
      "slot_index": 1,
      "width": 300,
      "height": 250,
      "ad": {"ad_id": 13, "impression_id": "opaque-token-b"}
    }
  ]
}
```

El ejemplo es ilustrativo: en producción cada objeto `ad` lleva el esquema completo de creatividad, sus tamaños y el token de seguimiento.

La aplicación solicitante convierte ese plan en HTML/DOM con componentes propios. Esto evita insertar cadenas sin confianza mediante `innerHTML` o `dangerouslySetInnerHTML`, permite aplicar el sistema visual de OSAP, mantiene accesibilidad y hace que el texto se escape como texto. Si se necesita incorporar anuncios en aplicaciones que no puedan renderizar JSON, se podrá añadir más adelante un modo de fragmento HTML generado por plantillas fijas, con escape de todo texto, URLs validadas, ninguna etiqueta `script`, ningún controlador de eventos y CSS limitado a clases prefijadas. No se debe permitir HTML suministrado libremente por una creatividad.

## 4. Modelo del espacio publicitario

Las dimensiones enviadas por el cliente son límites; no deben otorgar permisos arbitrarios. Recomiendo añadir una política por aplicación y ubicación (tabla futura `ad_placements` o equivalente) con, como mínimo:

- aplicación y código estable de ubicación;
- `allow_composition`, `max_ads` y tipos de distribución aceptados;
- ancho/alto máximos y mínimos útiles de cada tarjeta;
- separación recomendada, densidad por defecto y política de fallback;
- formatos estándar admitidos y estado activo.

La solicitud puede disminuir esos límites, nunca aumentarlos por encima de la política registrada. Si no hay política registrada, se conserva el modo fijo; no se improvisa una composición nueva en una ubicación no validada.

La tabla existente `ad_formats` describe formatos (ancho, alto, dispositivo, categoría). No reemplaza la política del espacio: una cosa es que exista un formato 300×250 y otra que una página haya reservado un rectángulo de ese tamaño y permita colocarlo allí.

## 5. Algoritmo, en orden

### Fase A — validar límites y contexto

1. Validar aplicación, tipo de página, ubicación y dispositivo.
2. Validar que width y height sean positivos y estén dentro de máximos globales. No aceptar medidas enormes o números no válidos.
3. Leer la política de esa ubicación; limitar `max_ads`, `gap`, densidad, tamaño de tarjeta y distribuciones.
4. Si la política prohíbe composición o la solicitud pide modo fijo, solo se considera una creatividad.
5. Si falta área o la petición es inválida, devolver un 4xx claro; no intentar deducirla usando el viewport.

### Fase B — obtener anuncios elegibles

Aplicar las reglas que ya existen en `ai_publicidad` antes de optimizar el espacio:

- campaña activa y dentro de fechas;
- creatividad aprobada;
- reglas de inclusión y exclusión de aplicación, página, ubicación, idioma y entidad;
- idioma compatible;
- formato activo y asociado a la creatividad cuando se solicita un tamaño estándar;
- destino HTTP(S) válido y campos de imagen accesibles/validados.

Una optimización geométrica nunca debe volver elegible una campaña que no lo es. Los anuncios archivados, pausados, rechazados o de otra ubicación no entran en el conjunto candidato.

### Fase C — generar configuraciones geométricas posibles

No probar combinaciones ilimitadas de creatividad por fuerza bruta. Primero enumerar **plantillas de distribución** con el catálogo de tamaños:

1. `single`: una creatividad.
2. `row`: dos o tres tarjetas lado a lado.
3. `column`: dos o tres tarjetas apiladas.
4. `grid`: combinaciones sencillas de dos o tres tarjetas en filas/columnas, si la política de la ubicación lo permite.

Para cada plantilla se calculan las dimensiones completas, incluyendo huecos. Se descartan inmediatamente las que excedan el ancho o alto del área. Cada tarjeta debe respetar su relación de aspecto. Una creatividad fija no se distorsiona; una creatividad declarada adaptable puede reducirse hasta el tamaño mínimo admitido, sin ampliarse si `allow_upscale=false`.

El cálculo debe trabajar con dimensiones CSS redondeadas y usar la misma regla en preview y entrega real. No se debe elegir un formato por área total sin comprobar ancho y alto: 160×600 no cabe solo porque su número de píxeles sea menor que el área disponible.

### Fase D — elegir la mejor plantilla

Evaluar solo plantillas válidas. Recomiendo una puntuación versionada, cuyos pesos se pueden ajustar mediante simulaciones:

- **Ajuste geométrico (35%)**: se adapta a los límites sin deformación ni escalado excesivo.
- **Aprovechamiento de área (25%)**: área útil ocupada respecto al área disponible, con una zona ideal configurable; no se exige llenar el 100%.
- **Preferencia de formato/espacio (15%)**: coincide con los formatos preferidos en la política de esa ubicación.
- **Valor y prioridad de campaña (15%)**: respeta prioridad y, cuando se añada, pacing/objetivos de entrega.
- **Variedad y legibilidad (10%)**: evita repeticiones y penaliza composiciones demasiado densas.

Los pesos son valores iniciales de diseño, no métricas validadas aún. La versión del algoritmo y el score por criterio deben poder consultarse en modo preview. Las condiciones de seguridad y ajuste de geometría son **restricciones duras**, no simples penalizaciones en una puntuación.

La densidad actúa sobre los criterios: `low` favorece una creatividad; `normal` tolera dos si aprovechan claramente mejor el espacio; `high` permite hasta el máximo configurado de tres. Incluso en densidad alta, no se añaden tarjetas diminutas solo para ocupar espacio.

### Fase E — asignar creatividades a las tarjetas

1. Por cada tarjeta de la plantilla, recuperar creatividades que admitan el formato y dimensiones de esa ranura.
2. Ordenar por prioridad de campaña, coincidencia exacta del formato, idioma y objetivo de entrega. Cuando haya campañas equivalentes, usar rotación equilibrada para que el primer ID no reciba todas las impresiones; hoy el orden por ID/priority puede favorecer siempre la primera creatividad.
3. No repetir la misma creatividad en una composición.
4. Favorecer anuncios de distintas campañas cuando sea posible, pero permitir varias creatividades de una campaña propia si no hay alternativas. Más adelante, al existir una entidad `advertiser`, impedir repetir el mismo anunciante en una composición si así se configura.
5. No usar campañas comerciales para todos los huecos y luego ocultar anuncios propios en el informe. Cada tarjeta lleva su tipo (`commercial` o `house`) y su propia entrega.
6. Si no hay conjunto suficiente, seguir la política de fallback: aceptar menos tarjetas, rellenar huecos con anuncios propios compatibles solo si la ubicación permite mezclar tipos, o elegir una plantilla enteramente de anuncios propios. La política por defecto debe ser explícita; no improvisar una mezcla de comerciales y propios.

### Fase F — registrar la composición y sus entregas

Una composición de tres anuncios no es una sola impresión. El servidor genera un token de impresión/clic independiente para cada tarjeta y registra cada entrega. Todas deben quedar relacionadas con un `composition_id` y `slot_index` para analizar qué algoritmo, área y disposición se usaron.

Recomiendo una tabla de composiciones (`ad_compositions`) o campos equivalentes para registrar:
- id opaco, aplicación, página/entidad, ubicación;
- ancho/alto, tipo de diseño, número de tarjetas y versión del algoritmo;
- fecha, score/razones de decisión y clave de idempotencia.

Cada `ad_delivery` referenciaría `composition_id`, `slot_index` y su `ad_format_id`. Crear el registro de composición y sus entregas en una sola transacción: evitar composiciones parciales si falla la base de datos.

La confirmación de impresión se realiza por tarjeta, cuando esa tarjeta realmente es visible, no por el simple hecho de descargar el plan completo. Los clics continúan pasando por la ruta de seguimiento. La idempotencia debe evitar que un render adicional o un timeout cree una segunda composición facturable.

## 6. Cómo evitar que el algoritmo se comporte mal

- **No cambiar el diseño del sitio por sorpresa:** la composición solo cabe dentro del rectángulo que el cliente declara.
- **No multiplicar anuncios por cada cambio de píxel:** el cliente solicita una composición al crear la instancia del espacio y al cambiar de un breakpoint/tamaño significativo; no en cada evento de `ResizeObserver`.
- **No contabilizar una petición como impresión:** las impresiones solo cuentan cuando los elementos están visibles.
- **No duplicar campañas inadvertidamente:** no repetir una creatividad, mantener cada impresión separada y aplicar una penalización de variedad.
- **No servir una pieza fija en el tamaño incorrecto:** las plantillas que deforman o recortan sin permiso se descartan.
- **No devolver huecos sin explicar por qué:** el plan incluye `reason` y, en preview, `rejections` (formato no compatible, targeting, tamaño, estado o fechas).
- **No depender de aleatoriedad irreproducible durante pruebas:** la rotación debe ser predecible por clave de idempotencia o por un mecanismo de pacing, y el modo preview debe mostrar el motivo de la decisión.
- **No devolver HTML no confiable:** el servidor decide estructura y contenido; el consumidor crea DOM a partir de datos validados.

## 7. Preview, observabilidad y aprendizaje

Antes de activar auto-layout en producción, añadir un endpoint de diagnóstico sin efectos laterales, por ejemplo `POST /api/v1/ads/preview`. Debe usar exactamente la misma elegibilidad y puntuación que `compose`, pero no crear tokens ni insertar entregas.

El preview debería devolver:
- la composición ganadora y score total;
- las dos mejores alternativas;
- score de geometría, utilización, prioridad/variedad por alternativa;
- creatividades descartadas y motivo;
- versión del algoritmo, dimensiones y límites de política efectivos.

Preparar fixtures representativos (728×90, 320×50, 640×320, 300×600, 200×200, contenedor estrecho y área excesivamente pequeña) y revisar el resultado visualmente. Registrar métricas agregadas: número de tarjetas, área ocupada, espacio restante, fallos de entrega, impresiones visibles y clics. Los datos servirán después para ajustar pesos, no para alterar los criterios de elegibilidad.

## 8. Ejemplos orientativos de resultados

| Área disponible | Opciones razonables | Criterio |
|---|---|---|
| 728×90 | Un banner 728×90 | Una pieza ocupa la ranura exacta; no mezclar más tarjetas. |
| 320×50 | Un banner 320×50 | Variante móvil exacta. |
| 640×320 | Dos rectángulos 300×250 en fila con hueco de 12 px, si existen | 612×250 cabe; se compara contra una pieza menor y la política de densidad. |
| 640×320 | Tres cuadrados 200×200 en fila | 624×200 cabe matemáticamente, pero solo se elige si la densidad/variedad compensa frente a dos piezas y la política lo admite. |
| 300×600 | Dos rectángulos 300×250 en columna con hueco de 12 px | 300×512 cabe si la distribución vertical está autorizada. |
| 160×600 | Un creativo vertical que admita ese tamaño | Nunca colocar un 300×250 en una columna de 160 px. |
| 140×180 | Un creativo adaptable que admita el mínimo o fallback propio | Si no existe uno legible, devolver `no_fill` de forma explícita y mantener el fallback del sitio; no forzar una creatividad diminuta. |

Las opciones son ejemplos geométricos, no resultados garantizados. La existencia de anuncios elegibles y la política de la ubicación determinan el resultado efectivo.

## 9. Migración desde el endpoint actual

1. Mantener `POST /api/v1/ads/serve` como contrato de una creatividad mientras se crea el algoritmo nuevo.
2. Refactorizar la elegibilidad actual en funciones reutilizables y sin efectos secundarios.
3. Construir el generador de plantillas, puntuador y asignador como módulos puros, probables sin MySQL ni red.
4. Añadir política de ubicación, registro de composición e idempotencia con migración Alembic.
5. Añadir `preview`; comparar resultados con fixtures y aprobación visual.
6. Añadir `compose` y las entregas múltiples dentro de una transacción.
7. Integrar un componente de OSAP que renderice el plan y confirme cada impresión visible.
8. Activar solo en una ubicación de prueba; mantener el modo fijo y el fallback anterior para rollback.

## 10. Criterios de aceptación

- Una petición fija devuelve exactamente una creatividad o un fallback de una pieza.
- Auto-layout nunca excede área ni máximo de anuncios y respeta huecos, tamaño mínimo y relación de aspecto.
- Con la misma entrada, política, inventario y estado de rotación, preview y entrega real seleccionan la misma composición.
- Un formato fijo no se deforma para caber en un hueco diferente.
- Una composición con N tarjetas genera N tokens, N entregas vinculadas y hasta N impresiones independientes.
- Los reintentos con la misma clave de idempotencia no generan otra composición ni más entregas.
- Cada impresión se cuenta como máximo una vez.
- Si no hay creatividad compatible, el endpoint comunica `no_fill` o devuelve el fallback permitido, sin romper la página.
- El texto de anuncios no puede introducir script/HTML en el sitio anfitrión.
- Las pruebas unitarias cubren geometría y score; las pruebas de API cubren elegibilidad, inventario insuficiente, fallback, idempotencia y seguimiento.

## 11. Alcance que no conviene mezclar con la primera versión

No construir todavía un motor de facturación/pacing avanzado, A/B tests automáticos, plantillas arbitrarias editables en HTML, vídeos, subastas ni perfiles de usuario. Primero validar geometría, targeting, mezcla comercial/propia, seguimiento por tarjeta y estabilidad visual. Cuando existan los modelos de anunciantes, espacios y contratos, el puntuador podrá incorporar presupuesto, objetivos y límites de campaña sin cambiar el contrato básico de composición.
