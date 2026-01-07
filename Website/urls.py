"""
URL configuration for Website project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('test/', views.test, name='test'),
    path('home/', views.home, name='home'),
    path('flips/', views.flips, name='flips'),
    path('flips/add/', views.add_flip, name='add_flip'),
    path('api/items/', views.item_search_api, name='item_search_api'),
    path('item_search/', views.item_search, name='item_search'),
    path('alerts/', views.alerts, name='alerts'),
]
