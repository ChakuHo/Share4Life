from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("thread/<int:thread_id>/", consumers.ChatConsumer.as_asgi()),
]