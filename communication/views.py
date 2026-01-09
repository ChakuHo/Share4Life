from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import Notification

@login_required
def inbox(request):
    items = request.user.notifications.order_by("-created_at")[:100]
    return render(request, "communication/inbox.html", {"items": items})

@login_required
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.mark_read()
    return redirect("inbox")