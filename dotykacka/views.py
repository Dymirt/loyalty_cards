from django.shortcuts import render
import dotykacka.api_utils as dotykacka_api
from .settings import DOTYKACKA_CLOUD_ID
import requests
import json
from django.shortcuts import redirect
from .models import Klient
from django.conf import settings
from django.core.mail import EmailMessage
from dotykacka.apple_wallet_pass import build_pass
import os
from dotykacka.brevo import send_contact_to_brevo
from .google_wallet.JWT  import get_wallet_url

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.mail import EmailMultiAlternatives
from django.views.decorators.http import require_POST
from multiprocessing import Process
from threading import Thread



import base64


superuser_required = user_passes_test(
	lambda user: user.is_active and user.is_superuser,
	login_url="/admin/login/",
)


@superuser_required
def get_acces_token(request):
	access_token = dotykacka_api.get_valid_access_token()
	return render(request, 'dotykacka/access_token.html', {
		'access_token_available': bool(access_token),
	})

@superuser_required
def get_all_costumers(request):

	if not request.user.is_superuser:
		return render(request, 'dotykacka/customers.html', {
			'error': "Nie masz uprawnień do przeglądania tej strony."
		})
	access_token = dotykacka_api.get_valid_access_token()
	base_url = f"https://api.dotykacka.cz/v2/clouds/{DOTYKACKA_CLOUD_ID}/customers"
	headers = {
		"Authorization": f"Bearer {access_token}"
	}

	all_customers = []
	page = 1
	error = []


	while True:
		params = {
			"page": page,
		}
		response = requests.get(
			base_url,
			headers=headers,
			params=params,
			timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
		)
		if response.status_code != 200:
			break  # stop loop on error
		response_json = response.json()

		page_data = response_json.get('data', [])
		all_customers.extend(page_data)

		if str(page) == str(response_json.get('lastPage')):
			break  # no more pages
		page += 1

	target_group_id = str(settings.DOTYKACKA_DISCOUNT_GROUP_ID)
	all_customers = [
		c for c in all_customers if str(c.get('_discountGroupId')) == target_group_id
	]
	# process customers
	for customer in all_customers:
		if customer.get('barcode'):
			try:
				customer['barcode_decode'] = customer['barcode'].strip("MB-")
			except Exception as e:
				error.append(e)
			if len(customer['barcode_decode']) > 3:
				customer['barcode_decode'] = ''
	if not settings.DEBUG:
		error.clear()

	return render(request, 'dotykacka/customers.html', {
		'customers': all_customers,
		'error': response.json() if response.status_code != 200 else None,
	})

def register_customer_form(request):
	if request.method == 'GET':
		return render(request, 'dotykacka/register_customer_form.html', {
        'MEDIA_URL': settings.MEDIA_URL
    })
	elif request.method == 'POST':

		barcode = request.POST.get('barcode')
		if barcode:
			barcode = barcode.upper().strip()
			if not barcode.startswith("MB-") or (barcode[3:].isdigit() and len(barcode) > 6):
				messages.error(request, "Nieprawidłowy format kodu kreskowego.")
				return redirect('index')

			try :
				Klient.objects.get(klient_id=barcode)
				messages.error(request, "Ta karta już istnieje w bazie danych.")
				return redirect('index')
			except Klient.DoesNotExist:
				pass # OK, can proceed

		Klient.objects.create(
			klient_id=barcode,
			email=request.POST.get('email'),
			phone=request.POST.get('tel'),
			first_name=request.POST.get('firstName'),
			last_name=request.POST.get('lastName'),
			google_jwt_url='',
			)

		# Generate Google Wallet Pass asynchronously

		klient = Klient.objects.get(klient_id=barcode)
		try:
			goole_pass_thread = update_klient_google_jwt_url_async(klient.pk)
		except Exception as e:
			messages.success(request, "Zarejestrowano klienta, ale nie udało się wygenerować Google Wallet Pass. Poproś administratora o ręczną synchronizację.")
			return redirect('index')

		# Register customer in Dotykacka asynchronously
		try:
			call_register_dotykacka_customer_async(klient)
		except Exception as e:
			messages.success(request, "Zarejestrowano klienta, ale nie udało się zsynchronizować z Dotykačką. Poproś administratora o ręczną synchronizację.")
			return redirect('index')


		# Send email with passes
		try:
			Thread(target=lambda: send_pass_email(klient=klient, wait_for=goole_pass_thread), daemon=True).start()
		except Exception as e:
			messages.success(request, "Zarejestrowano klienta, ale nie udało się wysłać e-maila. Poprośimy o kontakt z administratorem w celu otrzymania karty Apple Wallet.")
			return redirect('index')

		messages.success(request, "Zarejestrowano kartę klienta.")
		return redirect('index')



