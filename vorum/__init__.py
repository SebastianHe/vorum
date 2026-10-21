import hashlib
import hmac
import io
import os
import re
import secrets
import smtplib
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import bleach
from flask import Flask, abort, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash as werkzeug_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .mail import deliver_mail, system_message
from .avatars import MAX_AVATAR_BYTES, prepare_avatar

THEMES = {
    'default': ('#0077b6', '#03045e', '#caf0f8'),
    'forest': ('#23734c', '#103b29', '#d5f3df'),
    'violet': ('#7952b3', '#36205d', '#eee1ff'),
    'sunset': ('#b64d27', '#5a2518', '#ffeadb'),
    'rose': ('#b43e6c', '#591c37', '#ffe2ee'),
    'slate': ('#526b87', '#203247', '#e0eaf5'),
}
FORUM_INTRO_DEFAULTS = {
    'intro_eyebrow_de': 'DEINE COMMUNITY',
    'intro_eyebrow_en': 'YOUR COMMUNITY',
    'intro_title_de': 'Gute Gespräche beginnen hier.',
    'intro_title_en': 'Good conversations start here.',
    'intro_description_de': 'Teile Ideen, stelle Fragen und bleib im Austausch.',
    'intro_description_en': 'Share ideas, ask questions, and stay connected.',
}
COLORS = ['#235789','#a13d63','#286b54','#7952a8','#ad502a','#366c84','#824b71','#65732e','#326b73','#8d5544','#4b57a0','#9a3560','#27795c','#72549c','#93652d','#4f677c','#a04444','#476f46','#6b5792','#236f80']
# Contenteditable uses div blocks for Enter, including empty lines with a br.
ALLOWED_TAGS = ['div','p','br','strong','em','b','i','u','s','blockquote','ul','ol','li','a','h2','h3','pre','code']
SUPERADMIN_TENANT_COOKIE = 'vorum_superadmin_tenant'


def generate_password_hash(value):
    return werkzeug_hash(value, method="pbkdf2:sha256:1000000")


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def slug(text):
    value = unicodedata.normalize('NFKD', text).encode('ascii','ignore').decode().lower()
    return (re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:70] or 'entry') + '-' + secrets.token_hex(5)


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(g.app_db, timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def one(sql, args=()):
    return db().execute(sql, args).fetchone()


def rows(sql, args=()):
    return db().execute(sql, args).fetchall()


def clean_body(value):
    return bleach.clean(value, tags=ALLOWED_TAGS, attributes={'a': ['href','title']}, protocols=['http','https','mailto'], strip=True)


def valid_body(body):
    return bool(bleach.clean(body, tags=[], strip=True).replace('&nbsp;', ' ').strip()) and len(body) <= 100000


def valid_username(value):
    return 1 <= len(value) <= 25 and value == value.strip() and not re.search(r'\s{2}|[\t\n\r]', value)


def valid_email(value):
    return len(value) <= 254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value)


def safe_next(value):
    return value if value and value.startswith('/') and not value.startswith('//') and '\\' not in value and not any(ord(c)<32 for c in value) else '/'


def valid_http_url(value):
    if not isinstance(value, str) or len(value)>2048 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ('https','http') and bool(parsed.hostname) and parsed.port != 0 and not parsed.username and not parsed.password
    except ValueError:
        return False


def remove_avatar(data, filename):
    if filename and not valid_http_url(filename):
        (data/'uploads'/filename).unlink(missing_ok=True)


def email_exists(email, tenant_id, exclude=0):
    # Global identities reserve their email across all tenants; local identities may repeat.
    if tenant_id is None:
        return one('SELECT id FROM users WHERE id != ? AND (email = ? COLLATE NOCASE OR pending_email = ? COLLATE NOCASE)', (exclude,email,email))
    return one('SELECT id FROM users WHERE id != ? AND (tenant_id = ? OR tenant_id IS NULL) AND (email = ? COLLATE NOCASE OR pending_email = ? COLLATE NOCASE)', (exclude,tenant_id,email,email))


