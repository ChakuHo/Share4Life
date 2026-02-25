from django.urls import path
from . import consumers

websocket_urlpatterns = [
    # supports template: /ws/chat/thread/<id>/
    path("ws/chat/thread/<int:thread_id>/", consumers.ChatConsumer.as_asgi()),

    path("thread/<int:thread_id>/", consumers.ChatConsumer.as_asgi()),
]