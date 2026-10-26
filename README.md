# ai_publicidad

Servicio independiente de publicidad directa para OSAP/OpenMusicRepository. El núcleo actual gestiona campañas, creatividades, segmentación, entrega de anuncios, impresiones, clics y redirecciones. El modelo de clientes/anunciantes, contratos y espacios configurables todavía está pendiente; la primera pantalla web de mantenimiento ya está disponible en `/admin`.

El proyecto es un servicio independiente **Python 3.11+ + FastAPI**, alineado con `AI_osap-auth`, `AI_osap-storage` y `AI_osap-support`. Ya existe un primer núcleo funcional; el contrato de integración con `osap-app` sigue pendiente de validar con el código real del frontend.

## 1. Objetivos y principios

- OSAP solicita un anuncio a `ai_publicidad` según el contexto de la página y el espacio disponible.
- `ai_publicidad` decide qué anuncio compatible devuelve; OSAP no necesita conocer clientes, contratos ni destinos finales.
- Si no hay publicidad comercial válida, se devuelve un **anuncio propio de OSAP**. El espacio nunca queda vacío por falta de campañas.
- Los clics pasan por `ai_publicidad`, que registra el evento y redirige al destino configurado en el servidor.
- Se registran impresiones cuando el anuncio se muestra, no solo cuando se solicita.
- El servicio debe poder admitir otras aplicaciones en el futuro, aunque la primera integración sea `osap-app`.
- El código no contiene credenciales ni secretos. La configuración se obtiene del entorno o de un archivo local ignorado por Git.
- MySQL es la base de datos de producción. SQLite se utilizará para desarrollo y pruebas automatizadas.
- **Stack decidido:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic y MySQL/MariaDB en producción; SQLite para pruebas. Se reutilizarán las convenciones de configuración y autenticación de servicios OSAP, sin copiar secretos ni acoplar el servicio a la base de datos del catálogo.

## 2. Arquitectura lógica

1. **Aplicación cliente (`osap-app`)**: identifica la tipología de página, el espacio publicitario y el contexto; solicita el anuncio, lo presenta y confirma la impresión. Al pulsarlo, el navegador abre la URL de seguimiento recibida.
2. **API de `ai_publicidad`**: autentica la aplicación, valida la petición, selecciona un anuncio comercial o propio y entrega los datos necesarios para mostrarlo.
3. **Gestor publicitario**: mantiene clientes, campañas, creatividades, contratos/pedidos, segmentación, inventario y límites de entrega.
4. **Seguimiento**: registra impresiones y clics con identificadores únicos; la ruta de clic obtiene el destino de la base de datos y efectúa una redirección HTTP.
5. **Administración e informes**: permite gestionar el inventario y consultar resultados comerciales.

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

Los tamaños admitidos se configurarán por espacio y dispositivo (escritorio, tableta y móvil). La API devolverá dimensiones y formato explícitos. El cliente no debe tener que adivinar cómo representar la creatividad.

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
- Formato, dimensiones, título/texto y datos del recurso visual.
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
- **Histórico de entregas:** `GET /deliveries` y `GET /deliveries/{id}`, con filtros por campaña o creatividad.
- **Histórico de eventos:** `GET /events` y `GET /events/{id}`, con filtros por tipo de evento y entrega.

Las tablas de configuración tienen CRUD. `ad_deliveries` y `ad_events` son datos operativos e históricos: se consultan, pero no se editan ni borran desde la administración para no falsear métricas ni romper relaciones. Si una campaña o creatividad ya tiene entregas, se debe pausar en lugar de borrarla. Las reglas de segmentación admiten `application`, `page_type`, `placement`, `language`, `entity_type` y `entity_id`, con efecto `include` o `exclude`.

En el panel `/admin`, cada listado muestra los campos principales y ofrece **Ver**. La acción **Ver** abre la misma pantalla de formulario que **Editar**, pero con todos los campos deshabilitados y sin opción de guardar; en las entregas y eventos se utiliza ese mismo formato de solo lectura. En campañas, creatividades y reglas también están **Editar** y **Borrar**, además de **Nuevo**. Los formularios incluyen selectores de campaña/creatividad y el filtro busca dentro del listado actual.

