"""Views de erro custom — handler500 da página de erro 500
(byte_maze) e endpoint /500/ pra testar a mesma página sem
precisar forçar um crash."""

from django.http import HttpResponse
from django.template.loader import render_to_string


def server_error(request, template_name="500.html"):
    """Renderiza a página de erro 500 com status 500.

    Usada como:
      - Django handler500 (chamada quando há exception não-tratada).
      - URL /500/ para testes manuais.

    Roda sem context processors / request context, evitando que algo
    quebrado durante a request original também derrube esta página.
    """
    try:
        html = render_to_string(template_name)
    except Exception:
        html = (
            "<!doctype html><html><head><title>500</title></head>"
            "<body><h1>500 — Internal Server Error</h1></body></html>"
        )
    return HttpResponse(html, status=500, content_type="text/html; charset=utf-8")
