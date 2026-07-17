
from django.shortcuts import render
from dotykacka.tenancy import get_default_tenant


def index(request):
    tenant = get_default_tenant()
    return render(request, "register_button.html", {"tenant": tenant})