def can_moderate():
    return g.user and g.user['role'] in ('superadmin','admin','moderator')


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.user:
            return redirect(url_for('login', next=request.full_path.rstrip('?')))
        if not g.user['verified']:
            return redirect(url_for('verify', next=request.full_path.rstrip('?')))
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        @require_login
        def wrapper(*args, **kwargs):
            if g.user['role'] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def create_app(config=None):
    app = Flask(__name__)
    data = Path(os.environ.get('VORUM_DATA', 'data')).resolve()
    app.config.from_mapping(DATA_DIR=str(data), DATABASE=str(data/'vorum.sqlite3'), SECRET_KEY=os.environ.get('SECRET_KEY'),
        MAX_CONTENT_LENGTH=60*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','0')=='1', MAIL_SUPPRESS=False)
    if config:
        app.config.update(config)
    data = Path(app.config['DATA_DIR'])
    data.mkdir(parents=True, exist_ok=True)
    (data/'uploads').mkdir(exist_ok=True)
    if not app.config['SECRET_KEY']:
        keyfile = data/'secret.key'
        try:
            fd = os.open(keyfile, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = keyfile.read_text()
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.executescript(Path(__file__).with_name('schema.sql').read_text())
        migrations = {
            'tenants': {**{field: "TEXT NOT NULL DEFAULT '" + value.replace("'", "''") + "'"
                          for field, value in FORUM_INTRO_DEFAULTS.items()},
                        'timezone':"TEXT NOT NULL DEFAULT 'UTC'",
                        'logo':"TEXT NOT NULL DEFAULT ''",
                        'search_indexing_allowed':'INTEGER NOT NULL DEFAULT 1',
                        'guests_can_view_forum':'INTEGER NOT NULL DEFAULT 1',
                        'guests_can_view_topics':'INTEGER NOT NULL DEFAULT 1',
                        'registration_allowed':'INTEGER NOT NULL DEFAULT 1', 'registration_url':"TEXT NOT NULL DEFAULT ''",
                        'registration_terms':"TEXT NOT NULL DEFAULT ''", 'login_allowed':'INTEGER NOT NULL DEFAULT 1', 'login_url':"TEXT NOT NULL DEFAULT ''",
                        'digest_time':"TEXT NOT NULL DEFAULT '16:00'", 'digest_timezone':"TEXT NOT NULL DEFAULT 'Europe/Berlin'",
                        'digest_weekday':'INTEGER NOT NULL DEFAULT 5'},
            'users': {'registration_code':'TEXT', 'external_id':'TEXT', 'username_suggestion':'INTEGER NOT NULL DEFAULT 0',
                      'avatar_editable':'INTEGER NOT NULL DEFAULT 1', 'avatar_suggestion_url':'TEXT', 'profile_pending':'INTEGER NOT NULL DEFAULT 0'},
            'reads': {'visited_at':'TEXT'},
            'api_login_tokens': {'avatar_preview':'BLOB'},
        }
        for table, additions in migrations.items():
            columns = {column[1] for column in conn.execute(f'PRAGMA table_info({table})')}
            for column, definition in additions.items():
                if column not in columns:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS user_external_id ON users(tenant_id,external_id) WHERE external_id IS NOT NULL')
        conn.commit()
        conn.execute('PRAGMA journal_mode = WAL')
    app.extensions['outbox'] = []
    from .notifications import FORUM_MODES, TOPIC_MODES, dispatch_immediate, queue_immediate, register_notifications, subscription_mode, visit_forum

    @app.before_request
    def prepare():
        g.app_db = app.config['DATABASE']
        host = request.host.lower().split(':')[0].rstrip('.')
        g.tenant = one('SELECT t.* FROM tenants t JOIN hosts h ON h.tenant_id=t.id WHERE h.hostname=?', (host,))
        g.tenant_selection_active = False
        g.lang = session.get('lang') or request.accept_languages.best_match(['de','en']) or 'de'
        # JSON endpoints authenticate only with Bearer tokens, never browser cookies.
        if request.path.startswith('/api/'):
            g.user = None
            return
        g.user = one('SELECT * FROM users WHERE id=?', (session.get('user_id'),))
        if g.user and g.user['tenant_id'] is not None and (not g.tenant or g.user['tenant_id'] != g.tenant['id']):
            g.user = None
        # The cookie selects a forum, but never grants access on its own.
        if (g.user and g.user['role']=='superadmin' and g.user['verified'] and not g.user['profile_pending']
                and request.endpoint not in ('superadmin', 'api.external_login', 'api.avatar_preview')):
            selected = request.cookies.get(SUPERADMIN_TENANT_COOKIE)
            if selected:
                tenant = one('SELECT * FROM tenants WHERE slug=?', (selected,))
                if tenant:
                    g.tenant = tenant
                    g.tenant_selection_active = True
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST' and not hmac.compare_digest(session['csrf'].encode(), request.form.get('csrf','').encode()):
            abort(400, 'Ungültiges Formular. Bitte Seite neu laden.')
        allowed = {'index','register','login','logout','verify','resend','static','language','superadmin','tenant_edit','tenant_open'}
        if not g.tenant and request.endpoint not in allowed and request.endpoint is not None:
            abort(404)

        if g.user and g.user['profile_pending']:
            g.user = None
            session.pop('user_id', None)

        guest_endpoints = {'register','login','logout','verify','resend','static','language','forum_branding','robots',
                           'api.external_login','api.avatar_preview'}
        if g.tenant and not g.user and request.endpoint is not None:
            if (not g.tenant['guests_can_view_forum'] and request.endpoint not in guest_endpoints
                    or not g.tenant['guests_can_view_topics'] and request.endpoint == 'topic'):
                return redirect(url_for('login', next=request.full_path.rstrip('?')))

    @app.after_request
    def clear_tenant_selection(response):
        if request.path.startswith('/api/'):
            return response
        if request.cookies.get(SUPERADMIN_TENANT_COOKIE) and (
                request.endpoint=='superadmin'
                or not g.user or g.user['role']!='superadmin' or not g.user['verified']
                or g.user['profile_pending'] or session.get('user_id')!=g.user['id']):
            response.delete_cookie(SUPERADMIN_TENANT_COOKIE, secure=app.config['SESSION_COOKIE_SECURE'],
                                   httponly=True, samesite='Lax')
        return response

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop('db', None)
        if conn:
            conn.close()

    from .translations import DE, EN

    def tr(value):
        return EN.get(value, value) if g.lang == 'en' else DE.get(value, value)

    @app.context_processor
    def context():
        return dict(t=tr, themes=THEMES, colors=COLORS, can_moderate=can_moderate, csrf=session.get('csrf'),
                    valid_http_url=valid_http_url, forum_notification_modes=FORUM_MODES, topic_notification_modes=TOPIC_MODES,
                    notification_mode=subscription_mode,
                    palette=THEMES.get(g.tenant['theme'] if g.tenant else 'default',THEMES['default']))

    @app.template_filter('date')
    def format_date(value):
        if not value:
            return ''
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo(g.tenant['timezone'] if g.tenant else 'UTC'))
        return dt.strftime('%d.%m.%Y · %H:%M %Z' if g.lang=='de' else '%Y-%m-%d · %H:%M %Z')

    def fail(message, endpoint=None, **kwargs):
        flash(tr(message), 'error')
        return redirect(url_for(endpoint, **kwargs) if endpoint else request.full_path.rstrip('?'))

    def send_code(user, email=None):
        db().execute('BEGIN IMMEDIATE')
        user = one('SELECT * FROM users WHERE id=?', (user['id'],))
        stamp = time.time()
        if (user['cooldown_until'] or 0) > stamp:
            db().rollback()
            flash(tr('Zu viele Fehlversuche. Bitte 30 Minuten warten.'), 'error')
            return False
        if (user['code_sent'] or 0) > stamp-60:
            db().rollback()
            flash(tr('Bitte vor erneutem Versand 60 Sekunden warten.'), 'error')
            return False
        code = f'{secrets.randbelow(100000):05d}'
        target = user['pending_email'] or user['email']
        tenant = g.tenant
        message = system_message(
            tenant, target, (tenant['name'] if tenant else 'Vorum') + ' — ' + tr('Dein Freischaltcode'),
            language=g.lang, origin=request.url_root, title=tr('E-Mail bestätigen'), code=code,
            paragraphs=[tr('Du hast eine Bestätigung deiner E-Mail-Adresse angefordert.'),
                        tr('E-Mail-Adresse:') + ' ' + target,
                        tr('Öffne die Bestätigungsseite und gib dort den fünfstelligen Code ein. Melde dich bei Bedarf zuerst mit deinem Konto an.')],
            action_label=tr('E-Mail bestätigen'), action_path=url_for('verify'),
            notes=[tr('Der Code ist ab dem Versand 15 Minuten gültig. Wenn du einen neuen Code anforderst, verliert der bisherige Code seine Gültigkeit.'),
                   tr('Gib diesen Code nicht weiter. Falls du diese Bestätigung nicht angefordert hast, kannst du diese E-Mail ignorieren. Ohne Eingabe des Codes wird die E-Mail-Adresse nicht bestätigt.')])
        try:
            deliver_mail(tenant, message, code=code)
        except (OSError,smtplib.SMTPException,ValueError):
            db().rollback()
            app.logger.warning('Verification mail delivery failed')
            flash(tr('E-Mail konnte nicht versendet werden. Bitte SMTP-Einstellungen prüfen lassen und erneut versuchen.'),'error')
            return False
        # Resending never resets failures during the active verification cycle.
        attempts = 0 if user['cooldown_until'] and user['cooldown_until'] <= stamp else user['code_attempts']
        db().execute('UPDATE users SET code_hash=?, registration_code=?, code_until=?, code_sent=?, code_attempts=?, cooldown_until=NULL WHERE id=?',
            (generate_password_hash(code),code if not user['verified'] else None,stamp+900,stamp,attempts,user['id']))
        db().commit()
        flash(tr('Freischaltcode wurde versendet.'),'success')
        return True

    @app.post('/language/<lang>')
    def language(lang):
        session['lang'] = lang if lang in ('de','en') else 'de'
        return redirect(safe_next(request.form.get('next')))

    @app.get('/robots.txt')
    def robots():
        rule='Allow: /' if g.tenant['search_indexing_allowed'] else 'Disallow: /'
        return app.response_class('User-agent: *\n' + rule + '\n', mimetype='text/plain')

    @app.get('/')
    def index():
        if not g.tenant:
            return render_template('unconfigured.html', first=not one('SELECT id FROM users LIMIT 1'))
        visit_forum()
        db().commit()
        topics = rows('''SELECT t.*, c.name category, r.revision read_revision,
            (SELECT COUNT(*)-1 FROM posts p WHERE p.topic_id=t.id) replies
            FROM topics t LEFT JOIN categories c ON c.id=t.category_id
            LEFT JOIN reads r ON r.topic_id=t.id AND r.user_id=?
            WHERE t.tenant_id=? ORDER BY t.activity DESC LIMIT 100''', (g.user['id'] if g.user else 0,g.tenant['id']))
        authors = {}
        for topic in topics:
            authors[topic['id']] = rows('''SELECT DISTINCT p.username, p.user_id, u.avatar, COALESCE(u.color,0) color, u.slug
                FROM posts p LEFT JOIN users u ON u.id=p.user_id WHERE p.topic_id=? LIMIT 5''',(topic['id'],))
        return render_template('index.html', topics=topics, authors=authors)

    @app.route('/register',methods=['GET','POST'])
    def register():
        first = not one('SELECT id FROM users LIMIT 1')
        if g.tenant:
            if g.tenant['registration_url']:
                return redirect(g.tenant['registration_url'])
            if not g.tenant['registration_allowed']:
                abort(403, tr('Die Registrierung ist deaktiviert.'))
        if not g.tenant and not first:
            return redirect(url_for('login'))
        if request.method=='POST':
            if g.tenant and g.tenant['registration_terms'] and request.form.get('accept_terms') != 'on':
                return fail('Bitte die AGB akzeptieren.')
            name=request.form.get('username','')
            email=request.form.get('email','').strip().lower()
            password=request.form.get('password','')
            if not valid_username(name):
                return fail('Benutzername: 1–25 Zeichen, keine äußeren oder doppelten Leerzeichen.')
            if not valid_email(email):
                return fail('Bitte eine gültige E-Mail-Adresse eingeben.')
            if len(password)<6 or len(password)>1024 or password!=request.form.get('confirm'):
                return fail('Passwörter müssen übereinstimmen und mindestens 6 Zeichen haben.')
            db().execute('BEGIN IMMEDIATE')
            first = not one('SELECT id FROM users LIMIT 1')
            if not g.tenant and not first:
                db().rollback()
                abort(403)
            tenant_id=None if first else g.tenant['id']
            if email_exists(email,tenant_id):
                db().rollback()
                return fail('Diese E-Mail-Adresse wird bereits verwendet.')
            cursor=db().execute('INSERT INTO users (slug,tenant_id,username,email,password,role,verified,color,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (slug(name),tenant_id,name,email,generate_password_hash(password),'superadmin' if first else 'user',int(first),secrets.randbelow(20),now()))
            db().commit()
            session.clear()
            session['user_id']=cursor.lastrowid
            if not first:
                send_code(one('SELECT * FROM users WHERE id=?',(cursor.lastrowid,)))
                return redirect(url_for('verify',next=safe_next(request.args.get('next'))))
            return redirect(url_for('superadmin'))
        return render_template('auth.html', mode='register')

    @app.route('/login',methods=['GET','POST'])
    def login():
        if g.tenant:
            if g.tenant['login_url']:
                return redirect(g.tenant['login_url'])
            if not g.tenant['login_allowed']:
                abort(403, tr('Die Anmeldung ist deaktiviert.'))
        if request.method=='POST':
            email=request.form.get('email','').strip().lower()
            tenant_id=g.tenant['id'] if g.tenant else -1
            key=hashlib.sha256(f'{tenant_id}:{request.remote_addr}:{email}'.encode()).hexdigest()
            attempt=one('SELECT * FROM login_attempts WHERE key=?',(key,))
            if attempt and attempt['attempts']>=10 and attempt['until']>time.time():
                return fail('Zu viele Anmeldeversuche. Bitte 15 Minuten warten.')
            user=one('SELECT * FROM users WHERE email=? AND (tenant_id=? OR tenant_id IS NULL)',(email,tenant_id))
            password=request.form.get('password','')[:1025]
            if not user or user['external_id'] is not None or not check_password_hash(user['password'],password):
                count=attempt['attempts']+1 if attempt and attempt['until']>time.time() else 1
                db().execute('INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)',(key,count,time.time()+900))
                db().commit()
                return fail('E-Mail oder Passwort ist falsch.')
            db().execute('DELETE FROM login_attempts WHERE key=?',(key,))
            db().commit()
            session.clear()
            session['user_id']=user['id']
            target=safe_next(request.args.get('next'))
            if not user['verified']:
                send_code(user)
                return redirect(url_for('verify',next=target))
            return redirect(target)
        return render_template('auth.html',mode='login')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    @app.route('/verify', methods=['GET','POST'])
    def verify():
        if not g.user:
            return redirect(url_for('login'))
        if g.user['verified'] and not g.user['pending_email']:
            return redirect(safe_next(request.args.get('next')))
        if request.method=='POST':
            db().execute('BEGIN IMMEDIATE')
            user=one('SELECT * FROM users WHERE id=?',(g.user['id'],))
            stamp=time.time()
            if (user['cooldown_until'] or 0)>stamp:
                db().rollback()
                return fail('Zu viele Fehlversuche. Bitte 30 Minuten warten.', 'verify',next=safe_next(request.args.get('next')))
            if not user['code_hash'] or (user['code_until'] or 0)<stamp:
                db().rollback()
                return fail('Code abgelaufen. Bitte einen neuen Code anfordern.', 'verify',next=safe_next(request.args.get('next')))
            if not check_password_hash(user['code_hash'],request.form.get('code','')[:100]):
                attempts=user['code_attempts']+1
                db().execute('UPDATE users SET code_attempts=?,cooldown_until=?,code_hash=?,registration_code=? WHERE id=?',
                    (attempts,stamp+1800 if attempts>=5 else None,None if attempts>=5 else user['code_hash'],None if attempts>=5 else user['registration_code'],user['id']))
                db().commit()
                return fail('Code ist falsch.', 'verify',next=safe_next(request.args.get('next')))
            if user['pending_email'] and email_exists(user['pending_email'],user['tenant_id'],user['id']):
                db().rollback()
                return fail('Diese E-Mail-Adresse wird bereits verwendet.')
            db().execute('UPDATE users SET verified=1,email=COALESCE(pending_email,email),pending_email=NULL,code_hash=NULL,registration_code=NULL,code_attempts=0,cooldown_until=NULL,code_sent=NULL WHERE id=?',(user['id'],))
            db().commit()
            flash(tr('E-Mail-Adresse bestätigt.'),'success')
            return redirect(safe_next(request.args.get('next')))
        return render_template('auth.html',mode='verify')

    @app.post('/verify/resend')
    def resend():
        if not g.user:
            abort(403)
        if not g.user['verified'] or g.user['pending_email']:
            send_code(g.user)
        return redirect(url_for('verify',next=safe_next(request.form.get('next'))))

    def get_topic(topic_slug):
        topic=one('SELECT t.*, c.name category FROM topics t LEFT JOIN categories c ON c.id=t.category_id WHERE t.slug=? AND t.tenant_id=?',(topic_slug,g.tenant['id']))
        if not topic:
            abort(404)
        return topic

    def upload_attachments(post_id):
        files=request.files.getlist('attachments')
        if len([f for f in files if f.filename])>5:
            raise ValueError('Maximal 5 Anhänge pro Beitrag.')
        prepared=[]
        for f in files:
            if not f.filename:
                continue
            content=f.read(10*1024*1024+1)
            if len(content)>10*1024*1024:
                raise ValueError('Jeder Anhang darf maximal 10 MB groß sein.')
            prepared.append((f,content))
        for f,content in prepared:
            storage=secrets.token_hex(24)
            path=data/'uploads'/storage
            path.write_bytes(content)
            g.written_files.append(path)
            db().execute('INSERT INTO attachments (slug,post_id,filename,storage_name,size) VALUES (?,?,?,?,?)',
                (slug(f.filename),post_id,secure_filename(f.filename) or 'attachment',storage,len(content)))

    def save_post(topic_id, body):
        cursor=db().execute('INSERT INTO posts (slug,topic_id,user_id,username,body,created_at) VALUES (?,?,?,?,?,?)',
            (slug('post'),topic_id,g.user['id'],g.user['username'],body,now()))
        upload_attachments(cursor.lastrowid)
        return cursor.lastrowid

    @app.route('/topics/new',methods=['GET','POST'])
    @require_login
    def new_topic():
        categories=rows('SELECT * FROM categories WHERE tenant_id=? ORDER BY name',(g.tenant['id'],))
        if request.method=='POST':
            title=request.form.get('title','').strip()
            body=clean_body(request.form.get('body',''))
            category=next((c for c in categories if c['slug']==request.form.get('category')),None)
            if not title or len(title)>200 or not valid_body(body) or (categories and not category):
                flash(tr('Bitte Titel, Themenbereich und Beitrag prüfen.'),'error')
                return render_template('compose.html',categories=categories,post=None,topic=None),400
            topic_slug=slug(title)
            g.written_files=[]
            try:
                stamp=now()
                cursor=db().execute('INSERT INTO topics (tenant_id,slug,title,category_id,user_id,username,created_at,activity) VALUES (?,?,?,?,?,?,?,?)',
                    (g.tenant['id'],topic_slug,title,category['id'] if category else None,g.user['id'],g.user['username'],stamp,stamp))
                post_id=save_post(cursor.lastrowid,body)
                queue_immediate(post_id, is_topic=True)
                db().commit()
            except (ValueError,OSError) as e:
                db().rollback()
                for path in g.written_files:
                    path.unlink(missing_ok=True)
                flash(tr(str(e)) if isinstance(e,ValueError) else tr('Datei konnte nicht gespeichert werden.'),'error')
                return render_template('compose.html',categories=categories,post=None,topic=None),400
            dispatch_immediate(post_id)
            return redirect(url_for('topic',topic_slug=topic_slug))
        return render_template('compose.html',categories=categories,post=None,topic=None)

    @app.get('/topics/<topic_slug>')
    def topic(topic_slug):
        topic=get_topic(topic_slug)
        db().execute('UPDATE topics SET views=views+1 WHERE id=?',(topic['id'],))
        if g.user and g.user['verified']:
            db().execute('''INSERT INTO reads (user_id,topic_id,revision,visited_at) VALUES (?,?,?,?)
                ON CONFLICT(user_id,topic_id) DO UPDATE SET revision=excluded.revision,visited_at=excluded.visited_at''',
                (g.user['id'],topic['id'],topic['revision'],now()))
            visit_forum()
        db().commit()
        posts=rows('SELECT p.*,u.avatar,u.slug user_slug,COALESCE(u.color,0) color FROM posts p LEFT JOIN users u ON p.user_id=u.id WHERE p.topic_id=? ORDER BY p.id',(topic['id'],))
        attachments={p['id']: rows('SELECT * FROM attachments WHERE post_id=?',(p['id'],)) for p in posts}
        return render_template('topic.html',topic=topic,posts=posts,attachments=attachments)

    @app.route('/topics/<topic_slug>/reply',methods=['GET','POST'])
    @require_login
    def reply(topic_slug):
        topic=get_topic(topic_slug)
        if request.method=='POST':
            body=clean_body(request.form.get('body',''))
            if not valid_body(body):
                flash(tr('Bitte einen Beitrag eingeben.'),'error')
                return render_template('compose.html',topic=topic,post=None,categories=[]),400
            g.written_files=[]
            try:
                post_id=save_post(topic['id'],body)
                db().execute('UPDATE topics SET activity=?,revision=revision+1 WHERE id=?',(now(),topic['id']))
                queue_immediate(post_id)
                db().commit()
            except (ValueError,OSError) as e:
                db().rollback()
                for path in g.written_files:
                    path.unlink(missing_ok=True)
                flash(tr(str(e)) if isinstance(e,ValueError) else tr('Datei konnte nicht gespeichert werden.'),'error')
                return render_template('compose.html',topic=topic,post=None,categories=[]),400
            dispatch_immediate(post_id)
            return redirect(url_for('topic',topic_slug=topic_slug))
        return render_template('compose.html',topic=topic,post=None,categories=[])

    def get_post(post_slug):
        post=one('SELECT p.*,t.slug topic_slug FROM posts p JOIN topics t ON p.topic_id=t.id WHERE p.slug=? AND t.tenant_id=?',(post_slug,g.tenant['id']))
        if not post:
            abort(404)
        return post

    @app.route('/posts/<post_slug>/edit',methods=['GET','POST'])
    @require_login
    def edit_post(post_slug):
        post=get_post(post_slug)
        if not can_moderate() and post['user_id']!=g.user['id']:
            abort(403)
        if request.method=='POST':
            body=clean_body(request.form.get('body',''))
            if not valid_body(body):
                return fail('Bitte einen Beitrag eingeben.')
            stamp=now()
            g.written_files=[]
            try:
                upload_attachments(post['id'])
                db().execute('INSERT INTO edits (post_id,body,editor_name,created_at) VALUES (?,?,?,?)',(post['id'],post['body'],g.user['username'],stamp))
                db().execute('UPDATE posts SET body=?,edited_at=?,editor_name=? WHERE id=?',(body,stamp,g.user['username'],post['id']))
                db().execute('UPDATE topics SET revision=revision+1,activity=? WHERE id=?',(stamp,post['topic_id']))
                db().commit()
            except (ValueError,OSError) as e:
                db().rollback()
                for path in g.written_files:
                    path.unlink(missing_ok=True)
                return fail(str(e) if isinstance(e,ValueError) else 'Datei konnte nicht gespeichert werden.')
            return redirect(url_for('topic',topic_slug=post['topic_slug']))
        return render_template('compose.html',post=post,topic=get_topic(post['topic_slug']),categories=[])

    @app.get('/posts/<post_slug>/history')
    @require_login
    def history(post_slug):
        post=get_post(post_slug)
        if not can_moderate() and post['user_id']!=g.user['id']:
            abort(403)
        return render_template('history.html',post=post,edits=rows('SELECT * FROM edits WHERE post_id=? ORDER BY id DESC',(post['id'],)))

    @app.post('/posts/<post_slug>/delete')
    @role_required('superadmin','admin','moderator')
    def delete_post(post_slug):
        post=get_post(post_slug)
        files=rows('SELECT storage_name FROM attachments WHERE post_id=?',(post['id'],))
        db().execute('DELETE FROM posts WHERE id=?',(post['id'],))
        remaining=one('SELECT id FROM posts WHERE topic_id=?',(post['topic_id'],))
        if not remaining:
            db().execute('DELETE FROM topics WHERE id=?',(post['topic_id'],))
        else:
            db().execute('UPDATE topics SET revision=revision+1,activity=? WHERE id=?',(now(),post['topic_id']))
        db().commit()
        for f in files:
            (data/'uploads'/f['storage_name']).unlink(missing_ok=True)
        return redirect(url_for('topic',topic_slug=post['topic_slug']) if remaining else url_for('index'))

    @app.get('/attachments/<attachment_slug>')
    @require_login
    def attachment(attachment_slug):
        item=one('SELECT a.* FROM attachments a JOIN posts p ON p.id=a.post_id JOIN topics t ON t.id=p.topic_id WHERE a.slug=? AND t.tenant_id=?',(attachment_slug,g.tenant['id']))
        if not item:
            abort(404)
        return send_from_directory(data/'uploads',item['storage_name'],as_attachment=True,download_name=item['filename'],mimetype='application/octet-stream')

    @app.get('/avatars/<user_slug>')
    def avatar(user_slug):
        user=one('SELECT * FROM users WHERE slug=? AND (tenant_id=? OR tenant_id IS NULL)',(user_slug,g.tenant['id']))
        if not user or not user['avatar']:
            abort(404)
        if valid_http_url(user['avatar']):
            return redirect(user['avatar'])
        return send_from_directory(data/'uploads',user['avatar'],mimetype='image/png')

    def save_avatar(file):
        content=prepare_avatar(file.read(MAX_AVATAR_BYTES+1))
        filename=secrets.token_hex(24)+'.png'
        (data/'uploads'/filename).write_bytes(content)
        return filename

    def delete_user(user):
        db().execute('BEGIN IMMEDIATE')
        if user['role']=='superadmin' and one("SELECT COUNT(*) n FROM users WHERE role='superadmin'")['n']<=1:
            db().rollback()
            return False
        db().execute('UPDATE posts SET username=? WHERE user_id=?',(user['username'],user['id']))
        db().execute('UPDATE topics SET username=? WHERE user_id=?',(user['username'],user['id']))
        db().execute('DELETE FROM users WHERE id=?',(user['id'],))
        db().commit()
        remove_avatar(data, user['avatar'])
        return True

    @app.route('/settings',methods=['GET'])
    @require_login
    def settings():
        return render_template('settings.html',section=None)

    @app.route('/settings/<section>',methods=['GET','POST'])
    @require_login
    def account(section):
        if section not in ('email','password','avatar','delete'):
            abort(404)
        if g.user['external_id'] is not None and (section in ('email','password') or (section=='avatar' and not g.user['avatar_editable'])):
            abort(403, tr('Diese Profildaten werden von der angebundenen Anwendung verwaltet.'))
        if request.method=='POST':
            if g.user['external_id'] is not None and section=='delete' and request.form.get('confirm_delete') != 'on':
                return fail('Bitte die Kontolöschung bestätigen.')
            if g.user['external_id'] is None and section in ('email','password','delete') and not check_password_hash(g.user['password'],request.form.get('current_password','')[:1025]):
                return fail('Aktuelles Passwort ist falsch.')
            if section=='email':
                email=request.form.get('email','').strip().lower()
                db().execute('BEGIN IMMEDIATE')
                if not valid_email(email) or email_exists(email,g.user['tenant_id'],g.user['id']):
                    db().rollback()
                    return fail('E-Mail ungültig oder bereits vergeben.')
                db().execute('UPDATE users SET pending_email=? WHERE id=?',(email,g.user['id']))
                db().commit()
                user=one('SELECT * FROM users WHERE id=?',(g.user['id'],))
                # Invalidate any code sent to a previous pending address.
                db().execute('UPDATE users SET code_hash=NULL,registration_code=NULL WHERE id=?',(user['id'],))
                db().commit()
                send_code(user,email)
                return redirect(url_for('verify',next='/settings'))
            elif section=='password':
                password=request.form.get('password','')
                if len(password)<6 or len(password)>1024 or password!=request.form.get('confirm'):
                    return fail('Passwörter müssen übereinstimmen und mindestens 6 Zeichen haben.')
                db().execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(password),g.user['id']))
                db().commit()
            elif section=='avatar':
                db().execute('BEGIN IMMEDIATE')
                current_user=one('SELECT * FROM users WHERE id=?',(g.user['id'],))
                if not current_user or (current_user['external_id'] is not None and not current_user['avatar_editable']):
                    db().rollback()
                    abort(403, tr('Diese Profildaten werden von der angebundenen Anwendung verwaltet.'))
                file=request.files.get('avatar')
                if not file or not file.filename:
                    db().rollback()
                    return fail('Bitte eine Datei auswählen.')
                try:
                    filename=save_avatar(file)
                except ValueError as e:
                    db().rollback()
                    return fail(str(e))
                db().execute('UPDATE users SET avatar=? WHERE id=?',(filename,g.user['id']))
                db().commit()
                remove_avatar(data, current_user['avatar'])
            elif section=='delete':
                if not delete_user(g.user):
                    return fail('Der letzte Super-Admin kann nicht gelöscht werden.')
                session.clear()
                return redirect(url_for('index'))
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('settings'))
        return render_template('settings.html',section=section)

    @app.route('/super',methods=['GET','POST'])
    @role_required('superadmin')
    def superadmin():
        if request.method=='POST':
            return save_tenant(None)
        tenants=rows('SELECT * FROM tenants ORDER BY name')
        return render_template('super.html',tenants=tenants,hosts={t['id']:rows('SELECT hostname FROM hosts WHERE tenant_id=?',(t['id'],)) for t in tenants},editing=None)

    def save_tenant(tenant):
        name=request.form.get('name','').strip()
        hostnames=list(dict.fromkeys(h.strip().lower().rstrip('.') for h in request.form.get('hosts','').splitlines() if h.strip()))
        if not name or len(name)>100 or not hostnames or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',h) or '..' in h for h in hostnames):
            return fail('Bitte Namen und gültige Hostnamen ohne Protokoll oder Port eingeben.')
        try:
            if tenant:
                tid=tenant['id']
                db().execute('UPDATE tenants SET name=? WHERE id=?',(name,tid))
                db().execute('DELETE FROM hosts WHERE tenant_id=?',(tid,))
            else:
                tid=db().execute('INSERT INTO tenants (slug,name) VALUES (?,?)',(slug(name),name)).lastrowid
            for hostname in hostnames:
                db().execute('INSERT INTO hosts VALUES (?,?)',(hostname,tid))
            db().commit()
        except sqlite3.IntegrityError:
            db().rollback()
            return fail('Ein Hostname ist bereits vergeben.')
        return redirect(url_for('superadmin'))

    @app.route('/super/forums/<tenant_slug>',methods=['GET','POST'])
    @role_required('superadmin')
    def tenant_edit(tenant_slug):
        tenant=one('SELECT * FROM tenants WHERE slug=?',(tenant_slug,))
        if not tenant:
            abort(404)
        if request.method=='POST':
            return save_tenant(tenant)
        return render_template('super.html',tenants=[],hosts={},editing=tenant,host_text='\n'.join(h['hostname'] for h in rows('SELECT hostname FROM hosts WHERE tenant_id=?',(tenant['id'],))))

    @app.post('/super/forums/<tenant_slug>/open')
    @role_required('superadmin')
    def tenant_open(tenant_slug):
        tenant=one('SELECT * FROM tenants WHERE slug=?',(tenant_slug,))
        if not tenant:
            abort(404)
        destination=request.form.get('destination')
        if destination not in ('index','admin'):
            abort(400)
        response=redirect(url_for(destination))
        response.set_cookie(SUPERADMIN_TENANT_COOKIE,tenant['slug'],secure=app.config['SESSION_COOKIE_SECURE'],
                            httponly=True,samesite='Lax')
        return response

    @app.get('/admin')
    @role_required('superadmin','admin')
    def admin():
        counts={table:one(f'SELECT COUNT(*) n FROM {table} WHERE tenant_id=?',(g.tenant['id'],))['n'] for table in ('topics','categories','users')}
        return render_template('admin.html',section='dashboard',counts=counts)

    @app.route('/admin/categories',methods=['GET','POST'])
    @role_required('superadmin','admin')
    def categories():
        if request.method=='POST':
            name=request.form.get('name','').strip()
            if not name or len(name)>100:
                return fail('Bitte einen Namen mit maximal 100 Zeichen eingeben.')
            db().execute('INSERT INTO categories (tenant_id,slug,name) VALUES (?,?,?)',(g.tenant['id'],slug(name),name))
            db().commit()
            return redirect(url_for('categories'))
        return render_template('admin.html',section='categories',categories=rows('SELECT * FROM categories WHERE tenant_id=? ORDER BY name',(g.tenant['id'],)))

    @app.post('/admin/categories/<category_slug>')
    @role_required('superadmin','admin')
    def category_edit(category_slug):
        category=one('SELECT * FROM categories WHERE slug=? AND tenant_id=?',(category_slug,g.tenant['id']))
        if not category:
            abort(404)
        if request.form.get('action')=='delete':
            db().execute('DELETE FROM categories WHERE id=?',(category['id'],))
        else:
            name=request.form.get('name','').strip()
            if not name or len(name)>100:
                return fail('Bitte einen Namen mit maximal 100 Zeichen eingeben.','categories')
            db().execute('UPDATE categories SET name=? WHERE id=?',(name,category['id']))
        db().commit()
        return redirect(url_for('categories'))

    @app.get('/admin/users')
    @role_required('superadmin','admin')
    def users():
        query=request.args.get('q','')[:100]
        users=rows('SELECT * FROM users WHERE (tenant_id=? OR tenant_id IS NULL) AND (username LIKE ? OR email LIKE ?) ORDER BY username',(g.tenant['id'],'%'+query+'%','%'+query+'%'))
        return render_template('admin.html',section='users',users=users,query=query)

    @app.route('/admin/users/<user_slug>',methods=['GET','POST'])
    @role_required('superadmin','admin')
    def user_edit(user_slug):
        user=one('SELECT * FROM users WHERE slug=? AND (tenant_id=? OR tenant_id IS NULL)',(user_slug,g.tenant['id']))
        if not user:
            abort(404)
        editable=g.user['role']=='superadmin' or (user['tenant_id']==g.tenant['id'] and user['role'] != 'superadmin')
        if request.method=='POST':
            if not editable:
                abort(403)
            if request.form.get('action')=='activate':
                db().execute('BEGIN IMMEDIATE')
                user=one('SELECT * FROM users WHERE id=?',(user['id'],))
                if not user['verified']:
                    if user['pending_email'] and email_exists(user['pending_email'],user['tenant_id'],user['id']):
                        db().rollback()
                        return fail('Diese E-Mail-Adresse wird bereits verwendet.')
                    db().execute('UPDATE users SET verified=1,email=COALESCE(pending_email,email),pending_email=NULL,code_hash=NULL,registration_code=NULL,code_until=NULL,code_attempts=0,cooldown_until=NULL,code_sent=NULL WHERE id=?',(user['id'],))
                    flash(tr('Benutzer wurde freigeschaltet.'),'success')
                db().commit()
                return redirect(url_for('user_edit',user_slug=user_slug))
            if request.form.get('action')=='delete':
                if not delete_user(user):
                    return fail('Der letzte Super-Admin kann nicht gelöscht werden.')
                return redirect(url_for('users'))
            name=request.form.get('username','')
            email=request.form.get('email','').strip().lower()
            password=request.form.get('password','')
            role=request.form.get('role',user['role'])
            tenant_id=None if g.user['role']=='superadmin' and request.form.get('global') else user['tenant_id']
            if user['role']=='superadmin':
                tenant_id=None
            allowed_roles=('user','moderator','admin','superadmin') if g.user['role']=='superadmin' else ('user','moderator','admin')
            if role=='superadmin':
                tenant_id=None
            if not valid_username(name) or not valid_email(email) or role not in allowed_roles or (password and not 6<=len(password)<=1024):
                return fail('Bitte Benutzerdaten prüfen.')
            db().execute('BEGIN IMMEDIATE')
            user=one('SELECT * FROM users WHERE id=?',(user['id'],))
            if not user:
                db().rollback()
                abort(404)
            if user['external_id'] is not None and (email!=user['email'] or password or tenant_id!=user['tenant_id'] or (not user['avatar_editable'] and request.files.get('avatar') and request.files['avatar'].filename)):
                db().rollback()
                return fail('Diese Profildaten werden von der angebundenen Anwendung verwaltet.')
            if email_exists(email,tenant_id,user['id']) or email_exists(user['email'],tenant_id,user['id']) or (user['pending_email'] and email_exists(user['pending_email'],tenant_id,user['id'])):
                db().rollback()
                return fail('Diese E-Mail-Adresse wird bereits verwendet.')
            if user['role']=='superadmin' and role!='superadmin' and one("SELECT COUNT(*) n FROM users WHERE role='superadmin'")['n']<=1:
                db().rollback()
                return fail('Der letzte Super-Admin kann nicht herabgestuft werden.')
            avatar=user['avatar']
            file=request.files.get('avatar')
            if file and file.filename:
                try:
                    avatar=save_avatar(file)
                except ValueError as e:
                    db().rollback()
                    return fail(str(e))
            changed_email=email!=user['email']
            db().execute('UPDATE users SET username=?,pending_email=?,password=?,role=?,tenant_id=?,avatar=?,registration_code=CASE WHEN ? THEN NULL ELSE registration_code END,code_hash=? WHERE id=?',
                (name,email if changed_email else user['pending_email'],generate_password_hash(password) if password else user['password'],role,tenant_id,avatar,changed_email,None if changed_email else user['code_hash'],user['id']))
            db().commit()
            if avatar!=user['avatar']:
                remove_avatar(data, user['avatar'])
            if changed_email:
                send_code(one('SELECT * FROM users WHERE id=?',(user['id'],)),email)
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('user_edit',user_slug=user_slug))
        registration_code = user['registration_code'] if (editable and not user['verified'] and user['code_hash']
            and (user['code_until'] or 0) > time.time() and (user['cooldown_until'] or 0) <= time.time()) else None
        return render_template('admin.html',section='user',user=user,editable=editable,registration_code=registration_code)

    @app.route('/admin/appearance', methods=['GET','POST'])
    @role_required('superadmin','admin')
    def admin_appearance():
        if request.method=='POST':
            theme=request.form.get('theme',g.tenant['theme'])
            intro={field:request.form.get(field,g.tenant[field]).strip() for field in FORUM_INTRO_DEFAULTS}
            if theme not in THEMES:
                return fail('Bitte Einstellungen prüfen.')
            if any(len(value)>2000 for value in intro.values()):
                return fail('Startseitentexte dürfen jeweils maximal 2000 Zeichen enthalten.')
            db().execute('UPDATE tenants SET theme=?,' + ','.join(field+'=?' for field in intro) + ' WHERE id=?',
                         (theme,*intro.values(),g.tenant['id']))
            db().commit()
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('admin_appearance'))
        return render_template('admin.html',section='appearance')

    def remove_logo(filename):
        if filename:
            (data/'uploads'/filename).unlink(missing_ok=True)
            (data/'uploads'/Path(filename).with_suffix('.ico')).unlink(missing_ok=True)

    @app.route('/admin/appearance/logo', methods=['GET','POST'])
    @role_required('superadmin','admin')
    def admin_logo():
        if request.method=='POST':
            action=request.form.get('action')
            filename=''
            if action=='upload':
                file=request.files.get('logo')
                content=file.read(10*1024*1024+1) if file else b''
                message='Logo: maximal 10 MB und ein gültiges Bild mit höchstens 20 Millionen Pixeln.'
                if not content or len(content)>10*1024*1024:
                    return fail(message)
                try:
                    with Image.open(io.BytesIO(content)) as img:
                        if img.width*img.height>20000000:
                            return fail(message)
                        img.load()
                        logo=ImageOps.exif_transpose(img).convert('RGBA')
                        logo.thumbnail((1024,1024),Image.Resampling.LANCZOS)
                except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
                    return fail(message)
                filename=secrets.token_hex(24)+'.png'
                try:
                    logo.save(data/'uploads'/filename,'PNG')
                    icon=Image.new('RGBA',(256,256))
                    thumb=logo.copy()
                    thumb.thumbnail((256,256),Image.Resampling.LANCZOS)
                    icon.paste(thumb,((256-thumb.width)//2,(256-thumb.height)//2))
                    icon.save(data/'uploads'/Path(filename).with_suffix('.ico'),'ICO',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
                except Exception:
                    remove_logo(filename)
                    raise
            elif action!='remove':
                abort(400)
            try:
                db().execute('UPDATE tenants SET logo=? WHERE id=?',(filename,g.tenant['id']))
                db().commit()
            except Exception:
                remove_logo(filename)
                raise
            remove_logo(g.tenant['logo'])
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('admin_logo'))
        return render_template('admin.html',section='logo')

    @app.get('/branding/<filename>')
    def forum_branding(filename):
        logo=g.tenant['logo']
        if not logo or filename not in (logo,str(Path(logo).with_suffix('.ico'))):
            abort(404)
        return send_from_directory(data/'uploads',filename,
                                   mimetype='image/png' if filename==logo else 'image/vnd.microsoft.icon')

    @app.route('/admin/settings',methods=['GET','POST'])
    @role_required('superadmin','admin')
    def admin_settings():
        timezones = ['UTC'] + sorted(available_timezones() - {'UTC'})
        if request.method=='POST':
            name=request.form.get('name','').strip()
            forum_timezone=request.form.get('timezone',g.tenant['timezone']).strip()
            if forum_timezone not in timezones:
                return fail('Bitte eine gültige Zeitzone wählen.')
            registration_url=request.form.get('registration_url','').strip()
            login_url=request.form.get('login_url','').strip()
            terms=request.form.get('registration_terms','').strip()
            if not name or len(name)>100:
                return fail('Bitte Einstellungen prüfen.')
            if (registration_url and not valid_http_url(registration_url)) or (login_url and not valid_http_url(login_url)) or len(terms)>50000:
                return fail('Bitte gültige HTTP-/HTTPS-URLs und einen AGB-Text mit maximal 50000 Zeichen eingeben.')
            db().execute('UPDATE tenants SET name=?,timezone=?,registration_allowed=?,registration_url=?,registration_terms=?,login_allowed=?,login_url=? WHERE id=?',
                (name,forum_timezone,int(request.form.get('registration_allowed')=='on'),registration_url,terms,
                 int(request.form.get('login_allowed')=='on'),login_url,g.tenant['id']))
            db().commit()
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('admin_settings'))
        return render_template('admin.html',section='settings',timezones=timezones)

    @app.route('/admin/settings/access',methods=['GET','POST'])
    @role_required('superadmin','admin')
    def admin_access():
        if request.method=='POST':
            fields=('search_indexing_allowed','guests_can_view_forum','guests_can_view_topics')
            db().execute('UPDATE tenants SET ' + ','.join(field+'=?' for field in fields) + ' WHERE id=?',
                         (*[int(request.form.get(field)=='on') for field in fields],g.tenant['id']))
            db().commit()
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('admin_access'))
        return render_template('admin.html',section='access')

    @app.route('/admin/settings/mail',methods=['GET','POST'])
    @role_required('superadmin','admin')
    def admin_mail():
        timezones = ['UTC'] + sorted(available_timezones() - {'UTC'})
        if request.method=='POST':
            if request.form.get('action')=='test':
                recipient=request.form.get('recipient',g.user['email']).strip()
                if not valid_email(recipient):
                    return fail('Bitte eine gültige E-Mail-Adresse eingeben.')
                if not g.tenant['smtp_host'] or not g.tenant['mail_from']:
                    return fail('Bitte zuerst SMTP-Server und Mail-Absender speichern.')
                message=system_message(
                    g.tenant, recipient, g.tenant['name'] + ' — ' + tr('Vorum Testmail'),
                    language=g.lang, origin=request.url_root, title=tr('Vorum Testmail'),
                    paragraphs=[tr('Diese Testmail bestätigt, dass der E-Mail-Versand deines Forums funktioniert.'),
                                tr('Diese Nachricht wurde über die gespeicherten SMTP-Einstellungen versendet. Darüber werden auch Bestätigungsmails und abonnierte Benachrichtigungen verschickt.'),
                                tr('Empfänger:') + ' ' + recipient],
                    action_label=tr('Forum öffnen'),
                    notes=[tr('Diese Testmail wurde im Backend angefordert. Du musst nichts weiter tun.')])
                try:
                    deliver_mail(g.tenant,message,kind='test')
                except Exception:
                    app.logger.warning('Test mail delivery failed')
                    flash(tr('Testmail konnte nicht versendet werden. Bitte SMTP-Einstellungen prüfen.'),'error')
                else:
                    flash(tr('Testmail wurde versendet.'),'success')
                return redirect(url_for('admin_mail'))
            mail_from=request.form.get('mail_from','').strip()
            security=request.form.get('smtp_security','starttls')
            try:
                port=int(request.form.get('smtp_port','587'))
                assert 1<=port<=65535
            except (ValueError,AssertionError):
                return fail('Ungültiger SMTP-Port.')
            digest_time=request.form.get('digest_time',g.tenant['digest_time'])
            digest_timezone=request.form.get('digest_timezone',g.tenant['digest_timezone']).strip()
            try:
                digest_weekday=int(request.form.get('digest_weekday',g.tenant['digest_weekday']))
                if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',digest_time) or not 0<=digest_weekday<=6:
                    raise ValueError('Invalid schedule')
                ZoneInfo(digest_timezone)
            except (ValueError,ZoneInfoNotFoundError):
                return fail('Bitte eine gültige Uhrzeit, Zeitzone und einen Wochentag wählen.')
            if security not in ('starttls','ssl','plain') or (mail_from and not valid_email(mail_from)):
                return fail('Bitte Einstellungen prüfen.')
            password=request.form.get('smtp_password') or g.tenant['smtp_password']
            db().execute('UPDATE tenants SET smtp_host=?,smtp_port=?,smtp_user=?,smtp_password=?,smtp_security=?,mail_from=?,digest_time=?,digest_timezone=?,digest_weekday=? WHERE id=?',
                (request.form.get('smtp_host','').strip(),port,request.form.get('smtp_user','').strip(),password,
                 security,mail_from,digest_time,digest_timezone,digest_weekday,g.tenant['id']))
            db().commit()
            flash(tr('Gespeichert.'),'success')
            return redirect(url_for('admin_mail'))
        return render_template('admin.html',section='mail',timezones=timezones)

    from .api import register_api
    register_api(app, tr, send_code)
    register_notifications(app, tr)

    @app.after_request
    def security_headers(response):
        if g.get('tenant') and not g.tenant['search_indexing_allowed']:
            response.headers['X-Robots-Tag']='noindex, nofollow'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https: http:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.endpoint in ('api.external_login', 'api.avatar_preview'):
            response.headers['Referrer-Policy']='no-referrer'
        if request.endpoint!='static':
            response.headers['Cache-Control']='no-store'
        return response

    @app.errorhandler(HTTPException)
    def error(error):
        if request.path.startswith('/api/'):
            from .api import api_error
            response, status = api_error({400:'invalid_request',404:'not_found',405:'method_not_allowed',413:'payload_too_large',415:'unsupported_media_type'}.get(error.code,'http_error'), error.description, error.code)
            if error.code==405:
                response.headers['Allow']=', '.join(error.valid_methods or [])
            return response,status
        return render_template('error.html',error=error),error.code

    return app
