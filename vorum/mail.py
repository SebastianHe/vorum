"""The shared SMTP transport for verification and forum notifications."""
import smtplib
import ssl

from flask import current_app


def deliver_mail(tenant, message, **metadata):
    if current_app.config['MAIL_SUPPRESS']:
        current_app.extensions['outbox'].append({
            'to': message['To'], 'subject': message['Subject'],
            'body': message.get_content(), **metadata,
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
