from django.shortcuts import render


def test(request):
    return render(request, 'test.html')


def home(request):
    return render(request, 'home.html')


def flips(request):
    return render(request, 'flips.html')


def item_search(request):
    return render(request, 'item_search.html')


def alerts(request):
    return render(request, 'alerts.html')
