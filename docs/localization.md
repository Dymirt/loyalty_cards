# Język interfejsu i dodawanie tłumaczeń

Językiem źródłowym i jedynym językiem udostępnionym przy starcie SaaS jest
polski (`pl`). Django ustawia język odpowiedzi przez `LocaleMiddleware`, a
aktywny kod języka trafia do atrybutu `lang` dokumentu HTML. Wszystkie aktywne
szablony, etykiety formularzy, statusy i komunikaty przeznaczone dla użytkownika
są oznaczone mechanizmem tłumaczeń Django.

## Dodanie nowego języka

1. Dodaj język do `LANGUAGES` w `loyalty_platform/settings.py`, na przykład
   `("en", _("English"))`. Nie zmieniaj `LANGUAGE_CODE = "pl"`.
2. Utwórz katalog wiadomości:

   ```bash
   python manage.py makemessages -l en \
     --ignore 'turnkey_app/*' \
     --ignore 'local-data/*' \
     --ignore 'media/*' \
     --ignore 'staticfiles/*'
   ```

3. Przetłumacz wartości `msgstr` w `locale/en/LC_MESSAGES/django.po`. Polskie
   teksty `msgid` pozostają bez zmian.
4. Skompiluj katalog i uruchom testy:

   ```bash
   python manage.py compilemessages
   python manage.py test core.tests.test_localization --noinput
   python manage.py test --noinput
   ```

5. Dopiero po przetłumaczeniu całego katalogu dodaj w portalu formularz wyboru
   języka wysyłający `POST` do standardowego widoku Django `set_language` pod
   adresem `/i18n/setlang/`. Nie zapisuj języka firmy w polach integracji ani w
   danych dostawców.

Obraz Dockera zawiera GNU gettext, więc `makemessages` i `compilemessages`
działają w tym samym środowisku co aplikacja. Tekstów dla użytkownika nie należy
składać przez konkatenację: używaj nazwanych parametrów, `translate`,
`blocktranslate` oraz `ngettext`, gdy liczba zmienia odmianę.

## Zasady przeglądu

- Nie dodawaj nieoznaczonych tekstów do aktywnych szablonów, formularzy, widoków
  ani wyników testów połączeń widocznych w panelu.
- Nazwy produktów i protokołów, takie jak Apple Wallet, Google Wallet, Brevo,
  Dotykačka, SMTP, API, Client ID i Refresh Token, pozostają nazwami własnymi.
- Historyczne `turnkey_app` nie jest aktywną częścią interfejsu i nie jest
  włączane do katalogów tłumaczeń.
- Zmiana języka nie może zmieniać kodów statusów, kluczy idempotencji, danych
  integracji ani zapisów historycznych w bazie.
