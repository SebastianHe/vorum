import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from flask import g

from test_vorum import app, setup, login, new_topic, post, query, register, verified
from vorum import create_app
from vorum.notifications import digest_boundary, dispatch_digests, dispatch_immediate


@pytest.fixture
def clock(monkeypatch):
    current = [datetime.fromisoformat('2026-10-16T08:00:00+00:00')]

    def set_time(value):
        current[0] = datetime.fromisoformat(value)
        return current[0]

    def now():
        return current[0].isoformat(timespec='microseconds')

    monkeypatch.setattr('vorum.now', now)
    monkeypatch.setattr('vorum.notifications.now', now)
    return set_time


def subscribe(client, mode, topic=None, host='localhost'):
    return post(client, topic+'/notifications' if topic else '/notifications/forum', {'mode': mode}, host)


def notifications(app, recipient=None):
    return [mail for mail in app.extensions['outbox'] if 'kind' in mail and (recipient is None or mail['to'] == recipient)]


def run_digests(app, stamp):
    with app.app_context():
        g.app_db = app.config['DATABASE']
        return dispatch_digests(datetime.fromisoformat(stamp))


def run_immediate(app):
    with app.app_context():
        g.app_db = app.config['DATABASE']
        return dispatch_immediate()


@pytest.mark.parametrize('mode,expected', [('all', 2), ('topics', 1), ('daily', 0), ('weekly', 0), ('none', 0)])
def test_forum_immediate_modes_and_no_self_notification(app, setup, clock, mode, expected):
    member = verified(app)
    assert subscribe(member, mode).status_code == 302
    clock('2026-10-16T09:00:00+00:00')
    topic = new_topic(setup)
    post(setup, topic+'/reply', {'body': '<p>A reply</p>'})
    assert len(notifications(app)) == expected
    assert all(mail['to'] == 'member@example.org' for mail in notifications(app))
    assert subscribe(setup, 'all').status_code == 302
    post(setup, topic+'/reply', {'body': '<p>Own post</p>'})
    assert not notifications(app, 'root@example.org')


def test_topic_subscriptions_are_independent_and_direct_mails_deduplicated(app, setup, clock):
    member = verified(app)
    topic = new_topic(setup)
    other = new_topic(setup, title='Another topic')
    subscribe(member, 'all', topic)
    clock('2026-10-16T09:00:00+00:00')
    post(setup, other+'/reply', {'body': 'Elsewhere'})
    assert not notifications(app)
    post(setup, topic+'/reply', {'body': '<div>First</div><div>Second &amp; third</div>'})
    mail = notifications(app)[-1]
    assert 'First' in mail['body'] and 'Second & third' in mail['body'] and '<div>' not in mail['body']
    assert 'http://localhost'+topic+'#' in mail['body']
    subscribe(member, 'all')
    post(setup, topic+'/reply', {'body': 'Both subscriptions'})
    assert len(notifications(app)) == 2
    subscribe(member, 'none', topic)
    post(setup, topic+'/reply', {'body': 'Forum subscription still applies'})
    assert len(notifications(app)) == 3
    subscribe(member, 'none')
    subscribe(member, 'all', topic)
    post(setup, topic+'/reply', {'body': 'Topic subscription still applies'})
    assert len(notifications(app)) == 4
    assert run_immediate(app) == 0


def test_no_notifications_for_edits_deletes_or_failed_creation(app, setup, clock):
    member = verified(app)
    subscribe(member, 'all')
    clock('2026-10-16T09:00:00+00:00')
    response = post(setup, '/topics/new', {'title': 'Bad attachment', 'body': 'Valid text',
                    'attachments': (io.BytesIO(b'x'*(10*1024*1024+1)), 'huge.txt')})
    assert response.status_code == 400
    assert query(app, 'SELECT COUNT(*) n FROM notification_deliveries')['n'] == 0
    topic = new_topic(setup)
    original = query(app, 'SELECT slug FROM posts')['slug']
    post(setup, '/posts/'+original+'/edit', {'body': 'Changed'})
    post(setup, '/posts/'+original+'/delete')
    assert len(notifications(app)) == 1
    assert query(app, 'SELECT COUNT(*) n FROM notification_deliveries')['n'] == 0


