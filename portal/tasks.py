"""Tasks module

All tasks run via external message queue (via celery) are defined
within.

NB: a celery worker must be started for these to ever return.  See
`celery_worker.py`

"""
from datetime import datetime
from functools import wraps
import json
import random
import time
from traceback import format_exc

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from flask import current_app
from requests import Request, Session
from requests.exceptions import RequestException
from sqlalchemy import and_

from .database import db
from .dogpile_cache import dogpile_cache
from .factories.app import create_app
from .factories.celery import create_celery
from .models.assessment_status import (
    invalidate_assessment_status_cache,
    overall_assessment_status,
)
from .models.communication import Communication
from .models.communication_request import queue_outstanding_messages
from .models.questionnaire_bank import QuestionnaireBank
from .models.reporting import generate_and_send_summaries, get_reporting_stats
from .models.role import ROLE, Role
from .models.scheduled_job import check_active, update_job_status
from .models.tou import update_tous
from .models.user import User, UserRoles

# To debug, stop the celeryd running out of /etc/init, start in console:
#   celery worker -A portal.celery_worker.celery --loglevel=debug
# Import rdb and use like pdb:
#   from celery.contrib import rdb
#   rdb.set_trace()
# Follow instructions from celery console, i.e. telnet 127.0.0.1 6900

logger = get_task_logger(__name__)

celery = create_celery(create_app())


def scheduled_task(func):
    @wraps(func)
    def call_and_update(*args, **kwargs):
        job_id = kwargs.get('job_id')
        manual_run = kwargs.get('manual_run')

        if not manual_run and job_id and not check_active(job_id):
            message = "Job id `{}` inactive.".format(job_id)
            logger.debug(message)
            return message

        try:
            before = datetime.now()
            output = func(*args, **kwargs)
            duration = datetime.now() - before
            message = ('{} ran in {} '
                       'seconds.'.format(func.__name__, duration.seconds))
            if output:
                message += " {}".format(output)
            current_app.logger.debug(message)
        except Exception as exc:
            message = ("Unexpected exception in `{}` "
                       "on {} : {}".format(func.__name__, job_id, exc))
            logger.error(message)
            logger.error(format_exc())

        if job_id:
            update_job_status(job_id, status=message)

        return message

    return call_and_update


@celery.task(name="tasks.add")
def add(x, y):
    return x + y


@celery.task(name="tasks.info")
def info():
    return "BROKER_URL: {} <br/> SERVER_NAME: {}".format(
        current_app.config.get('BROKER_URL'),
        current_app.config.get('SERVER_NAME'))


@celery.task(name="tasks.post_request", bind=True)
def post_request(self, url, data, timeout=10, retries=3):
    """Wrap requests.post for asyncronous posts - includes timeout & retry"""
    logger.debug("task: %s retries:%s", self.request.id, self.request.retries)

    s = Session()
    req = Request('POST', url, data=data)
    prepped = req.prepare()
    try:
        resp = s.send(prepped, timeout=timeout)
        if resp.status_code < 400:
            logger.info("{} received from {}".format(resp.status_code, url))
        else:
            logger.error("{} received from {}".format(resp.status_code, url))

    except RequestException as exc:
        """Typically raised on timeout or connection error

        retry after countdown seconds unless retry threshold has been exceeded
        """
        logger.warn("{} on {}".format(exc.message, url))
        if self.request.retries < retries:
            raise self.retry(exc=exc, countdown=20)
        else:
            logger.error(
                "max retries exceeded for {}, last failure: {}".format(
                    url, exc))
    except Exception as exc:
        logger.error("Unexpected exception on {} : {}".format(url, exc))


@celery.task
@scheduled_task
def test(**kwargs):
    return "Test"


@celery.task
@scheduled_task
def test_args(*args, **kwargs):
    alist = ",".join(args)
    klist = json.dumps(kwargs)
    return "{}|{}".format(",".join(args), json.dumps(kwargs))


@celery.task(
    name="tasks.test_consume_list", ignore_result=True, soft_time_limit=4)
def test_consume_list(id_list, priority):
    """Proof of concept / test code to eval producer/consumer pattern.

    See also the produce_list() task, and the trigger view
    at /test-producer-consumer

    """
    try:
        # sleep for a number of seconds, so the process looks to take
        # a bit and evaluation of tasks and priorities can be observed.
        time.sleep(random.randint(1, 5))
        logger.info("priority: {} consuming {}".format(priority, id_list))
    except SoftTimeLimitExceeded:
        logger.info("timed out")


@celery.task(name="tasks.test_produce_list")
def test_produce_list():
    """Proof of concept / test code to eval producer/consumer pattern.

    See also the consume_list() task, and the trigger view
    at /test-producer-consumer

    """
    j = 0
    step = 5
    numlists = 50
    for i in range(step, (step*numlists)+1, step):
        id_list = (range(j, i))
        priority = random.choice((0, 5, 9))
        logger.info("priority {}; producing {}".format(priority, id_list))
        test_consume_list.apply_async(
            priority=priority,
            kwargs={'id_list': id_list, 'priority': priority})
        j = i
    logger.info("producer done")


@celery.task
@scheduled_task
def cache_reporting_stats(**kwargs):
    """Populate reporting dashboard stats cache

    Reporting stats can be a VERY expensive lookup - cached for an hour
    at a time.  This task is responsible for renewing the potentially
    stale cache.  Expected to be called as a scheduled job.

    """
    dogpile_cache.invalidate(get_reporting_stats)
    dogpile_cache.refresh(get_reporting_stats)


