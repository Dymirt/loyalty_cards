from django.db import models
from django.utils import timezone

class AccessToken(models.Model):
	token = models.CharField(max_length=1000)
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return self.created_at.strftime("%Y-%m-%d %H:%M:%S")

class Klient (models.Model):
	klient_id = models.CharField(max_length=60, unique=True)
	email = models.EmailField(max_length=100, blank=True, null=True)
	phone = models.CharField(max_length=20, blank=True, null=True)
	first_name = models.CharField(max_length=100, blank=True, null=True)
	last_name = models.CharField(max_length=100, blank=True, null=True)
	google_jwt_url = models.CharField(max_length=10000, blank=True, null=True)

	def __str__(self):
		return f"{self.first_name} {self.last_name} ({self.klient_id} ({self.pk}))"