def test_preferences_require_verified_login_csrf_and_correct_tenant(app, setup):
    topic = new_topic(setup)
    anonymous = app.test_client()
    assert subscribe(anonymous, 'all').location.startswith('/login')
    pending = app.test_client()
    register(pending, 'pending@example.org')
    assert subscribe(pending, 'all').location.startswith('/verify')
    assert setup.post('/notifications/forum', data={'mode': 'all'}).status_code == 400
    assert subscribe(setup, 'invalid').status_code == 400
    assert subscribe(setup, 'topics', topic).status_code == 400
    login(setup, host='other.test')
    assert subscribe(setup, 'all', topic, host='other.test').status_code == 404
    assert query(app, 'SELECT COUNT(*) n FROM forum_subscriptions')['n'] == 0
    assert query(app, 'SELECT COUNT(*) n FROM topic_subscriptions')['n'] == 0


def test_global_preferences_are_scoped_by_forum_and_mail_language_is_saved(app, setup, clock):
    verified(app, 'local@example.org')
    login(setup, host='alias.test')
    post(setup, '/language/en', {'next': '/'}, host='alias.test')
    subscribe(setup, 'all', host='alias.test')
    login(setup, host='other.test')
    subscribe(setup, 'none', host='other.test')
    first = verified(app, 'writer@example.org')
    second = verified(app, 'writer@example.org', host='other.test')
    clock('2026-10-16T09:00:00+00:00')
    new_topic(second, host='other.test')
    assert not notifications(app)
    new_topic(first)
    mail = notifications(app)[0]
    assert mail['to'] == 'root@example.org'
    assert 'New topic' in mail['subject']
    assert 'http://alias.test/topics/' in mail['body']
    assert not notifications(app, 'local@example.org')


def test_digest_waits_until_16_berlin_and_only_sends_new_posts_once(app, setup, clock):
    member = verified(app)
    new_topic(setup, title='Before subscription')
    clock('2026-10-16T09:00:00+00:00')
    subscribe(member, 'daily')
    clock('2026-10-16T10:00:00+00:00')
    topic = new_topic(setup, title='Digest topic')
    post(setup, topic+'/reply', {'body': 'A new reply'})
    assert run_digests(app, '2026-10-16T13:59:59+00:00') == 0
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 1
    mail = notifications(app)[0]
    assert mail['kind'] == 'daily' and len(mail['post_ids']) == 2
    assert 'Before subscription' not in mail['body']
    assert run_digests(app, '2026-10-16T14:01:00+00:00') == 0
    assert run_digests(app, '2026-10-17T14:00:00+00:00') == 0


def test_forum_digest_respects_last_forum_visit(app, setup, clock):
    member = verified(app)
    subscribe(member, 'daily')
    clock('2026-10-16T09:00:00+00:00')
    topic = new_topic(setup, title='Earlier topic')
    clock('2026-10-16T10:00:00+00:00')
    member.get('/')
    clock('2026-10-16T11:00:00+00:00')
    post(setup, topic+'/reply', {'body': 'After the visit'})
    latest = query(app, 'SELECT id FROM posts ORDER BY id DESC')['id']
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 1
    assert notifications(app)[0]['post_ids'] == [latest]


def test_topic_digest_respects_topic_visits_and_deduplicates_forum_overlap(app, setup, clock):
    member = verified(app)
    topic = new_topic(setup)
    subscribe(member, 'daily', topic)
    subscribe(member, 'daily')
    clock('2026-10-16T09:00:00+00:00')
    post(setup, topic+'/reply', {'body': 'Already read'})
    clock('2026-10-16T10:00:00+00:00')
    member.get(topic)
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 0
    clock('2026-10-17T09:00:00+00:00')
    post(setup, topic+'/reply', {'body': 'Unread'})
    latest = query(app, 'SELECT id FROM posts ORDER BY id DESC')['id']
    assert run_digests(app, '2026-10-17T14:00:00+00:00') == 1
    assert notifications(app)[0]['post_ids'] == [latest]


