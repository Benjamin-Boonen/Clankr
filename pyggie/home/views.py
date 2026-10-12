# home/views.py
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render, get_object_or_404
from .models import Chat, Message
from . import ollama
from ddgs import DDGS


@login_required
def index(request):
    chats  = Chat.objects.filter(user=request.user).order_by('-created_at')
    models = ollama.get_models()
    return render(request, 'home/index.html', {'chats': chats, 'models': models})

@login_required
def get_chat(request, chat_id):
    chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    messages = list(chat.messages.values('role', 'content', 'created_at'))
    return JsonResponse({'id': chat.id, 'title': chat.title, 'messages': messages})

@login_required
@require_POST
def send_message(request):
    data    = json.loads(request.body)
    content = data['content']
    model   = data.get('model', 'llama3')
    chat_id = data.get('chat_id')

    if chat_id:
        chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    else:
        chat = Chat.objects.create(user=request.user, title=content[:60])

    Message.objects.create(chat=chat, role='user', content=content)

    history = [
        {'role': 'assistant' if m.role == 'ai' else 'user', 'content': m.content}
        for m in chat.messages.all()
    ]

    full_reply = []

    def search(query, n=7):
        hits = [{"title": h["title"], "url": h["href"], "description": h["body"]}
        for h in DDGS().text(query, max_results=5)]
        return hits
    
    Message.objects.create(chat=chat, role='web-search', content=search(content))
    def stream():
        # first chunk: send the chat_id so the frontend knows which chat this is
        yield f"data: {json.dumps({'chat_id': chat.id})}\n\n"

        for token in ollama.chat_stream(model=model, messages=history):
            full_reply.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        # save complete response once done
        Message.objects.create(chat=chat, role='ai', content=''.join(full_reply))
        yield "data: [DONE]\n\n"

    return StreamingHttpResponse(stream(), content_type='text/event-stream')
