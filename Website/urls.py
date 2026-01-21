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
    path('/', views.flips, name='flips'),
    path('', views.flips, name='flips'),
    path('flips/add/', views.add_flip, name='add_flip'),
    path('flips/edit/', views.edit_flip, name='edit_flip'),
    path('flips/delete/<int:item_id>/', views.delete_flip, name='delete_flip'),
    path('api/flips/stats/', views.flips_stats_api, name='flips_stats_api'),
    path('api/flips/data/', views.flips_data_api, name='flips_data_api'),
    path('flips/delete_single/', views.delete_single_flip, name='delete_single_flip'),
    path('flips/item/<int:item_id>/', views.item_detail, name='item_detail'),
    path('api/items/', views.item_search_api, name='item_search_api'),
    path('api/items/random/', views.random_item_api, name='random_item_api'),
    path('item_search/', views.item_search, name='item_search'),
    path('api/item/data/', views.item_data_api, name='item_data_api'),
    path('api/item/history/', views.item_history_api, name='item_history_api'),
    path('alerts/', views.alerts, name='alerts'),
    path('alerts/create/', views.create_alert, name='create_alert'),
    path('api/alerts/', views.alerts_api, name='alerts_api'),
    path('api/alerts/dismiss/', views.dismiss_triggered_alert, name='dismiss_triggered_alert'),
    path('api/alerts/delete/', views.delete_alerts, name='delete_alerts'),
    path('api/alerts/update/', views.update_alert, name='update_alert'),
    path('api/alerts/group/', views.group_alerts, name='group_alerts'),
    path('api/alerts/groups/delete/', views.delete_groups, name='delete_groups'),
    path('api/alerts/unlink-groups/', views.unlink_groups, name='unlink_groups'),
    path('alerts/<int:alert_id>/', views.alert_detail, name='alert_detail'),
    path('api/alerts/<int:alert_id>/update/', views.update_single_alert, name='update_single_alert'),
    path('api/favorites/add/', views.add_favorite, name='add_favorite'),
    path('api/favorites/remove/', views.remove_favorite, name='remove_favorite'),
    path('api/favorites/groups/delete/', views.delete_favorite_group, name='delete_favorite_group'),
    path('api/favorites/update-group/', views.update_favorite_group, name='update_favorite_group'),
    path('favorites/', views.favorites_page, name='favorites'),
    # Authentication
    path('auth/', views.auth_page, name='auth'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/change-email/', views.change_email_view, name='change_email'),
    path('settings/request-password-reset/', views.request_password_reset_view, name='request_password_reset'),
    path('reset-password/<str:token>/', views.reset_password_view, name='reset_password'),
    path('settings/delete-account/', views.delete_account_view, name='delete_account'),
]