############################################################################
# Register a specific Klient in Dotykacka asynchronously
############################################################################

def call_register_dotykacka_customer_async(klient: Klient):
    def _worker():
        try:
            dotykacka_api.register_dotykacka_customer(
                klient.klient_id,
                klient.first_name,
                klient.last_name,
                klient.email,
                klient.phone
            )
            print(f"[INFO] Registered {klient.email} in Dotykačka")
        except Exception as e:
            print(f"[ERROR] Dotykačka sync failed for {klient.email}: {e}")

    Thread(target=_worker, daemon=True).start()


###########################################################################
# Generate Google Wallet Pass for a specific Klient and update the database
############################################################################

def update_klient_google_jwt_url(klient_id: int):
    try:
        klient = Klient.objects.get(pk=klient_id)
    except Klient.DoesNotExist:
        return  # or raise an exception

    klient.google_jwt_url=get_wallet_url(
        name=f"{klient.first_name} {klient.last_name}",
        customer_id=klient.klient_id,
		customer_image_url=f"{settings.APP_BASE_URL}/media/cropped_images/cropped_image_{klient.klient_id.strip('MB-')}.jpg")
    klient.save()

def update_klient_google_jwt_url_async(klient_id: int):
    t = Thread(target=lambda: update_klient_google_jwt_url(klient_id))
    t.start()
    return t


############################################################################
# Send email with Google Wallet and Apple Wallet passes
############################################################################


