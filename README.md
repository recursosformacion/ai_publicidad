# ai_publicidad

Servicio independiente de publicidad directa para OSAP/OpenMusicRepository. Gestiona clientes, campañas, anuncios, espacios publicitarios, selección de anuncios, impresiones, clics, redirecciones y estadísticas.

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
- Administración: rutas separadas, autenticadas y no accesibles a la clave pública de `osap-app`.

## 8. Modelo de datos inicial

Tablas previstas para la primera migración:

1. `applications`
2. `advertisers`
3. `campaigns`
4. `placements`
5. `creatives`
6. `targeting_rules`
7. `orders` (o `contracts`, según el modelo comercial final)
8. `ad_deliveries` (entrega e identificador de impresión)
9. `ad_events`
10. `house_ad_settings` o clasificación equivalente en campañas/creatividades
11. `admin_users` si la administración necesita usuarios propios
12. `audit_log`

Se usarán claves foráneas, índices para las búsquedas de selección y fechas almacenadas de forma consistente. Los eventos de alto volumen deben poder archivarse o resumirse sin perder los totales comerciales.

## 9. Base de datos y configuración

- **Nombre de la base de datos de publicidad:** `OSAP_PUBLICIDAD`; no se usa ni se modifica la base operativa `osap-api`.
- **Reutilización de `osap.toml`:** si no se define `AI_PUBLICIDAD_DATABASE_URL`, el servicio lee la sección `[db]` del `osap.toml` indicado por `OSAP_CONFIG` (o `AI_PUBLICIDAD_OSAP_CONFIG`). Si no se indica ruta, busca `./osap.toml`. Reutiliza host, puerto, usuario y contraseña, pero reemplaza siempre el nombre de la base por `OSAP_PUBLICIDAD`. Sin una ruta explícita, busca primero `./osap.toml` y después `../osap-api/osap.toml`, disposición usada en el desarrollo local.
- No se debe copiar el fichero real `osap.toml` a Git ni introducir sus credenciales en este repositorio. Para desarrollo local sin ese fichero se utiliza SQLite.
- **Creación:** `python scripts/create_database.py` comprueba la configuración sin modificar el servidor; `python scripts/create_database.py --apply` intenta crear únicamente `OSAP_PUBLICIDAD` con codificación `utf8mb4`, leyendo la conexión de `osap.toml`. También está disponible `infrastructure/db/create_database.sql` para ejecución manual por una cuenta MySQL/MariaDB autorizada. Ninguno de estos procedimientos crea usuarios ni contraseñas.
- **Permisos:** la cuenta que aparece en el `osap.toml` podría tener permisos únicamente sobre `osap-api.*`. Crear la nueva base no concede acceso automáticamente. Antes de conectar, un administrador debe conceder a esa cuenta los permisos mínimos sobre `OSAP_PUBLICIDAD.*`, o configurar un usuario de base de datos específico para este servicio. El servicio no intenta ampliar permisos.
- Una URL explícita `AI_PUBLICIDAD_DATABASE_URL` tiene precedencia sobre `osap.toml`. Ejemplo de formato (valores ficticios, no copiar secretos aquí): `mysql+pymysql://USUARIO:CONTRASEÑA@SERVIDOR:3306/OSAP_PUBLICIDAD?charset=utf8mb4`.
- Tras crear la base y confirmar permisos, inicializar el esquema con Alembic. En PowerShell, desde `D:\\Proyectos\\AI_OSAP\\ai_publicidad`, se puede ejecutar:
  ```powershell
  $env:AI_PUBLICIDAD_OSAP_CONFIG = "D:\\Proyectos\\AI_OSAP\\osap-api\\osap.toml"
  $env:AI_PUBLICIDAD_DATABASE_URL = ""
  python -c "from infrastructure.config import get_settings; from sqlalchemy.engine import make_url; u=make_url(get_settings().database_url); print(f'Destino: {u.host}:{u.port}/{u.database}; usuario={u.username}')"
  alembic upgrade head
  ```
  Antes de la última orden, comprobar que la línea de destino muestra exactamente `OSAP_PUBLICIDAD`. El entorno vacío sobrescribe una posible URL SQLite del `.env` para esta consola. La migración tiene una protección adicional que rechaza cualquier base MySQL distinta de `OSAP_PUBLICIDAD`.
- La API no crea tablas automáticamente cuando se conecta a MySQL, ni siquiera en modo desarrollo. El auto-esquema queda reservado al SQLite local.
- Producción requiere `AI_PUBLICIDAD_SERVICE_TOKEN`, `AI_PUBLICIDAD_PUBLIC_BASE_URL` con HTTPS y una conexión MySQL/MariaDB que termine en `OSAP_PUBLICIDAD`; la configuración falla al arrancar si estas condiciones no se cumplen.
- Variables de configuración documentadas en `.env.example`: `AI_PUBLICIDAD_DATABASE_URL` (opcional), `OSAP_CONFIG` o `AI_PUBLICIDAD_OSAP_CONFIG`, `AI_PUBLICIDAD_ENV`, `AI_PUBLICIDAD_PUBLIC_BASE_URL` y `AI_PUBLICIDAD_SERVICE_TOKEN`.

