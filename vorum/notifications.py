"""Independent forum/topic subscriptions, durable immediate mail, and scheduled digests."""
import re
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import bleach
import click
from flask import Blueprint, abort, current_app, flash, g, redirect, request, url_for

from . import db, now, one, require_login, rows
from .mail import deliver_mail, system_message
from .translations import EN

FORUM_MODES = (
    ('all', 'Bei jedem neuen Thema und Beitrag sofort informieren'),
    ('topics', 'Bei jedem neuen Thema sofort informieren'),
    ('daily', 'Tägliche Zusammenfassung'),
    ('weekly', 'Wöchentliche Zusammenfassung'),
    ('none', 'Keine Benachrichtigung'),
)
TOPIC_MODES = (('all', 'Bei jedem neuen Beitrag sofort informieren'),) + FORUM_MODES[2:]


def subscription_mode(topic_id=None):
    if not g.user or not g.user['verified']:
        return 'none'
    subscription = one('SELECT mode FROM topic_subscriptions WHERE user_id=? AND topic_id=?',
                       (g.user['id'], topic_id)) if topic_id else one(
        'SELECT mode FROM forum_subscriptions WHERE user_id=? AND tenant_id=?', (g.user['id'], g.tenant['id']))
    return subscription['mode'] if subscription else 'none'


def visit_forum():
    if g.user and g.user['verified']:
        db().execute('''INSERT INTO forum_visits (user_id,tenant_id,visited_at) VALUES (?,?,?)
            ON CONFLICT(user_id,tenant_id) DO UPDATE SET visited_at=excluded.visited_at''',
            (g.user['id'], g.tenant['id'], now()))


def queue_immediate(post_id, is_topic=False):
    """Called inside the same transaction as the new post."""
    db().execute('''INSERT INTO notification_deliveries (user_id,post_id,is_topic)
        SELECT u.id,p.id,? FROM posts p JOIN topics t ON t.id=p.topic_id JOIN users u
        ON (u.tenant_id=t.tenant_id OR u.tenant_id IS NULL)
        WHERE p.id=? AND u.verified=1 AND u.profile_pending=0 AND u.id!=p.user_id AND (
            EXISTS (SELECT 1 FROM forum_subscriptions f WHERE f.user_id=u.id AND f.tenant_id=t.tenant_id
                AND (f.mode='all' OR (f.mode='topics' AND ?)) AND f.since<=p.created_at)
            OR EXISTS (SELECT 1 FROM topic_subscriptions s WHERE s.user_id=u.id AND s.topic_id=t.id
                AND s.mode='all' AND s.since<=p.created_at))''', (int(is_topic), post_id, int(is_topic)))


def _origin(subscription, tenant):
    origin = subscription['base_url']
    host = urlsplit(origin).hostname
    if one('SELECT 1 FROM hosts WHERE hostname=? AND tenant_id=?', (host, tenant['id'])):
        return origin
    host = one('SELECT hostname FROM hosts WHERE tenant_id=? ORDER BY hostname LIMIT 1', (tenant['id'],))
    if not host:
        raise ValueError('Forum has no hostname')
    scheme = 'https' if current_app.config['SESSION_COOKIE_SECURE'] else 'http'
    return scheme + '://' + host['hostname']


def _translate(language, value):
    return EN.get(value, value) if language == 'en' else value


def _excerpt(body):
    body = re.sub(r'</(?:div|p|li|blockquote|h2|h3)>|<br\s*/?>', '\n', body)
    return unescape(bleach.clean(body, tags=[], strip=True)).strip()[:1200]


def _send(tenant, user, subscription, posts, kind):
    tr = lambda value: _translate(subscription['language'], value)
    origin = _origin(subscription, tenant)
    label = tr({'immediate': 'Neuer Beitrag', 'new_topic': 'Neues Thema',
                'daily': 'Tägliche Zusammenfassung', 'weekly': 'Wöchentliche Zusammenfassung'}[kind])
    subject = f"{tenant['name']} — {label}"
    if kind in ('immediate', 'new_topic'):
        subject += ': ' + posts[0]['title']
    entries = []
    for post in posts:
        date = datetime.fromisoformat(post['created_at']).astimezone(ZoneInfo(tenant['timezone']))
        entries.append(dict(title=post['title'], author=post['username'],
                            date=date.strftime('%Y-%m-%d · %H:%M %Z' if subscription['language'] == 'en'
                                               else '%d.%m.%Y · %H:%M %Z'),
                            excerpt=_excerpt(post['body']),
                            url=f"{origin}/topics/{post['topic_slug']}#{post['slug']}"))
    introduction = tr('In deinem abonnierten Forum oder Thema gibt es Neuigkeiten.')
    if kind in ('daily', 'weekly'):
        introduction = tr('Hier findest du neue, noch nicht gelesene Beiträge aus deinen Abonnements.')
    message = system_message(
        tenant, user['email'], subject, language=subscription['language'], origin=origin, title=label,
        paragraphs=[introduction, tr('Beiträge in dieser E-Mail:') + ' ' + str(len(posts))],
        action_label=tr('Forum öffnen'), posts=entries,
        notes=[tr('Du erhältst diese E-Mail, weil du Benachrichtigungen für das Forum oder ein Thema abonniert hast.'),
               tr('Die Texte sind Auszüge. Über „Beitrag lesen“ gelangst du zum vollständigen Beitrag und kannst im Forum antworten.'),
               tr('Benachrichtigungen kannst du oben rechts im Forum oder Topic ändern.'),
               tr('Forum- und Topic-Abos gelten unabhängig voneinander.')])
    deliver_mail(tenant, message, kind=kind, post_ids=[post['id'] for post in posts])