def send_pass_email(barcode=None, google_jwt_url=None, first_name=None, last_name=None, email=None, klient: Klient=None, wait_for=None):

    if wait_for:
        wait_for.join()  # wait for the thread to finish

    if klient:
        barcode = klient.klient_id
        first_name = klient.first_name
        last_name = klient.last_name
        email = klient.email
        klient.refresh_from_db(fields=["google_jwt_url"])
        google_jwt_url = klient.google_jwt_url

    customer_name = f"{first_name} {last_name}"
    google_jwt_url = google_jwt_url
    pass_file_name = f"pass_{barcode.strip('MB-')}.pkpass"
    pass_file_path = os.path.join(settings.MEDIA_ROOT, f"output_passes/{pass_file_name}")
    recipient_email = email

    subject = "Twoja karta gościa Atelier-Café Marta Banaszek"
    # Plaintext fallback (dla klientów bez HTML w mailach)
    text_content = f"""
    Dzień dobry {customer_name},

    Twoja karta lojalnościowa Atelier Café jest gotowa 🎉
    Google Wallet: {google_jwt_url}
    Apple Wallet: karta w załączniku (.pkpass)

    Pozdrawiamy,
    Zespół Atelier Café
    """

    # HTML treść
    html_content = f"""
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width">
        <title>Karta lojalnościowa Atelier Café</title>
        <style>
        /* Some clients support embedded styles; critical styles are inlined below too */
        @media screen and (max-width: 620px) {{
            .container {{ width: 100% !important; }}
            .stack {{ display:block !important; width:100% !important; }}
            .btn img {{ height:44px !important; }}
        }}
        </style>
    </head>
    <body style="margin:0; padding:0; background:#f5f5f7;">
        <!-- Full width wrapper -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f5f5f7;">
        <tr>
            <td align="center" style="padding:24px 12px;">
            <!-- Centered container -->
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" class="container" style="width:600px; max-width:600px; background:#ffffff; border-radius:12px; overflow:hidden;">
                <tr>
                <td align="center" style="padding:24px 24px 8px 24px;">
                    <img src="{settings.APP_BASE_URL}/media/logo_atelier_cafe.png"
                        width="120" height="60" alt="Atelier-Café Marta Banaszek"
                        style="display:block; width:120px; height:auto; margin:0 auto;">
                </td>
                </tr>

                <tr>
                <td style="padding:8px 24px 0 24px; font-family:Arial,Helvetica,sans-serif; color:#111; font-size:18px; line-height:1.5;">
                    <p style="margin:0 0 12px 0;">Dzień dobry {customer_name},</p>
                    <p style="margin:0 0 12px 0;">Twoja karta lojalnościowa Atelier Café jest gotowa 🎉</p>
                    <p style="margin:0 0 16px 0;">Dodaj ją do swojego portfela:</p>
                </td>
                </tr>

                <!-- Card preview image -->
                <tr>
                <td align="center" style="padding:0 24px 8px 24px;">
                    <img src="{settings.APP_BASE_URL}/media/cards/card-{barcode.strip('MB-')}/{barcode}_front.jpg"
                        alt="Karta lojalnościowa"
                        width="552"
                        style="display:block; width:100%; max-width:552px; height:auto; border-radius:10px;">
                </td>
                </tr>

                <!-- Buttons row -->
                <tr>
                <td align="center" style="padding:8px 24px 24px 24px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <!-- Google Wallet -->
                        <td class="stack" align="center" style="padding:6px 8px;">
                        <a href="{google_jwt_url}" target="_blank" style="text-decoration:none;">
                            <img src="{settings.APP_BASE_URL}/media/add-wallet-google.png"
                                alt="Dodaj do Google Wallet"
                                height="44"
                                style="display:block; height:44px; width:auto;">
                        </a>

                        </td>
                        <!-- Apple Wallet -->
                        <td class="stack" align="center" style="padding:6px 8px;">
                        <a href="{settings.APP_BASE_URL}/media/output_passes/{pass_file_name}" target="_blank" style="text-decoration:none;">
                            <img src="{settings.APP_BASE_URL}/media/add-to-apple-wallet-logo.png"
                                alt="Dodaj do Apple Wallet"
                                height="44"
                                style="display:block; height:44px; width:auto;">
                        </a>
                        </td>
                    </tr>
                    </table>
                    <div style="font-family:Arial,Helvetica,sans-serif; color:#666; font-size:13px; margin-top:12px;">
                    Jeśli przycisk Apple nie działa, otwórz załączony plik <b>.pkpass</b> na iPhonie.
                    </div>
                </td>
                </tr>

                <!-- Footer -->
                <tr>
                <td style="padding:0 24px 24px 24px; font-family:Arial,Helvetica,sans-serif; color:#444; font-size:14px; line-height:1.5;">
                    <p style="margin:0 0 8px 0;">Pozdrawiamy,<br>Zespół Atelier-Café Marta Banaszek</p>
                    <p style="margin:0; color:#888; font-size:12px;">
                    Jeśli nie rejestrowałeś(-aś) karty, zignoruj tę wiadomość.
                    </p>
                </td>
                </tr>
            </table>

            <!-- small spacer -->
            <div style="height:24px; line-height:24px; font-size:24px;">&nbsp;</div>
            </td>
        </tr>
        </table>
    </body>
    </html>
    """

    # Email z HTML
    email = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [recipient_email])
    email.attach_alternative(html_content, "text/html")

    # Attach the .pkpass file
    with open(pass_file_path, 'rb') as f:
        email.attach(filename='atelier_card.pkpass', content=f.read(), mimetype='application/vnd.apple.pkpass')

    email.send()



