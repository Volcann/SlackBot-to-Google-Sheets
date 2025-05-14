from django.urls import path
from . import views

urlpatterns = [
    path("update/sheets/", views.get_slack_messages_html, name="slack_messages"),
    path('pmo-report/', views.pmo_report, name='pmo_report'),
    path('pmo-report/<str:user_id>/', views.member_messages, name='member_messages'),
    path("slack/history/", views.get_slack_messages, name="slack_history"),
]
