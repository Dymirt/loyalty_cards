
from django.shortcuts import render
from django.conf import settings

from dotykacka.tenancy import get_default_tenant

def index(request):
    tenant = get_default_tenant()
    return render(request, 'register_button.html', {
        'MEDIA_URL': settings.MEDIA_URL,
        'tenant': tenant,
    })
