from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

app_name = 'dotykacka'

urlpatterns = [
	path('acces_token', views.get_acces_token, name='acces_token'),
	path('customers', views.get_all_costumers, name='customers'),
	path('register', views.register_customer_form, name='register'),
	#				<form action="{% url 'dotykacka:send_pass' customer.barcode_decode %}" method="post">
	#				{% csrf_token %}
	#				<button type="submit">Send Pass</button>
	#				</form>
	path('send_pass/<str:barcode>', views.send_pass, name='send_pass'),
    # add all to brevo
	path('add_all_to_brevo', views.add_all_to_brevo, name='add_all_to_brevo'),
	path('generate_jwt_passes', views.generate_jwt_passes, name='generate_jwt_passes'),
	path('send_passes_to_all', views.send_all_passes, name='send_passes_to_all'),
	# add single to brevo
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
