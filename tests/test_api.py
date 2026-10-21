import io
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest

from test_vorum import app, setup, login, post, query, register, verified
from vorum import SUPERADMIN_TENANT_COOKIE, create_app
import vorum.api as api_module


@pytest.fixture
def api_key(app, setup):
    response = post(setup, '/admin/api', {'action': 'create', 'name': 'CRM'})
    assert response.status_code == 200
    return re.search(r'value="(vorum_[A-Za-z0-9_-]+)"', response.text)[1]


def transfer(app, key, data=None, host='localhost'):
    payload = {'external_id': 'crm:0001', 'email': 'external@example.org', 'email_verified': True,
               'username': 'External', 'username_suggestion': False,
               'avatar_url': 'https://images.example.org/avatar.png', 'avatar_suggestion': False}
    payload.update(data or {})
    return app.test_client().post('/api/v1/users/login', json=payload, headers={'Authorization': 'Bearer '+key}, base_url='http://'+host)


def external_user(app):
    return query(app, 'SELECT * FROM users WHERE external_id=?', ('crm:0001',))


def test_key_is_shown_once_hashed_and_revocable(app, setup, api_key):
    key = query(app, 'SELECT * FROM api_keys')
    assert key['token_hash'] != api_key and len(key['token_hash']) == 64
    assert api_key not in setup.get('/admin/api').text
    assert setup.get('/admin/api/docs').status_code == 200
    assert b'Bearer' in setup.get('/admin/api/docs').data
    response = transfer(app, api_key)
    assert response.status_code == 201
    assert query(app, 'SELECT last_used_at FROM api_keys')['last_used_at']
    assert post(setup, '/admin/api', {'action': 'revoke', 'key': key['slug']}).status_code == 302
    assert transfer(app, api_key).status_code == 401
    assert app.test_client().get(response.json['login_url']).status_code == 410
    assert query(app, 'SELECT COUNT(*) n FROM api_login_tokens')['n'] == 0
    assert external_user(app)


def test_api_has_bearer_only_auth_json_errors_and_no_cookie(app, setup, api_key):
    for headers in ({}, {'Authorization': 'Basic abc'}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer '+api_key+' extra'}):
        response = setup.post('/api/v1/users/login', json={}, headers=headers)
        assert response.status_code == 401 and response.json['error']['code'] == 'unauthorized'
        assert response.headers['WWW-Authenticate'].startswith('Bearer')
    response = transfer(app, api_key)
    assert 'Set-Cookie' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'
    for path, method, status in [('/api/v1/missing', 'get', 404), ('/api/v1/users/login', 'get', 405)]:
        response = getattr(setup, method)(path)
        assert response.status_code == status and response.is_json
    response = setup.post('/api/v1/users/login', data='{}', headers={'Authorization': 'Bearer '+api_key})
    assert response.status_code == 415 and response.is_json
    response = setup.post('/api/v1/users/login', data='{', content_type='application/json', headers={'Authorization': 'Bearer '+api_key})
    assert response.status_code == 400 and response.json['error']['code'] == 'invalid_request'
    response = setup.post('/api/v1/users/login', json=['bad'], headers={'Authorization': 'Bearer '+api_key})
    assert response.status_code == 400
    response = setup.post('/api/v1/users/login', json={'huge': 'x'*17000}, headers={'Authorization': 'Bearer '+api_key})
    assert response.status_code == 413 and response.is_json


def test_api_ignores_superadmin_forum_selection_cookie(app,setup,api_key):
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    assert post(setup,'/super/forums/'+tenant['slug']+'/open',{'destination':'admin'}).status_code==302
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE)
    assert '<title>Second · Vorum</title>' in setup.get('/admin').text
    payload={'external_id':'cookie-test','email':'cookie@example.org','email_verified':True,'username':'Cookie test'}
    response=setup.post('/api/v1/users/login',json=payload,headers={'Authorization':'Bearer '+api_key})
    assert response.status_code==201
    assert 'Set-Cookie' not in response.headers
    assert external_user(app) is None
    user=query(app,"SELECT * FROM users WHERE external_id='cookie-test'")
    assert user['tenant_id']!=tenant['id']
    # Browser login links also retain their hostname-based forum assignment.
    assert setup.get(response.json['login_url']).location=='/'
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    assert '<title>Community · Vorum</title>' in setup.get('/').text


