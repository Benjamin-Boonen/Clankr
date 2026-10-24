# home/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('',                    views.index,       name='index'),
    path('chat/<int:chat_id>/', views.get_chat,    name='get_chat'),
    path('send/',               views.send_message, name='send_message'),
    path('agent/send/',    views.agent_send,    name='agent_send'),
    path('agent/approve/', views.agent_approve, name='agent_approve'),
    path('artifact/<int:artifact_id>/', views.artifact_view, name='artifact'),
]
