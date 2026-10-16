from email import policy
from email.parser import BytesParser

import pytest
from flask import g

from test_vorum import app, setup, post, query, register
from vorum.mail import system_message
from vorum.notifications import _send


@pytest.mark.parametrize('language', ['de', 'en'])
def test_verification_and_test_mail_have_both_alternatives(app, setup, language):
    client = app.test_client()
    post(client, '/language/' + language, {'next': '/'})
    register(client, 'mail@example.org')
    mail = app.extensions['outbox'][-1]
    for body in (mail['body'], mail['html']):
        assert mail['code'] in body
        assert 'http://localhost/verify' in body
        assert '15' in body
        assert ('Do not share this code.' if language == 'en' else 'Gib diesen Code nicht weiter.') in body
    post(setup, '/language/' + language, {'next': '/'})
    post(setup, '/admin/settings/mail', {'smtp_host': 'mail.test', 'mail_from': 'forum@example.org'})
    post(setup, '/admin/settings/mail', {'action': 'test'})
    mail = app.extensions['outbox'][-1]
    for body in (mail['body'], mail['html']):
        assert 'root@example.org' in body
        assert 'SMTP' in body
        assert ('Open forum' if language == 'en' else 'Forum öffnen') in body


def test_mime_encoding_branding_and_html_escaping_without_request(app, setup):
    tenant = dict(query(app, "SELECT * FROM tenants WHERE name='Community'"))
    tenant.update(name='Forum <script>alert(1)</script>', theme='forest', logo='logo.png')
    with app.app_context():
        message = system_message(
            tenant, 'member@example.org', 'Subject\r\nBcc: injected', language='de',
            origin='https://forum.example.org', title='<b>Titel</b>',
            paragraphs=['Text mit Umlauten: Grüße & mehr'], action_label='Öffnen',
            posts=[dict(title='<img src=x onerror=alert(1)>', author='A & B', date='16.10.2026',
                        excerpt='<script>bad</script>\nZweite Zeile', url='https://forum.example.org/topics/test#post')])
    parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
    assert parsed.get_content_type() == 'multipart/alternative'
    assert [part.get_content_type() for part in parsed.iter_parts()] == ['text/plain', 'text/html']
    assert parsed['Bcc'] is None
    text = parsed.get_body(preferencelist=('plain',)).get_content()
    html = parsed.get_body(preferencelist=('html',)).get_content()
    assert 'Grüße & mehr' in text and 'Grüße &amp; mehr' in html
    assert '#23734c' in html
    assert 'https://forum.example.org/branding/logo.png' in html
    assert '<script>' not in html and '<img src=x' not in html
    assert '&lt;script&gt;' in html


@pytest.mark.parametrize('kind', ['immediate', 'new_topic', 'daily', 'weekly'])
@pytest.mark.parametrize('language', ['de', 'en'])
def test_notification_alternatives_in_worker(app, setup, kind, language):
    tenant = query(app, "SELECT * FROM tenants WHERE name='Community'")
    subscription = dict(base_url='https://alias.test', language=language)
    with app.app_context():
        g.app_db = app.config['DATABASE']
        _send(tenant, dict(email='member@example.org'), subscription,
              [dict(id=1, title='Neuigkeiten & Fragen', username='Autor <Name>',
                    created_at='2026-10-16T10:00:00+00:00', body='<p>Ein Auszug &amp; mehr</p>',
                    topic_slug='topic', slug='post')], kind)
    mail = app.extensions['outbox'][-1]
    for body in (mail['body'], mail['html']):
        assert 'https://alias.test/topics/topic#post' in body
        assert ('Read post' if language == 'en' else 'Beitrag lesen') in body
        assert '10:00 UTC' in body
    assert 'Ein Auszug & mehr' in mail['body']
    assert 'Ein Auszug &amp; mehr' in mail['html']
    assert 'Autor &lt;Name&gt;' in mail['html']
