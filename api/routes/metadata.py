"""Public, non-sensitive service metadata."""

from fastapi import APIRouter

router = APIRouter(tags=["metadata"])

PAGE_TYPES = [
    {"code": "home", "label": "Portada"},
    {"code": "search_results", "label": "Resultados de búsqueda"},
    {"code": "work_detail", "label": "Ficha de obra"},
    {"code": "person_detail", "label": "Ficha de persona"},
    {"code": "catalog_detail", "label": "Ficha de catálogo"},
    {"code": "classification", "label": "Clasificación"},
    {"code": "instrument_detail", "label": "Ficha de instrumento"},
    {"code": "ensemble_detail", "label": "Ficha de conjunto"},
    {"code": "representation_detail", "label": "Ficha de representación"},
    {"code": "viewer", "label": "Visor musical"},
    {"code": "source_detail", "label": "Ficha de fuente"},
    {"code": "amigos_index", "label": "Los Amigos: índice"},
    {"code": "amigos_group", "label": "Los Amigos: grupo"},
    {"code": "amigos_article", "label": "Los Amigos: artículo"},
    {"code": "amigos_event", "label": "Los Amigos: actuación o evento"},
    {"code": "static_page", "label": "Página informativa"},
    {"code": "other", "label": "Otra página"},
]


@router.get("/metadata/page-types")
def page_types() -> dict[str, object]:
    """Return the current provisional, versioned page taxonomy."""
    return {"version": 1, "status": "provisional", "page_types": PAGE_TYPES}
