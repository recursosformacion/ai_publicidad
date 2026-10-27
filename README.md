# ai_publicidad

Servicio independiente de publicidad directa para OSAP/OpenMusicRepository. El núcleo actual gestiona campañas, creatividades, segmentación, entrega de anuncios, impresiones, clics y redirecciones. El modelo de clientes/anunciantes, contratos y espacios configurables todavía está pendiente; la primera pantalla web de mantenimiento ya está disponible en `/admin`.

El proyecto es un servicio independiente **Python 3.11+ + FastAPI**, alineado con `AI_osap-auth`, `AI_osap-storage` y `AI_osap-support`. Ya existe un primer núcleo funcional; el contrato de integración con `osap-app` sigue pendiente de validar con el código real del frontend.

## Integración con OSAP

La guía de implementación se mantiene en el repositorio OSAP, tras revisar el frontend y su API actuales: [`docs/ads-integration.md` de AI_GAMEPC2](https://github.com/recursosformacion/AI_GAMEPC2/blob/main/docs/ads-integration.md).

El motor de composición ya está implementado en [`docs/ad-layout-optimization.md`](docs/ad-layout-optimization.md): filtra primero las campañas comercialmente elegibles, aplica marcas y restricciones temporales y después busca el tamaño más grande que encaje. Una composición solo usa anuncios del mismo tamaño y devuelve el HTML listo para insertar. El laboratorio visual permite comprobarlo sin escribir en la base de datos real.

Importante: la SPA actual todavía usa `SponsorSlot` y `sponsors.json`; la integración requiere una fachada servidor-a-servidor en `osap-api`. No envíes `AI_PUBLICIDAD_SERVICE_TOKEN` al navegador ni publiques el panel `/admin` del servicio publicitario antes de añadir autorización.

## 1. Objetivos y principios

- OSAP solicita un anuncio a `ai_publicidad` según el contexto de la página y el espacio disponible.
- `ai_publicidad` decide qué anuncio compatible devuelve; OSAP no necesita conocer clientes, contratos ni destinos finales.
- Si no hay publicidad comercial válida, se devuelve un **anuncio propio de OSAP**. El espacio nunca queda vacío por falta de campañas.
- Los clics pasan por `ai_publicidad`, que registra el evento y redirige al destino configurado en el servidor.
- En el endpoint JSON legado `/ads/serve` la impresión conserva confirmación separada; en `/ads/compose`, la emisión del HTML registra una impresión por cada anuncio incluido, de acuerdo con el contrato simplificado elegido.
- El servicio debe poder admitir otras aplicaciones en el futuro, aunque la primera integración sea `osap-app`.
- El código no contiene credenciales ni secretos. La configuración se obtiene del entorno o de un archivo local ignorado por Git.
- MySQL es la base de datos de producción. SQLite se utilizará para desarrollo y pruebas automatizadas.
- **Stack decidido:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic y MySQL/MariaDB en producción; SQLite para pruebas. Se reutilizarán las convenciones de configuración y autenticación de servicios OSAP, sin copiar secretos ni acoplar el servicio a la base de datos del catálogo.

## 2. Arquitectura lógica

1. **Aplicación cliente (`osap-app`)**: identifica la página y la ubicación física, reserva un área con medidas CSS y solicita el bloque. Puede elegir un formato fijo o dejar que el servicio componga el área. Con `/ads/compose` no tiene que construir cada tarjeta ni confirmar impresiones por separado.
2. **API de `ai_publicidad`**: valida la petición, selecciona anuncios elegibles de acuerdo con campañas, ubicación, fechas, segmentación, marcas y restricciones temporales, y devuelve HTML calculado.
3. **Motor de composición**: usa anuncios de un mismo tamaño por bloque, prueba el mayor tamaño disponible antes de bajar a formatos menores, calcula posiciones y no repite marcas ni incluye parejas competidoras.
4. **Seguimiento**: el modo `/ads/compose` registra una entrega e impresión por tarjeta emitida; los clics pasan por `/r/{token}` y el destino se obtiene del registro almacenado.
5. **Administración e informes**: permite mantener campañas, marcas y competidores, creatividades, formatos y reglas, y consultar el histórico.

## 3. Tipología de páginas de OSAP

La tipología se debe acordar con `osap-app` y utilizar identificadores estables, no nombres traducidos ni URL completas. Las rutas de OSAP pueden cambiar sin invalidar las reglas de campañas.

Catálogo inicial propuesto (ampliable y versionado):

| Código | Tipo de página | Ejemplo de uso |
|---|---|---|
| `home` | Portada | Página principal de OSAP |
| `search_results` | Resultados de búsqueda | Búsqueda de obras, personas u otros recursos |
| `work_detail` | Ficha de obra | Información y recursos de una obra musical |
| `person_detail` | Ficha de persona | Compositor, arreglista, autor, intérprete, etc. |
| `catalog_detail` | Ficha de catálogo | Catálogo o colección |
| `classification` | Clasificación | Épocas, géneros, instrumentos o conjuntos |
| `instrument_detail` | Ficha de instrumento | Información de un instrumento |
| `ensemble_detail` | Ficha de conjunto | Conjunto vocal o instrumental |
| `representation_detail` | Ficha de representación | Partitura, audio u otra representación de una obra |
| `viewer` | Visor musical | Visor de partitura o recurso compatible |
| `source_detail` | Ficha de fuente | Fuente externa o proveedor de recursos |
| `amigos_index` | Índice de Los Amigos | Comunidad coral, artículos y actuaciones |
| `amigos_group` | Grupo de Los Amigos | Ficha pública de una agrupación |
| `amigos_article` | Artículo | Artículo o publicación comunitaria |
| `amigos_event` | Actuación/evento | Información de una actuación |
| `static_page` | Página informativa | Manual, ayuda o página estática |
| `other` | Otra página | Solo para casos excepcionales; registrar el contexto |

Cada solicitud podrá incluir, cuando proceda, `entity_type` y `entity_id` (por ejemplo, obra concreta o persona concreta). No se debe usar la URL como único identificador de página.

**Estado de validación:** la documentación accesible de `AI_GAMEPC2` describe el contrato del frontend como pendiente y no permite confirmar todas las rutas públicas actuales de `osap-app`. Por tanto, esta lista sigue siendo una propuesta de integración, no una afirmación de que cada página exista. Antes de conectar anuncios se deberá contrastar con el código real del frontend y mantener los códigos estables en ambos proyectos.

## 4. Espacios publicitarios y formatos

Un espacio (`placement`) define dónde puede mostrarse un anuncio y qué dimensiones admite. Ejemplos de códigos:

- `header`: cabecera.
- `sidebar`: columna lateral.
- `content_top`: comienzo del contenido.
- `content_inline`: dentro del contenido o entre resultados.
- `content_bottom`: final del contenido.
- `footer`: pie de página.

Formatos iniciales:

- `image`: imagen con texto alternativo obligatorio.
- `text`: título, texto y enlace.
- `image_text`: imagen, título y texto.
- `responsive`: creatividad adaptable a tamaños previamente autorizados.

Los tamaños se catalogan en `ad_formats`, separados del tipo de creatividad. El catálogo inicial contiene `728×90` (banner de escritorio), `320×50` (banner móvil), `300×250` (rectángulo), `160×600` (vertical) y `200×200` (cuadrado compacto solicitado para el diseño OSAP). Las notas del catálogo explican el efecto estructural de cada medida: el rectángulo de 300×250 puede centrarse, pero una columna lateral estrecha puede requerir ampliación; el vertical de 160×600 necesita al menos ese ancho y no implica que ya exista reproducción de vídeo.

Un anuncio puede asociarse a varios formatos estándar. El banner institucional de OpenMusicRepository se asocia a los dos tamaños de cabecera: escritorio y móvil. Cuando se solicitan dimensiones, la entrega prioriza un anuncio asignado exactamente a ese tamaño y dispositivo; si no lo hay, puede usar una creatividad genérica compatible como reserva, pero no un anuncio fijo de dimensiones distintas. Los clientes deben enviar `width` y `height` juntos; sin dimensiones, solo se entregan creatividades genéricas no asociadas a tamaños fijos.

## 5. Composición automática del espacio

Además de `POST /api/v1/ads/serve` (una creatividad en JSON), el servicio ofrece `POST /api/v1/ads/compose`, que devuelve un fragmento **HTML listo para insertar**. La petición puede fijar un formato del catálogo o especificar el área disponible, la ubicación, el dispositivo, el número máximo de anuncios (1–3), la separación y la orientación. El algoritmo actual evalúa composiciones sencillas en fila o columna, comprueba que cada tarjeta cabe y no repite una creatividad en el mismo bloque.

Ejemplo de petición automática:

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

La respuesta es HTML con coordenadas por tarjeta, medidas, formato y enlaces `/r/{token}`. El servicio escapa los campos de texto y genera las tarjetas desde una plantilla controlada; no acepta HTML suministrado por las creatividades. No se persiste una composición independiente: solo se almacenan las entregas individuales.

**Contabilización de vistas:** en `/ads/compose`, generar la respuesta HTML registra una entrega y una impresión inmediata por cada anuncio incluido. Así el consumidor no necesita una segunda petición por anuncio. Es una decisión deliberada del contrato simplificado: la métrica representa el bloque emitido, no una comprobación posterior de visibilidad en el viewport. El endpoint antiguo `/ads/serve` conserva su flujo separado de confirmación de impresión.

### Laboratorio visual local

Para una prueba aislada en Windows/PowerShell, crea una base SQLite propia para el laboratorio (no apunta a `OSAP_PUBLICIDAD`):

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

Con ese servicio arrancado, abre **http://127.0.0.1:8305/layout-lab**. El laboratorio solicita espacios predefinidos (728×90, 320×50, 640×320, 300×600, 640×240, 160×600 y 140×80), muestra el HTML real devuelto y permite enviar medidas personalizadas. El script de carga crea los formatos y los anuncios de muestra, incluidos los permisos de ubicación `layout_lab`. Esta secuencia crea una base de pruebas aparte y no escribe en `OSAP_PUBLICIDAD`.

Las solicitudes del laboratorio usan `page.type=ad_layout_lab`; las muestras de la campaña deben tener la regla de ubicación `layout_lab`. Para añadir esa regla a las creatividades iniciales, vuelve a ejecutar de forma idempotente `python scripts/seed_omr_campaign.py --apply` después de revisar la conexión.

**El laboratorio crea impresiones reales en la base de datos seleccionada.** Está deshabilitado en `AI_PUBLICIDAD_ENV=production`. En SQLite local se permite en desarrollo; si la aplicación usa MySQL, también requiere `AI_PUBLICIDAD_ENABLE_LAYOUT_LAB=true` como habilitación explícita. Recomendación: usar la base SQLite local y no un esquema compartido de producción. No registra composiciones separadas ni ofrece un endpoint de previsualización sin efectos secundarios.

## 5. Selección de anuncios

La petición podrá incluir:

- `application`: aplicación cliente, inicialmente `osap`.
- `page.type`: código de tipología de página.
- `page.entity_type` y `page.entity_id`: entidad concreta, si procede.
- `placement`: espacio solicitado.
- `format`: tipo y dimensiones disponibles.
- `language`: idioma de la página.
- `device`: dispositivo.
- `context`: categorías temáticas opcionales.

Se seleccionarán anuncios cuya campaña esté activa y dentro de sus fechas, cuyo material esté aprobado y que coincidan con aplicación, página, ubicación, formato e idioma configurados. Las campañas podrán incluir o excluir tipos de página y entidades concretas.

Cuando haya varias coincidencias, el orden de decisión será explícito: compromisos de ubicación exclusiva o prioridad contratada, límites de campaña, prioridad administrativa y rotación entre anuncios equivalentes. No se prometerá una ubicación exclusiva si no se ha contratado y configurado como tal.

### Anuncios propios (reserva obligatoria)

La base de datos tendrá anuncios propios de OSAP, identificados como tales y gestionados desde la misma administración. Se prepararán varias creatividades propias por formato/idioma/ubicación: por ejemplo, invitación a explorar el catálogo, descubrir recursos musicales o conocer la comunidad Los Amigos.

Reglas:

1. Primero se busca un anuncio comercial válido para la petición.
2. Si no existe una coincidencia comercial válida, se busca un anuncio propio compatible.
3. Si no hay uno específico, se utiliza un anuncio propio genérico compatible con ese formato.
4. Solo si hay un fallo técnico que impide consultar el servicio se aplica el fallback local que se defina en `osap-app`; el servicio debe permitir que el cliente no deje un hueco visual.

Los anuncios propios se registran y contabilizan igual que los demás, pero con `is_house_ad = true` o una clasificación equivalente. Sus impresiones y clics deben poder separarse de las métricas comerciales y no generar importes facturables.

## 6. Clientes, campañas y creatividades

Entidades de datos previstas:

- **Advertisers / clientes**: datos comerciales, contacto, estado y datos fiscales necesarios.
- **Campaigns / campañas**: cliente, nombre, fechas, estado, prioridad, objetivo, límites y condiciones comerciales.
- **Creatives / anuncios**: campaña (nullable solo para anuncios propios, según el modelo final), título, texto, recurso visual, formato, idioma, texto alternativo, destino y estado de aprobación.
- **Placements / espacios**: aplicación, código de ubicación, formatos y dimensiones admitidas.
- **Targeting / segmentación**: reglas para tipos de página, entidades concretas, ubicaciones, idiomas, dispositivos y categorías; reglas de inclusión y exclusión.
- **Orders/contracts / pedidos o contratos**: condiciones contratadas, periodo, importe, modelo comercial y referencia documental.
- **Ad events / eventos**: impresiones, clics y otros eventos de seguimiento.
- **Applications / aplicaciones cliente**: aplicaciones autorizadas, credenciales o claves rotables, estado y permisos.
- **Audit log / auditoría**: cambios administrativos relevantes.

La factura fiscal y la contabilidad deben diseñarse según los requisitos aplicables; no se considerarán resueltas simplemente por guardar un importe en la campaña.

## 7. Contrato inicial de API

Las rutas son el contrato inicial previsto para FastAPI; se validarán mediante pruebas antes de integrarlas en `osap-app`.

### Solicitar un anuncio

`POST /api/v1/ads/serve`

Ejemplo de petición:

```json
{
  "application": "osap",
  "page": {
    "type": "work_detail",
    "entity_type": "work",
    "entity_id": "12345",
    "language": "ca"
  },
  "placement": "sidebar",
  "format": {
    "type": "image_text",
    "width": 300,
    "height": 250
  },
  "device": "desktop",
  "context": ["choral_music"]
}
```

La respuesta satisfactoria incluirá, como mínimo:

- `ad_id` y un `impression_id` opaco y único.
- `kind`: `commercial` o `house`.
- Tipo de creatividad, título/texto y datos del recurso visual.
- `ad_format_code`, `ad_format_name`, `ad_width` y `ad_height` del tamaño seleccionado, si la solicitud especificó dimensiones.
- Texto alternativo y etiqueta de publicidad cuando corresponda.
- `click_url` alojada en `ai_publicidad`, no la URL final expuesta directamente.
- Caducidad o versión de la entrega si resulta necesaria.

Si no existe anuncio comercial, la API devuelve el anuncio propio compatible. La falta de inventario comercial no es un error HTTP.

### Confirmar una impresión

`POST /api/v1/events/impression`

Recibe el `impression_id` y la información mínima necesaria para confirmar que se mostró. El endpoint debe ser idempotente: repetir la misma confirmación no aumenta el contador más de una vez.

### Registrar el clic y redirigir

`GET /r/{token}`

El token identifica una entrega válida. El servidor registra el clic y obtiene la URL final del registro autorizado; después responde con una redirección HTTP. No aceptará una URL arbitraria proporcionada por el navegador. Deben limitarse los destinos a protocolos permitidos (normalmente HTTPS y, cuando sea necesario, HTTP) y bloquear esquemas peligrosos.

### Salud y configuración

- `GET /health`: estado básico del servicio, sin revelar credenciales.
- `GET /api/v1/metadata/page-types`: opcionalmente, catálogo versionado de tipos de página.
- Administración: rutas separadas. La autorización de usuarios se implementará en una fase posterior; mientras tanto, no expongas públicamente la pantalla ni los endpoints de administración.

### API de administración implementada

Las rutas CRUD están disponibles bajo `/api/v1/admin`. La pantalla web está en `/admin` y utiliza estas rutas en el mismo origen. La autenticación y autorización de administradores se aplaza expresamente a una fase posterior; hasta implementarla, ejecuta el panel solo en entorno local o en una red interna de confianza y no lo publiques directamente en Internet.

- **Campañas:** `GET/POST /campaigns`, `GET/PUT/DELETE /campaigns/{id}`.
- **Creatividades:** `GET/POST /creatives`, `GET/PUT/DELETE /creatives/{id}`.
- **Segmentación:** `GET/POST /targeting-rules`, `GET/PUT/DELETE /targeting-rules/{id}`.
- **Marcas y competencia:** `GET/POST /brands`, `GET/PUT/DELETE /brands/{id}`; las relaciones competidoras son simétricas.
- **Formatos estándar:** `GET/POST /ad-formats`, `GET/PUT/DELETE /ad-formats/{id}`; se catalogan dimensiones, dispositivo, categoría y notas de adaptación.
- **Histórico de entregas:** `GET /deliveries` y `GET /deliveries/{id}`, con filtros por campaña o creatividad.
- **Histórico de eventos:** `GET /events` y `GET /events/{id}`, con filtros por tipo de evento y entrega.

Las tablas de configuración tienen CRUD. `ad_deliveries` y `ad_events` son datos operativos e históricos: se consultan, pero no se editan ni borran desde la administración para no falsear métricas ni romper relaciones. Al borrar una creatividad con entregas, se archiva (`status = archived`) y deja de participar en futuras entregas, conservando sus relaciones históricas. Si se borra una campaña con entregas, se archiva también la campaña y todas sus creatividades. Si la campaña no tiene entregas, se elimina físicamente junto con sus creatividades y reglas de segmentación. Los registros archivados se ocultan de los listados normales; el control **Mostrar archivados** permite consultarlos y, si procede, reactivarlos. Las reglas admiten `application`, `page_type`, `placement`, `language`, `entity_type` y `entity_id`, con efecto `include` o `exclude`.

En el panel `/admin`, cada listado muestra los campos principales y ofrece **Ver**. La acción **Ver** abre la misma pantalla de formulario que **Editar**, pero con todos los campos deshabilitados y sin opción de guardar; en las entregas y eventos se utiliza ese mismo formato de solo lectura. En campañas, creatividades, reglas y formatos están **Editar** y **Borrar**, además de **Nuevo**. La creatividad permite asignarle varios formatos estándar desde un selector múltiple. El filtro busca en el listado actual; **Mostrar archivados** recupera la configuración archivada y **Mostrar inactivos** los formatos desactivados.

## 8. Modelo de datos inicial

**Tablas que existen en el esquema funcional actual:**

1. `campaigns`: estado, fechas, prioridad, marca asignada e intervalo mínimo de repetición.
2. `brands`: marcas de anunciantes, web, notas y estado activo/inactivo.
3. `brand_competitors`: relación simétrica entre marcas que no deben aparecer juntas en la misma composición.
4. `creatives`: título, contenido, tipo de creatividad, idioma, destino y estado de aprobación.
5. `ad_formats`: catálogo normalizado de tamaños, dispositivo, categoría y notas de integración.
6. `creative_ad_formats`: relación muchos-a-muchos; un anuncio puede admitir varios tamaños, como el banner de escritorio y su variante móvil.
7. `targeting_rules`: reglas de inclusión/exclusión por aplicación, página, ubicación, idioma y entidad.
8. `ad_deliveries`: entrega, token de impresión, formato elegido y confirmación de impresión.
9. `ad_events`: impresiones y clics registrados.

Las migraciones `0002_ad_format_catalog` y `0003_brands_and_cooldown` añaden el catálogo de formatos, las relaciones de marcas y las reglas de intervalo temporal. Las dimensiones se guardan como enteros de píxeles; no se codifican dentro del texto del anuncio. No se guardan combinaciones publicitarias ni una tabla de composición: cada entrega se registra individualmente.

**Entidades comerciales aún pendientes:** anunciantes/contactos más completos, contratos/pedidos, presupuestos y límites máximos de impresiones o clics, límites diarios, pacing e identificadores para frecuencia por visitante. No deben darse por implementados.

## 9. Base de datos y configuración

- **Base de datos propia:** `OSAP_PUBLICIDAD`. `ai_publicidad` es una aplicación independiente y no utiliza la base operativa `osap-api`.
- **Configuración propia:** el repositorio incluye `osap.toml.example`. En el directorio raíz, crea tu configuración privada:
  ```powershell
  Copy-Item .\\osap.toml.example .\\osap.toml
  notepad .\\osap.toml
  ```
  Copia desde el `osap-api\\osap.toml` existente únicamente los parámetros de conexión que vayas a reutilizar: `host`, `port`, `user` y `password`. En el fichero de `ai_publicidad`, configura `name = "OSAP_PUBLICIDAD"`. No copies el nombre de base `osap-api`. El fichero real `osap.toml` está excluido de Git.
- El servicio lee primero una URL explícita `AI_PUBLICIDAD_DATABASE_URL`; si está vacía, utiliza el `osap.toml` propio del directorio actual o la ruta privada indicada por `AI_PUBLICIDAD_OSAP_CONFIG` (también admite `OSAP_CONFIG`). Ya no busca ni toma automáticamente la configuración del directorio hermano `osap-api`.
- **Permisos MySQL:** copiar usuario y contraseña no concede acceso a una base nueva. Si la cuenta copiada no tiene permisos sobre `OSAP_PUBLICIDAD.*`, un administrador tendrá que conceder los permisos mínimos o configurar una cuenta específica. La aplicación no cambia permisos ni usuarios.
- La base vacía ya existente no necesita crearse de nuevo. Si aún se necesitara crear en otro entorno, `python scripts/create_database.py --apply` crea solo la base vacía, usando esta configuración propia; no crea tablas, usuarios ni permisos.
- **Inicialización del esquema:** con `OSAP_PUBLICIDAD` creada y con permisos concedidos, ejecuta en PowerShell desde `D:\\Proyectos\\AI_OSAP\\ai_publicidad`:
  ```powershell
  Remove-Item Env:AI_PUBLICIDAD_OSAP_CONFIG -ErrorAction SilentlyContinue
  Remove-Item Env:OSAP_CONFIG -ErrorAction SilentlyContinue
  $env:AI_PUBLICIDAD_DATABASE_URL = ""
  python -c "from infrastructure.config import get_settings; from sqlalchemy.engine import make_url; u=make_url(get_settings().database_url); print(f'Destino: {u.host}:{u.port}/{u.database}; usuario={u.username}')"
  python -m alembic upgrade head
  ```
  Antes de la última orden, comprueba que el destino mostrado es exactamente `OSAP_PUBLICIDAD`. La migración bloquea conexiones MySQL a cualquier otra base.
- En desarrollo, `.env.example` mantiene SQLite como opción segura predeterminada. La API no crea tablas automáticamente sobre MySQL; el esquema se gestiona mediante Alembic.
- Producción requiere `AI_PUBLICIDAD_SERVICE_TOKEN` para las operaciones de entrega, `AI_PUBLICIDAD_PUBLIC_BASE_URL` con HTTPS y una conexión que termine en `OSAP_PUBLICIDAD`. Antes de exponer los endpoints administrativos en producción hay que implementar autenticación y autorización.

### Campaña inicial de OpenMusicRepository

`scripts/seed_omr_campaign.py` prepara de forma idempotente cinco entradas de catálogo y la campaña propia **OpenMusicRepository — campaña de difusión** con cuatro creatividades:

1. **Fondo OSAP adaptable**: admite 728×90 en escritorio y 320×50 en móvil.
2. **Rectángulo destacado**: 300×250, orientado a un bloque centrado.
3. **Formato vertical**: 160×600, asociado a la zona vertical/audiovisual.
4. **Cuadrado compacto**: 200×200, alternativa que requiere menos adaptación de columna.

Cada creatividad tiene texto promocional en español, destino `https://openmusicrepository.com/` y reglas por aplicación `osap` y ubicación (`header`, `content_top`, `sidebar` o `content_inline`). Se trata de creatividades de texto adaptable; no se ha inventado una imagen ni un vídeo. El formato 160×600 cataloga el tamaño del espacio, pero necesitará un recurso audiovisual y un reproductor antes de funcionar como vídeo real.

La carga se prepara y revisa primero con `python scripts/seed_omr_campaign.py`; solo escribe al ejecutar `python scripts/seed_omr_campaign.py --apply` (o `--apply --allow-sqlite` para SQLite local). No se ha aplicado automáticamente a `OSAP_PUBLICIDAD`.

## 10. Prueba HTTP real de entrega y fallback

Los tests automáticos usan una base SQLite en memoria y ejercitan las rutas HTTP de FastAPI; **no utilizan ni vacían `OSAP_PUBLICIDAD`**. Para comprobar también el servicio arrancado y la base configurada en tu máquina, se incluye un smoke test explícito.

Con el servicio iniciado y su configuración comprobada, ejecuta primero una simulación (solo consulta `/health`):

```powershell
python scripts/smoke_test_delivery.py
```

Después, para crear datos de prueba mediante el CRUD, solicitar un anuncio comercial, pausar esa campaña por API y verificar que la siguiente solicitud devuelve una creatividad propia de OSAP:

```powershell
python scripts/smoke_test_delivery.py --apply
```

Si trabajas desde cero, instala también las dependencias de desarrollo (`python -m pip install -e ".[dev]"`) para disponer de `httpx`. El proceso requiere que exista al menos una campaña propia activa con una creatividad aprobada compatible con el formato `text` y el idioma solicitado. La campaña temporal queda limitada mediante una regla a un identificador de aplicación único generado para la prueba, por lo que esa creatividad no es elegible para peticiones normales de `application=osap`. La campaña de prueba termina pausada y sus entregas permanecen en el histórico deliberadamente; no se borran registros históricos. Revisa el host/base de datos del servicio antes de usar `--apply`.

## 11. Seguridad, privacidad y fiabilidad

- Autenticación entre `osap-app` y el servicio mediante credencial específica de aplicación, rotación y límites de uso; nunca usar una clave administrativa en el navegador.
- Validación de todos los parámetros y de los recursos publicitarios antes de publicarlos.
- Las URL de destino se administran en el servidor y no se aceptan como parámetro de redirección abierto.
- Registro idempotente de impresiones y protección básica frente a repetición de eventos y clics automatizados.
- Minimización de datos personales, retención definida, control de acceso y registro de cambios.
- No incluir identificadores personales ni datos innecesarios de usuarios en las URL de seguimiento.
- Los anuncios deben etiquetarse como publicidad y las creatividades propias diferenciarse en los informes.
- Si se usan cookies, perfiles o tecnologías de seguimiento no esenciales, analizar antes su necesidad y los requisitos de consentimiento aplicables.
- La API debe tener tiempos de espera, límites de tamaño y una respuesta de reserva definida para que un fallo publicitario no rompa las páginas de OSAP.

## 12. Estado de implementación

### Implementado en el prototipo
- Aplicación FastAPI y `GET /health`.
- Catálogo provisional en `GET /api/v1/metadata/page-types`.
- `POST /api/v1/ads/serve`: selecciona creatividades aprobadas, prioriza campañas comerciales y usa anuncios propios como reserva; permite reglas de inclusión/exclusión por aplicación, página, espacio, idioma y entidad.
- `POST /api/v1/ads/compose`: devuelve HTML seguro para un espacio fijo o área disponible, calcula una composición de hasta tres anuncios y registra entrega/impresión por pieza en la misma transacción.
- Laboratorio visual local en `/layout-lab` (solo desarrollo), con escenarios reales y medidas personalizadas.
- `POST /api/v1/events/impression`: confirma la impresión con protección de idempotencia.
- `GET /r/{token}`: registra el clic y redirige al destino almacenado en la creatividad, nunca a una URL recibida en la petición.
- Modelos SQLAlchemy y primera migración Alembic; esquema local automático solo en desarrollo/pruebas.
- CRUD REST para campañas, marcas, relaciones de competencia, creatividades, reglas de segmentación y formatos estándar; consultas paginadas de entregas y eventos.
- Catálogo de tamaños estándar, asociación de formatos por creatividad y composición de anuncios del mismo tamaño.
- Selección comercial primero; cooldown por campaña en el mismo contexto, marcas competidoras excluidas del mismo bloque y prioridad por el tamaño más grande que cabe.
- Script idempotente para cargar la campaña de OpenMusicRepository con cuatro creatividades, sin escribir en base de datos hasta añadir `--apply`.
- Borrado seguro: eliminación física de configuración sin histórico y archivado automático cuando hay entregas, manteniendo intactas las estadísticas.
- Panel web en `/admin` con menú de secciones, listados, filtros, acción **Ver** en formulario de solo lectura, formularios de alta/edición y confirmación de borrado.
- Pruebas de integración HTTP usando una SQLite en memoria aislada, sin borrar ni escribir en la base configurada de OSAP.
- Script de prueba real `scripts/smoke_test_delivery.py`, protegido tras `--apply`, para comprobar el endpoint HTTP contra el servicio y su base configurada.
- Pruebas de entrega comercial, fallback propio, idempotencia de impresiones, redirección segura, CRUD y carga de la interfaz web.

### Arranque local del prototipo

El arranque siguiente es para desarrollo local con SQLite (valor predeterminado de `.env.example`) y no utiliza MySQL. Para usar la base MySQL de esta aplicación, crea su propio `osap.toml` desde `osap.toml.example`, fija `name = "OSAP_PUBLICIDAD"` y sigue el procedimiento de la sección 9. La cuenta deberá tener permisos sobre ese esquema. Ejecuta las migraciones antes de cargar los anuncios.

```powershell
python -m pip install -e ".[dev]"
python -m alembic upgrade head
# Revisa primero el destino que muestra cada simulación.
python scripts/seed_house_ads.py
python scripts/seed_omr_campaign.py
# Para desarrollo SQLite:
python scripts/seed_house_ads.py --apply --allow-sqlite
python scripts/seed_omr_campaign.py --apply --allow-sqlite
uvicorn api.main:app --host 127.0.0.1 --port 8305
```

En PowerShell, deja `AI_PUBLICIDAD_DATABASE_URL` vacía cuando quieras usar el `osap.toml` privado. Las dos cargas son idempotentes, pero deben revisarse por separado: `seed_house_ads.py` prepara un anuncio propio genérico de reserva y `seed_omr_campaign.py` añade cinco formatos estándar y la campaña propia de OpenMusicRepository con cuatro creatividades. No se han aplicado las cargas a tu base desde este cambio; `--apply` es una acción explícita. Para SQLite se exige `--allow-sqlite`; para MySQL el destino debe ser `OSAP_PUBLICIDAD`. Para ejecutar pruebas: `pytest -q`. Con el servicio arrancado, abre **http://127.0.0.1:8305/admin**.

### Pendiente antes de integrar en producción
- Confirmar el resultado de CI y ejecutar el smoke test contra el servicio arrancado y la conexión real, después de comprobar que apunta a `OSAP_PUBLICIDAD`.
- Ejecutar `scripts/seed_house_ads.py --apply` para la creatividad propia genérica de reserva y `scripts/seed_omr_campaign.py --apply` para el catálogo y los cuatro anuncios de OpenMusicRepository, una vez revisado el destino.
- Revisar la idempotencia bajo peticiones concurrentes y endurecer autenticación/limitación de uso.
- Validar la taxonomía con el código real de `osap-app`.
- Añadir las entidades comerciales aún no modeladas (clientes/anunciantes, espacios, contratos/pedidos) y después sus informes y políticas de retención.
- Implementar autenticación y autorización de administración antes de publicar el panel fuera de una red de confianza.

### Fase 2 — API funcional
- Entrega de anuncios.
- Confirmación idempotente de impresiones.
- Seguimiento de clics y redirección segura.
- Pruebas de campañas específicas y anuncios de reserva.

### Fase 3 — Administración comercial
- Gestión de clientes, campañas, creatividades, ubicaciones y contratos.
- Aprobación y activación de anuncios.
- Informes por cliente, campaña, creatividad, página y ubicación.

### Fase 4 — Integración con OSAP
- Implementar el cliente API en `osap-app`.
- Confirmar los eventos desde el cliente sin bloquear la representación de la página.
- Verificar tamaños, accesibilidad, idiomas y comportamiento móvil.
- Probar caída del servicio y fallback de anuncios propios.

## 13. Criterios de aceptación iniciales

- Una petición compatible devuelve un anuncio comercial activo si corresponde según las reglas de selección.
- Si no existe una campaña comercial compatible, devuelve un anuncio propio válido.
- Se pueden dirigir campañas a tipos de página y a entidades concretas.
- Una impresión repetida con el mismo identificador no se cuenta dos veces.
- El clic se registra y redirige únicamente al destino autorizado del anuncio.
- La autorización de usuarios para el mantenimiento de campañas y creatividades queda pendiente y debe implementarse antes de exponer el panel públicamente.
- Las pruebas se ejecutan con SQLite y la aplicación funciona con MySQL en producción.
- No hay credenciales reales en Git y un fallo de `ai_publicidad` no debe impedir que OSAP muestre su contenido principal.

---

**Estado:** diseño inicial. La lista de tipos de página, los contratos comerciales y los endpoints se deben contrastar con la implementación real de `osap-app` antes de cerrar el contrato de integración.
