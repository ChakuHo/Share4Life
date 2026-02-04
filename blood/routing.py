from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/blood/donor/", consumers.DonorPingConsumer.as_asgi()),
    path("ws/blood/request/<int:request_id>/", consumers.RequestRoomConsumer.as_asgi()),
    path("donor/", consumers.DonorPingConsumer.as_asgi()),
    path("request/<int:request_id>/", consumers.RequestRoomConsumer.as_asgi()),
]
