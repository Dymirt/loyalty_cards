"""Read-only HTTP endpoints for customer contact exports."""

from urllib.parse import urlencode

from django.core.paginator import EmptyPage, Paginator
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from customers.models import Customer
from .customer_export_auth import customer_export_token_required


DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


def _positive_integer(value, default, *, maximum=None):
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError from exc
    if number < 1 or (maximum is not None and number > maximum):
        raise ValueError
    return number


def _page_url(request, page_number, page_size):
    if page_number is None:
        return None
    query = urlencode({"page": page_number, "page_size": page_size})
    path = reverse("customers_api:clients")
    return request.build_absolute_uri(f"{path}?{query}")


@require_GET
@customer_export_token_required
def client_list(request):
    try:
        page_number = _positive_integer(request.GET.get("page"), 1)
        page_size = _positive_integer(
            request.GET.get("page_size"),
            DEFAULT_PAGE_SIZE,
            maximum=MAX_PAGE_SIZE,
        )
    except ValueError:
        return JsonResponse(
            {
                "detail": (
                    f"page must be positive and page_size must be between "
                    f"1 and {MAX_PAGE_SIZE}."
                )
            },
            status=400,
            headers={"Cache-Control": "no-store"},
        )

    customers = (
        Customer.objects.filter(
            tenant=request.customer_export_api_token.tenant,
        )
        .exclude(email__isnull=True)
        .exclude(email="")
        .order_by("pk")
        .values("klient_id", "first_name", "last_name", "email")
    )
    paginator = Paginator(customers, page_size)
    try:
        page = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse(
            {"detail": "Page does not exist."},
            status=404,
            headers={"Cache-Control": "no-store"},
        )

    response = JsonResponse(
        {
            "count": paginator.count,
            "page": page.number,
            "page_size": page_size,
            "next": _page_url(
                request,
                page.next_page_number() if page.has_next() else None,
                page_size,
            ),
            "previous": _page_url(
                request,
                page.previous_page_number() if page.has_previous() else None,
                page_size,
            ),
            "results": [
                {
                    "client_id": customer["klient_id"],
                    "first_name": customer["first_name"] or "",
                    "last_name": customer["last_name"] or "",
                    "email": customer["email"],
                }
                for customer in page.object_list
            ],
        }
    )
    response["Cache-Control"] = "private, no-store"
    return response