@pytest.mark.parametrize('data,code', [
    ({'external_id': 123}, 'invalid_external_id'),
    ({'external_id': ''}, 'invalid_external_id'),
    ({'external_id': 'x'*256}, 'invalid_external_id'),
    ({'external_id': 'a\nb'}, 'invalid_external_id'),
    ({'email': 'bad'}, 'invalid_email'),
    ({'email': None}, 'invalid_email'),
    ({'username': ' A'}, 'invalid_username'),
    ({'username': 'a  b'}, 'invalid_username'),
    ({'username': None}, 'invalid_username'),
    ({'email_verified': 'true'}, 'invalid_boolean'),
    ({'email_verified': None}, 'invalid_boolean'),
    ({'username_suggestion': 1}, 'invalid_boolean'),
    ({'avatar_suggestion': 'false'}, 'invalid_boolean'),
    ({'avatar_url': 'javascript:alert(1)'}, 'invalid_avatar_url'),
    ({'avatar_url': 'file:///etc/passwd'}, 'invalid_avatar_url'),
    ({'avatar_url': 'https://user:password@example.org/a'}, 'invalid_avatar_url'),
    ({'avatar_url': 'https://example.org:bad/a'}, 'invalid_avatar_url'),
    ({'avatar_url': 'https://example.org/a\nb'}, 'invalid_avatar_url'),
    ({'avatar_url': []}, 'invalid_avatar_url'),
    ({'role': 'superadmin'}, 'invalid_request'),
])
def test_validation_is_atomic(app, setup, api_key, data, code):
    response = transfer(app, api_key, data)
    assert response.status_code == 400 and response.json['error']['code'] == code
    assert external_user(app) is None
    assert query(app, 'SELECT COUNT(*) n FROM api_login_tokens')['n'] == 0


def test_new_user_login_is_single_use_and_supersedes_browser_session(app, setup, api_key):
    response = transfer(app, api_key, {'external_id': 'crm:0001', 'email': 'External@Example.org'})
    assert response.status_code == 201 and response.json['created'] is True
    assert response.json['expires_in'] == 300
    assert response.json['user']['profile_required'] is False
    link = response.json['login_url']
    stored = query(app, 'SELECT * FROM api_login_tokens')
    assert stored['token_hash'] != urlsplit(link).path.rsplit('/', 1)[1]
    assert setup.head(link).status_code == 204
    result = setup.get(link)
    assert result.status_code == 302 and result.location == '/'
    assert result.headers['Referrer-Policy'] == 'no-referrer'
    with setup.session_transaction() as sess:
        assert sess['user_id'] == external_user(app)['id']
    assert setup.get('/topics/new').status_code == 200
    assert app.test_client().get(link).status_code == 410
    assert external_user(app)['role'] == 'user'
    assert external_user(app)['email'] == 'external@example.org'


def test_login_expiry_and_superseded_links(app, setup, api_key):
    old = transfer(app, api_key).json['login_url']
    new = transfer(app, api_key).json['login_url']
    assert app.test_client().get(old).status_code == 410
    query(app, 'UPDATE api_login_tokens SET expires_at=0')
    assert app.test_client().get(new).status_code == 410
    assert query(app, 'SELECT COUNT(*) n FROM users WHERE external_id IS NOT NULL')['n'] == 1


def test_parallel_redemption_consumes_link_once(app, setup, api_key):
    link = transfer(app, api_key).json['login_url']
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: app.test_client().get(link).status_code, range(2)))
    assert sorted(statuses) == [302, 410]


def test_revoked_key_cannot_authenticate_when_database_id_is_reused(app, setup, api_key, monkeypatch):
    original_one = api_module.one

    def revoke_after_lookup(sql, args=()):
        result = original_one(sql, args)
        if sql.startswith('SELECT * FROM api_keys WHERE token_hash') and result:
            query(app, 'DELETE FROM api_keys WHERE id=?', (result['id'],))
            query(app, 'INSERT INTO api_keys (id,slug,tenant_id,name,token_hash,prefix,created_at) VALUES (?,?,?,?,?,?,?)',
                  (result['id'], 'replacement', result['tenant_id'], 'Replacement', api_module.token_hash('new-secret'), 'new', result['created_at']))
        return result

    monkeypatch.setattr(api_module, 'one', revoke_after_lookup)
    assert transfer(app, api_key).status_code == 401
    assert external_user(app) is None


