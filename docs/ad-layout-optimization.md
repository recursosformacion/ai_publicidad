# Motor de composición y selección publicitaria

**Estado:** algoritmo inicial implementado en `POST /api/v1/ads/compose`; laboratorio visual local en `/layout-lab`. Esta guía describe el comportamiento real y las reglas que debemos preservar al ampliarlo.

## 1. La idea del motor

`ai_publicidad` no es solo un selector de anuncios. Recibe una ubicación y un rectángulo disponible, filtra los anuncios según sus condiciones comerciales, aplica restricciones temporales y de marcas, decide el tamaño más adecuado, organiza una o varias piezas de ese mismo tamaño y devuelve el HTML listo para insertar.

El servicio no necesita guardar una tabla de todas las posibles composiciones. Las combinaciones se calculan para cada petición y el histórico conserva una fila por anuncio entregado.

## 2. Orden obligatorio de las decisiones

### Fase A — formar el conjunto de anuncios comercialmente elegibles

Antes de calcular geometría, se seleccionan las creatividades que pueden servirse en el contexto solicitado. La composición **nunca** convierte en elegible una campaña que no cumpla estas condiciones:

1. Campaña activa y dentro de sus fechas de inicio y fin.
2. Creatividad aprobada.
3. Marca asignada activa, cuando la campaña tiene una marca registrada.
4. Reglas de segmentación compatibles: aplicación, tipo de página, ubicación, idioma y entidad; las exclusiones prevalecen.
5. Idioma compatible con la página.
6. Destino e imagen con URL válida.
7. Formato estándar activo y disponible para el dispositivo, con medidas que caben en el área.
8. Restricciones temporales de repetición satisfechas.

Las campañas sin marca pueden seguir funcionando mientras se migra el inventario al registro de marcas. Las campañas asociadas a marcas inactivas no son elegibles.

**Política comercial frente a anuncios propios:** primero se trabaja exclusivamente con las creatividades comerciales elegibles. Los anuncios propios de OSAP se usan como reserva solo cuando no queda ninguna creatividad comercial elegible para ese espacio después de aplicar ubicación, dimensiones, estado, fechas, idioma, marca y cooldown. No se mezclan anuncios propios y comerciales en el mismo bloque de esta primera versión.

El campo `priority` ordena las campañas dentro del tamaño seleccionado. Las condiciones de elegibilidad son previas a la prioridad: una campaña más prioritaria no puede saltarse fechas, segmentación, marca inactiva ni cooldown.

### Fase B — aplicar restricciones temporales

Cada campaña puede definir `minimum_interval_seconds`. Si vale cero, no impone intervalo adicional. Si es mayor que cero, se omite la campaña cuando ya se entregó en el último intervalo dentro del mismo contexto:

- aplicación;
- tipo de página;
- entidad (tipo e ID);
- ubicación física (`placement`).

Esto permite no repetir continuamente una creatividad para el mismo hueco de una ficha o pantalla, manteniendo la selección independiente entre ubicaciones o entidades distintas. Se consulta `ad_deliveries`, por lo que no requiere una tabla nueva de composición.

**No es un límite por persona:** actualmente no identificamos visitantes ni guardamos un identificador persistente de usuario. El intervalo es por contexto de página/entidad/ubicación, no una garantía de frecuencia por usuario. Para implementar límites por visitante en el futuro haría falta definir un identificador de ranura/sesión respetuoso con la privacidad.

Las fechas de campaña (`starts_at` y `ends_at`) y este intervalo son reglas distintas: las primeras definen cuándo está autorizada la campaña; el segundo regula cuándo puede repetirse en el mismo contexto.

### Fase C — elegir el tamaño, siempre homogéneo

**Una composición nunca mezcla tamaños distintos.** Cada tarjeta del mismo bloque usa exactamente el mismo ancho y alto de catálogo. No se pone un rectángulo de 300×250 al lado de un cuadrado de 200×200 ni se estira uno para aparentar el otro.

El servicio:

