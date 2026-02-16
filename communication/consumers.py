from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django.db.models import Q
from .models import ChatThread, ChatMessage, Notification, NotificationPreference


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close()
            return

        self.thread_id = int(self.scope["url_route"]["kwargs"]["thread_id"])

        ok = await self._user_in_thread(self.thread_id, user.id)
        if not ok:
            await self.close()
            return

        self.group_name = f"chat_thread_{self.thread_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            return

        msg_type = (content.get("type") or "").upper()
        if msg_type != "SEND":
            return

        body = (content.get("body") or "").strip()
        if not body:
            return

        if len(body) > 2000:
            body = body[:2000]

        msg = await self._create_message_and_notify(self.thread_id, user.id, body)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "data": {
                    "type": "MESSAGE",
                    "id": msg["id"],
                    "thread_id": self.thread_id,
                    "sender_id": msg["sender_id"],
                    "sender_name": msg["sender_name"],
                    "body": msg["body"],
                    "created_at": msg["created_at"],
                }
            }
        )

    async def chat_message(self, event):
        await self.send_json(event.get("data", {}))

    # ---------- DB helpers ----------
    @database_sync_to_async
    def _user_in_thread(self, thread_id: int, user_id: int) -> bool:
        return ChatThread.objects.filter(
            id=thread_id
        ).filter(
            Q(requester_id=user_id) | Q(donor_id=user_id)
        ).exists()

    @database_sync_to_async
    def _create_message_and_notify(self, thread_id: int, sender_id: int, body: str) -> dict:
        thread = ChatThread.objects.select_related("request", "requester", "donor").get(id=thread_id)

        if sender_id not in (thread.requester_id, thread.donor_id):
            raise PermissionError("Not allowed")

        # sender obj
        sender = thread.requester if sender_id == thread.requester_id else thread.donor
        sender_name = (sender.get_full_name() or sender.username or "User").strip()

        # create message
        m = ChatMessage.objects.create(thread=thread, sender_id=sender_id, body=body)

        thread.last_message_at = timezone.now()
        thread.save(update_fields=["last_message_at", "updated_at"])

        # notify the other participant (throttle to avoid spam notifications every second)  
        receiver_id = thread.donor_id if sender_id == thread.requester_id else thread.requester_id
        notif_key = f"s4l:chat_notif:{thread_id}:{receiver_id}"

        if cache.add(notif_key, 1, timeout=30):
            # respect mute settings
            pref = NotificationPreference.objects.filter(user_id=receiver_id).first()
            if not (pref and pref.is_muted("CHAT")):
                url = reverse("chat_thread_detail", args=[thread_id])
                Notification.objects.create(
                    user_id=receiver_id,
                    category="CHAT", 
                    title="New chat message",
                    body=f"New message on blood request #{thread.request_id}.",
                    url=url,
                    level="INFO",
                )

        return {
            "id": m.id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
        }