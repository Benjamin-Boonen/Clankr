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



class AgentRun(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='runs')
    model = models.CharField(max_length=100)
    msgs = models.JSONField(default=list)       # full transcript incl. tool calls/results
    pending = models.JSONField(default=list)    # tool calls waiting for approval
    allowed = models.JSONField(default=list)    # tools the user said "always allow" for this run
    steps = models.IntegerField(default=0)
    status = models.CharField(max_length=10, default='running')


class Artifact(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='artifacts')
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10)      # html | svg | markdown
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class Attachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments')
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10)       # text | pdf | image
    text = models.TextField(blank=True)
    image_b64 = models.TextField(blank=True)
