import io
import sqlite3
import time

import pytest
from markupsafe import escape
from PIL import Image

from vorum import FORUM_INTRO_DEFAULTS, SUPERADMIN_TENANT_COOKIE, create_app


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path), 'DATABASE': str(tmp_path/'test.sqlite3'), 'SECRET_KEY':'test-secret', 'MAIL_SUPPRESS': True})


def query(app, sql, args=(), all=False):
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.row_factory=sqlite3.Row
        result=conn.execute(sql,args)
        return result.fetchall() if all else result.fetchone()


def post(client, path, data=None, host='localhost', follow=False):
    client.get('/',base_url='http://'+host)
    with client.session_transaction(base_url='http://'+host) as sess:
        csrf=sess['csrf']
    return client.post(path,data={**(data or {}),'csrf':csrf},base_url='http://'+host,follow_redirects=follow)


def register(client,email='root@example.org',name='Root',host='localhost',path='/register'):
    return post(client,path,{'username':name,'email':email,'password':'secret123','confirm':'secret123'},host)


def login(client,email='root@example.org',host='localhost',path='/login'):
    return post(client,path,{'email':email,'password':'secret123'},host)


@pytest.fixture
def setup(app):
    root=app.test_client()
    assert register(root).location=='/super'
    assert post(root,'/super',{'name':'Community','hosts':'localhost\nalias.test'}).status_code==302
    assert post(root,'/super',{'name':'Second','hosts':'other.test'}).status_code==302
    return root


def verified(app,email='member@example.org',host='localhost'):
    client=app.test_client()
    register(client,email,'Member',host)
    code=app.extensions['outbox'][-1]['code']
    assert post(client,'/verify',{'code':code},host).status_code==302
    return client


def new_topic(client,title='Hello world',host='localhost',**extra):
    result=post(client,'/topics/new',{'title':title,'body':'<p>Hello <strong>world</strong></p>',**extra},host)
    assert result.status_code==302
    return result.location


def test_post_line_breaks_survive_create_reply_edit_and_history(app,setup):
    body='First<div>Second</div><div><br></div><div>Fourth<br>Fifth</div>'
    topic=new_topic(setup,body=body)
    original=query(app,'SELECT * FROM posts')
    assert original['body']==body
    assert body in setup.get(topic).text

    assert post(setup,topic+'/reply',{'body':body}).status_code==302
    assert query(app,'SELECT body FROM posts ORDER BY id DESC')['body']==body

    edited=body+'<div>Sixth</div>'
    assert post(setup,'/posts/'+original['slug']+'/edit',{'body':edited}).status_code==302
    assert query(app,'SELECT body FROM posts WHERE id=?',(original['id'],))['body']==edited
    assert edited in setup.get(topic).text
    assert query(app,'SELECT body FROM edits')['body']==body
    assert body in setup.get('/posts/'+original['slug']+'/history').text


def test_post_line_blocks_still_strip_unsafe_attributes(app,setup):
    topic=new_topic(setup,body='<div onclick="alert(1)" style="display:none">First</div><div>Second</div>')
    assert query(app,'SELECT body FROM posts')['body']=='<div>First</div><div>Second</div>'
    assert '<div>First</div><div>Second</div>' in setup.get(topic).text


def test_bootstrap_and_unknown_host(app):
    client=app.test_client()
    assert b'Hostname nicht Konfiguriert' in client.get('/').data
    assert register(client).location=='/super'
    user=query(app,'SELECT * FROM users')
    assert user['role']=='superadmin' and user['tenant_id'] is None and user['verified']
    assert not app.extensions['outbox']
    assert app.test_client().get('/register').location=='/login'
    assert client.get('/topics/new').status_code==404
    assert post(client,'/super',{'name':'Forum','hosts':'localhost'}).status_code==302
    assert client.get('/').status_code==200


@pytest.mark.parametrize('destination,path', [('index','/'), ('admin','/admin')])
@pytest.mark.parametrize('host', ['localhost', 'unknown.test:8080'])
def test_superadmin_opens_forum_on_current_host(app,setup,destination,path,host):
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    if host!='localhost':
        assert login(setup,host=host).status_code==302
    response=post(setup,'/super/forums/'+tenant['slug']+'/open',{'destination':destination},host)
    assert response.status_code==302 and response.location==path
    cookie=setup.get_cookie(SUPERADMIN_TENANT_COOKIE,domain=host.split(':')[0])
    assert cookie.value==tenant['slug'] and cookie.http_only and cookie.same_site=='Lax'
    assert cookie.origin_only and cookie.path=='/' and cookie.expires is None
    page=setup.get(path,base_url='http://'+host)
    assert page.status_code==200 and '<title>Second · Vorum</title>' in page.text
    assert '<title>Second · Vorum</title>' in setup.get('/admin/settings',base_url='http://'+host).text
    # Writes and resource lookups use the selected forum too.
    location=new_topic(setup,host=host)
    assert query(app,'SELECT tenant_id FROM topics')['tenant_id']==tenant['id']
    assert setup.get(location,base_url='http://'+host).status_code==200
    other_host='alias.test'
    login(setup,host=other_host)
    assert setup.get(location,base_url='http://'+other_host).status_code==404
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE,domain=other_host) is None


def test_superadmin_selection_ends_in_overview_and_on_logout(app,setup):
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    switch='/super/forums/'+tenant['slug']+'/open'
    post(setup,switch,{'destination':'index'})
    assert setup.get('/super').status_code==200
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    assert '<title>Community · Vorum</title>' in setup.get('/').text
    post(setup,switch,{'destination':'admin'})
    assert post(setup,'/logout').status_code==302
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    assert login(setup).status_code==302
    assert '<title>Community · Vorum</title>' in setup.get('/').text


@pytest.mark.parametrize('forum', ['Community','Second'])
def test_selected_forum_header_warning_and_return(app,setup,forum):
    assert 'class="tenant-warning"' not in setup.get('/').text
    tenant=query(app,'SELECT * FROM tenants WHERE name=?',(forum,))
    post(setup,'/super/forums/'+tenant['slug']+'/open',{'destination':'index'})
    for path in ('/','/admin','/admin/settings'):
        header=setup.get(path).text.split('</header>')[0]
        assert 'class="tenant-warning" role="alert"' in header
        assert 'Du rufst ein Fremd-Forum über den aktuellen Hostnamen auf:' in header
        assert '<strong>'+forum+'</strong>' in header
        assert '<a class="button secondary compact" href="/super">Zurück</a>' in header
    post(setup,'/language/en',{'next':'/admin'})
    header=setup.get('/admin').text.split('</header>')[0]
    assert 'You are viewing another forum using the current hostname:' in header
    assert 'href="/super">Back</a>' in header
    response=setup.get('/super')
    assert response.status_code==200 and 'class="tenant-warning"' not in response.text
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    assert '<title>Community · Vorum</title>' in setup.get('/').text
    assert 'class="tenant-warning"' not in setup.get('/admin').text