1. Calcula qué tamaños estándar activos caben en el área real.
2. Ordena los tamaños por superficie descendente.
3. Prueba primero el tamaño mayor que tenga anuncios elegibles y una distribución que quepa.
4. Si existen varias creatividades compatibles con ese tamaño, intenta colocar el máximo posible de hasta tres.
5. Si los anuncios disponibles de ese tamaño chocan por marca/campaña o no caben en cantidad, reduce la cantidad de tarjetas; no añade una tarjeta de otra medida.
6. Solo baja al tamaño siguiente cuando no existe ninguna composición válida del tamaño anterior.

Así se prioriza una pieza grande y se reduce progresivamente el tamaño, en lugar de maximizar superficie mezclando formatos. La prioridad de campaña desempata entre anuncios del tamaño elegido; no hace que se incluya una campaña que ha fallado los filtros comerciales.

### Fase D — calcular la disposición

La primera versión admite distribuciones sencillas en fila (`row`) o columna (`column`) y un máximo de tres anuncios. El cliente puede indicar la orientación o pedir al servicio que la decida.

Para tamaño `w × h`, separación `g` y cantidad `n`:

- fila: ancho total `n × w + (n − 1) × g`, alto `h`;
- columna: ancho `w`, alto total `n × h + (n − 1) × g`.

Una distribución que rebase el área se descarta. Las posiciones se calculan en píxeles CSS y el HTML contiene tanto las dimensiones como las coordenadas. No hay escalado arbitrario de formatos fijos.

## 3. Marcas y competencia

Las marcas se registran y mantienen desde el menú web **Marcas y competencia** del panel `/admin`, y a través del CRUD `/api/v1/admin/brands`.

Modelo:

- `brands`: nombre, web, notas internas y estado activo/inactivo.
- `brand_competitors`: relación simétrica entre dos marcas que compiten entre sí.
- `campaigns.brand_id`: marca a la que pertenece la campaña.
- `campaigns.minimum_interval_seconds`: intervalo mínimo antes de repetir esa campaña en el mismo contexto.

Al guardar una marca se pueden declarar sus competidores. La relación es simétrica: si A declara competencia con B, B también aparece como competidora de A. No se permite una marca como competidora de sí misma.

Al construir una composición se aplican estas reglas:

1. No aparece dos veces una misma marca en el mismo bloque.
2. Dos marcas declaradas competidoras nunca aparecen juntas en el bloque.
3. Tampoco se repite una misma campaña en la composición.
4. Se eligen primero combinaciones de mayor número de tarjetas que respeten las incompatibilidades.
5. Si la combinación más grande contiene marcas incompatibles, se reduce la cantidad de anuncios de ese mismo tamaño antes de considerar un tamaño menor.

Una marca se desactiva, en lugar de borrarse, si tiene campañas asociadas. Las campañas vinculadas a una marca inactiva dejan de ser elegibles. El histórico de entregas no se modifica.

Las campañas propias de OpenMusicRepository se etiquetan con la marca `OpenMusicRepository`. Las campañas sin marca son válidas por compatibilidad, pero conviene asignar una marca a los anunciantes comerciales para que la prevención de competencia funcione.

## 4. Peticiones

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

Este modo devuelve como máximo una creatividad del formato concreto. Si no hay una elegible, devuelve HTML `no-fill`. La petición puede incluir `creative_id` para solicitar una creatividad determinada; ese ID no anula las restricciones de campaña, fecha, ubicación, marca, cooldown ni formato. Si la creatividad no cumple las reglas, el resultado será `no-fill`.