@celery.task
@scheduled_task
def cache_assessment_status(**kwargs):
    """Populate assessment status cache

    Assessment status is an expensive lookup - cached for an hour
    at a time.  This task is responsible for renewing the potentially
    stale cache.  Expected to be called as a scheduled job.

    """
    update_patient_loop(update_cache=True, queue_messages=False, as_task=True)


@celery.task
@scheduled_task
def prepare_communications(**kwargs):
    """Move any ready communications into prepared state """
    update_patient_loop(
        update_cache=False, queue_messages=True, as_task=True)


def update_patient_loop(
        update_cache=True, queue_messages=True, as_task=False):
    """Function to loop over valid patients and update as per settings

    Typically called as a scheduled_job - also directly from tests
    """
    patient_role_id = Role.query.filter(
        Role.name == ROLE.PATIENT.value).with_entities(Role.id).first()[0]
    valid_patients = User.query.join(UserRoles).filter(and_(
        User.id == UserRoles.user_id,
        User.deleted_id.is_(None),
        UserRoles.role_id == patient_role_id)).with_entities(User.id)

    patients = valid_patients.all()
    j = 0
    batchsize = current_app.config.get('UPDATE_PATIENT_TASK_BATCH_SIZE', 16)

    while True:
        sublist = patients[j:j+batchsize]
        if not sublist:
            break
        logger.debug("Sending sublist {} to update_patients".format(sublist))
        j += batchsize
        kwargs = {
            'patient_list': sublist, 'update_cache': update_cache,
            'queue_messages': queue_messages}
        if as_task:
            update_patients_task.apply_async(priority=9, kwargs=kwargs)
        else:
            update_patients(**kwargs)


@celery.task(name="tasks.update_patients_task", soft_time_limit=60)
def update_patients_task(patient_list, update_cache, queue_messages):
    """Task form - wraps call to testable function `update_patients` """
    update_patients(patient_list, update_cache, queue_messages)


def update_patients(patient_list, update_cache, queue_messages):
    now = datetime.utcnow()
    for user_id in patient_list:
        if update_cache:
            dogpile_cache.invalidate(overall_assessment_status, user_id)
            dogpile_cache.refresh(overall_assessment_status, user_id)
        if queue_messages:
            user = User.query.get(user_id)
            qbd = QuestionnaireBank.most_current_qb(user=user, as_of_date=now)
            if qbd.questionnaire_bank:
                queue_outstanding_messages(
                    user=user,
                    questionnaire_bank=qbd.questionnaire_bank,
                    iteration_count=qbd.iteration)
        db.session.commit()


@celery.task
@scheduled_task
def send_queued_communications(**kwargs):
    """Look for communication objects ready to send"""
    send_messages(as_task=True)


def send_messages(as_task=False):
    """Function to send all queued messages

    Typically called as a scheduled_job - also directly from tests
    """
    ready = Communication.query.filter(
        Communication.status == 'preparation').with_entities(Communication.id)

    for communication_id in ready:
        if as_task:
            send_communication_task.apply_async(
                priority=9, kwargs={'communication_id': communication_id})
        else:
            send_communication(communication_id)


@celery.task(name="tasks.send_communication_task")
def send_communication_task(communication_id):
    send_communication(communication_id)


def send_communication(communication_id):
    communication = Communication.query.get(communication_id)
    communication.generate_and_send()
    db.session.commit()


def send_user_messages(user, force_update=False):
    """Send queued messages to only given user (if found)

    @param user: to email
    @param force_update: set True to force reprocessing of cached
    data and queue any messages previously overlooked.

    Triggers a send for any messages found in a prepared state ready
    for transmission.

    """
    ready, reason = user.email_ready()
    if not ready:
        raise ValueError("Cannot send messages to {user}; {reason}".format(
            user=user, reason=reason))

    if force_update:
        invalidate_assessment_status_cache(user_id=user.id)
        qbd = QuestionnaireBank.most_current_qb(
            user=user, as_of_date=datetime.utcnow())
        if qbd.questionnaire_bank:
            queue_outstanding_messages(
                user=user,
                questionnaire_bank=qbd.questionnaire_bank,
                iteration_count=qbd.iteration)
    count = 0
    ready = Communication.query.join(User).filter(
        Communication.status == 'preparation').filter(User == user)
    for communication in ready:
        communication.generate_and_send()
        db.session.commit()
        count += 1
    message = "Sent {} messages to {}".format(count, user.email)
    if force_update:
        message += " after forced update"
    return message


@celery.task
@scheduled_task
def send_questionnaire_summary(**kwargs):
    "Generate and send a summary of questionnaire counts to all Staff in org"
    cutoff_days = kwargs['cutoff_days']
    org_id = kwargs['org_id']
    error_emails = generate_and_send_summaries(cutoff_days, org_id)
    if error_emails:
        return ('\nUnable to reach recipient(s): '
                '{}'.format(', '.join(error_emails)))


@celery.task
@scheduled_task
def update_tous_task(**kwargs):
    """Job to manage updates for various ToUs

    Scheduled task, see docs in ``tou.update_tous()``

    """
    return update_tous(**kwargs)


@celery.task
@scheduled_task
def token_watchdog(**kwargs):
    """Clean up stale tokens and alert service sponsors if nearly expired"""
    from .models.auth import token_janitor
    error_emails = token_janitor()
    if error_emails:
        return '\nUnable to reach recipient(s): {}'.format(
            ', '.join(error_emails))
