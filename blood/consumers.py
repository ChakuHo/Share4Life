from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser


class DonorPingConsumer(AsyncJsonWebsocketConsumer):
    """
    Each donor joins a private group: donor_<user_id>
    Server pushes real-time request pings here.
    """
    async def connect(self):
        user = self.scope.get("user", None)
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close()
            return

        # only donors should connect
        if not getattr(user, "is_donor", False):
            await self.close()
            return

        self.group_name = f"donor_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def donor_ping(self, event):
        # event["data"] is sent from server
        await self.send_json(event.get("data", {}))


class RequestRoomConsumer(AsyncJsonWebsocketConsumer):
    """
    Request owner (and optionally org staff) can listen for response updates.
    Joins group: blood_request_<id>
    """
    async def connect(self):
        user = self.scope.get("user", None)
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close()
            return

        self.request_id = self.scope["url_route"]["kwargs"]["request_id"]
        self.group_name = f"blood_request_{self.request_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def request_event(self, event):
        await self.send_json(event.get("data", {}))