def _direct_subscription(user_id, post):
    subscription = one('''SELECT * FROM topic_subscriptions WHERE user_id=? AND topic_id=?
        AND mode='all' AND since<=?''', (user_id, post['topic_id'], post['created_at']))
    return subscription or one('''SELECT * FROM forum_subscriptions WHERE user_id=? AND tenant_id=?
        AND (mode='all' OR (mode='topics' AND ?)) AND since<=?''',
        (user_id, post['tenant_id'], post['is_topic'], post['created_at']))


def dispatch_immediate(post_id=None):
    pending = rows('SELECT user_id,post_id FROM notification_deliveries WHERE delivered_at IS NULL'
                   + (' AND post_id=?' if post_id is not None else ''), (post_id,) if post_id is not None else ())
    sent = 0
    for item in pending:
        # Serialize each delivery across HTTP workers and the background worker.
        db().execute('BEGIN IMMEDIATE')
        post = one('''SELECT p.*,t.tenant_id,t.title,t.slug topic_slug,n.is_topic FROM notification_deliveries n
            JOIN posts p ON p.id=n.post_id JOIN topics t ON t.id=p.topic_id
            WHERE n.user_id=? AND n.post_id=? AND n.delivered_at IS NULL''', (item['user_id'], item['post_id']))
        user = one('SELECT * FROM users WHERE id=?', (item['user_id'],))
        subscription = _direct_subscription(user['id'], post) if post and user else None
        if not (post and user and user['verified'] and not user['profile_pending'] and user['id'] != post['user_id']
                and user['tenant_id'] in (None, post['tenant_id']) and subscription):
            db().execute('DELETE FROM notification_deliveries WHERE user_id=? AND post_id=? AND delivered_at IS NULL',
                         (item['user_id'], item['post_id']))
            db().commit()
            continue
        tenant = one('SELECT * FROM tenants WHERE id=?', (post['tenant_id'],))
        try:
            _send(tenant, user, subscription, [post], 'new_topic' if post['is_topic'] else 'immediate')
        except (OSError, smtplib.SMTPException, ValueError):
            db().rollback()
            current_app.logger.warning('Notification delivery failed; retained for retry')
            continue
        db().execute('UPDATE notification_deliveries SET delivered_at=? WHERE user_id=? AND post_id=?',
                     (now(), user['id'], post['id']))
        db().commit()
        sent += 1
    return sent


def digest_boundary(tenant, mode, stamp):
    """Most recent scheduled occurrence in the forum's local timezone, returned as UTC."""
    local = stamp.astimezone(ZoneInfo(tenant['digest_timezone']))
    hour, minute = map(int, tenant['digest_time'].split(':'))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
    if mode == 'weekly':
        candidate -= timedelta(days=(local.weekday() - tenant['digest_weekday']) % 7)
    if candidate.astimezone(timezone.utc) > stamp:
        candidate -= timedelta(days=7 if mode == 'weekly' else 1)
    return candidate.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _digest_subscriptions(user_id, tenant_id, mode):
    return rows('''SELECT 'forum' scope,tenant_id scope_id,since,last_digest_at,language,base_url
        FROM forum_subscriptions WHERE user_id=? AND tenant_id=? AND mode=?
        UNION ALL SELECT 'topic',s.topic_id,s.since,s.last_digest_at,s.language,s.base_url
        FROM topic_subscriptions s JOIN topics t ON t.id=s.topic_id
        WHERE s.user_id=? AND t.tenant_id=? AND s.mode=?''',
        (user_id, tenant_id, mode, user_id, tenant_id, mode))


