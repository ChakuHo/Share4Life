from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect

def donor_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not getattr(request.user, "is_donor", False):
            messages.warning(request, "Enable Donor role in your profile to access this feature.")
            return redirect("profile_edit")
        return view_func(request, *args, **kwargs)
    return _wrapped

def recipient_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not getattr(request.user, "is_recipient", False):
            messages.warning(request, "Enable Recipient role in your profile to access this feature.")
            return redirect("profile_edit")
        return view_func(request, *args, **kwargs)
    return _wrapped