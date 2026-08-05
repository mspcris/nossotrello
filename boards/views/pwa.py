# boards/views/pwa.py
"""Service worker do PWA do Espaço Social.

Servido em /sw.js (raiz) para que o escopo cubra o site inteiro — um SW em
/static/ só controlaria /static/. Passthrough puro: nada de cache offline,
só o suficiente para o app ser instalável em navegadores que ainda pedem SW
(Samsung Internet, Chrome antigo).
"""

from django.http import HttpResponse
from django.views.decorators.cache import cache_control

_SW_JS = """\
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function () {});
"""


@cache_control(max_age=3600)
def service_worker(request):
    return HttpResponse(_SW_JS, content_type="application/javascript")
