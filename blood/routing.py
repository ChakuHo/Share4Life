from django.urls import path
from .consumers import DonorPingConsumer, RequestRoomConsumer

websocket_urlpatterns = [
    path("donor/", DonorPingConsumer.as_asgi()),
    path("request/<int:request_id>/", RequestRoomConsumer.as_asgi()),
]