@superuser_required
@require_POST
def send_pass(request, barcode):
	if request.method == 'POST':
		pass_index = barcode.strip("MB-")
		pass_file_name = f"pass_{pass_index}.pkpass"
		pass_file_path = os.path.join(settings.MEDIA_ROOT, f"output_passes/{pass_file_name}")

		if not os.path.exists(pass_file_path):
			messages.error(request, "Nie znaleziono pliku karty.")
			return redirect('dotykacka:customers')

		try:
			klient = Klient.objects.get(klient_id=barcode)
			Thread(target=lambda: send_pass_email(klient.klient_id, klient.google_jwt_url, klient.first_name, klient.last_name, klient.email), daemon=True).start()
			messages.success(request, "Karta została wysłana.")
		except Klient.DoesNotExist:
			messages.error(request, "Nie znaleziono klienta.")
		except Exception as e:
			messages.error(
				request,
				f"Nie udało się wysłać karty: {str(e)}. Poproś administratora o przesłanie karty ręcznie."
			)

		return redirect('dotykacka:customers')

############################################################################
# Bulk operations
############################################################################

@superuser_required
@require_POST
def add_all_to_brevo(request):
	if request.method == 'POST':
		klients = Klient.objects.all()
		for klient in klients:
			send_contact_to_brevo(klient)
		return redirect('dotykacka:customers')
	return render(request, 'dotykacka/customers.html', {
		'error': "Invalid request method."
	})

@superuser_required
@require_POST
def generate_jwt_passes(request):
	if request.method == 'POST':
		klients = Klient.objects.all()
		for klient in klients:
			if klient.email and klient.klient_id:
				try:
					jwt_url = get_wallet_url(name=f"{klient.first_name} {klient.last_name}", customer_id=klient.klient_id, customer_image_url=f"{settings.APP_BASE_URL}/media/cropped_images/cropped_image_{klient.klient_id.strip('MB-')}.jpg")
					klient.google_jwt_url = jwt_url
					klient.save()
				except Exception as e:
					messages.error(request, f"Nie udało się wygenerować Google Wallet Pass dla {klient.klient_id}: {str(e)}")
					continue
			send_pass_email(klient=klient)
		messages.success(request, "Wygenerowano Google Wallet Pass dla wszystkich klientów.")
		return redirect('dotykacka:customers')

import csv
from datetime import datetime


@superuser_required
@require_POST
def send_all_passes(request):
    if request.method == "POST":
        log_dir = _get_writable_log_dir()
        log_path = os.path.join(log_dir, "send_passes_log.csv")

        created_now = not os.path.exists(log_path)
        success_count = 0
        fail_count = 0

        with open(log_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Write header once
            if created_now:
                writer.writerow(["timestamp", "klient_id", "email", "status", "error"])

            # Iterate safely in chunks
            for klient in Klient.objects.all().iterator(chunk_size=200):
                if klient.email and klient.klient_id:
                    try:
                        send_pass_email(klient=klient)
                        writer.writerow([
                            datetime.now().isoformat(sep=" ", timespec="seconds"),
                            klient.klient_id, klient.email, "SENT", ""
                        ])
                        success_count += 1
                    except Exception as e:
                        writer.writerow([
                            datetime.now().isoformat(sep=" ", timespec="seconds"),
                            klient.klient_id, klient.email, "FAILED", str(e)
                        ])
                        fail_count += 1

        messages.success(
            request,
            f"Wysłano {success_count} kart (nieudane: {fail_count}). "
            f"Log zapisany w: {log_path}"
        )
        return redirect("dotykacka:customers")

import tempfile

def _get_writable_log_dir():
    candidates = []

    # Prefer MEDIA_ROOT/logs (normally writable)
    if getattr(settings, "MEDIA_ROOT", None):
        candidates.append(os.path.join(settings.MEDIA_ROOT, "logs"))

    # Next, a local var dir inside the project (if you chown it)
    candidates.append(os.path.join(settings.BASE_DIR, "var", "logs"))

    # Last resort: system temp
    candidates.append(os.path.join(tempfile.gettempdir(), "turnkey_logs"))

    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            # Probe write access
            probe = os.path.join(d, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return d
        except Exception:
            continue

    # If everything fails, raise a clear error
    raise PermissionError("No writable directory found for logs.")