@pytest.mark.parametrize('accept', [False, True])
def test_suggestions_require_profile_and_allow_avatar_choice(app, setup, api_key, accept):
    response = transfer(app, api_key, {'username_suggestion': True, 'avatar_suggestion': True})
    assert response.json['user']['profile_required']
    link = response.json['login_url']
    client = app.test_client()
    page = client.get(link)
    assert page.status_code == 200 and 'value="External"' in page.text
    assert 'https://images.example.org/avatar.png' in page.text
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
    assert post(client, urlsplit(link).path, {'username': ' Bad'}).status_code == 400
    assert external_user(app)['profile_pending']
    # A direct form POST without CSRF cannot consume the login link.
    assert client.post(link, data={'username': 'Chosen'}).status_code == 400
    response = post(client, urlsplit(link).path, {'username': 'Chosen', **({'accept_avatar': 'on'} if accept else {})})
    assert response.status_code == 302
    user = external_user(app)
    assert user['username'] == 'Chosen' and not user['profile_pending']
    assert user['avatar'] == ('https://images.example.org/avatar.png' if accept else None)
    assert user['avatar_editable']
    assert client.get(link).status_code == 410
    # Later suggestions never overwrite a chosen name/avatar or repeat onboarding.
    response = transfer(app, api_key, {'username': 'New suggestion', 'username_suggestion': True,
                                      'avatar_url': 'https://images.example.org/new.png', 'avatar_suggestion': True})
    assert response.status_code == 200 and not response.json['user']['profile_required']
    assert external_user(app)['username'] == 'Chosen'
    assert external_user(app)['avatar'] == user['avatar']


def test_pending_profile_obeys_latest_transfer_and_link_expiry(app, setup, api_key):
    old = transfer(app, api_key, {'username_suggestion': True}).json['login_url']
    response = transfer(app, api_key, {'username': 'Latest', 'username_suggestion': True, 'avatar_suggestion': True})
    client = app.test_client()
    assert client.get(old).status_code == 410
    assert 'value="Latest"' in client.get(response.json['login_url']).text
    query(app, 'UPDATE api_login_tokens SET expires_at=0')
    assert post(client, urlsplit(response.json['login_url']).path, {'username': 'Chosen'}).status_code == 410
    assert external_user(app)['profile_pending']
    response = transfer(app, api_key, {'username': 'Authoritative'})
    assert response.json['user']['profile_required'] is False
    assert client.get(response.json['login_url']).status_code == 302
    assert external_user(app)['username'] == 'Authoritative'


def test_avatar_suggestion_with_fixed_username(app, setup, api_key):
    response = transfer(app, api_key, {'avatar_suggestion': True})
    client = app.test_client()
    page = client.get(response.json['login_url'])
    assert page.status_code == 200 and 'name="username"' not in page.text
    post(client, urlsplit(response.json['login_url']).path, {'username': 'Hijacked', 'accept_avatar': 'on'})
    assert external_user(app)['username'] == 'External'
    assert external_user(app)['avatar'] == 'https://images.example.org/avatar.png'


