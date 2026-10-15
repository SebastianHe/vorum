"""Tenant-scoped integrations and single-use browser login links."""
import hashlib
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from . import db, email_exists, generate_password_hash, now, one, remove_avatar, role_required, rows, slug, valid_email, valid_http_url, valid_username


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def api_error(code, message, status=400):
    response = jsonify(error={'code': code, 'message': message})
    if status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer realm="Vorum API"'
    return response, status


def register_api(app, tr, send_code):
    api = Blueprint('api', __name__)

    @api.route('/admin/api', methods=['GET', 'POST'])
    @role_required('superadmin', 'admin')
    def admin_api():
        new_key = None
        if request.method == 'POST':
            if request.form.get('action') == 'revoke':
                removed = db().execute('DELETE FROM api_keys WHERE slug=? AND tenant_id=?', (request.form.get('key'), g.tenant['id']))
                if not removed.rowcount:
                    db().rollback()
                    abort(404)
                db().commit()
                flash(tr('API-Schlüssel wurde entfernt.'), 'success')
                return redirect(url_for('api.admin_api'))
            if request.form.get('action') != 'create':
                abort(400)
            name = request.form.get('name', '').strip()
            if not 1 <= len(name) <= 100:
                abort(400, tr('Bitte einen Namen mit maximal 100 Zeichen eingeben.'))
            new_key = 'vorum_' + secrets.token_urlsafe(32)
            db().execute('INSERT INTO api_keys (slug,tenant_id,name,token_hash,prefix,created_at) VALUES (?,?,?,?,?,?)',
                         (slug(name), g.tenant['id'], name, token_hash(new_key), new_key[:14], now()))
            db().commit()
        return render_template('admin.html', section='api', new_key=new_key,
                               api_keys=rows('SELECT slug,name,prefix,created_at,last_used_at FROM api_keys WHERE tenant_id=? ORDER BY id DESC', (g.tenant['id'],)))

    @api.get('/admin/api/docs')
    @role_required('superadmin', 'admin')
    def documentation():
        return send_from_directory(Path(__file__).resolve().parent.parent/'docs', 'api.md', as_attachment=True, mimetype='text/markdown')

    @api.post('/api/v1/users/login')
    def create_login():
        authorization = re.fullmatch(r'Bearer ([A-Za-z0-9_-]{1,200})', request.headers.get('Authorization', ''), re.IGNORECASE)
        key = one('SELECT * FROM api_keys WHERE token_hash=? AND tenant_id=?',
                  (token_hash(authorization[1]), g.tenant['id'])) if authorization and g.tenant else None
        if not key:
            return api_error('unauthorized', 'Gültiger Bearer-Token für dieses Forum erforderlich.', 401)
        request.max_content_length = 16384
        if not request.is_json:
            return api_error('unsupported_media_type', 'Content-Type muss application/json sein.', 415)
        if (request.content_length or 0) > 16384:
            return api_error('payload_too_large', 'JSON darf maximal 16 KiB groß sein.', 413)
        payload = request.get_json(silent=True)
        fields = {'external_id', 'email', 'email_verified', 'username', 'username_suggestion', 'avatar_url', 'avatar_suggestion'}
        if not isinstance(payload, dict) or payload.keys() - fields:
            return api_error('invalid_request', 'Ein JSON-Objekt mit den dokumentierten Feldern ist erforderlich.')
        external_id = payload.get('external_id')
        email = payload.get('email')
        name = payload.get('username')
        email_verified = payload.get('email_verified')
        name_suggestion = payload.get('username_suggestion', False)
        avatar_suggestion = payload.get('avatar_suggestion', False)
        avatar_url = payload.get('avatar_url')
        if not isinstance(external_id, str) or not external_id.strip() or len(external_id)>255 or re.search(r'[\x00-\x1f\x7f]', external_id):
            return api_error('invalid_external_id', 'external_id muss ein nicht leerer String mit maximal 255 Zeichen sein.')
        if not isinstance(email, str) or not valid_email(email):
            return api_error('invalid_email', 'email muss eine gültige E-Mail-Adresse sein.')
        email = email.lower()
        if not isinstance(name, str) or not valid_username(name):
            return api_error('invalid_username', 'username muss 1–25 Zeichen ohne äußere oder doppelte Leerzeichen enthalten.')
        if any(type(value) is not bool for value in (email_verified, name_suggestion, avatar_suggestion)):
            return api_error('invalid_boolean', 'email_verified ist erforderlich; Bestätigungs- und Vorschlagsfelder müssen JSON-Booleans sein.')
        if avatar_url is not None and (not isinstance(avatar_url, str) or (avatar_url and not valid_http_url(avatar_url))):
            return api_error('invalid_avatar_url', 'avatar_url muss eine HTTP-/HTTPS-URL oder null sein.')
        avatar_url = avatar_url or None

        # Serialize identity lookup, collision checks and token creation with revocation.
        db().execute('BEGIN IMMEDIATE')
        if not one('SELECT id FROM api_keys WHERE id=? AND tenant_id=? AND token_hash=?', (key['id'], g.tenant['id'], key['token_hash'])):
            db().rollback()
            return api_error('unauthorized', 'API-Schlüssel wurde entfernt.', 401)
        user = one('SELECT * FROM users WHERE tenant_id=? AND external_id=?', (g.tenant['id'], external_id))
        if email_exists(email, g.tenant['id'], user['id'] if user else 0):
            db().rollback()
            return api_error('email_conflict', 'Diese E-Mail-Adresse wird bereits von einem anderen Benutzer verwendet.', 409)
        created = user is None
        old_avatar = user['avatar'] if user else None
        if created:
            pending = name_suggestion or (avatar_suggestion and bool(avatar_url))
            user_id = db().execute('''INSERT INTO users
                (slug,tenant_id,username,email,password,verified,color,created_at,external_id,
                 username_suggestion,avatar_editable,avatar,avatar_suggestion_url,profile_pending)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (slug(name), g.tenant['id'], name, email, generate_password_hash(secrets.token_urlsafe(48)), int(email_verified),
                 secrets.randbelow(20), now(), external_id, int(name_suggestion), int(avatar_suggestion),
                 None if avatar_suggestion else avatar_url, avatar_url if avatar_suggestion else None, int(pending))).lastrowid
        else:
            user_id = user['id']
            # Verification is monotonic for the same address, never for a new one.
            verified = email_verified or (email == user['email'].lower() and bool(user['verified']))
            name = name if not name_suggestion or user['profile_pending'] else user['username']
            db().execute('''UPDATE users SET username=?,email=?,verified=?,username_suggestion=?,avatar_editable=?,
                avatar=?,avatar_suggestion_url=?,profile_pending=?,pending_email=NULL WHERE id=?''',
                (name, email, int(verified), int(name_suggestion), int(avatar_suggestion),
                 user['avatar'] if avatar_suggestion else avatar_url, avatar_url if avatar_suggestion else None,
                 int(bool(user['profile_pending']) and (name_suggestion or (avatar_suggestion and bool(avatar_url)))), user_id))
            if email != user['email'].lower() or verified:
                db().execute('''UPDATE users SET code_hash=NULL,registration_code=NULL,code_until=NULL,
                    code_attempts=0,cooldown_until=NULL,code_sent=NULL WHERE id=?''', (user_id,))
        user = one('SELECT * FROM users WHERE id=?', (user_id,))
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + 300
        # A fresh transfer supersedes earlier login links for the same identity.
        db().execute('DELETE FROM api_login_tokens WHERE user_id=? OR expires_at<=?', (user_id, time.time()))
        db().execute('INSERT INTO api_login_tokens (token_hash,tenant_id,user_id,key_id,expires_at) VALUES (?,?,?,?,?)',
                     (token_hash(token), g.tenant['id'], user_id, key['id'], expires_at))
        db().execute('UPDATE api_keys SET last_used_at=? WHERE id=?', (now(), key['id']))
        db().commit()
        if old_avatar != user['avatar']:
            remove_avatar(Path(app.config['DATA_DIR']), old_avatar)
        return jsonify(created=created, login_url=url_for('api.external_login', token=token, _external=True), expires_in=300,
                       expires_at=datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
                       user={'external_id': external_id, 'email': user['email'], 'email_verified': bool(user['verified']),
                             'username': user['username'], 'profile_required': bool(user['profile_pending'])}), 201 if created else 200

    @api.route('/api-login/<token>', methods=['GET', 'POST'])
    def external_login(token):
        db().execute('BEGIN IMMEDIATE')
        link = one('SELECT * FROM api_login_tokens WHERE token_hash=? AND tenant_id=? AND expires_at>?',
                   (token_hash(token), g.tenant['id'], time.time()))
        if not link:
            db().rollback()
            abort(410, tr('Dieser Login-Link ist ungültig oder abgelaufen. Bitte einen neuen Link anfordern.'))
        user = one('SELECT * FROM users WHERE id=? AND tenant_id=?', (link['user_id'], g.tenant['id']))
        if not user:
            db().rollback()
            abort(410)
        if request.method == 'HEAD':
            db().rollback()
            return '', 204
        if user['profile_pending']:
            name = request.form.get('username', user['username']) if user['username_suggestion'] else user['username']
            error = None
            if request.method == 'POST' and not valid_username(name):
                error = tr('Benutzername: 1–25 Zeichen, keine äußeren oder doppelten Leerzeichen.')
            if request.method != 'POST' or error:
                db().rollback()
                return render_template('api_profile.html', user=user, username=name, error=error), 400 if error else 200
            avatar = user['avatar_suggestion_url'] if user['avatar_editable'] and request.form.get('accept_avatar')=='on' else user['avatar']
            db().execute('UPDATE users SET username=?,avatar=?,profile_pending=0,avatar_suggestion_url=NULL WHERE id=?', (name, avatar, user['id']))
        db().execute('DELETE FROM api_login_tokens WHERE token_hash=?', (link['token_hash'],))
        db().commit()
        session.clear()
        session['user_id'] = user['id']
        if not user['verified']:
            send_code(user)
            return redirect(url_for('verify'))
        return redirect(url_for('index'))

    app.register_blueprint(api)
