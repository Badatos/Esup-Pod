"""Esup-Pod video encoding and transcripting utilities."""

import bleach
import logging
import os
import time

from django.urls import reverse
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.mail import mail_admins
from django.core.mail import send_mail
from django.core.mail import mail_managers
from django.core.mail import EmailMultiAlternatives
from pod.video.models import Video
from pod.progressive_web_app.utils import notify_user
from .models import EncodingStep
from .models import EncodingLog

DEBUG = getattr(settings, "DEBUG", True)
logger = logging.getLogger(__name__)
if DEBUG:
    logger.setLevel(logging.DEBUG)

TEMPLATE_VISIBLE_SETTINGS = getattr(
    settings,
    "TEMPLATE_VISIBLE_SETTINGS",
    {
        "TITLE_SITE": "Pod",
        "TITLE_ETB": "University name",
        "LOGO_SITE": "img/logoPod.svg",
        "LOGO_ETB": "img/esup-pod.svg",
        "LOGO_PLAYER": "img/pod_favicon.svg",
        "LINK_PLAYER": "",
        "LINK_PLAYER_NAME": _("Home"),
        "FOOTER_TEXT": ("",),
        "FAVICON": "img/pod_favicon.svg",
        "CSS_OVERRIDE": "",
        "PRE_HEADER_TEMPLATE": "",
        "POST_FOOTER_TEMPLATE": "",
        "TRACKING_TEMPLATE": "",
    },
)

__TITLE_SITE__ = (
    TEMPLATE_VISIBLE_SETTINGS["TITLE_SITE"]
    if (TEMPLATE_VISIBLE_SETTINGS.get("TITLE_SITE"))
    else "Pod"
)

DEFAULT_FROM_EMAIL = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@univ.fr")

USE_ESTABLISHMENT_FIELD = getattr(settings, "USE_ESTABLISHMENT_FIELD", False)

MANAGERS = getattr(settings, "MANAGERS", {})

SECURE_SSL_REDIRECT = getattr(settings, "SECURE_SSL_REDIRECT", False)
VIDEOS_DIR = getattr(settings, "VIDEOS_DIR", "videos")


# ##########################################################################
# ENCODE VIDEO: GENERIC FUNCTIONS
# ##########################################################################


def change_encoding_step(video_id: int, num_step: int, desc: str) -> None:
    """Change encoding step."""
    encoding_step, created = EncodingStep.objects.get_or_create(
        video=Video.objects.get(id=video_id)
    )
    encoding_step.num_step = num_step
    encoding_step.desc_step = desc[:255]
    encoding_step.save()
    logger.debug("Video: %s - step: %d - desc: %s" % (video_id, num_step, desc))


def add_encoding_log(video_id, log) -> None:
    """Add message in video_id encoding log."""
    encoding_log, created = EncodingLog.objects.get_or_create(
        video=Video.objects.get(id=video_id)
    )
    if created:
        encoding_log.log = log
    else:
        encoding_log.log += "\n\n%s" % log
    encoding_log.save()
    logger.debug(log)


def check_file(path_file) -> bool:
    """Check if path_file is accessible and is not null."""
    if os.access(path_file, os.F_OK) and os.stat(path_file).st_size > 0:
        return True
    return False


def create_outputdir(video_id, video_path):
    """ENCODE VIDEO: CREATE OUTPUT DIR."""
    dirname = os.path.dirname(video_path)
    output_dir = os.path.join(dirname, "%04d" % video_id)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    return output_dir


###############################################################
# EMAIL
###############################################################


def send_email_item(msg, item, item_id) -> None:
    """Send email notification when encoding fails for a specific item."""
    subject = "[" + __TITLE_SITE__ + "] Error Encoding %s id: %s" % (item, item_id)
    message = "Error Encoding %s id: %s\n%s" % (item, item_id, msg)
    html_message = "<p>Error Encoding %s id: %s</p><p>%s</p>" % (
        item,
        item_id,
        msg.replace("\n", "<br>"),
    )
    mail_admins(subject, message, fail_silently=False, html_message=html_message)


def send_email_recording(msg, recording_id) -> None:
    """Send email notification when recording encoding failed."""
    send_email_item(msg, "Recording", recording_id)


def send_email_encoding(video_to_encode) -> None:
    """Send email on encoding completion."""
    subject_prefix = _("Encoding")
    send_notification_email(video_to_encode, subject_prefix)


