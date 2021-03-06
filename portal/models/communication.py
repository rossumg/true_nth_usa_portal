"""Communication model"""
from __future__ import unicode_literals  # isort:skip

from collections import MutableMapping
from datetime import datetime
from smtplib import SMTPRecipientsRefused
from string import Formatter

from flask import current_app, url_for
from flask_babel import force_locale, gettext as _
import regex
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM

from ..audit import auditable_event
from ..database import db
from ..date_tools import localize_datetime
from ..extensions import user_manager
from ..trace import dump_trace, establish_trace, trace
from .assessment_status import overall_assessment_status
from .app_text import MailResource
from .intervention import INTERVENTION
from .message import EmailMessage
from .practitioner import Practitioner
from .questionnaire_bank import QuestionnaireBank
from .user import User

# https://www.hl7.org/fhir/valueset-event-status.html
event_status_types = ENUM(
    'preparation', 'in-progress', 'suspended', 'aborted', 'completed',
    'entered-in-error', 'unknown', name='event_statuses',
    create_type=False)


def locale_closure(locale_code, fn):
    """Capture preferred locale at load for use later during render

    As the variable load may be invoked by another user (say staff)
    or when run by celery outside a request context, force the locale
    of the subject.  Must capture in a closure to preserve, as the acting
    user may change before the template has been rendered.

    """
    locale_code = locale_code

    def function_with_forced_locale():
        if not locale_code:
            return fn()
        with force_locale(locale_code):
            return fn()

    return function_with_forced_locale