@pytest.mark.parametrize('role', ['admin','moderator','user',None])
def test_forum_selection_cookie_cannot_grant_superadmin_access(app,setup,role):
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    if role:
        query(app,"UPDATE users SET role=? WHERE email='root@example.org'",(role,))
        client=setup
    else:
        client=app.test_client()
    client.set_cookie(SUPERADMIN_TENANT_COOKIE,tenant['slug'])
    page=client.get('/').text
    assert '<title>Community · Vorum</title>' in page
    assert 'class="tenant-warning"' not in page
    assert client.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    response=post(client,'/super/forums/'+tenant['slug']+'/open',{'destination':'admin'})
    assert response.status_code==(403 if role else 302)
    assert client.get_cookie(SUPERADMIN_TENANT_COOKIE) is None


def test_local_user_cannot_switch_tenant_with_forged_cookie(app,setup):
    member=verified(app)
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    member.set_cookie(SUPERADMIN_TENANT_COOKIE,tenant['slug'])
    location=new_topic(member)
    assert query(app,'SELECT tenant_id FROM topics')['tenant_id']!=tenant['id']
    assert member.get(location).status_code==200
    assert member.get('/admin').status_code==403


def test_unverified_superadmin_cannot_select_forum(app,setup):
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    query(app,"UPDATE users SET verified=0 WHERE role='superadmin'")
    setup.set_cookie(SUPERADMIN_TENANT_COOKIE,tenant['slug'])
    assert '<title>Community · Vorum</title>' in setup.get('/').text
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    assert post(setup,'/super/forums/'+tenant['slug']+'/open',{'destination':'index'}).location.startswith('/verify')
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None


def test_superadmin_selection_validation_and_secure_cookie(app,setup):
    tenant=query(app,"SELECT * FROM tenants WHERE name='Second'")
    switch='/super/forums/'+tenant['slug']+'/open'
    assert setup.get(switch).status_code==405
    assert setup.post(switch,data={'destination':'admin'}).status_code==400
    assert post(setup,'/super/forums/missing/open',{'destination':'index'}).status_code==404
    for destination in ('','https://evil.test','//evil.test','settings'):
        assert post(setup,switch,{'destination':destination}).status_code==400
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE) is None
    setup.set_cookie(SUPERADMIN_TENANT_COOKIE,'missing-forum')
    page=setup.get('/').text
    assert '<title>Community · Vorum</title>' in page
    assert 'class="tenant-warning"' not in page
    app.config['SESSION_COOKIE_SECURE']=True
    assert post(setup,switch,{'destination':'admin'}).status_code==302
    assert setup.get_cookie(SUPERADMIN_TENANT_COOKIE).secure


def test_superadmin_forum_links_and_dropdown_translations(app,setup):
    page=setup.get('/super').text
    for host in ('localhost','alias.test','other.test'):
        assert 'href="http://'+host+'/"' in page
        assert 'href="http://'+host+'/admin"' in page
    assert page.count('class="forum-open-menu"')==6
    assert page.count('Über den aktuellen Hostname öffnen')==6
    post(setup,'/language/en',{'next':'/super'})
    assert setup.get('/super').text.count('Open using the current hostname')==6


def test_all_pages_and_languages(app,setup):
    topic=new_topic(setup)
    post_slug=query(app,'SELECT slug FROM posts')['slug']
    user_slug=query(app,'SELECT slug FROM users')['slug']
    tenant_slug=query(app,'SELECT slug FROM tenants')['slug']
    for path in ['/',topic,'/super','/super/forums/'+tenant_slug,'/admin','/admin/categories','/admin/users','/admin/users/'+user_slug,'/admin/settings','/admin/settings/mail','/admin/appearance','/admin/appearance/logo','/settings','/settings/email','/settings/password','/settings/avatar','/settings/delete','/topics/new',topic+'/reply','/posts/'+post_slug+'/edit','/posts/'+post_slug+'/history']:
        assert setup.get(path).status_code==200,path
    post(setup,'/language/en',{'next':'/'})
    assert b'Good conversations start here.' in setup.get('/').data


@pytest.mark.parametrize('role', ['superadmin', 'admin', 'moderator', 'user', None])
def test_home_smtp_warning_visibility(app,setup,role):
    if role:
        query(app,"UPDATE users SET role=? WHERE email='root@example.org'",(role,))
        client=setup
    else:
        client=app.test_client()
    page=client.get('/').text
    visible=role in ('superadmin','admin')
    assert ('Noch kein SMTP-Server hinterlegt.' in page)==visible
    if visible:
        assert 'role="alert" class="flash warning"' in page
        assert '<a href="/admin/settings/mail">E-Mail-Versand einrichten</a>' in page
        assert 'Noch kein SMTP-Server hinterlegt.' in client.get('/').text
        assert 'Noch kein SMTP-Server hinterlegt.' not in client.get('/settings').text
    query(app,"UPDATE tenants SET smtp_host='mail.test' WHERE name='Community'")
    assert 'Noch kein SMTP-Server hinterlegt.' not in client.get('/').text


def test_home_smtp_warning_language_and_tenant(app,setup):
    query(app,"UPDATE tenants SET smtp_host='mail.test' WHERE name='Community'")
    assert 'Noch kein SMTP-Server hinterlegt.' not in setup.get('/').text
    assert login(setup,host='other.test').status_code==302
    assert 'Noch kein SMTP-Server hinterlegt.' in setup.get('/',base_url='http://other.test').text
    post(setup,'/language/en',{'next':'/'},host='other.test')
    page=setup.get('/',base_url='http://other.test').text
    assert 'No SMTP server configured yet.' in page
    assert 'Configure email delivery</a>' in page


def test_registration_validation_and_scoped_email(app,setup):
    client=app.test_client()
    register(client,'root@example.org')
    assert query(app,'SELECT COUNT(*) n FROM users')['n']==1
    for name in [' leading','trailing ','double  space','x'*26,'']:
        register(client,'bad@example.org',name)
    assert query(app,'SELECT COUNT(*) n FROM users')['n']==1
    first=verified(app,'same@example.org')
    second=verified(app,'same@example.org','other.test')
    assert query(app,'SELECT COUNT(*) n FROM users WHERE email=?',('same@example.org',))['n']==2
    assert first.get('/admin').status_code==403
    assert second.get('/super',base_url='http://other.test').status_code==403


