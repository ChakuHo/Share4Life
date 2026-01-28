from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("donor/", consumers.DonorPingConsumer.as_asgi()),
    path("request/<int:request_id>/", consumers.RequestRoomConsumer.as_asgi()),
]
