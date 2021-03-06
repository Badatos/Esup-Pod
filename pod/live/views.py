from django.shortcuts import render
from django.shortcuts import get_object_or_404
from .models import Building, Broadcaster, HeartBeat
from .forms import LivePasswordForm
from django.conf import settings
from django.shortcuts import redirect
from django.contrib.sites.shortcuts import get_current_site
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.db.models import Prefetch
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, HttpResponseBadRequest
import json
from django.utils import timezone

VIEWERS_ONLY_FOR_STAFF = getattr(
        settings, 'VIEWERS_ONLY_FOR_STAFF', False)

HEARTBEAT_DELAY = getattr(
        settings, 'HEARTBEAT_DELAY', 45)


def lives(request):  # affichage des directs
    site = get_current_site(request)
    buildings = Building.objects.all().filter(sites=site).prefetch_related(
        Prefetch("broadcaster_set", queryset=Broadcaster.objects.filter(
            public=True)))
    return render(request, "live/lives.html", {
        'buildings': buildings
    })


def get_broadcaster_by_slug(slug, site):
    broadcaster = None
    if slug.isnumeric():
        try:
            broadcaster = Broadcaster.objects.get(
                id=slug, building__sites=site)
        except ObjectDoesNotExist:
            pass
    if broadcaster is None:
        broadcaster = get_object_or_404(Broadcaster, slug=slug,
                                        building__sites=site)
    return broadcaster


def video_live(request, slug):  # affichage des directs
    site = get_current_site(request)
    broadcaster = get_broadcaster_by_slug(slug, site)
    if broadcaster.is_restricted and not request.user.is_authenticated():
        iframe_param = 'is_iframe=true&' if (
            request.GET.get('is_iframe')) else ''
        return redirect(
            '%s?%sreferrer=%s' % (
                settings.LOGIN_URL,
                iframe_param,
                request.get_full_path())
        )
    is_password_protected = (
        broadcaster.password is not None and broadcaster.password != '')
    if is_password_protected and not (request.POST.get('password')
                                      and request.POST.get(
                                          'password') == broadcaster.password):
        form = LivePasswordForm(
            request.POST) if request.POST else LivePasswordForm()
        if (request.POST.get('password')
                and request.POST.get('password') != broadcaster.password):
            messages.add_message(
                request, messages.ERROR,
                _('The password is incorrect.'))
        return render(
            request, 'live/live.html', {
                'broadcaster': broadcaster,
                'form': form,
                'heartbeat_delay': HEARTBEAT_DELAY
            }
        )
    return render(request, "live/live.html", {
        'broadcaster': broadcaster,
        'heartbeat_delay': HEARTBEAT_DELAY
    })


""" use rest api to change status
def change_status(request, slug):
    broadcaster = get_object_or_404(Broadcaster, slug=slug)
    if request.GET.get("online") == "1":
        broadcaster.status = 1
    else:
        broadcaster.status = 0
    broadcaster.save()
    return HttpResponse("ok")
"""


def heartbeat(request):
    if request.is_ajax() and request.method == "GET":
        broadcaster_id = int(request.GET.get('liveid', 0))
        broadcast = get_object_or_404(
            Broadcaster, id=broadcaster_id)
        key = request.GET.get('key', '')
        heartbeat, created = HeartBeat.objects.get_or_create(
            viewkey=key, broadcaster_id=broadcaster_id)
        if created:
            if not request.user.is_anonymous:
                heartbeat.user = request.user
        heartbeat.last_heartbeat = timezone.now()
        heartbeat.save()

        mimetype = 'application/json'
        viewers = broadcast.viewers.values(
            'first_name', 'last_name', 'is_superuser')
        can_see = (VIEWERS_ONLY_FOR_STAFF and
                   request.user.is_staff) or not VIEWERS_ONLY_FOR_STAFF
        return HttpResponse(json.dumps(
            {"viewers": broadcast.viewcount, "viewers_list": list(
                viewers) if can_see else []}), mimetype)
    return HttpResponseBadRequest()