def test_verification_cooldown_cannot_be_reset(app,setup):
    client=app.test_client()
    register(client,'code@example.org')
    code=app.extensions['outbox'][-1]['code']
    assert query(app,'SELECT code_hash FROM users WHERE email=?',('code@example.org',))['code_hash']!=code
    wrong='00000' if code!='00000' else '11111'
    for i in range(5):
        post(client,'/verify',{'code':wrong})
    user=query(app,'SELECT * FROM users WHERE email=?',('code@example.org',))
    assert user['code_attempts']==5 and user['cooldown_until']>time.time()
    count=len(app.extensions['outbox'])
    post(client,'/verify/resend')
    post(client,'/verify',{'code':code})
    assert len(app.extensions['outbox'])==count
    assert not query(app,'SELECT verified FROM users WHERE email=?',('code@example.org',))['verified']
    query(app,'UPDATE users SET cooldown_until=?,code_sent=? WHERE email=?',(time.time()-1,time.time()-100,'code@example.org'))
    post(client,'/verify/resend')
    post(client,'/verify',{'code':app.extensions['outbox'][-1]['code']})
    assert query(app,'SELECT verified FROM users WHERE email=?',('code@example.org',))['verified']


def test_resend_preserves_attempts(app,setup):
    client=app.test_client()
    register(client,'code@example.org')
    post(client,'/verify',{'code':'wrong'})
    query(app,'UPDATE users SET code_sent=0 WHERE email=?',('code@example.org',))
    post(client,'/verify/resend')
    assert query(app,'SELECT code_attempts FROM users WHERE email=?',('code@example.org',))['code_attempts']==1


def test_auth_returns_to_original_action(app,setup):
    client=app.test_client()
    assert client.get('/topics/new').location.endswith('/login?next=/topics/new')
    register(client,'new@example.org',path='/register?next=/topics/new')
    response=post(client,'/verify?next=/topics/new',{'code':app.extensions['outbox'][-1]['code']})
    assert response.location=='/topics/new'
    post(client,'/logout')
    assert login(client,'new@example.org',path='/login?next=/topics/new').location=='/topics/new'
    post(client,'/logout')
    assert login(client,'new@example.org',path='/login?next=//evil.test').location=='/'


def test_tenant_isolation_all_resources(app,setup):
    location=new_topic(setup,attachments=(io.BytesIO(b'private'),'note.txt'))
    post_slug=query(app,'SELECT slug FROM posts')['slug']
    file_slug=query(app,'SELECT slug FROM attachments')['slug']
    # Global superadmin still cannot access a resource through the wrong tenant.
    login(setup,host='other.test')
    for path in [location,location+'/reply','/posts/'+post_slug+'/edit','/posts/'+post_slug+'/history','/attachments/'+file_slug]:
        login(setup,host='other.test')
    assert setup.get(path,base_url='http://other.test').status_code==404,path
    member=verified(app,'local@example.org')
    with member.session_transaction() as sess:
        uid=sess['user_id']
    with member.session_transaction(base_url='http://other.test') as sess:
        sess['user_id']=uid
    assert member.get('/topics/new',base_url='http://other.test').status_code==302


def test_posts_read_status_edit_history_and_sanitization(app,setup):
    member=verified(app)
    location=new_topic(setup)
    member.get(location)
    assert query(app,'SELECT revision FROM reads')['revision']==1
    post(setup,location+'/reply',{'body':'<p>New</p><img src=x onerror=alert(1)><script>alert(1)</script><a href="javascript:alert(1)">x</a>'})
    assert b'topic-row unread' in member.get('/').data
    body=query(app,'SELECT body FROM posts ORDER BY id DESC')['body']
    assert '<script' not in body and '<img' not in body and 'javascript:' not in body
    member.get(location)
    assert b'topic-row unread' not in member.get('/').data
    post_slug=query(app,'SELECT slug FROM posts ORDER BY id')['slug']
    assert post(member,'/posts/'+post_slug+'/edit',{'body':'<p>Hijack</p>'}).status_code==403
    post(setup,'/posts/'+post_slug+'/edit',{'body':'<p>Edited</p>'})
    assert query(app,'SELECT COUNT(*) n FROM edits')['n']==1
    assert 'Hello' in query(app,'SELECT body FROM edits')['body']
    assert b'Zuletzt bearbeitet von' in setup.get(location).data


def test_attachments_login_and_limits(app,setup):
    location=new_topic(setup,attachments=(io.BytesIO(b'hello'),'hello.txt'))
    item=query(app,'SELECT * FROM attachments')
    path='/attachments/'+item['slug']
    assert app.test_client().get(path).location.startswith('/login?next=')
    result=setup.get(path)
    assert result.data==b'hello' and 'attachment;' in result.headers['Content-Disposition']
    count=query(app,'SELECT COUNT(*) n FROM topics')['n']
    result=post(setup,'/topics/new',{'title':'Too big','body':'<p>body</p>','attachments':(io.BytesIO(b'x'*(10*1024*1024+1)),'big.txt')})
    assert result.status_code==400
    assert query(app,'SELECT COUNT(*) n FROM topics')['n']==count
    assert query(app,'SELECT COUNT(*) n FROM attachments')['n']==1


def test_category_required_and_delete_sets_null(app,setup):
    post(setup,'/admin/categories',{'name':'General'})
    cat=query(app,'SELECT * FROM categories')
    assert post(setup,'/topics/new',{'title':'Bad','body':'text'}).status_code==400
    location=new_topic(setup,category=cat['slug'])
    assert query(app,'SELECT category_id FROM topics')['category_id']==cat['id']
    post(setup,'/admin/categories/'+cat['slug'],{'action':'delete'})
    assert query(app,'SELECT category_id FROM topics')['category_id'] is None
    assert setup.get(location).status_code==200


def test_account_deletion_preserves_guest_posts(app,setup):
    member=verified(app)
    location=new_topic(member)
    post(member,location+'/reply',{'body':'<p>Reply</p>'})
    post(member,'/settings/delete',{'current_password':'secret123'})
    assert query(app,'SELECT COUNT(*) n FROM users')['n']==1
    assert query(app,'SELECT user_id FROM topics')['user_id'] is None
    assert all(p['user_id'] is None and p['username']=='Member' for p in query(app,'SELECT * FROM posts',all=True))
    assert b'(Gast)' in member.get(location).data
    post(setup,'/settings/delete',{'current_password':'secret123'})
    assert query(app,'SELECT COUNT(*) n FROM users')['n']==1


