from django.shortcuts import redirect


def index(request):
    """Keep the old URL while handing ownership to the marketing app."""

    return redirect("marketing:home")
