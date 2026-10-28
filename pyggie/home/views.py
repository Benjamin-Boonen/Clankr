# home/views.py
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_exempt
from django.shortcuts import render, get_object_or_404
from .models import Chat, Message, AgentRun, Artifact
from . import agent, files
from django.http import HttpResponse
from django.core.cache import cache
from . import ollama


def _stop_key(chat_id):
    return f"clankr-stop:{chat_id}"


def _stop_requested(chat_id):
    return cache.get(_stop_key(chat_id)) is not None


def _parse(request):
    """JSON body, or multipart form (text fields + 'files')."""
    if request.content_type and request.content_type.startswith('multipart'):
        return request.POST.dict(), request.FILES.getlist('files')
    return json.loads(request.body), []


@login_required
def index(request):
    chats  = Chat.objects.filter(user=request.user).order_by('-created_at')
    models = ollama.get_models()
    return render(request, 'home/index.html', {'chats': chats, 'models': models})

@login_required
def get_chat(request, chat_id):
    chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    messages = [{'role': m.role, 'content': m.content, 'created_at': m.created_at,
                 'files': [a.name for a in m.attachments.all()]}
                for m in chat.messages.prefetch_related('attachments')]
    arts = list(chat.artifacts.values('id', 'title', 'kind'))
    return JsonResponse({'id': chat.id, 'title': chat.title, 'messages': messages, 'artifacts': arts})

@login_required
@require_POST
def send_message(request):
    data, uploads = _parse(request)
    content = data['content']
    model   = data.get('model', 'llama3')
    chat_id = data.get('chat_id')

    if chat_id:
        chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    else:
        chat = Chat.objects.create(user=request.user, title=content[:60])

    msg = Message.objects.create(chat=chat, role='user', content=content)
    upload_errors = files.save_attachments(msg, uploads)
    history = files.build_history(chat, ollama.get_caps(model), data.get('vision_model', '').strip())
    cache.delete(_stop_key(chat.id))

    full_reply = []

    def stream():
        # first chunk: send the chat_id so the frontend knows which chat this is
        yield f"data: {json.dumps({'chat_id': chat.id})}\n\n"
        if upload_errors:
            yield f"data: {json.dumps({'token': '> △ ' + '; '.join(upload_errors) + chr(10) + chr(10)})}\n\n"

        # kind is 'token', 'thinking' or 'tool'; only the answer is saved.
        # finally: whatever was written is saved, even when stopped or disconnected
        replies = ollama.chat_stream(model=model, messages=history)
        try:
            for kind, value in replies:
                if _stop_requested(chat.id):
                    break                      # the user pressed stop
                if kind == 'token':
                    full_reply.append(value)
                yield f"data: {json.dumps({kind: value})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': ollama.friendly_error(e)})}\n\n"
        finally:
            replies.close()                    # closes the connection to Ollama
            cache.delete(_stop_key(chat.id))
            if ''.join(full_reply).strip():
                Message.objects.create(chat=chat, role='ai', content=''.join(full_reply))
        yield "data: [DONE]\n\n"

    return StreamingHttpResponse(stream(), content_type='text/event-stream')


def _agent_stream(run, chat, gen, prefix_events=()):
    """Wrap an agent generator as SSE; saves the assistant's text as one AI message at the end."""
    texts = []
    def stream():
        yield f"data: {json.dumps({'chat_id': chat.id, 'run_id': run.id})}\n\n"
        stopped = False
        try:
            for kind, value in gen:
                if _stop_requested(chat.id):
                    stopped = True
                    break                      # the user pressed stop
                if kind == 'token': texts.append(value)
                yield f"data: {json.dumps({kind: value})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': ollama.friendly_error(e)})}\n\n"
        finally:
            # runs even if the browser disconnects mid-stream, so the reply is kept
            gen.close()
            cache.delete(_stop_key(chat.id))
            if stopped:
                run.status, run.pending = 'stopped', []
            run.save()
            if ''.join(texts).strip():
                Message.objects.create(chat=chat, role='ai', content=''.join(texts))
        yield "data: [DONE]\n\n"
    return StreamingHttpResponse(stream(), content_type='text/event-stream')

