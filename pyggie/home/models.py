from django.db import models
from django.contrib.auth.models import User

class Chat(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chats')
    def __str__(self):
        return self.title or f"Chat {self.id}"


class Message(models.Model):
    ROLES = [('user', 'User'), ('ai', 'AI')]

    chat    = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    role    = models.CharField(max_length=10, choices=ROLES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