def test_email_change_verified_and_reserved(app,setup):
    member=verified(app)
    post(member,'/settings/email',{'email':'changed@example.org','current_password':'secret123'})
    user=query(app,'SELECT * FROM users WHERE username=?',('Member',))
    assert user['email']=='member@example.org' and user['pending_email']=='changed@example.org'
    register(app.test_client(),'changed@example.org')
    assert query(app,'SELECT COUNT(*) n FROM users')['n']==2
    post(member,'/verify',{'code':app.extensions['outbox'][-1]['code']})
    assert query(app,'SELECT email FROM users WHERE username=?',('Member',))['email']=='changed@example.org'


def test_avatar_validated_and_resized(app,setup):
    assert post(setup,'/settings/avatar',{'avatar':(io.BytesIO(b'not an image'),'fake.png')}).status_code==302
    assert query(app,'SELECT avatar FROM users')['avatar'] is None
    buffer=io.BytesIO()
    Image.new('RGB',(800,600),'red').save(buffer,'PNG')
    buffer.seek(0)
    post(setup,'/settings/avatar',{'avatar':(buffer,'image.png')})
    user=query(app,'SELECT * FROM users')
    response=setup.get('/avatars/'+user['slug'])
    assert Image.open(io.BytesIO(response.data)).size==(256,192)


def test_csrf_and_local_admin_cannot_edit_global(app,setup):
    assert setup.post('/admin/categories',data={'name':'No token'}).status_code==400
    member=verified(app)
    query(app,"UPDATE users SET role='admin' WHERE username='Member'")
    root=query(app,"SELECT * FROM users WHERE role='superadmin'")
    assert post(member,'/admin/users/'+root['slug'],{'action':'delete'}).status_code==403
    assert member.get('/admin').status_code==200
    assert member.get('/super').status_code==403


def test_delete_post_removes_files_and_empty_topic(app,setup):
    location=new_topic(setup,attachments=(io.BytesIO(b'hello'),'note.txt'))
    post_slug=query(app,'SELECT slug FROM posts')['slug']
    response=post(setup,'/posts/'+post_slug+'/delete')
    assert response.location=='/'
    assert setup.get(location).status_code==404
    assert query(app,'SELECT COUNT(*) n FROM attachments')['n']==0


def test_smtp_failure_is_recoverable(app,setup):
    app.config['MAIL_SUPPRESS']=False
    client=app.test_client()
    register(client,'mail@example.org')
    assert not query(app,'SELECT verified FROM users WHERE email=?',('mail@example.org',))['verified']
    assert b'E-Mail konnte nicht versendet' in client.get('/verify').data
    app.config['MAIL_SUPPRESS']=True
    post(client,'/verify/resend')
    assert app.extensions['outbox'][-1]['to']=='mail@example.org'


def test_admin_edits_roles_profile_and_tenant_settings(app,setup):
    member=verified(app)
    user=query(app,"SELECT * FROM users WHERE username='Member'")
    post(setup,'/admin/users/'+user['slug'],{'username':'Updated','email':user['email'],'role':'moderator','password':'different123'})
    changed=query(app,'SELECT * FROM users WHERE id=?',(user['id'],))
    assert changed['username']=='Updated' and changed['role']=='moderator'
    assert member.get('/admin').status_code==403
    post(setup,'/admin/settings',{'name':'Updated forum'})
    post(setup,'/admin/settings/mail',{'smtp_host':'mail.test','smtp_port':'465','smtp_user':'mailuser','smtp_password':'mailsecret','smtp_security':'ssl','mail_from':'noreply@example.org'})
    post(setup,'/admin/appearance',{'theme':'forest'})
    tenant=query(app,"SELECT * FROM tenants WHERE name='Updated forum'")
    assert tenant['theme']=='forest' and tenant['smtp_port']==465
    assert b'mailsecret' not in setup.get('/admin/settings').data
    assert b'#23734c' in member.get('/').data


def test_forum_timezone_defaults_selection_and_tenant_scope(app,setup):
    assert all(tenant['timezone']=='UTC' for tenant in query(app,'SELECT timezone FROM tenants',all=True))
    html=setup.get('/admin/settings').text
    assert '<select name="timezone"' in html
    assert '<option value="UTC" selected>UTC</option>' in html
    for zone in ('Europe/Berlin','Atlantic/Canary','America/New_York','Asia/Kathmandu'):
        assert f'<option value="{zone}"' in html

    assert post(setup,'/admin/settings',{'name':'Community','timezone':'Asia/Kathmandu'}).status_code==302
    assert query(app,"SELECT timezone FROM tenants WHERE name='Community'")['timezone']=='Asia/Kathmandu'
    assert query(app,"SELECT timezone FROM tenants WHERE name='Second'")['timezone']=='UTC'
    assert '<option value="Asia/Kathmandu" selected>' in setup.get('/admin/settings').text
    # Older clients that omit the new setting keep the current timezone.
    post(setup,'/admin/settings',{'name':'Community'})
    assert query(app,"SELECT timezone FROM tenants WHERE name='Community'")['timezone']=='Asia/Kathmandu'
    post(setup,'/language/en',{'next':'/admin/settings'})
    assert 'Forum timezone' in setup.get('/admin/settings').text


def test_invalid_forum_timezone_does_not_save_settings(app,setup):
    for zone in ('','Invalid/Zone','../UTC','/etc/passwd'):
        response=post(setup,'/admin/settings',{'name':'Changed','timezone':zone},follow=True)
        assert 'Bitte eine gültige Zeitzone wählen.' in response.text
        tenant=query(app,"SELECT name,timezone FROM tenants WHERE name='Community'")
        assert tenant and tenant['timezone']=='UTC'


def test_existing_database_adds_forum_timezone_without_resetting_it(app,setup):
    query(app,'ALTER TABLE tenants DROP COLUMN timezone')
    create_app(dict(app.config))
    assert all(tenant['timezone']=='UTC' for tenant in query(app,'SELECT timezone FROM tenants',all=True))
    query(app,"UPDATE tenants SET timezone='Europe/Berlin' WHERE name='Community'")
    create_app(dict(app.config))
    assert query(app,"SELECT timezone FROM tenants WHERE name='Community'")['timezone']=='Europe/Berlin'


