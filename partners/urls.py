from django.urls import path

from partners import views

app_name = 'partners'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('actors/', views.actor_list, name='actor_list'),
    path('actors/add/', views.actor_create, name='actor_create'),
    path('actors/<int:pk>/', views.actor_detail, name='actor_detail'),
    path('actors/<int:pk>/edit/', views.actor_edit, name='actor_edit'),
    path('log/', views.observation_log, name='observation_log'),
    path('observations/', views.observation_list, name='observation_list'),
    path('bands/', views.band_list, name='band_list'),
    path('bands/recompute/', views.band_recompute, name='band_recompute'),
]
