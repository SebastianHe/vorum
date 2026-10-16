"""The shared SMTP transport for verification and forum notifications."""
import re
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from .translations import EN


def system_message(tenant, recipient, subject, *, language, origin, title,
                   paragraphs, action_label, action_path='/', code=None, posts=(), notes=()):
    """Build equivalent plain-text and escaped HTML alternatives, also in workers."""
    from . import THEMES

    tr = lambda value: EN.get(value, value) if language == 'en' else value
    origin = origin.rstrip('/')
    context = dict(
        t=tr, language=language, name=tenant['name'] if tenant else 'Vorum',
        brand=THEMES.get(tenant['theme'] if tenant else 'default', THEMES['default'])[0],
        logo_url=origin + '/branding/' + tenant['logo'] if tenant and tenant['logo'] else None,
        origin=origin, title=title, paragraphs=paragraphs, code=code, posts=posts,
        action_label=action_label, action_url=origin + action_path, notes=notes,
    )
    message = EmailMessage()
    message['Subject'] = re.sub(r'[\r\n]+', ' ', subject)
    message['From'] = tenant['mail_from'] if tenant and tenant['mail_from'] else 'vorum@localhost'
    message['To'] = recipient
    # Render without web context processors: scheduled mail has no request/session.
    message.set_content(current_app.jinja_env.get_template('mail/message.txt').render(**context))
    message.add_alternative(current_app.jinja_env.get_template('mail/message.html').render(**context), subtype='html')
    return message


def deliver_mail(tenant, message, **metadata):
    if current_app.config['MAIL_SUPPRESS']:
        current_app.extensions['outbox'].append({
            'to': message['To'], 'subject': message['Subject'],
            'body': message.get_body(preferencelist=('plain',)).get_content(),
            'html': message.get_body(preferencelist=('html',)).get_content()
                    if message.get_body(preferencelist=('html',)) else None,
            **metadata,
        })
        return
    if not tenant or not tenant['smtp_host'] or not tenant['mail_from']:
        raise ValueError('SMTP is not configured')
    transport = smtplib.SMTP_SSL if tenant['smtp_security'] == 'ssl' else smtplib.SMTP
    with transport(tenant['smtp_host'], tenant['smtp_port'], timeout=10) as smtp:
        if tenant['smtp_security'] == 'starttls':
            smtp.starttls(context=ssl.create_default_context())
        if tenant['smtp_user']:
            smtp.login(tenant['smtp_user'], tenant['smtp_password'])
        smtp.send_message(message)
