# Diseño propuesto: preliquidación publicitaria por pedido

**Estado:** propuesta técnica; no implementada.  
**Ámbito:** repositorio `ai_publicidad`.  
**Objetivo:** obtener un cálculo interno revisable por pedido y periodo, sin emitir facturas, registrar pagos ni alterar el histórico de entregas/eventos.

## 1. Principios

1. La preliquidación no es una factura, saldo exigible ni justificante de cobro.
2. `ad_deliveries` y `ad_events` son el histórico de actividad. No se editan para ajustar importes.
3. Las tarifas y condiciones se copian a una instantánea al congelar el cálculo. Un cambio posterior del pedido no debe modificar una preliquidación cerrada.
4. No se suman monedas diferentes. Cada preliquidación pertenece a un único pedido y usa su moneda.
5. Los importes se calculan con enteros en microcéntimos/céntimos. No se utiliza coma flotante para dinero.
6. Los anuncios propios no generan líneas comerciales.
7. Un evento no puede quedar incluido en dos preliquidaciones cerradas.

## 2. Reglas de cálculo

| Modelo del pedido | Línea de preliquidación | Fuente |
|---|---|---|
| Fijo | Una línea por tarifa fija acordada para el periodo contractual que corresponda | Instantánea de `fixed_fee_cents` |
| CPM | Una línea por impresiones contabilizadas y cargadas, con tarifa CPM y cantidad | Eventos `impression` del pedido |
| CPC | Una línea por clics contabilizados y cargados, con tarifa CPC y cantidad | Eventos `click` del pedido |

- El cargo CPM por impresión se calcula con la regla vigente: `cpm_cents × 1.000` microcéntimos.
- El cargo CPC por clic se calcula con la regla vigente: `cpc_cents × 1.000.000` microcéntimos.
- La tarifa fija no se añade a cada evento. Se incorpora una sola vez según la periodicidad pactada, que deberá quedar configurada en el contrato antes de automatizarla.
- Las reservas temporales de impresiones CPM aún no confirmadas sirven para controlar el presupuesto, pero no son eventos cobrables. La preliquidación solo incluye impresiones confirmadas y cargadas.
- Si una impresión se entrega en un día y se confirma en otro, el periodo económico se asigna por `AdEvent.occurred_at`, no por `delivered_at`.
- Los ajustes manuales deben ser líneas independientes con motivo, autor y fecha; nunca se cambia el cargo original del evento.

## 3. Entidad lógica: preliquidación

Campos mínimos propuestos:

- Identificador y referencia legible.
- `order_id`, anunciante y moneda.
- Inicio y fin del periodo en UTC.
- Estado: `draft`, `reviewed`, `closed` o `void`.
- Fecha de cálculo, creador y revisor.
- Instantánea de las condiciones económicas: modelo, tarifa fija, CPM, CPC, presupuesto y referencia/versión contractual disponible.
- Totales separados por tarifa fija, CPM, CPC y ajustes; total calculado.
- Número de eventos incluidos y fecha/hora de corte del cálculo.
- Observaciones y motivo de anulación, si procede.

La instantánea debe guardar también la razón social y los datos de facturación disponibles en ese momento solo cuando se haya decidido que son necesarios para el flujo económico y con permisos de acceso adecuados. No se deben copiar datos personales de contacto que no sean necesarios.

## 4. Líneas y trazabilidad

Cada línea debe guardar:

- Tipo de concepto: `fixed_fee`, `cpm_impressions`, `cpc_clicks` o `adjustment`.
- Descripción legible.
- Cantidad y unidad (periodo, impresión, clic o ajuste).
- Precio unitario entero y moneda.
- Importe entero en microcéntimos o céntimos, con unidad explícita.
- Referencias de origen: pedido, campañas y eventos que justifican el cálculo.
- En ajustes: motivo, usuario responsable y fecha.

Para impedir la doble liquidación, la futura implementación necesita una relación explícita entre cada evento incluido y la preliquidación. Una restricción única sobre el ID del evento liquidado debe impedir que un mismo evento se incorpore a dos preliquidaciones cerradas. No basta con guardar solo un total agregado.

## 5. Ciclo de vida

1. **Crear borrador:** seleccionar un pedido y un periodo cerrado; obtener eventos elegibles y condiciones actuales.
2. **Comprobar:** verificar moneda, fechas, estado del pedido, eventos duplicados, cargos cero, límites y reservas CPM pendientes.
3. **Recalcular:** permitido mientras sea borrador. Cada cálculo registra su fecha de corte y el resultado anterior no se presenta como definitivo.
4. **Revisar:** una persona autorizada contrasta cantidades y tarifas con el contrato.
5. **Cerrar:** congela la instantánea y las líneas; reserva de forma definitiva los eventos incluidos para impedir reutilizarlos.
6. **Corregir:** no se modifica un cierre. Se crea una nueva preliquidación de ajuste vinculada a la anterior, con trazabilidad.

No debe existir una acción que transforme directamente una preliquidación en factura hasta que se definan las obligaciones fiscales, numeración, series, impuestos y requisitos documentales.

## 6. Validaciones imprescindibles

- El pedido existe, tiene anunciante y una sola moneda.
- El intervalo es válido y está expresado en UTC, con inicio inclusivo y fin exclusivo.
- No se incluyen anuncios propios ni campañas sin pedido.
- Los eventos pertenecen al pedido y corresponden al modelo de tarifa.
- Los cargos de los eventos coinciden con las reglas del motor; cualquier discrepancia bloquea el cierre y se informa.
- No se incluyen impresiones pendientes sin evento confirmado.
- Ningún evento está asignado a otra preliquidación cerrada.
- El cargo fijo no se repite en periodos solapados; su periodicidad debe venir del acuerdo.
- Los cálculos se realizan con aritmética entera y redondeo definido.
- El total de una moneda nunca se mezcla con otra.
- La operación de cierre es transaccional e idempotente.

## 7. Pantalla administrativa prevista

La primera versión debería permitir:

- Elegir pedido y periodo.
- Generar/recalcular borrador.
- Ver tarifa contractual, cantidades, precio unitario y subtotal por concepto.
- Consultar el detalle de eventos que componen CPM/CPC.
- Ver advertencias de eventos ya asignados, reservas pendientes, moneda y discrepancias.
- Añadir ajustes justificados.
- Marcar como revisada y cerrar, con permisos diferenciados.

No se necesita todavía portal de anunciante, PDF fiscal, pasarela de pago ni integración bancaria.

## 8. Decisiones previas a desarrollar

1. ¿La tarifa fija se cobra por pedido completo, por mes, por campaña o por otro hito?
2. ¿Se liquida el periodo por fecha de evento (propuesta) o por otra fecha contractual?
3. ¿Qué sucede con eventos tardíos que llegan después del cierre?
4. ¿Quién puede crear, revisar y cerrar una preliquidación?
5. ¿Se permiten periodos parciales y liquidaciones extraordinarias?
6. ¿Qué política se aplica a descuentos, bonificaciones y ajustes?
7. ¿Qué conservación y trazabilidad exige el marco fiscal aplicable?

Hasta resolver estas decisiones, la propuesta debe mantenerse como diseño y no debe generar nuevas tablas ni modificar la base de datos.
