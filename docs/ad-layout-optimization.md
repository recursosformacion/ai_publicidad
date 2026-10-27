# Composición de anuncios a partir del área disponible

**Estado:** primera implementación disponible en `POST /api/v1/ads/compose`. La prueba visual local está en `/layout-lab`.

## Objetivo

La aplicación llama al servicio y le indica una ubicación y un hueco concreto. `ai_publicidad` escoge una creatividad que quepa o una combinación pequeña de hasta tres, calcula sus posiciones, genera el HTML listo para insertar y registra la impresión de cada anuncio emitido.

No se crean registros independientes de composición: el histórico existente de `ad_deliveries` y `ad_events` registra individualmente cada anuncio. No existe un endpoint de previsualización ni una lista de creatividades descartadas.

## Modos de petición

### Formato fijo

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
  "mode": "fixed_format",
  "format_code": "leaderboard_728x90"
}
```

Se devuelve una sola creatividad compatible con ese formato. Si no hay ninguna elegible, se devuelve un bloque sin anuncios con estado `no-fill`.

### Área automática

```json
{
  "application": "osap",
  "page": {
    "type": "ad_layout_lab",
    "entity_type": "layout_test",
    "entity_id": "test-640x320",
    "language": "es"
  },
  "placement": "layout_lab",
  "device": "desktop",
  "mode": "auto_area",
  "area": { "width": 640, "height": 320 },
  "max_ads": 3,
  "gap": 12,
  "orientation": "auto"
}
```

Dimensiones en píxeles CSS del rectángulo real reservado. Se limita el ancho a 2000 px, el alto a 1200 px, el máximo de anuncios a tres y el hueco entre tarjetas a 32 px. `orientation` admite `auto`, `row` y `column`. No se redimensionan creatividades fijas fuera de las dimensiones definidas en el catálogo.

## Algoritmo de la primera versión

1. Consulta las creatividades aprobadas con campañas activas y fechas válidas.
2. Aplica las reglas de aplicación, página, ubicación, idioma y entidad.
3. Obtiene formatos activos asociados a cada creatividad. Las creatividades flexibles que no tienen formatos asignados pueden probar formatos activos del catálogo.
4. Descarta cada opción que exceda el área de una tarjeta.
5. Genera al vuelo combinaciones de una, dos y tres creatividades distintas, probando fila y/o columna. La búsqueda está acotada a 18 opciones elegibles; no persiste combinaciones.
6. Descarta cualquier distribución cuya suma de anchuras/alturas, incluidos los espacios, exceda el área disponible.
7. Puntúa las alternativas por superficie aprovechada, un pequeño incentivo por utilizar más de una pieza, preferencia por campaña comercial y prioridad, con desempate determinista. La geometría es una restricción dura; una puntuación nunca permite desbordar el espacio.
8. Calcula coordenadas CSS `x/y` por pieza, genera el HTML usando una plantilla fija y devuelve el fragmento.

El algoritmo actual solo implementa distribuciones sencillas en fila o columna. No hace una búsqueda de mosaicos arbitrarios, porque eso aumentaría complejidad y dificultaría explicar y probar sus decisiones. Es una versión inicial para ver resultados y ajustar reglas a partir de ejemplos.

## HTML devuelto

El endpoint devuelve directamente `text/html`, no una cadena HTML arbitraria guardada por un anunciante ni un JSON que cada aplicación deba convertir manualmente en tarjetas. Cada tarjeta lleva:

- dimensiones CSS y coordenadas calculadas;
- identificadores de anuncio, tipo comercial/propio y código de formato en atributos `data-*`;
- título y texto escapados;
- imagen validada, si la creatividad tiene una;
- enlace de seguimiento `/r/{token}` para registrar el clic y redirigir al destino guardado.

La plantilla generada no acepta etiquetas ni scripts de las creatividades. El consumidor puede insertar el fragmento recibido. Si el área no admite ninguna creatividad, se devuelve un contenedor `data-layout-status="no-fill"` que el cliente puede sustituir por su reserva visual.

## Impresiones: contabilización en la emisión del bloque

Para `/ads/compose`, generar el fragmento HTML significa que se ha emitido el bloque. Cada anuncio incluido genera, en la misma transacción:

- una fila en `ad_deliveries`;
- `impression_confirmed = true` y su fecha;
- un `ad_events` de tipo `impression`.

Por tanto, una respuesta con tres tarjetas produce tres entregas y tres impresiones, y no requiere llamar después a `/events/impression`. Si no hay anuncios, no se genera ninguna impresión. El endpoint existente `/ads/serve` conserva su flujo de confirmación independiente; esta regla simplificada pertenece al nuevo endpoint de composición.

No se guarda un objeto compuesto, hash de composición ni combinaciones precomputadas. El histórico de cada creatividad sigue siendo consultable y los registros de laboratorio se identifican por `page_type=ad_layout_lab` y `placement=layout_lab`.

## Laboratorio de prueba visual

Con `ai_publicidad` arrancado en desarrollo, abre:

`http://127.0.0.1:8305/layout-lab`

El laboratorio solicita espacios de distintos tamaños y dibuja el HTML real devuelto dentro de un marco visual. Incluye:

- cabecera escritorio 728×90 (formato fijo);
- cabecera móvil 320×50 (formato fijo);
- contenido ancho 640×320;
- espacio alto 300×600;
- contenido bajo 640×240;
- columna estrecha 160×600;
- espacio demasiado pequeño 140×80;
- un formulario para probar dimensiones personalizadas, zona, dispositivo, número máximo de anuncios, separación y orientación.

Las acciones crean entregas e impresiones reales en la base de datos de desarrollo. La página está deshabilitada si `AI_PUBLICIDAD_ENV=production`; no se debe publicar como una herramienta pública.

Para ver varios formatos en una misma composición, carga el catálogo y la campaña de OMR. El seed `scripts/seed_omr_campaign.py` añade una regla `placement=layout_lab` a cada una de las cuatro creatividades de muestra. Si la campaña ya estaba cargada antes de añadir dicha regla, ejecutar de nuevo el script con `--apply` después de comprobar la base hace la actualización idempotente.

## Pruebas de aceptación

Las pruebas automatizadas comprueban que:

- el formato fijo devuelve una sola pieza y usa el tamaño solicitado;
- un hueco de 640×320 puede elegir dos piezas distintas que caben en fila;
- todas las coordenadas calculadas están dentro del área;
- cada tarjeta incluye una ruta de seguimiento;
- cada anuncio emitido crea una entrega y un evento de impresión, inmediatamente y una sola vez por emisión;
- un hueco sin tamaño compatible devuelve `no-fill` sin crear impresiones;
- el laboratorio se sirve en desarrollo y devuelve 404 en producción.

## Siguiente evolución — solo si la prueba lo justifica

Después de ver los resultados visuales, se decidirá si hacen falta otras distribuciones, reglas por ubicación o una política de mezcla comercial/propia más rica. No se añadirán tablas de composición ni un endpoint de diagnóstico por separado salvo que aparezca una necesidad concreta.