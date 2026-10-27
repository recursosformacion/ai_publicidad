# Control comercial y elegibilidad de entregas

## Modelo implementado

- **Anunciantes**: datos de contacto, web y estado. Se archivan si tienen pedidos.
- **Pedidos/contratos**: vigencia, moneda, modelo CPM/CPC/tarifa fija, presupuesto total/diario para facturación variable, tarifas, topes de impresiones/clics y pacing.
- **Campañas**: pueden asociarse a un pedido y establecer topes propios de impresiones/clics y de frecuencia por visitante.
- **Registro económico**: cada evento registra el cargo calculado con enteros en microcéntimos. Los anuncios propios no generan cargo variable.
- **Elegibilidad**: los controles comerciales se verifican antes de seleccionar el anuncio o entrar al optimizador geométrico.

## API administrativa

Las rutas `/api/v1/admin/advertisers` y `/api/v1/admin/orders` permiten listar, consultar, crear, editar y eliminar/archivar. Los listados aceptan paginación; pedidos permite filtrar por anunciante. Si hay relaciones históricas, DELETE archiva en vez de romperlas.

La autorización administrativa todavía está pendiente: mantén `/admin` y las rutas de administración dentro de una red local/de confianza. La entrega usa su token de servicio, independiente del mantenimiento.

## Presupuesto y cargo por evento

Importes de tarifa/presupuesto se envían en céntimos. El cargo se registra como microcéntimos (un millonésimo de céntimo), sin coma flotante:

- `cpm`: cada impresión confirmada genera `cpm_cents * 1_000` microcéntimos.
- `cpc`: cada clic genera `cpc_cents * 1_000_000` microcéntimos.
- `fixed`: guarda `fixed_fee_cents`, sin cargos variables por evento.
- Presupuestos total/diario y pacing solo aplican a CPM/CPC. Se validan topes monetarios e impresiones/clics antes de entregar.
- Una entrega CPM aún sin confirmar reserva temporalmente su coste previsto durante 15 minutos. Esto impide gastar repetidamente el mismo saldo mientras el cliente confirma. Una confirmación tardía vuelve a comprobar el presupuesto antes de registrar el cargo.
- `pacing_mode=even` exige presupuesto total y fechas; aplica un umbral proporcional al tiempo transcurrido.

Esto no emite facturas ni procesa pagos. El registro de cargos es un mecanismo de control de presupuesto, no facturación fiscal.

## Frecuencia por visitante y privacidad

Las peticiones a `/api/v1/ads/serve` y `/api/v1/ads/compose` pueden enviar `visitor_id`, que debe ser un identificador opaco de primera parte, aleatorio y estable definido por OSAP. No se deben enviar email, ID de cuenta, IP ni otro dato personal. El servicio guarda solo su HMAC-SHA256 en `ad_deliveries.visitor_key_hash`.

Si una campaña configura `max_impressions_per_visitor` o `visitor_interval_seconds`, la petición debe incluir `visitor_id`; sin él, esa campaña no es elegible. Si no hay otra opción, `/serve` devuelve 503 y `/compose` devuelve `no-fill`. En producción es obligatorio configurar `AI_PUBLICIDAD_VISITOR_HASH_SECRET` con una clave privada larga e independiente.

Ejemplo de `/compose`:
```json
{
  "application": "osap",
  "page": {"type": "work_detail", "entity_type": "work", "entity_id": "12345", "language": "es"},
  "placement": "content_top",
  "device": "desktop",
  "mode": "auto_area",
  "area": {"width": 640, "height": 320},
  "max_ads": 3,
  "visitor_id": "opaque-first-party-session-value"
}
```

La respuesta de `/compose` sigue siendo HTML y registra las impresiones al emitir el bloque; no necesita llamada de confirmación adicional. `/serve` sigue devolviendo JSON y conserva la confirmación idempotente por `/api/v1/events/impression`.

## Límites restantes

No se emiten facturas, no se procesan pagos, no hay antifraude sofisticado ni informes contables. La concurrencia se protege mediante `SELECT FOR UPDATE` en MySQL, pero antes de prometer garantías comerciales estrictas hay que realizar pruebas de carga distribuidas y conciliar los eventos con el sistema de facturación.