def dispatch_digests(stamp=None):
    stamp = stamp or datetime.now(timezone.utc)
    cutoff = stamp.astimezone(timezone.utc).isoformat(timespec='microseconds')
    groups = rows('''SELECT user_id,tenant_id,mode FROM forum_subscriptions WHERE mode IN ('daily','weekly')
        UNION SELECT s.user_id,t.tenant_id,s.mode FROM topic_subscriptions s JOIN topics t ON t.id=s.topic_id
        WHERE s.mode IN ('daily','weekly')''')
    sent = 0
    for group in groups:
        db().execute('BEGIN IMMEDIATE')
        user = one('SELECT * FROM users WHERE id=?', (group['user_id'],))
        tenant = one('SELECT * FROM tenants WHERE id=?', (group['tenant_id'],))
        if not (user and tenant and user['verified'] and not user['profile_pending']
                and user['tenant_id'] in (None, tenant['id'])):
            db().rollback()
            continue
        boundary = digest_boundary(tenant, group['mode'], stamp)
        subscriptions = [s for s in _digest_subscriptions(user['id'], tenant['id'], group['mode'])
                         if max(s['since'], s['last_digest_at'] or s['since']) < boundary]
        selected = {}
        for subscription in subscriptions:
            since = max(subscription['since'], subscription['last_digest_at'] or subscription['since'])
            if subscription['scope'] == 'forum':
                visit = one('SELECT visited_at FROM forum_visits WHERE user_id=? AND tenant_id=?', (user['id'], tenant['id']))
                since = max(since, visit['visited_at']) if visit else since
            candidates = rows('''SELECT p.*,t.title,t.slug topic_slug FROM posts p JOIN topics t ON t.id=p.topic_id
                LEFT JOIN reads r ON r.topic_id=t.id AND r.user_id=?
                WHERE t.tenant_id=? AND p.user_id IS NOT ? AND p.created_at>? AND p.created_at<=?
                AND (r.visited_at IS NULL OR p.created_at>r.visited_at)'''
                + (' AND t.id=?' if subscription['scope'] == 'topic' else ''),
                (user['id'], tenant['id'], user['id'], since, cutoff)
                + ((subscription['scope_id'],) if subscription['scope'] == 'topic' else ()))
            selected.update((p['id'], p) for p in candidates)
        if selected:
            try:
                _send(tenant, user, subscriptions[0], sorted(selected.values(), key=lambda p: p['id']), group['mode'])
            except (OSError, smtplib.SMTPException, ValueError):
                db().rollback()
                current_app.logger.warning('Digest delivery failed; retained for retry')
                continue
            sent += 1
        for subscription in subscriptions:
            table, column = ('forum_subscriptions', 'tenant_id') if subscription['scope'] == 'forum' else ('topic_subscriptions', 'topic_id')
            db().execute(f'UPDATE {table} SET last_digest_at=? WHERE user_id=? AND {column}=?',
                         (cutoff, user['id'], subscription['scope_id']))
        db().commit()
    return sent


def register_notifications(app, tr):
    notifications = Blueprint('notifications', __name__)

    def save_subscription(topic=None):
        mode = request.form.get('mode')
        if mode not in dict(TOPIC_MODES if topic else FORUM_MODES):
            abort(400)
        table, column, scope_id = ('topic_subscriptions', 'topic_id', topic['id']) if topic else ('forum_subscriptions', 'tenant_id', g.tenant['id'])
        db().execute(f'''INSERT INTO {table} (user_id,{column},mode,since,language,base_url) VALUES (?,?,?,?,?,?)
            ON CONFLICT(user_id,{column}) DO UPDATE SET mode=excluded.mode,language=excluded.language,base_url=excluded.base_url,
            since=CASE WHEN mode=excluded.mode THEN since ELSE excluded.since END,
            last_digest_at=CASE WHEN mode=excluded.mode THEN last_digest_at ELSE NULL END''',
            (g.user['id'], scope_id, mode, now(), g.lang, request.url_root.rstrip('/')))
        db().commit()
        flash(tr('Benachrichtigungen gespeichert.'), 'success')
        return redirect(url_for('topic', topic_slug=topic['slug']) if topic else url_for('index'))

    @notifications.post('/notifications/forum')
    @require_login
    def forum_subscription():
        return save_subscription()

    @notifications.post('/topics/<topic_slug>/notifications')
    @require_login
    def topic_subscription(topic_slug):
        topic = one('SELECT id,slug FROM topics WHERE slug=? AND tenant_id=?', (topic_slug, g.tenant['id']))
        if not topic:
            abort(404)
        return save_subscription(topic)

    app.register_blueprint(notifications)

    def run_once():
        g.app_db = app.config['DATABASE']
        return dispatch_immediate() + dispatch_digests()

    @app.cli.command('send-notifications')
    def send_notifications():
        """Send due digests and retry pending immediate notifications once."""
        click.echo(f'{run_once()} notification email(s) sent.')

    @app.cli.command('notification-worker')
    def notification_worker():
        """Continuously send due notifications, checking every 60 seconds."""
        while True:
            try:
                run_once()
            except (OSError, sqlite3.Error):
                db().rollback()
                app.logger.exception('Notification worker will retry')
            finally:
                conn = g.pop('db', None)
                if conn:
                    conn.close()
            time.sleep(60)