def test_avatar_authority_and_account_restrictions_follow_latest_transfer(app, setup, api_key):
    response = transfer(app, api_key)
    client = app.test_client()
    client.get(response.json['login_url'])
    user = external_user(app)
    assert client.get('/avatars/'+user['slug']).location == user['avatar']
    for section in ('email', 'password', 'avatar'):
        assert client.get('/settings/'+section).status_code == 403
        assert post(client, '/settings/'+section, {'email': 'changed@example.org', 'password': 'newsecret'}).status_code == 403
    page = client.get('/settings').text
    assert '/settings/email' not in page and '/settings/password' not in page and '/settings/avatar' not in page
    # A new suggestion unlocks uploads for an existing account without replacing its image.
    transfer(app, api_key, {'avatar_suggestion': True})
    assert client.get('/settings/avatar').status_code == 200
    assert external_user(app)['avatar'] == user['avatar']
    transfer(app, api_key, {'username': 'Updated', 'avatar_url': None})
    assert external_user(app)['username'] == 'Updated'
    assert external_user(app)['avatar'] is None
    assert client.get('/settings/avatar').status_code == 403
    path = '/admin/users/'+user['slug']
    data = {'username': 'Updated', 'email': user['email'], 'role': 'user'}
    for change in ({'email': 'forbidden@example.org'}, {'password': 'newpassword'}, {'global': 'on'}, {'role': 'superadmin'}, {'avatar': (io.BytesIO(b'bad'), 'bad.png')}):
        assert post(setup, path, {**data, **change}).status_code == 302
        updated = external_user(app)
        assert updated['email'] == user['email'] and updated['password'] == user['password']
        assert updated['tenant_id'] == user['tenant_id'] and updated['role'] == 'user' and updated['avatar'] is None
    post(client, '/logout')
    login(client, 'external@example.org')
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_api_account_deletion_does_not_require_unknown_password(app, setup, api_key):
    response = transfer(app, api_key)
    client = app.test_client()
    client.get(response.json['login_url'])
    assert 'name="current_password"' not in client.get('/settings/delete').text
    post(client, '/settings/delete')
    assert external_user(app)
    post(client, '/settings/delete', {'confirm_delete': 'on'})
    assert external_user(app) is None
    assert transfer(app, api_key).status_code == 201


def test_email_collisions_never_link_local_or_global_accounts(app, setup, api_key):
    verified(app, 'taken@example.org')
    for address in ('taken@example.org', 'root@example.org', 'ROOT@example.org'):
        response = transfer(app, api_key, {'email': address})
        assert response.status_code == 409 and response.json['error']['code'] == 'email_conflict'
    assert external_user(app) is None
    transfer(app, api_key)
    response = transfer(app, api_key, {'email': 'taken@example.org', 'username': 'Must not change'})
    assert response.status_code == 409 and external_user(app)['username'] == 'External'
    query(app, "UPDATE users SET pending_email='reserved@example.org' WHERE email='taken@example.org'")
    assert transfer(app, api_key, {'email': 'reserved@example.org'}).status_code == 409


def test_verification_persists_for_same_email_but_not_new_address(app, setup, api_key):
    transfer(app, api_key)
    assert transfer(app, api_key, {'email_verified': False}).json['user']['email_verified'] is True
    response = transfer(app, api_key, {'email': 'new@example.org', 'email_verified': False})
    assert response.json['user']['email_verified'] is False
    client = app.test_client()
    assert client.get(response.json['login_url']).location == '/verify'
    assert client.get('/topics/new').location.startswith('/verify')
    post(client, '/verify', {'code': app.extensions['outbox'][-1]['code']})
    assert client.get('/topics/new').status_code == 200
    response = transfer(app, api_key, {'email': 'NEW@example.org', 'email_verified': False})
    assert response.json['user']['email_verified'] is True


def test_api_sync_preserves_verification_resend_limits(app, setup, api_key):
    response = transfer(app, api_key, {'email_verified': False})
    app.test_client().get(response.json['login_url'])
    before = external_user(app)
    assert before['code_hash'] and len(app.extensions['outbox']) == 1
    response = transfer(app, api_key, {'email_verified': False})
    after = external_user(app)
    assert after['code_hash'] == before['code_hash'] and after['code_sent'] == before['code_sent']
    app.test_client().get(response.json['login_url'])
    assert len(app.extensions['outbox']) == 1


def test_key_and_external_identity_isolation_and_aliases(app, setup, api_key):
    assert transfer(app, api_key, host='other.test').status_code == 401
    assert transfer(app, api_key, host='unknown.test').status_code == 401
    first = transfer(app, api_key)
    link = urlsplit(first.json['login_url']).path
    assert app.test_client().get(link, base_url='http://other.test').status_code == 410
    response = transfer(app, api_key, host='alias.test')
    assert response.status_code == 200
    assert query(app, 'SELECT COUNT(*) n FROM users WHERE external_id IS NOT NULL')['n'] == 1
    login(setup, host='other.test')
    result = post(setup, '/admin/api', {'action': 'create', 'name': 'Second'}, host='other.test')
    second_key = re.search(r'value="(vorum_[A-Za-z0-9_-]+)"', result.text)[1]
    assert transfer(app, second_key, host='other.test').status_code == 201
    assert query(app, 'SELECT COUNT(*) n FROM users WHERE external_id IS NOT NULL')['n'] == 2
    first_key_slug = query(app, 'SELECT slug FROM api_keys ORDER BY id')['slug']
    assert post(setup, '/admin/api', {'action': 'revoke', 'key': first_key_slug}, host='other.test').status_code == 404