def test_topic_digest_survives_forum_unsubscribe_and_own_posts_do_not_count(app, setup, clock):
    member = verified(app)
    topic = new_topic(setup)
    subscribe(member, 'daily', topic)
    subscribe(member, 'none')
    clock('2026-10-16T09:00:00+00:00')
    post(member, topic+'/reply', {'body': 'Own post'})
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 0
    clock('2026-10-17T09:00:00+00:00')
    post(setup, topic+'/reply', {'body': 'Someone else'})
    clock('2026-10-17T10:00:00+00:00')
    member.get('/')
    assert run_digests(app, '2026-10-17T14:00:00+00:00') == 1


def test_weekly_digest_is_sent_on_saturday(app, setup, clock):
    member = verified(app)
    subscribe(member, 'weekly')
    clock('2026-10-16T09:00:00+00:00')
    new_topic(setup)
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 0
    assert run_digests(app, '2026-10-17T13:59:59+00:00') == 0
    assert run_digests(app, '2026-10-17T14:00:00+00:00') == 1
    assert notifications(app)[0]['kind'] == 'weekly'
    assert run_digests(app, '2026-10-24T14:00:00+00:00') == 0


@pytest.mark.parametrize('stamp,expected', [
    ('2026-07-04T14:00:00+00:00', '2026-07-04T14:00:00.000000+00:00'),
    ('2026-12-05T15:00:00+00:00', '2026-12-05T15:00:00.000000+00:00'),
    ('2026-10-25T14:59:59+00:00', '2026-10-24T14:00:00.000000+00:00'),
    ('2026-10-25T15:00:00+00:00', '2026-10-25T15:00:00.000000+00:00'),
])
def test_schedule_accounts_for_daylight_saving(stamp, expected):
    tenant = {'digest_time': '16:00', 'digest_timezone': 'Europe/Berlin', 'digest_weekday': 5}
    assert digest_boundary(tenant, 'daily', datetime.fromisoformat(stamp)) == expected


def test_failed_mail_does_not_undo_post_and_is_retried_once(app, setup, clock):
    member = verified(app)
    subscribe(member, 'all')
    clock('2026-10-16T09:00:00+00:00')
    app.config['MAIL_SUPPRESS'] = False
    topic = new_topic(setup)
    assert setup.get(topic).status_code == 200
    assert query(app, 'SELECT delivered_at FROM notification_deliveries')['delivered_at'] is None
    app.config['MAIL_SUPPRESS'] = True
    assert run_immediate(app) == 1
    assert run_immediate(app) == 0
    assert len(notifications(app)) == 1


def test_unsubscribe_cancels_pending_immediate_mail(app, setup, clock):
    member = verified(app)
    subscribe(member, 'all')
    clock('2026-10-16T09:00:00+00:00')
    app.config['MAIL_SUPPRESS'] = False
    new_topic(setup)
    subscribe(member, 'none')
    app.config['MAIL_SUPPRESS'] = True
    assert run_immediate(app) == 0
    assert not notifications(app)


def test_digest_failure_retries_without_advancing_cursor(app, setup, clock):
    member = verified(app)
    subscribe(member, 'daily')
    clock('2026-10-16T09:00:00+00:00')
    new_topic(setup)
    app.config['MAIL_SUPPRESS'] = False
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 0
    assert query(app, 'SELECT last_digest_at FROM forum_subscriptions')['last_digest_at'] is None
    app.config['MAIL_SUPPRESS'] = True
    assert run_digests(app, '2026-10-16T14:01:00+00:00') == 1
    assert run_digests(app, '2026-10-16T14:02:00+00:00') == 0


def test_concurrent_workers_do_not_duplicate_digests(app, setup, clock):
    member = verified(app)
    subscribe(member, 'daily')
    clock('2026-10-16T09:00:00+00:00')
    new_topic(setup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_digests(app, '2026-10-16T14:00:00+00:00'), range(2)))
    assert sum(results) == 1
    assert len(notifications(app)) == 1


def test_concurrent_workers_do_not_duplicate_pending_immediate_mail(app, setup, clock):
    member = verified(app)
    subscribe(member, 'all')
    clock('2026-10-16T09:00:00+00:00')
    app.config['MAIL_SUPPRESS'] = False
    new_topic(setup)
    app.config['MAIL_SUPPRESS'] = True
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_immediate(app), range(2)))
    assert sum(results) == 1
    assert len(notifications(app)) == 1