@pytest.mark.parametrize('zone,stamp,expected',[
    ('UTC','2026-07-15T12:00:00+00:00','15.07.2026 · 12:00 UTC'),
    ('Europe/Berlin','2026-01-15T12:00:00+00:00','15.01.2026 · 13:00 CET'),
    ('Europe/Berlin','2026-07-15T12:00:00+00:00','15.07.2026 · 14:00 CEST'),
    ('America/New_York','2026-01-15T01:00:00+00:00','14.01.2026 · 20:00 EST'),
    ('Asia/Kathmandu','2026-07-15T12:00:00+00:00','15.07.2026 · 17:45 +0545'),
    ('UTC','2026-07-15T12:00:00+02:00','15.07.2026 · 10:00 UTC'),
    ('Europe/Berlin','2026-07-15T12:00:00','15.07.2026 · 14:00 CEST'),
])
def test_forum_dates_use_selected_timezone(app,setup,zone,stamp,expected):
    topic=new_topic(setup)
    query(app,'UPDATE topics SET created_at=?,activity=?',(stamp,stamp))
    query(app,'UPDATE posts SET created_at=?',(stamp,))
    post(setup,'/admin/settings',{'name':'Community','timezone':zone})
    assert expected in setup.get('/').text
    assert expected in setup.get(topic).text
    assert query(app,'SELECT created_at FROM posts')['created_at']==stamp
    post(setup,'/language/en',{'next':topic})
    english=expected[6:10]+'-'+expected[3:5]+'-'+expected[:2]+expected[10:]
    assert english in setup.get(topic).text


def test_global_promotion_rejects_existing_email_elsewhere(app,setup):
    verified(app,'same@example.org')
    verified(app,'same@example.org','other.test')
    user=query(app,"SELECT * FROM users WHERE email='same@example.org' ORDER BY id")
    post(setup,'/admin/users/'+user['slug'],{'username':'Global','email':'new@example.org','role':'user','global':'on'})
    assert query(app,'SELECT tenant_id FROM users WHERE id=?',(user['id'],))['tenant_id'] is not None


def test_admin_email_change_needs_code(app,setup):
    member=verified(app)
    user=query(app,"SELECT * FROM users WHERE username='Member'")
    post(setup,'/admin/users/'+user['slug'],{'username':'Member','email':'new@example.org','role':'user'})
    assert query(app,'SELECT email FROM users WHERE id=?',(user['id'],))['email']==user['email']
    code=app.extensions['outbox'][-1]['code']
    post(member,'/verify',{'code':code})
    assert query(app,'SELECT email FROM users WHERE id=?',(user['id'],))['email']=='new@example.org'


def test_real_mail_branch_uses_configured_transport(app,setup,monkeypatch):
    sent=[]
    class SMTP:
        def __init__(self,host,port,timeout):
            assert host=='mail.test' and port==587
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def starttls(self,context):
            sent.append('tls')
        def login(self,user,password):
            assert user=='mailer' and password=='smtp-secret'
        def send_message(self,message):
            sent.append(message)
    monkeypatch.setattr('vorum.smtplib.SMTP',SMTP)
    query(app,"UPDATE tenants SET smtp_host='mail.test',smtp_user='mailer',smtp_password='smtp-secret',mail_from='noreply@example.org' WHERE name='Community'")
    app.config['MAIL_SUPPRESS']=False
    register(app.test_client(),'delivery@example.org')
    assert sent[0]=='tls'
    assert sent[1]['To']=='delivery@example.org'
    assert sent[1]['From']=='noreply@example.org'


def test_oversized_request_has_clean_error(app,setup):
    app.config['MAX_CONTENT_LENGTH']=1024
    assert post(setup,'/topics/new',{'body':'x'*2048}).status_code==413


def test_admin_registration_code_lifecycle(app,setup):
    member=app.test_client()
    register(member,'pending@example.org','Pending')
    user=query(app,'SELECT * FROM users WHERE email=?',('pending@example.org',))
    path='/admin/users/'+user['slug']
    code=app.extensions['outbox'][-1]['code']
    assert f'<strong>{code}</strong>' in setup.get(path).text
    assert member.get(path).status_code==302
    login(setup,host='other.test')
    assert setup.get(path,base_url='http://other.test').status_code==404
    query(app,'UPDATE users SET code_until=0 WHERE id=?',(user['id'],))
    assert 'Freischaltcode:' not in setup.get(path).text
    query(app,'UPDATE users SET code_sent=0 WHERE id=?',(user['id'],))
    post(member,'/verify/resend')
    code=app.extensions['outbox'][-1]['code']
    assert f'<strong>{code}</strong>' in setup.get(path).text
    post(member,'/verify',{'code':code})
    assert 'Freischaltcode:' not in setup.get(path).text
    assert query(app,'SELECT registration_code FROM users WHERE id=?',(user['id'],))['registration_code'] is None


def test_locked_registration_code_is_removed(app,setup):
    member=app.test_client()
    register(member,'locked@example.org','Locked')
    code=app.extensions['outbox'][-1]['code']
    for _ in range(5):
        post(member,'/verify',{'code':'wrong'})
    user=query(app,'SELECT * FROM users WHERE email=?',('locked@example.org',))
    assert user['registration_code'] is None
    assert f'<strong>{code}</strong>' not in setup.get('/admin/users/'+user['slug']).text


def test_existing_database_adds_registration_code(app):
    query(app,'ALTER TABLE users DROP COLUMN registration_code')
    create_app(dict(app.config))
    assert any(column['name']=='registration_code' for column in query(app,'PRAGMA table_info(users)',all=True))


def test_admin_can_activate_unverified_user(app,setup):
    member=app.test_client()
    register(member,'activate@example.org','Activate')
    user=query(app,'SELECT * FROM users WHERE email=?',('activate@example.org',))
    path='/admin/users/'+user['slug']
    query(app,'UPDATE users SET code_attempts=5,cooldown_until=? WHERE id=?',(time.time()+1800,user['id']))
    assert 'value="activate"' in setup.get(path).text
    assert setup.post(path,data={'action':'activate'}).status_code==400
    assert post(setup,path,{'action':'activate'}).status_code==302
    updated=query(app,'SELECT * FROM users WHERE id=?',(user['id'],))
    assert updated['verified']
    for field in ('code_hash','registration_code','code_until','cooldown_until','code_sent'):
        assert updated[field] is None
    assert updated['code_attempts']==0
    assert 'value="activate"' not in setup.get(path).text
    assert member.get('/topics/new').status_code==200
    assert post(setup,path,{'action':'activate'}).status_code==302


