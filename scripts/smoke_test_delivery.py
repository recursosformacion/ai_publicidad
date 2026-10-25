"""Explicit smoke test against a running ai_publicidad API and its configured database.

This script only creates live test data when invoked with --apply. Historical delivery
rows are intentionally retained; the created test campaign is paused in a finally block.
"""

import argparse
import os
import sys
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba la entrega comercial real y el fallback propio mediante la API HTTP."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8305",
        help="URL HTTP del servicio ya iniciado (por defecto: %(default)s).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Crea datos de prueba y realiza dos entregas; sin esto no se hacen escrituras.",
    )
    args = parser.parse_args()
    load_dotenv()

    base_url = args.base_url.rstrip("/")
    token = os.getenv("AI_PUBLICIDAD_SERVICE_TOKEN", "").strip()
    headers = {"X-OSAP-Service-Token": token} if token else {}

    with httpx.Client(base_url=base_url, headers=headers, timeout=20.0) as client:
        try:
            health = client.get("/health")
        except httpx.HTTPError as exc:
            print(f"No se puede contactar con {base_url}: {exc}", file=sys.stderr)
            return 2
        if health.status_code != 200:
            print(f"El endpoint /health respondió {health.status_code}: {health.text}", file=sys.stderr)
            return 2
        print(f"Servicio accesible: {base_url}/health")

        if not args.apply:
            print("Simulación: no se han creado datos ni solicitado anuncios.")
            print("Cuando hayas revisado la URL y la base de datos del servicio, añade --apply.")
            return 0

        suffix = uuid4().hex[:10]
        campaign_id: int | None = None

        def call(method: str, path: str, payload: dict | None = None) -> dict:
            response = client.request(method, path, json=payload)
            if not response.is_success:
                raise RuntimeError(
                    f"{method} {path} respondió {response.status_code}: {response.text}"
                )
            if not response.content:
                return {}
            return response.json()

        def campaign_payload(status: str) -> dict:
            return {
                "name": f"SMOKE TEST {suffix}",
                "status": status,
                "starts_at": None,
                "ends_at": None,
                "priority": 100000,
                "is_house_ad": False,
            }

        creative_payload: dict = {
            "campaign_id": 0,
            "title": f"SMOKE TEST {suffix}",
            "body": "Creatividad temporal de comprobación del endpoint.",
            "image_url": None,
            "alt_text": None,
            "format": "text",
            "language": "es",
            "destination_url": "https://openmusicrepository.com/",
            "status": "approved",
        }
        serve_payload: dict = {
            "application": "osap",
            "page": {
                "type": "work_detail",
                "entity_type": "work",
                "entity_id": "smoke-test",
                "language": "es",
            },
            "placement": "sidebar",
            "format": {"type": "text"},
        }

        try:
            campaign = call("POST", "/api/v1/admin/campaigns", campaign_payload("active"))
            campaign_id = int(campaign["id"])
            creative_payload["campaign_id"] = campaign_id
            creative = call("POST", "/api/v1/admin/creatives", creative_payload)

            commercial = call("POST", "/api/v1/ads/serve", serve_payload)
            if commercial.get("kind") != "commercial" or commercial.get("ad_id") != creative["id"]:
                raise RuntimeError(
                    "La primera entrega no devolvió la creatividad de prueba: "
                    f"kind={commercial.get('kind')!r}, ad_id={commercial.get('ad_id')!r}"
                )
            print(
                "ENTREGA COMERCIAL OK: "
                f"campaign_id={campaign_id}, ad_id={commercial['ad_id']}, kind=commercial"
            )

            # Confirm the first impression exactly once and verify the delivery was persisted.
            impression_request = {"impression_id": commercial["impression_id"]}
            first_impression = call(
                "POST", "/api/v1/events/impression", impression_request
            )
            second_impression = call(
                "POST", "/api/v1/events/impression", impression_request
            )
            if first_impression.get("counted") is not True or second_impression.get("counted") is not False:
                raise RuntimeError(
                    "La confirmación de impresión no es idempotente: "
                    f"primera={first_impression!r}, repetida={second_impression!r}"
                )
            persisted_commercial = call(
                "GET", f"/api/v1/admin/deliveries?campaign_id={campaign_id}"
            )
            if not any(
                row.get("creative_id") == commercial["ad_id"]
                and row.get("impression_confirmed") is True
                for row in persisted_commercial
            ):
                raise RuntimeError("La entrega comercial no aparece confirmada en el histórico.")
            print("IMPRESIÓN E HISTÓRICO OK: primera confirmación contada; repetición ignorada.")

            # Pause via the CRUD API; the next identical request must use an OSAP house ad.
            call("PUT", f"/api/v1/admin/campaigns/{campaign_id}", campaign_payload("paused"))
            fallback = call("POST", "/api/v1/ads/serve", serve_payload)
            if fallback.get("kind") != "house" or fallback.get("is_house_ad") is not True:
                raise RuntimeError(
                    "El fallback no devolvió un anuncio propio de OSAP. "
                    f"Respuesta recibida: kind={fallback.get('kind')!r}, "
                    f"is_house_ad={fallback.get('is_house_ad')!r}. "
                    "Comprueba que exista una campaña propia activa con una creatividad compatible."
                )
            persisted_house = call(
                "GET", f"/api/v1/admin/deliveries?creative_id={fallback['ad_id']}"
            )
            if not persisted_house:
                raise RuntimeError("La entrega del anuncio propio no aparece en el histórico.")
            print(
                "FALLBACK PROPIO OK: "
                f"ad_id={fallback['ad_id']}, kind=house, is_house_ad=true"
            )
            print(
                "Las dos entregas se conservan en el histórico. "
                "La campaña de prueba queda pausada para que no vuelva a participar."
            )
            return 0
        except (RuntimeError, httpx.HTTPError, KeyError, ValueError) as exc:
            print(f"PRUEBA FALLIDA: {exc}", file=sys.stderr)
            return 1
        finally:
            # Do not leave the test campaign active if any assertion/API call fails.
            if campaign_id is not None:
                try:
                    call(
                        "PUT",
                        f"/api/v1/admin/campaigns/{campaign_id}",
                        campaign_payload("paused"),
                    )
                except Exception as exc:  # preserve the original failure for diagnostics
                    print(
                        f"AVISO: no se pudo pausar automáticamente la campaña {campaign_id}: {exc}",
                        file=sys.stderr,
                    )


if __name__ == "__main__":
    raise SystemExit(main())