def test_topic_digest_excludes_other_topics_tenants_and_edited_old_posts(app, setup, clock):
    member = verified(app)
    topic = new_topic(setup, title='Subscribed topic')
    old_post = query(app, 'SELECT slug FROM posts')['slug']
    other = new_topic(setup, title='Other topic')
    subscribe(member, 'daily', topic)
    clock('2026-10-16T09:00:00+00:00')
    post(setup, '/posts/'+old_post+'/edit', {'body': 'Edited old content'})
    post(setup, other+'/reply', {'body': 'Another topic'})
    outsider = verified(app, 'outsider@example.org', host='other.test')
    new_topic(outsider, host='other.test')
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 0
    clock('2026-10-17T09:00:00+00:00')
    post(setup, topic+'/reply', {'body': 'New content'})
    assert run_digests(app, '2026-10-17T14:00:00+00:00') == 1
    assert 'New content' in notifications(app)[0]['body']
    assert 'Edited old content' not in notifications(app)[0]['body']
    assert 'Other topic' not in notifications(app)[0]['body']


def test_saving_same_mode_keeps_digest_cursor(app, setup, clock):
    member = verified(app)
    subscribe(member, 'daily')
    clock('2026-10-16T09:00:00+00:00')
    new_topic(setup)
    assert run_digests(app, '2026-10-16T14:00:00+00:00') == 1
    cursor = query(app, 'SELECT since,last_digest_at FROM forum_subscriptions')
    clock('2026-10-17T09:00:00+00:00')
    subscribe(member, 'daily')
    saved = query(app, 'SELECT since,last_digest_at FROM forum_subscriptions')
    assert tuple(saved) == tuple(cursor)
    subscribe(member, 'weekly')
    changed = query(app, 'SELECT since,last_digest_at FROM forum_subscriptions')
    assert changed['since'] != cursor['since'] and changed['last_digest_at'] is None


def test_existing_database_migrates_and_schedule_is_validated(app, setup):
    query(app, 'ALTER TABLE reads DROP COLUMN visited_at')
    for column in ('digest_time', 'digest_timezone', 'digest_weekday'):
        query(app, f'ALTER TABLE tenants DROP COLUMN {column}')
    create_app(dict(app.config))
    tenant = query(app, 'SELECT * FROM tenants')
    assert (tenant['digest_time'], tenant['digest_timezone'], tenant['digest_weekday']) == ('16:00', 'Europe/Berlin', 5)
    assert any(column['name'] == 'visited_at' for column in query(app, 'PRAGMA table_info(reads)', all=True))
    data = {'name': 'Community', 'digest_time': '19:30', 'digest_timezone': 'Atlantic/Canary', 'digest_weekday': '2'}
    assert post(setup, '/admin/settings', data).status_code == 302
    tenant = query(app, 'SELECT * FROM tenants WHERE name=?', ('Community',))
    assert (tenant['digest_time'], tenant['digest_timezone'], tenant['digest_weekday']) == ('19:30', 'Atlantic/Canary', 2)
    for bad in [{'digest_timezone': 'Invalid/Zone'}, {'digest_weekday': '7'}, {'digest_time': '25:61'}]:
        post(setup, '/admin/settings', {**data, **bad})
        assert query(app, 'SELECT digest_time FROM tenants WHERE name=?', ('Community',))['digest_time'] == '19:30'


def test_cli_and_notification_ui(app, setup):
    assert app.test_cli_runner().invoke(args=['send-notifications']).exit_code == 0
    html = setup.get('/').text
    assert 'notifications/forum' in html and 'Bei jedem neuen Thema und Beitrag' in html
    subscribe(setup, 'weekly')
    assert 'value="weekly" aria-pressed="true"' in setup.get('/').text
    topic = new_topic(setup)
    assert topic+'/notifications' in setup.get(topic).text
    post(setup, '/language/en', {'next': '/'})
    assert 'Daily digest' in setup.get('/').text
    assert 'notification-menu' not in app.test_client().get('/').text