## 10. Seguridad, privacidad y fiabilidad

- Autenticación entre `osap-app` y el servicio mediante credencial específica de aplicación, rotación y límites de uso; nunca usar una clave administrativa en el navegador.
- Validación de todos los parámetros y de los recursos publicitarios antes de publicarlos.
- Las URL de destino se administran en el servidor y no se aceptan como parámetro de redirección abierto.
- Registro idempotente de impresiones y protección básica frente a repetición de eventos y clics automatizados.
- Minimización de datos personales, retención definida, control de acceso y registro de cambios.
- No incluir identificadores personales ni datos innecesarios de usuarios en las URL de seguimiento.
- Los anuncios deben etiquetarse como publicidad y las creatividades propias diferenciarse en los informes.
- Si se usan cookies, perfiles o tecnologías de seguimiento no esenciales, analizar antes su necesidad y los requisitos de consentimiento aplicables.
- La API debe tener tiempos de espera, límites de tamaño y una respuesta de reserva definida para que un fallo publicitario no rompa las páginas de OSAP.

## 11. Estado de implementación

### Implementado en el prototipo
- Aplicación FastAPI y `GET /health`.
- Catálogo provisional en `GET /api/v1/metadata/page-types`.
- `POST /api/v1/ads/serve`: selecciona creatividades aprobadas, prioriza campañas comerciales y usa anuncios propios como reserva; permite reglas de inclusión/exclusión por aplicación, página, espacio, idioma y entidad.
- `POST /api/v1/events/impression`: confirma la impresión con protección de idempotencia.
- `GET /r/{token}`: registra el clic y redirige al destino almacenado en la creatividad, nunca a una URL recibida en la petición.
- Modelos SQLAlchemy y primera migración Alembic; esquema local automático solo en desarrollo/pruebas.
- Pruebas iniciales de entrega comercial, fallback propio, impresiones y redirección.

### Arranque local del prototipo

El `.env.example` selecciona SQLite para que el arranque local no escriba accidentalmente en el MySQL de OSAP. Para utilizar la conexión privada existente, define `OSAP_CONFIG` (o `AI_PUBLICIDAD_OSAP_CONFIG`) y quita o deja vacía `AI_PUBLICIDAD_DATABASE_URL`; se usará host/usuario/contraseña de `[db]`, pero el esquema destino siempre será `OSAP_PUBLICIDAD`. La cuenta deberá tener permisos sobre ese esquema.

```bash
python -m venv .venv
# Activar el entorno virtual según el sistema operativo
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python scripts/seed_house_ads.py
uvicorn api.main:app --host 127.0.0.1 --port 8305
```

En PowerShell, sustituye `cp .env.example .env` por `Copy-Item .env.example .env`. El inicializador solo crea un anuncio propio en desarrollo/pruebas y se niega a ejecutarse si `AI_PUBLICIDAD_ENV=production`. Para ejecutar pruebas: `pytest -q`.

### Pendiente antes de integrar en producción
- Ejecutar la suite en un entorno local con dependencias instaladas y corregir cualquier fallo.
- Revisar la idempotencia bajo peticiones concurrentes y endurecer autenticación/limitación de uso.
- Crear un proceso de inicialización explícito para insertar los anuncios propios iniciales (no se ha ejecutado ningún seed ni migración de producción).
- Validar la taxonomía con el código real de `osap-app`.
- Completar administración de clientes, campañas, creatividades y contratos; informes y retención de eventos.

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

## 12. Criterios de aceptación iniciales

- Una petición compatible devuelve un anuncio comercial activo si corresponde según las reglas de selección.
- Si no existe una campaña comercial compatible, devuelve un anuncio propio válido.
- Se pueden dirigir campañas a tipos de página y a entidades concretas.
- Una impresión repetida con el mismo identificador no se cuenta dos veces.
- El clic se registra y redirige únicamente al destino autorizado del anuncio.
- La clave del cliente no permite gestionar campañas ni leer datos de otros clientes.
- Las pruebas se ejecutan con SQLite y la aplicación funciona con MySQL en producción.
- No hay credenciales reales en Git y un fallo de `ai_publicidad` no debe impedir que OSAP muestre su contenido principal.

---

**Estado:** diseño inicial. La lista de tipos de página, los contratos comerciales y los endpoints se deben contrastar con la implementación real de `osap-app` antes de cerrar el contrato de integración.