## 8. Modelo de datos inicial

**Tablas que existen en el esquema funcional actual:**

1. `campaigns`: estado, fechas, prioridad y marca de anuncio propio.
2. `creatives`: título, contenido, formato, idioma, destino y estado de aprobación.
3. `targeting_rules`: reglas de inclusión/exclusión por aplicación, página, ubicación, idioma y entidad.
4. `ad_deliveries`: entrega, token de impresión y confirmación de impresión.
5. `ad_events`: impresiones y clics registrados.

**Entidades previstas para fases posteriores, que todavía no forman parte de esta migración:** `applications`, `advertisers`, `placements`, `orders/contracts`, configuración específica de anuncios propios, usuarios administrativos y auditoría.

Se usan claves foráneas e índices en las tablas existentes. Las entregas y los eventos se conservan como histórico; informes más amplios, archivo de eventos y retención deben diseñarse en fases posteriores.

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
- `POST /api/v1/events/impression`: confirma la impresión con protección de idempotencia.
- `GET /r/{token}`: registra el clic y redirige al destino almacenado en la creatividad, nunca a una URL recibida en la petición.
- Modelos SQLAlchemy y primera migración Alembic; esquema local automático solo en desarrollo/pruebas.
- CRUD REST para campañas, creatividades y reglas de segmentación; consultas paginadas de entregas y eventos.
- Panel web en `/admin` con menú de secciones, listados, filtros, acción **Ver** en formulario de solo lectura, formularios de alta/edición y confirmación de borrado.
- Pruebas de integración HTTP usando una SQLite en memoria aislada, sin borrar ni escribir en la base configurada de OSAP.
- Script de prueba real `scripts/smoke_test_delivery.py`, protegido tras `--apply`, para comprobar el endpoint HTTP contra el servicio y su base configurada.
- Pruebas de entrega comercial, fallback propio, idempotencia de impresiones, redirección segura, CRUD y carga de la interfaz web.

### Arranque local del prototipo

El arranque siguiente es para desarrollo local con SQLite (valor predeterminado de `.env.example`) y no utiliza MySQL. Para usar la base MySQL de esta aplicación, crea su propio `osap.toml` desde `osap.toml.example`, copia los parámetros de conexión que corresponda reutilizar y fija `name = "OSAP_PUBLICIDAD"`. Deja vacía `AI_PUBLICIDAD_DATABASE_URL` para que lea ese fichero y sigue el procedimiento de la sección 9 antes de aplicar migraciones. La cuenta deberá tener permisos sobre ese esquema. El script `seed_house_ads.py` admite SQLite para desarrollo solo con la opción explícita `--allow-sqlite`; para MySQL exige que la base de destino sea `OSAP_PUBLICIDAD`.

```bash
python -m venv .venv
# Activar el entorno virtual según el sistema operativo
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python scripts/seed_house_ads.py
python scripts/seed_house_ads.py --apply --allow-sqlite
uvicorn api.main:app --host 127.0.0.1 --port 8305
```

En PowerShell, sustituye `cp .env.example .env` por `Copy-Item .env.example .env`. La primera llamada a `seed_house_ads.py` es una simulación y no escribe nada; `--apply` confirma la carga. El comando valida que una conexión MySQL apunte a `OSAP_PUBLICIDAD` y es idempotente: si campaña y creatividad ya existen, no duplica filas. En SQLite se niega a escribir salvo que añadas `--allow-sqlite`; esa opción es solo para desarrollo local. Para una carga real en MySQL, usa el `osap.toml` privado de esta aplicación y revisa la simulación antes de ejecutar `--apply`. Para ejecutar pruebas: `pytest -q`. Con el servicio arrancado, abre **http://127.0.0.1:8305/admin** para utilizar el panel local.

### Pendiente antes de integrar en producción
- Confirmar el resultado de CI y ejecutar el smoke test contra el servicio arrancado y la conexión real, después de comprobar que apunta a `OSAP_PUBLICIDAD`.
- Ejecutar `scripts/seed_house_ads.py --apply` en la base correcta si todavía no se ha cargado la campaña y creatividad propias iniciales.
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