def test_admin_key_management_requires_role_and_csrf(app, setup):
    assert setup.post('/admin/api', data={'action': 'create', 'name': 'Missing CSRF'}).status_code == 400
    member = verified(app)
    for path in ('/admin/api', '/admin/api/docs'):
        assert member.get(path).status_code == 403
    assert post(member, '/admin/api', {'action': 'create', 'name': 'Forbidden'}).status_code == 403
    assert query(app, 'SELECT COUNT(*) n FROM api_keys')['n'] == 0


def site_settings(client, **extra):
    return post(client, '/admin/settings', {'name': 'Community', 'theme': 'default', 'smtp_port': '587',
                 'smtp_security': 'starttls', 'registration_allowed': 'on', 'login_allowed': 'on', **extra})


def test_site_auth_defaults_and_disabled_forms_leave_api_available(app, setup, api_key):
    tenant = query(app, "SELECT * FROM tenants WHERE name='Community'")
    assert tenant['registration_allowed'] == tenant['login_allowed'] == 1
    assert tenant['registration_url'] == tenant['login_url'] == tenant['registration_terms'] == ''
    assert site_settings(setup, registration_allowed='', login_allowed='').status_code == 302
    client = app.test_client()
    for path in ('/register', '/login'):
        assert client.get(path).status_code == 403
        assert post(client, path, {'username': 'No', 'email': 'no@example.org', 'password': 'secret123', 'confirm': 'secret123'}).status_code == 403
    assert '/login' not in client.get('/').text
    response = transfer(app, api_key)
    assert response.status_code == 201
    assert client.get(response.json['login_url']).location == '/'
    assert client.get('/topics/new').status_code == 200
    # Unconfigured second forum keeps its defaults.
    assert app.test_client().get('/login', base_url='http://other.test').status_code == 200


def test_external_auth_redirects_override_disabled_local_forms(app, setup):
    site_settings(setup, registration_allowed='', login_allowed='',
                  registration_url='https://app.example.org/register', login_url='https://app.example.org/login')
    client = app.test_client()
    for path, target in [('/register', 'https://app.example.org/register'), ('/login', 'https://app.example.org/login')]:
        assert client.get(path+'?next=/admin').location == target
        assert post(client, path, {'password': 'sensitive'}).location == target
    site_settings(setup, login_url='javascript:alert(1)')
    assert query(app, "SELECT login_url FROM tenants WHERE name='Community'")['login_url'] == 'https://app.example.org/login'


def test_terms_are_escaped_displayed_and_required_server_side(app, setup):
    site_settings(setup, registration_terms='First line\n<script>alert(1)</script>')
    client = app.test_client()
    page = client.get('/register').text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page and 'name="accept_terms"' in page
    register(client, 'terms@example.org')
    assert query(app, "SELECT id FROM users WHERE email='terms@example.org'") is None
    result = post(client, '/register', {'username': 'Terms', 'email': 'terms@example.org', 'password': 'secret123',
                                      'confirm': 'secret123', 'accept_terms': 'on'})
    assert result.location.startswith('/verify')


def test_existing_database_migrates_and_keeps_users(app, setup):
    query(app, 'DROP INDEX user_external_id')
    for column in ('external_id', 'username_suggestion', 'avatar_editable', 'avatar_suggestion_url', 'profile_pending'):
        query(app, f'ALTER TABLE users DROP COLUMN {column}')
    for column in ('registration_allowed', 'registration_url', 'registration_terms', 'login_allowed', 'login_url'):
        query(app, f'ALTER TABLE tenants DROP COLUMN {column}')
    create_app(dict(app.config))
    assert query(app, 'SELECT username,external_id FROM users')['username'] == 'Root'
    tenant = query(app, 'SELECT * FROM tenants')
    assert tenant['registration_allowed'] == tenant['login_allowed'] == 1
    assert tenant['registration_url'] == tenant['login_url'] == tenant['registration_terms'] == ''
    create_app(dict(app.config))  # Migration is safe to repeat.