@login_required
@require_POST
def agent_send(request):
    data, uploads = _parse(request)
    content, model = data['content'], data.get('model', 'llama3')
    if data.get('chat_id'):
        chat = get_object_or_404(Chat, id=data['chat_id'], user=request.user)
    else:
        chat = Chat.objects.create(user=request.user, title=content[:60])
    msg = Message.objects.create(chat=chat, role='user', content=content)
    upload_errors = files.save_attachments(msg, uploads)
    cache.delete(_stop_key(chat.id))
    agent.copy_to_workspace(chat.id, msg)     # so run_python / read_file can open them
    history = files.build_history(chat, ollama.get_caps(model), data.get('vision_model', '').strip())
    run = AgentRun.objects.create(chat=chat, model=model, msgs=history)
    def gen():
        if upload_errors:
            yield 'token', '> △ ' + '; '.join(upload_errors) + '\n\n'
        yield from agent.drive(run, model)
    return _agent_stream(run, chat, gen())

@login_required
@require_POST
def agent_approve(request):
    data = json.loads(request.body)
    run = get_object_or_404(AgentRun, id=data['run_id'], chat__user=request.user, status='running')
    if not run.pending:
        return JsonResponse({'error': 'nothing pending'}, status=400)
    def gen():
        yield from agent.resume(run, bool(data.get('approve')), bool(data.get('always')))
        yield from agent.drive(run, run.model)
    return _agent_stream(run, run.chat, gen())

@login_required
@require_POST
def stop_reply(request):
    """Ask the reply in progress in this chat to stop. The running stream checks
    this flag between chunks; a run waiting for approval is ended right here."""
    data = json.loads(request.body)
    chat = get_object_or_404(Chat, id=data.get('chat_id'), user=request.user)
    cache.set(_stop_key(chat.id), True, timeout=300)
    AgentRun.objects.filter(chat=chat, status='running').update(status='stopped', pending=[])
    return JsonResponse({'ok': True})


@login_required
@xframe_options_exempt        # the UI previews artifacts in a sandboxed iframe; a
                               # frame-deny header made browsers show their
                               # own "can't show this page" error inside the bubble
def artifact_view(request, artifact_id):
    a = get_object_or_404(Artifact, id=artifact_id, chat__user=request.user)
    if a.kind == 'html':   body, ct = a.content, 'text/html'
    elif a.kind == 'svg':  body, ct = a.content, 'image/svg+xml'
    else:
        import html
        body, ct = f"<pre style='white-space:pre-wrap;font:14px system-ui;padding:1rem'>{html.escape(a.content)}</pre>", 'text/html'
    r = HttpResponse(body, content_type=ct + '; charset=utf-8')
    r['Content-Security-Policy'] = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'unsafe-inline'; img-src data:; connect-src 'none'"
    return r


# ─── artifacts & skills panels ───

@login_required
def artifacts_list(request):
    """All of the user's artifacts (most recent first)."""
    arts = (Artifact.objects.filter(chat__user=request.user)
           .select_related('chat').order_by('-created_at'))
    return JsonResponse({'artifacts': [
        {'id': a.id, 'title': a.title, 'kind': a.kind, 'chat_id': a.chat_id,
         'chat_title': a.chat.title, 'created_at': a.created_at} for a in arts]})


@login_required
@require_POST
def artifact_create(request):
    """Create an artifact by hand from the Artifacts panel."""
    data, _ = _parse(request)
    title = (data.get('title') or 'Untitled').strip()[:200]
    kind = data.get('kind', 'markdown')
    content = data.get('content') or ''
    if kind not in ('html', 'svg', 'markdown'):
        return JsonResponse({'error': 'kind must be html, svg or markdown'}, status=400)
    if not content.strip():
        return JsonResponse({'error': 'content is empty'}, status=400)
    chat_id = data.get('chat_id')
    if chat_id:
        chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    else:                      # no conversation open yet: start one for it
        chat = Chat.objects.create(user=request.user, title=title[:60])
    a = Artifact.objects.create(chat=chat, title=title, kind=kind, content=content)
    return JsonResponse({'id': a.id, 'title': a.title, 'kind': a.kind, 'chat_id': chat.id})


@login_required
def skills_list(request):
    return JsonResponse({'skills': agent.list_skills()})


@login_required
@require_POST
def skill_create(request):
    data, _ = _parse(request)
    ok, err = agent.create_skill(data.get('name') or '', data.get('content') or '')
    if err:
        return JsonResponse({'error': err}, status=400)
    return JsonResponse({'ok': True})