### Área automática

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
  "mode": "auto_area",
  "area": { "width": 640, "height": 320 },
  "max_ads": 3,
  "gap": 12,
  "orientation": "auto"
}
```

Las medidas son píxeles CSS del contenedor que ya existe en la página; no se deducen a partir de toda la pantalla. Límites de la petición: ancho hasta 2000 px, alto hasta 1200 px, 1–3 anuncios y separación de 0–32 px. `creative_id` es opcional para limitar la petición a una creatividad; en ese caso se devuelve como máximo una pieza.

## 5. HTML directo y registro de vistas

`POST /api/v1/ads/compose` responde con `Content-Type: text/html`. El HTML se genera mediante una plantilla controlada, no a partir de fragmentos HTML arbitrarios del anunciante. Los títulos, textos, URLs y atributos se escapan o validan; no se admiten scripts suministrados por las creatividades.

Cada tarjeta incluye:

- ancho, alto y coordenadas calculadas;
- identificador de la creatividad, tipo comercial/propio y código de formato en atributos `data-*`;
- título y texto escapados;
- imagen y texto alternativo, cuando la creatividad tiene imagen;
- enlace de seguimiento `/r/{token}` para registrar el clic y redirigir al destino configurado.

Si no existe una composición válida, devuelve un bloque `data-layout-status="no-fill"`. El consumidor puede sustituirlo por su propio anuncio de reserva.

**Regla de impresión del modo compose:** la emisión del fragmento cuenta como vista. Dentro de la misma transacción se crea, por cada tarjeta del HTML, una fila en `ad_deliveries` con `impression_confirmed=true` y un evento `impression` en `ad_events`. Si se devuelven tres anuncios, se registran tres entregas y tres impresiones; si se devuelve `no-fill`, no se registran. No hay endpoint posterior de impresión ni tabla de composiciones. El endpoint legado `/ads/serve` conserva su flujo separado.

La métrica representa **el bloque emitido**, no una medición de visibilidad real del navegador. Es la decisión deliberada para mantener una integración sencilla sin llamadas adicionales de impresión.

## 6. Laboratorio visual

En desarrollo local, abre `http://127.0.0.1:8305/layout-lab`. Permite probar cabeceras, áreas anchas, espacios altos, columnas estrechas y medidas personalizadas. La página muestra el HTML real devuelto por `/compose`.

El laboratorio registra entregas e impresiones reales. Debe usarse contra SQLite aislado, nunca contra una base compartida que contenga métricas reales. Está deshabilitado en producción; su uso con MySQL requiere habilitación explícita mediante `AI_PUBLICIDAD_ENABLE_LAYOUT_LAB=true`.

En PowerShell:

```powershell
cd D:\Proyectos\AI_OSAP\ai_publicidad
git pull origin main
$env:AI_PUBLICIDAD_ENV = "development"
$env:AI_PUBLICIDAD_DATABASE_URL = "sqlite:///./ai_publicidad_layout_lab.sqlite3"
$env:AI_PUBLICIDAD_SERVICE_TOKEN = ""
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python scripts/seed_omr_campaign.py --apply --allow-sqlite
python -m uvicorn api.main:app --host 127.0.0.1 --port 8305
```

Después abre `http://127.0.0.1:8305/layout-lab`. El seed es idempotente. Las solicitudes del laboratorio usan la página `ad_layout_lab` y la ubicación `layout_lab`.

## 7. Límites de negocio aún pendientes

Esta versión ya aplica estado, fechas, prioridades, reglas de ubicación/segmentación, marca activa, incompatibilidad entre marcas e intervalo de repetición. Todavía no se han construido:

- presupuestos monetarios, contratos y pedidos;
- límites máximos de impresiones/clics por día o campaña;
- frecuencia por visitante;
- pacing o reparto automático de un presupuesto a lo largo de una campaña;
- un registro histórico de razones de selección.

No se debe simular que esas restricciones existen. Antes de añadirlas, se definirán sus campos comerciales en el modelo y se aplicarán al filtro de elegibilidad **antes** de entrar al algoritmo geométrico.

## 8. Pruebas de aceptación

La suite verifica que:

- la composición nunca excede el área;
- todas las tarjetas de un bloque tienen el mismo ancho y alto;
- se elige primero el tamaño mayor disponible que encaja;
- no se repite una creatividad, campaña o marca en el mismo bloque;
- marcas competidoras nunca aparecen juntas y la relación se consulta simétricamente;
- una campaña dentro del intervalo se omite en ese mismo contexto y se puede recurrir a anuncios propios;
- el formato fijo devuelve una única creatividad;
- cada tarjeta emitida crea una entrega y una impresión, y `no-fill` no las crea;
- el laboratorio es accesible en desarrollo pero no en producción.

La integración con OSAP debe mantener separado el nombre de página del código de ubicación física. El servidor de OSAP solicita el área real, y `ai_publicidad` decide exclusivamente entre las opciones comercialmente elegibles y devuelve el bloque HTML listo para insertar.