def test_activation_respects_admin_scope(app,setup):
    admin=verified(app,'admin@example.org')
    query(app,"UPDATE users SET role='admin' WHERE email='admin@example.org'")
    member=verified(app,'ordinary@example.org')
    pending=app.test_client()
    register(pending,'scoped@example.org','Scoped')
    user=query(app,"SELECT * FROM users WHERE email='scoped@example.org'")
    path='/admin/users/'+user['slug']
    assert post(member,path,{'action':'activate'}).status_code==403
    login(setup,host='other.test')
    assert post(setup,path,{'action':'activate'},host='other.test').status_code==404
    query(app,'UPDATE users SET tenant_id=NULL WHERE id=?',(user['id'],))
    assert 'value="activate"' not in admin.get(path).text
    assert post(admin,path,{'action':'activate'}).status_code==403
    assert not query(app,'SELECT verified FROM users WHERE id=?',(user['id'],))['verified']
    query(app,'UPDATE users SET tenant_id=(SELECT id FROM tenants WHERE name=?) WHERE id=?',('Community',user['id']))
    assert post(admin,path,{'action':'activate'}).status_code==302
    assert query(app,'SELECT verified FROM users WHERE id=?',(user['id'],))['verified']


def test_activation_checks_pending_email_and_keeps_verified_accounts(app,setup):
    verified(app,'taken@example.org')
    pending=app.test_client()
    register(pending,'new@example.org','New')
    user=query(app,"SELECT * FROM users WHERE email='new@example.org'")
    path='/admin/users/'+user['slug']
    query(app,'UPDATE users SET pending_email=? WHERE id=?',('taken@example.org',user['id']))
    post(setup,path,{'action':'activate'})
    assert not query(app,'SELECT verified FROM users WHERE id=?',(user['id'],))['verified']
    query(app,'UPDATE users SET pending_email=? WHERE id=?',('available@example.org',user['id']))
    post(setup,path,{'action':'activate'})
    updated=query(app,'SELECT * FROM users WHERE id=?',(user['id'],))
    assert updated['verified'] and updated['email']=='available@example.org'
    assert updated['pending_email'] is None
    query(app,'UPDATE users SET pending_email=? WHERE id=?',('later@example.org',user['id']))
    post(setup,path,{'action':'activate'})
    assert query(app,'SELECT pending_email FROM users WHERE id=?',(user['id'],))['pending_email']=='later@example.org'


def test_forum_intro_defaults_and_language_specific_settings(app,setup):
    settings=setup.get('/admin/appearance').text
    for field,value in FORUM_INTRO_DEFAULTS.items():
        assert f'name="{field}"' in settings
        assert value in settings
    values={
        'intro_eyebrow_de':'UNSER FORUM', 'intro_eyebrow_en':'OUR FORUM',
        'intro_title_de':'Willkommen <script>alert(1)</script>', 'intro_title_en':'Welcome everyone',
        'intro_description_de':'Fragen & Antworten', 'intro_description_en':'Questions & answers',
    }
    assert post(setup,'/admin/appearance',values).status_code==302
    tenant=query(app,"SELECT * FROM tenants WHERE name='Community'")
    assert all(tenant[field]==value for field,value in values.items())
    for language in ('de','en'):
        post(setup,'/language/'+language,{'next':'/'})
        html=setup.get('/').text
        for field in ('eyebrow','title','description'):
            assert str(escape(values[f'intro_{field}_{language}'])) in html
        assert '<script>alert(1)</script>' not in html
        assert values['intro_title_'+('en' if language=='de' else 'de')] not in html
        other=setup.get('/',base_url='http://other.test',headers={'Accept-Language':language}).text
        assert FORUM_INTRO_DEFAULTS['intro_title_'+language] in other
    # Saving unrelated settings preserves the six customized texts.
    post(setup,'/admin/settings',{'name':'Community'})
    tenant=query(app,"SELECT * FROM tenants WHERE name='Community'")
    assert all(tenant[field]==value for field,value in values.items())
    assert 'Homepage texts' in setup.get('/admin/appearance').text


def test_forum_intro_empty_text_and_length_validation(app,setup):
    assert post(setup,'/admin/appearance',{'intro_eyebrow_de':''}).status_code==302
    assert '<span class="eyebrow"></span>' in setup.get('/').text
    response=post(setup,'/admin/appearance',{'intro_title_de':'x'*2001},follow=True)
    assert 'Startseitentexte dürfen jeweils maximal 2000 Zeichen enthalten.' in response.text
    assert query(app,"SELECT name FROM tenants WHERE name='Community'")


def test_existing_database_adds_forum_intro_and_preserves_customizations(app,setup):
    for field in FORUM_INTRO_DEFAULTS:
        query(app,'ALTER TABLE tenants DROP COLUMN '+field)
    create_app(dict(app.config))
    for tenant in query(app,'SELECT * FROM tenants',all=True):
        assert all(tenant[field]==value for field,value in FORUM_INTRO_DEFAULTS.items())
    query(app,"UPDATE tenants SET intro_title_de='Unser Treffpunkt' WHERE name='Community'")
    create_app(dict(app.config))
    assert query(app,"SELECT intro_title_de FROM tenants WHERE name='Community'")['intro_title_de']=='Unser Treffpunkt'


def logo_upload(client, color='red', host='localhost'):
    image=io.BytesIO()
    Image.new('RGBA',(1600,800),color).save(image,'PNG')
    image.seek(0)
    return post(client,'/admin/appearance/logo',{'action':'upload','logo':(image,'logo.png')},host)


def test_appearance_is_separate_and_tenant_scoped(app,setup):
    settings=setup.get('/admin/settings').text
    assert 'name="theme"' not in settings and 'name="intro_title_de"' not in settings
    assert '/admin/appearance' in settings and '/admin/appearance/logo' in settings
    post(setup,'/admin/appearance',{'theme':'forest','intro_title_de':'Unser Forum'})
    post(setup,'/admin/settings',{'name':'Community','theme':'rose','intro_title_de':'Wrong'})
    tenant=query(app,"SELECT * FROM tenants WHERE name='Community'")
    assert tenant['theme']=='forest' and tenant['intro_title_de']=='Unser Forum'
    other=query(app,"SELECT * FROM tenants WHERE name='Second'")
    assert other['theme']=='default' and other['intro_title_de']==FORUM_INTRO_DEFAULTS['intro_title_de']
    post(setup,'/admin/appearance',{'theme':'invalid','intro_title_de':'Wrong'})
    assert query(app,"SELECT theme FROM tenants WHERE name='Community'")['theme']=='forest'