def send_notification_encoding(video_to_encode) -> None:
    """Send push notification on encoding completion."""
    subject_prefix = _("Encoding")
    send_notification(video_to_encode, subject_prefix)


def send_email(msg, video_id) -> None:
    """Send email notification when video encoding failed."""
    send_email_item(msg, "Video", video_id)


def send_email_transcript(video_to_encode) -> None:
    """Send email on transcripting completion."""
    subject_prefix = _("The transcripting of content")
    send_notification_email(video_to_encode, subject_prefix)


def send_notification_email(video_to_encode, subject_prefix) -> None:
    """Send email notification on video encoding or transcripting completion."""
    logger.debug("SEND EMAIL ON %s COMPLETION" % subject_prefix.upper())
    url_scheme = "https" if SECURE_SSL_REDIRECT else "http"
    content_url = "%s:%s" % (url_scheme, video_to_encode.get_full_url())
    subject = "[%s] %s" % (
        __TITLE_SITE__,
        _("%(subject)s #%(content_id)s completed")
        % {"subject": subject_prefix, "content_id": video_to_encode.id},
    )

    html_message = (
        '<p>%s</p><p>%s</p><p>%s<br><a href="%s"><i>%s</i></a>\
                </p><p>%s</p>'
        % (
            _("Hello,"),
            _(
                "%(content_type)s “%(content_title)s” has been %(action)s"
                + ", and is now available on %(site_title)s."
            )
            % {
                "content_type": (
                    _("The content")
                    if subject_prefix == _("The transcripting of content")
                    else _("The video")
                ),
                "content_title": "<b>%s</b>" % video_to_encode.title,
                "action": (
                    _("automatically transcripted")
                    if (subject_prefix == _("The transcripting of content"))
                    else _("encoded to Web formats")
                ),
                "site_title": __TITLE_SITE__,
            },
            _("You will find it here:"),
            content_url,
            content_url,
            _("Regards."),
        )
    )

    full_html_message = html_message + "<br>%s%s<br>%s%s" % (
        _("Post by:"),
        video_to_encode.owner,
        _("the:"),
        video_to_encode.date_added,
    )

    message = bleach.clean(html_message, tags=[], strip=True)
    full_message = bleach.clean(full_html_message, tags=[], strip=True)

    from_email = DEFAULT_FROM_EMAIL
    to_email = []
    to_email.append(video_to_encode.owner.email)

    if (
        USE_ESTABLISHMENT_FIELD
        and MANAGERS
        and video_to_encode.owner.owner.establishment.lower() in dict(MANAGERS)
    ):
        bcc_email = []
        video_estab = video_to_encode.owner.owner.establishment.lower()
        manager = dict(MANAGERS)[video_estab]
        if isinstance(manager, (list, tuple)):
            bcc_email = manager
        elif isinstance(manager, str):
            bcc_email.append(manager)
        msg = EmailMultiAlternatives(
            subject, message, from_email, to_email, bcc=bcc_email
        )
        msg.attach_alternative(html_message, "text/html")
        msg.send()
    else:
        mail_managers(
            subject,
            full_message,
            fail_silently=False,
            html_message=full_html_message,
        )
        if not DEBUG:
            send_mail(
                subject,
                message,
                from_email,
                to_email,
                fail_silently=False,
                html_message=html_message,
            )


def send_notification(video_to_encode, subject_prefix) -> None:
    """Send push notification on video encoding or transcripting completion."""
    subject = "[%s] %s" % (
        __TITLE_SITE__,
        _("%(subject)s #%(content_id)s completed")
        % {"subject": subject_prefix, "content_id": video_to_encode.id},
    )
    message = _(
        "%(content_type)s “%(content_title)s” has been %(action)s"
        + ", and is now available on %(site_title)s."
    ) % {
        "content_type": (
            _("content") if subject_prefix == _("Transcripting") else _("video")
        ),
        "content_title": video_to_encode.title,
        "action": (
            _("automatically transcripted")
            if (subject_prefix == _("Transcripting"))
            else _("encoded to Web formats")
        ),
        "site_title": __TITLE_SITE__,
    }

    notify_user(
        video_to_encode.owner,
        subject,
        message,
        url=reverse("video:video", args=(video_to_encode.slug,)),
    )


def time_to_seconds(a_time) -> int:
    """Convert a time to seconds."""
    seconds = time.strptime(str(a_time), "%H:%M:%S")
    seconds = seconds.tm_sec + seconds.tm_min * 60 + seconds.tm_hour * 3600
    return seconds
