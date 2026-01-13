from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
from .models import OrganizationMembership


def org_member_required(roles=None):
    roles = set(roles or [])

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")

            qs = OrganizationMembership.objects.filter(
                user=request.user,
                is_active=True,
                organization__status="APPROVED",
            )
            if roles:
                qs = qs.filter(role__in=list(roles))

            membership = qs.select_related("organization").first()
            if not membership:
                messages.error(request, "You do not have access to the institution portal.")
                return redirect("home")

            request.org_membership = membership
            request.organization = membership.organization
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator