
from django.shortcuts import render
from django.conf import settings

def index(request):
    return render(request, 'register_button.html', {
        'MEDIA_URL': settings.MEDIA_URL
    })
