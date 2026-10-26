# home/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('',                    views.index,       name='index'),
    path('chat/<int:chat_id>/', views.get_chat,    name='get_chat'),
    path('send/',               views.send_message, name='send_message'),
    path('agent/send/',    views.agent_send,    name='agent_send'),
    path('agent/approve/', views.agent_approve, name='agent_approve'),
    path('stop/',               views.stop_reply,  name='stop_reply'),
    path('artifact/<int:artifact_id>/', views.artifact_view, name='artifact'),
    # artifacts & skills panels
    path('artifacts/',       views.artifacts_list,  name='artifacts_list'),
    path('artifact/create/', views.artifact_create, name='artifact_create'),
    path('skills/',          views.skills_list,    name='skills_list'),
    path('skills/create/',   views.skill_create,   name='skill_create'),
]