def test_forum_logo_upload_replace_remove_and_isolation(app,setup):
    from pathlib import Path
    assert 'rel="icon"' not in setup.get('/').text
    assert logo_upload(setup).status_code==302
    filename=query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']
    icon=str(Path(filename).with_suffix('.ico'))
    logo_url='/branding/'+filename
    icon_url='/branding/'+icon
    anonymous=app.test_client()
    home=anonymous.get('/').text
    assert logo_url in home and icon_url in home and 'class="forum-logo"' in home
    assert logo_url in setup.get('/admin/appearance/logo').text
    png=anonymous.get(logo_url)
    assert png.status_code==200 and png.mimetype=='image/png'
    with Image.open(io.BytesIO(png.data)) as img:
        assert img.size==(1024,512)
    ico=anonymous.get(icon_url)
    assert ico.status_code==200
    with Image.open(io.BytesIO(ico.data)) as img:
        assert img.format=='ICO' and (16,16) in img.ico.sizes() and (32,32) in img.ico.sizes()
    assert anonymous.get(logo_url,base_url='http://alias.test').status_code==200
    assert anonymous.get(logo_url,base_url='http://other.test').status_code==404
    assert anonymous.get(icon_url,base_url='http://other.test').status_code==404
    assert logo_url not in anonymous.get('/',base_url='http://other.test').text
    assert logo_upload(setup,'blue').status_code==302
    assert anonymous.get(logo_url).status_code==404
    uploads=Path(app.config['DATA_DIR'])/'uploads'
    assert not (uploads/filename).exists() and not (uploads/icon).exists()
    current=query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']
    assert current!=filename
    assert post(setup,'/admin/appearance/logo',{'action':'remove'}).status_code==302
    assert query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']==''
    assert not list(uploads.iterdir())
    assert 'rel="icon"' not in anonymous.get('/').text
    assert 'class="logo"' in anonymous.get('/').text


def test_logo_validation_permissions_and_csrf(app,setup):
    assert logo_upload(setup).status_code==302
    original=query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']
    for value in (b'not an image',b'x'*(10*1024*1024+1)):
        response=post(setup,'/admin/appearance/logo',{'action':'upload','logo':(io.BytesIO(value),'fake.png')},follow=True)
        assert 'Logo: maximal 10 MB' in response.text
    oversized=io.BytesIO()
    Image.new('1',(5000,4001)).save(oversized,'PNG')
    oversized.seek(0)
    response=post(setup,'/admin/appearance/logo',{'action':'upload','logo':(oversized,'large.png')},follow=True)
    assert 'Logo: maximal 10 MB' in response.text
    assert query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']==original
    member=verified(app)
    for path in ('/admin/appearance','/admin/appearance/logo'):
        assert member.get(path).status_code==403
        assert post(member,path,{'action':'remove','theme':'rose'}).status_code==403
        assert app.test_client().get(path).status_code==302
    assert setup.post('/admin/appearance/logo',data={'action':'remove'}).status_code==400
    assert query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']==original


def test_existing_database_adds_logo_without_resetting_it(app,setup):
    query(app,'ALTER TABLE tenants DROP COLUMN logo')
    create_app(dict(app.config))
    assert query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']==''
    logo_upload(setup)
    original=query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']
    create_app(dict(app.config))
    assert query(app,"SELECT logo FROM tenants WHERE name='Community'")['logo']==original


def test_mail_settings_are_separate_and_tenant_scoped(app,setup):
    general=setup.get('/admin/settings').text
    assert 'name="smtp_host"' not in general and 'name="digest_time"' not in general
    assert 'href="/admin/settings/mail"' in general
    mail=setup.get('/admin/settings/mail').text
    assert 'name="recipient" value="root@example.org"' in mail
    assert 'name="smtp_host"' in mail and 'name="digest_time"' in mail
    settings={'smtp_host':'mail.example.org','smtp_port':'465','smtp_security':'ssl',
              'mail_from':'forum@example.org','smtp_user':'mailer','smtp_password':'private-test-password',
              'digest_time':'18:30','digest_timezone':'Atlantic/Canary','digest_weekday':'2'}
    assert post(setup,'/admin/settings/mail',settings).location=='/admin/settings/mail'
    tenant=dict(query(app,"SELECT * FROM tenants WHERE name='Community'"))
    assert tenant['smtp_password']=='private-test-password' and tenant['smtp_port']==465
    assert query(app,"SELECT smtp_host FROM tenants WHERE name='Second'")['smtp_host']==''
    assert 'private-test-password' not in setup.get('/admin/settings/mail').text
    assert post(setup,'/admin/settings',{'name':'Renamed','smtp_host':'ignored'}).status_code==302
    changed=dict(query(app,'SELECT * FROM tenants WHERE id=?',(tenant['id'],)))
    for field in settings:
        assert changed[field]==tenant[field]
    assert post(setup,'/admin/settings/mail',{**settings,'smtp_password':''}).status_code==302
    assert query(app,'SELECT smtp_password FROM tenants WHERE id=?',(tenant['id'],))['smtp_password']==tenant['smtp_password']
    assert query(app,'SELECT name FROM tenants WHERE id=?',(tenant['id'],))['name']=='Renamed'


def test_test_mail_defaults_custom_recipient_and_failure(app,setup,monkeypatch):
    result=post(setup,'/admin/settings/mail',{'action':'test'},follow=True)
    assert 'Bitte zuerst SMTP-Server und Mail-Absender speichern.' in result.text
    assert not app.extensions['outbox']
    post(setup,'/admin/settings/mail',{'smtp_host':'mail.example.org','mail_from':'forum@example.org'})
    result=post(setup,'/admin/settings/mail',{'action':'test'},follow=True)
    assert 'Testmail wurde versendet.' in result.text
    assert app.extensions['outbox'][-1]['to']=='root@example.org'
    assert app.extensions['outbox'][-1]['kind']=='test'
    result=post(setup,'/admin/settings/mail',{'action':'test','recipient':'other@example.org'},follow=True)
    assert app.extensions['outbox'][-1]['to']=='other@example.org'
    count=len(app.extensions['outbox'])
    for invalid in ['', 'invalid', 'other@example.org\r\nBcc: hidden@example.org']:
        result=post(setup,'/admin/settings/mail',{'action':'test','recipient':invalid},follow=True)
        assert 'Bitte eine gültige E-Mail-Adresse eingeben.' in result.text
    assert len(app.extensions['outbox'])==count
    def broken_delivery(tenant,message,**metadata):
        assert message['From']=='forum@example.org'
        assert message['To']=='root@example.org'
        raise OSError('private SMTP details')
    monkeypatch.setattr('vorum.deliver_mail',broken_delivery)
    result=post(setup,'/admin/settings/mail',{'action':'test'},follow=True)
    assert 'Testmail konnte nicht versendet werden.' in result.text
    assert 'private SMTP details' not in result.text
    assert len(app.extensions['outbox'])==count


