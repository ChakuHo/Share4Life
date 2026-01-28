from django.urls import path
from channels.routing import URLRouter

import blood.routing

websocket_urlpatterns = [
    path("ws/blood/", URLRouter(blood.routing.websocket_urlpatterns)),
]