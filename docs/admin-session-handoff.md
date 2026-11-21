# Sesión administrativa y handoff desde OSAP

El panel se abre desde osap-api mediante `POST /auth/session`. El formulario lleva el
access token del usuario y el destino en el cuerpo; no se acepta el token en query string.

El origen se valida contra `AI_PUBLICIDAD_ADMIN_HANDOFF_ORIGINS` (lista separada por comas).
En producción debe incluir `https://app.openmusicrepository.com`.

El receptor consulta `osap-auth /auth/me` y solo acepta usuarios con el rol admin actual.
Emite una cookie firmada, host-only, `HttpOnly`, `Secure` en HTTPS y `SameSite=Lax`, con
una duración máxima de cinco minutos. Las mutaciones protegidas por cookie requieren
`Origin` same-origin. La cookie no contiene el access token; conserva únicamente los datos
de sesión necesarios y una expiración corta.

El endpoint antiguo `GET /auth/session?token=...` queda retirado.