@pytest.mark.parametrize('role',['admin','moderator','user',None])
def test_mail_settings_permissions_and_csrf(app,setup,role):
    if role:
        query(app,"UPDATE users SET role=? WHERE email='root@example.org'",(role,))
        client=setup
    else:
        client=app.test_client()
    expected=200 if role=='admin' else 403 if role else 302
    assert client.get('/admin/settings/mail').status_code==expected
    result=post(client,'/admin/settings/mail',{'action':'test'})
    assert result.status_code==(302 if role in ('admin',None) else 403)
    assert setup.post('/admin/settings/mail',data={'action':'test'}).status_code==400
    assert not app.extensions['outbox']


ACCESS_FIELDS=('search_indexing_allowed','guests_can_view_forum','guests_can_view_topics')


def test_access_settings_defaults_save_scope_and_permissions(app,setup):
    path='/admin/settings/access'
    page=setup.get(path).text
    assert 'Zugriff' in page and path in setup.get('/admin/settings').text
    for field in ACCESS_FIELDS:
        assert f'name="{field}" checked' in page
    assert all(query(app,'SELECT * FROM tenants WHERE name=?',(name,))[field]==1
               for name in ('Community','Second') for field in ACCESS_FIELDS)
    assert setup.post(path,data={}).status_code==400
    assert post(setup,path,{}).status_code==302
    assert all(query(app,"SELECT * FROM tenants WHERE name='Community'")[field]==0 for field in ACCESS_FIELDS)
    assert all(query(app,"SELECT * FROM tenants WHERE name='Second'")[field]==1 for field in ACCESS_FIELDS)
    # Unrelated settings cannot reset access choices.
    post(setup,'/admin/settings',{'name':'Community','registration_allowed':'on','login_allowed':'on'})
    assert all(query(app,"SELECT * FROM tenants WHERE name='Community'")[field]==0 for field in ACCESS_FIELDS)
    assert post(setup,path,{field:'on' for field in ACCESS_FIELDS}).status_code==302
    assert all(query(app,"SELECT * FROM tenants WHERE name='Community'")[field]==1 for field in ACCESS_FIELDS)
    member=verified(app)
    assert member.get(path).status_code==403
    assert post(member,path,{}).status_code==403
    assert app.test_client().get(path).status_code==302
    post(setup,'/language/en')
    assert 'Allow guests to view topics' in setup.get(path).text


def test_guest_access_controls_listing_and_direct_topics(app,setup):
    topic=new_topic(setup,title='Private discussion')
    guest=app.test_client()
    assert 'Private discussion' in guest.get('/').text
    assert guest.get(topic).status_code==200
    post(setup,'/admin/settings/access',{'search_indexing_allowed':'on','guests_can_view_forum':'on'})
    home=guest.get('/')
    assert home.status_code==200
    assert 'Private discussion' in home.text
    assert f'href="{topic}"' in home.text
    assert guest.get(topic).location.startswith('/login?next=')
    assert 'Private discussion' in setup.get('/').text
    assert setup.get(topic).status_code==200
    post(setup,'/admin/settings/access',{'search_indexing_allowed':'on','guests_can_view_topics':'on'})
    assert guest.get('/').location=='/login?next=/'
    assert guest.get(topic).status_code==302
    assert guest.get('/login').status_code==200
    assert guest.get('/register').status_code==200
    assert guest.get('/static/style.css').status_code==200
    assert guest.get('/',base_url='http://other.test').status_code==200
    assert setup.get(topic).status_code==200
    # External login remains reachable when the forum is private.
    query(app,"UPDATE tenants SET login_url='https://example.org/login' WHERE name='Community'")
    assert guest.get('/login').location=='https://example.org/login'


def test_search_indexing_header_is_tenant_scoped(app,setup):
    guest=app.test_client()
    assert 'X-Robots-Tag' not in guest.get('/').headers
    post(setup,'/admin/settings/access',{'guests_can_view_forum':'on','guests_can_view_topics':'on'})
    assert guest.get('/').headers['X-Robots-Tag']=='noindex, nofollow'
    assert guest.get('/missing').headers['X-Robots-Tag']=='noindex, nofollow'
    assert 'X-Robots-Tag' not in guest.get('/',base_url='http://other.test').headers
    post(setup,'/admin/settings/access',{field:'on' for field in ACCESS_FIELDS})
    assert 'X-Robots-Tag' not in guest.get('/').headers


def test_access_migration_defaults_and_preserves_choices(app,setup):
    for field in ACCESS_FIELDS:
        query(app,'ALTER TABLE tenants DROP COLUMN '+field)
    create_app(app.config)
    assert all(tenant[field]==1 for tenant in query(app,'SELECT * FROM tenants',all=True) for field in ACCESS_FIELDS)
    query(app,"UPDATE tenants SET guests_can_view_forum=0 WHERE name='Community'")
    create_app(app.config)
    assert query(app,"SELECT guests_can_view_forum FROM tenants WHERE name='Community'")[0]==0


@pytest.mark.parametrize('indexing_allowed',[False,True])
@pytest.mark.parametrize('guest_access',[False,True])
def test_robots_respects_indexing_setting_without_guest_login(app,setup,indexing_allowed,guest_access):
    values={}
    if indexing_allowed:
        values['search_indexing_allowed']='on'
    if guest_access:
        values['guests_can_view_forum']='on'
        values['guests_can_view_topics']='on'
    assert post(setup,'/admin/settings/access',values).status_code==302
    guest=app.test_client()
    rule='Allow: /' if indexing_allowed else 'Disallow: /'
    for host in ('localhost','alias.test'):
        response=guest.get('/robots.txt',base_url='http://'+host)
        assert response.status_code==200
        assert response.mimetype=='text/plain'
        assert response.text=='User-agent: *\n'+rule+'\n'
    # Another forum keeps its own default, including on subsequent requests.
    assert guest.get('/robots.txt',base_url='http://other.test').text=='User-agent: *\nAllow: /\n'
    assert guest.get('/robots.txt',base_url='http://unknown.test').status_code==404