def load_template_args(user, questionnaire_bank_id=None):
    """Capture known variable lookup functions and values

    To add additional template variable lookup functions, name the
    local function with the `_lookup_` prefix to match, i.e::
        `_lookup_first_name` -> `first_name`

    """

    def ae_link():
        token = user_manager.token_manager.generate_token(user.id)
        auditable_event(
            "generated access token {} for ae_link".format(
                token), user_id=user.id, subject_id=user.id,
            context='authentication')

        return url_for(
            'portal.access_via_token', token=token,
            next_step='present_needed', _external=True)

    def make_button(text, inline=False):
        if inline:
            match = regex.search(r'href=([^>]+)>([^<]*)', text)
            if not match:
                raise ValueError("Can't make button w/o matching href pattern")

            return (
                """<a href={link}
                style="font-size: 0.9em;
                font-family: Helvetica, Arial, sans-serif;
                display: inline-block; color: #FFF;
                background-color: #7C959E; border-color: #7C959E;
                border-radius: 0;
                letter-spacing: 2px; cursor: pointer;
                text-transform: uppercase; text-align: center;
                line-height: 1.42857143;
                font-weight: 400; padding: 0.6em; text-decoration: none;">
                {label}</a>""".format(
                    link=match.groups()[0], label=match.groups()[1]))
        else:
            return text.replace('<a href', '<a class="btn" href')

    def _lookup_assessment_button():
        return make_button(_lookup_assessment_link(), inline=True)

    def _lookup_assessment_link():
        label = _('Complete Questionnaire')
        return (
            '<a href="{ae_link}">{label}</a>'.format(
                ae_link=ae_link(), label=label))

    def _lookup_clinic_name():
        org = user.organizations.first()
        if org:
            return _(org.name)
        return ""

    def _lookup_decision_support_via_access_button():
        return make_button(_lookup_decision_support_via_access_link())

    def _lookup_decision_support_via_access_link():
        token = user_manager.token_manager.generate_token(user.id)
        url = url_for(
            'portal.access_via_token', token=token,
            next_step='decision_support', _external=True)
        system_user = User.query.filter_by(email='__system__').one()
        auditable_event(
            "generated access token for user {} to embed in email".format(
                user.id),
            user_id=system_user.id, subject_id=user.id,
            context='authentication')
        label = _('TrueNTH P3P')
        return '<a href="{url}">{label}</a>'.format(url=url, label=label)

    def _lookup_debug_slot():
        """Special slot added when configuration DEBUG_EMAIL is set"""
        open_div = '<div style="background-color: #D3D3D3">'
        close_div = '</div>'

        trace_data = dump_trace()
        if not trace_data:
            trace_data = ['no trace data found']
        result = '{open_div} {trace} {close_div}'.format(
            open_div=open_div, close_div=close_div,
            trace='<br/>'.join(trace_data))
        return result

    def _lookup_first_name():
        name = ''
        if user:
            name = getattr(user, 'first_name', '')
        return name

    def _lookup_last_name():
        name = ''
        if user:
            name = getattr(user, 'last_name', '')
        return name

    def _lookup_parent_org():
        org = user.first_top_organization()
        if org:
            return _(org.name)
        return ""

    def _lookup_password_reset_button():
        return make_button(_lookup_password_reset_link())

    def _lookup_password_reset_link():
        label = _('Password Reset')
        return (
            '<a href="{url}">{label}</a>'.format(
                url=url_for('user.forgot_password', _external=True),
                label=label))

    def _lookup_practitioner_name():
        if not user.practitioner_id:
            return ''
        practitioner = Practitioner.query.get(user.practitioner_id)
        return practitioner.display_name

    def _lookup_questionnaire_due_date():
        if not questionnaire_bank_id:
            return ''
        qb = QuestionnaireBank.query.get(questionnaire_bank_id)
        trigger_date = qb.trigger_date(user)
        now = datetime.utcnow()
        due = qb.calculated_start(trigger_date, now).relative_start
        due = qb.calculated_due(trigger_date, now) or due
        trace("UTC due date: {}".format(due))
        due_date = localize_datetime(due, user)
        tz = user.timezone or 'UTC'
        trace("Localized due date (timezone = {}): {}".format(tz, due_date))
        return due_date

    def _lookup_registrationlink():
        return 'url_placeholder'

    def _lookup_st_button():
        return make_button(_lookup_st_link())

    def _lookup_st_link():
        label = _("Symptom Tracker")
        return '<a href="{0.link_url}">{label}</a>'.format(
            INTERVENTION.SELF_MANAGEMENT, label=label)

    def _lookup_verify_account_button():
        return make_button(_lookup_verify_account_link(), inline=True)

    def _lookup_verify_account_link():
        token = user_manager.token_manager.generate_token(user.id)
        url = url_for(
            'portal.access_via_token', token=token, _external=True)
        system_user = User.query.filter_by(email='__system__').one()
        auditable_event(
            "generated access token for user {} to embed in email".format(
                user.id),
            user_id=system_user.id, subject_id=user.id,
            context='authentication')
        label = _('Verify Account')
        return '<a href="{url}">{label}</a>'.format(url=url, label=label)

    # Load all functions from the local space with the `_lookup_` prefix
    # into the args instance
    args = DynamicDictLookup()
    lc = user.locale_code if user else None
    for fname, function in locals().items():
        if fname.startswith('_lookup_'):
            # chop the prefix and assign to the function
            args[fname[len('_lookup_'):]] = locale_closure(
                locale_code=lc, fn=function)
    return args


