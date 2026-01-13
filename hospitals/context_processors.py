from .models import OrganizationMembership

def org_context(request):
    if not request.user.is_authenticated:
        return {"org_membership": None, "org_application": None}

    org_membership = (
        OrganizationMembership.objects
        .filter(user=request.user, is_active=True, organization__status="APPROVED")
        .select_related("organization")
        .order_by("-added_at")
        .first()
    )

    org_application = (
        OrganizationMembership.objects
        .filter(user=request.user)
        .select_related("organization")
        .order_by("-added_at")
        .first()
    )

    return {"org_membership": org_membership, "org_application": org_application}