class Communication(db.Model):
    """Model representing a FHIR-like Communication Resource

    Used to track communications tied to a user `basedOn` a
    CommunicationRequest.

    """
    __tablename__ = 'communications'
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column('status', event_status_types, nullable=False)

    # FHIR Communication spec says `basedOn` can return to any
    # object.  For current needs, this is always a CommunicationRequest
    communication_request_id = db.Column(
        db.ForeignKey('communication_requests.id'), nullable=False)
    communication_request = db.relationship('CommunicationRequest')

    user_id = db.Column(db.ForeignKey(
        'users.id', ondelete='cascade'), nullable=False)

    # message_id is null until sent
    message_id = db.Column(db.ForeignKey(
        'email_messages.id', ondelete='cascade'), nullable=True)
    message = db.relationship('EmailMessage')

    __table_args__ = (
        UniqueConstraint(
            communication_request_id, user_id,
            name='_communication_request_user'),
    )

    def __str__(self):
        if not self.communication_request:
            from .communication_request import CommunicationRequest
            self.communication_request = CommunicationRequest.query.get(
                self.communication_request_id)
        return (
            'Communication for user {0.user_id}'
            ' of {0.communication_request.name}'.format(self))

    def generate_message(self):
        """Collate message details into EmailMessage"""
        user = User.query.get(self.user_id)

        qb_id = self.communication_request.questionnaire_bank_id
        args = load_template_args(user=user, questionnaire_bank_id=qb_id)
        mailresource = MailResource(
            url=self.communication_request.content_url,
            locale_code=user.locale_code,
            variables=args)

        missing = set(mailresource.variable_list) - set(args)
        if missing:
            raise ValueError(
                "{} contains unknown varables: {}".format(
                    mailresource.url,
                    ','.join(missing)))

        msg = EmailMessage(
            subject=mailresource.subject,
            body=mailresource.body,
            recipients=user.email,
            sender=current_app.config['MAIL_DEFAULT_SENDER'],
            user_id=user.id)

        return msg

    def generate_and_send(self):
        """Collate message details and send"""

        if current_app.config.get('DEBUG_EMAIL', False):
            # hack to restart trace when in loop from celery task
            # don't want to reset if in the middle of a request
            from celery import current_task
            establish_trace(
                "BEGIN trace as per DEBUG_EMAIL configuration",
                reset_trace=current_task is None)

        user = User.query.get(self.user_id)
        ready, reason = user.email_ready()
        if not ready:
            raise ValueError(
                "can't send communication to {user}; {reason}".format(
                    user=user, reason=reason))

        if overall_assessment_status(self.user_id) == 'Withdrawn':
            current_app.logger.info(
                "Skipping message send for withdrawn {}".format(user))
            self.status = 'suspended'
            return

        trace("load variables for {user} & UUID {uuid} on {request}".format(
            user=user,
            uuid=self.communication_request.lr_uuid,
            request=self.communication_request.name))

        self.message = self.generate_message()
        try:
            self.message.send_message()
            self.status = 'completed'
        except SMTPRecipientsRefused as exc:
            msg = ("Error sending Communication {} to {}: "
                   "{}".format(self.id, user.email, exc))
            current_app.logger.error(msg)
            sys = User.query.filter_by(email='__system__').first()
            auditable_event(message=msg,
                            user_id=(sys.id if sys else user.id),
                            subject_id=user.id,
                            context="user")
            self.status = 'aborted'

    def preview(self):
        "Collate message details and return preview (DOES NOT SEND)"

        msg = self.generate_message()
        msg.body = msg.style_message(msg.body)
        return msg


class DynamicDictLookup(MutableMapping):
    """Dictionary like interface with lazy lookup of values"""

    def __init__(self, *args, **kwargs):
        self.store = dict()
        self.update(dict(*args, **kwargs))

    def __getitem__(self, key):
        if key in self.store:
            value = self.store[key]
            if callable(value):
                return self.store[key].__call__()
            return value
        else:
            raise KeyError(key)

    def __setitem__(self, key, value):
        self.store[key] = value

    def __delitem__(self, key):
        del self.store[key]

    def __len__(self):
        return len(self.store)

    def __iter__(self):
        return iter(self.store)

    def minimal_subdict(self, target):
        """Return subdict including only keys referenced in target string

        Passing a dictionary to `format` forces evaluation of every (key,
        value) in the dict.  To avoid unnecessary lookups, this returns a
        dict like object with only the keys referenced in the given string.

        """
        needed = [v[1] for v in Formatter().parse(target) if v[1]]
        result = DynamicDictLookup()
        for key in self.store:
            if key in needed:
                result[key] = self.store[key]
        return result
