"""Optional browser smoke test: pip install playwright; playwright install chromium."""
import io
import logging
import re
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from vorum import create_app

logging.getLogger('werkzeug').setLevel(logging.ERROR)
output=Path('/tmp/vorum-preview')
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='vorum-browser-') as tmp:
    app=create_app({'TESTING':True,'DATA_DIR':tmp,'DATABASE':tmp+'/browser.sqlite3','SECRET_KEY':'browser-test','MAIL_SUPPRESS':True})
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000},locale='de-DE')
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base)
            page.get_by_role('link',name='Ersten Super-Admin anlegen').click()
            page.get_by_label('Benutzername',exact=True).fill('Alex')
            page.get_by_label('E-Mail',exact=True).fill('alex@example.org')
            page.get_by_label('Passwort',exact=True).fill('browser-password')
            page.get_by_label('Passwort wiederholen').fill('browser-password')
            page.get_by_role('button',name='Registrieren',exact=True).click()
            page.wait_for_url('**/super')
            page.get_by_label('Name des Forums').fill('Vorum Community')
            page.get_by_label('Hostnamen').fill('127.0.0.1')
            page.get_by_role('button',name='Forum anlegen',exact=True).click()
            page.get_by_label('Name des Forums').fill('Zweites Forum')
            page.get_by_label('Hostnamen').fill('unconfigured.example.org')
            page.get_by_role('button',name='Forum anlegen',exact=True).click()
            second=page.locator('.forum-card').filter(has=page.get_by_role('heading',name='Zweites Forum',exact=True))
            assert second.get_by_role('link',name='Frontend ↗',exact=True).get_attribute('href').startswith('http://unconfigured.example.org:')
            for width,theme in ((1440,'light'),(390,'light'),(390,'dark')):
                page.set_viewport_size({'width':width,'height':1000})
                page.emulate_media(color_scheme=theme)
                second.locator('.forum-open-menu summary').first.click()
                option=second.get_by_role('button',name='Über den aktuellen Hostname öffnen',exact=True).first
                assert option.is_visible()
                bounds=option.bounding_box()
                assert bounds['x']>=0 and bounds['x']+bounds['width']<=width
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/f'super-dropdown-{width}-{theme}.png'),full_page=True)
                page.keyboard.press('Escape')
                assert not option.is_visible()
            for index,path in ((0,'/'),(1,'/admin')):
                menu=second.locator('.forum-open-menu').nth(index)
                menu.locator('summary').click()
                menu.get_by_role('button',name='Über den aktuellen Hostname öffnen',exact=True).click()
                page.wait_for_url(base+path)
                assert page.title()=='Zweites Forum · Vorum'
                warning=page.locator('header .tenant-warning')
                assert warning.is_visible() and 'Zweites Forum' in warning.inner_text()
                for width,theme in ((1440,'light'),(390,'light'),(390,'dark')):
                    page.set_viewport_size({'width':width,'height':1000})
                    page.emulate_media(color_scheme=theme)
                    assert warning.get_by_role('link',name='Zurück',exact=True).is_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output/f'forum-warning-{index}-{width}-{theme}.png'),full_page=True)
                page.goto(base+'/admin/settings')
                assert page.title()=='Zweites Forum · Vorum'
                page.locator('header .tenant-warning').get_by_role('link',name='Zurück',exact=True).click()
                page.wait_for_url(base+'/super')
                assert not any(cookie['name']=='vorum_superadmin_tenant' for cookie in page.context.cookies())
                assert page.locator('.tenant-warning').count()==0
            page.set_viewport_size({'width':1440,'height':1000})
            page.emulate_media(color_scheme='light')
            page.goto(base)
            page.locator('.notification-menu summary').click()
            assert page.locator('.notification-dropdown button').count()==5
            page.get_by_role('button',name='Bei jedem neuen Thema und Beitrag sofort informieren',exact=True).click()
            page.locator('.notification-menu summary').click()
            assert page.get_by_role('button',name='Bei jedem neuen Thema und Beitrag sofort informieren',exact=True).get_attribute('aria-pressed')=='true'
            page.goto(base+'/admin/categories')
            page.get_by_label('Name',exact=True).fill('Allgemein')
            page.get_by_role('button',name='Anlegen',exact=True).click()
            for title in ['Willkommen in unserer Community','Welche Ideen habt ihr für unser Forum?','Ein Ort für Fragen, Wissen und Austausch']:
                page.goto(base+'/topics/new')
                page.get_by_label('Titel',exact=True).fill(title)
                page.locator('select[name=category]').select_option(label='Allgemein')
                page.locator('#rich-editor').fill('Schön, dass du dabei bist! Hier können wir Ideen teilen und gemeinsam ins Gespräch kommen.')
                editor=page.locator('#rich-editor')
                editor.press('End')
                for line in ['Zweite Zeile','','Vierte Zeile','Fünfte Zeile']:
                    editor.press('Enter')
                    if line:
                        editor.press_sequentially(line)
                multiline=editor.inner_text()
                page.get_by_role('button',name=re.compile('Topic veröffentlichen')).click()
                page.wait_for_url(re.compile(r'/topics/(?!new).+'))
                assert page.locator('.prose').inner_text()==multiline
            topic_url=page.url
            page.locator('.notification-menu summary').click()
            assert page.locator('.notification-dropdown button').count()==4
            page.get_by_role('button',name='Tägliche Zusammenfassung',exact=True).click()
            page.locator('.notification-menu summary').click()
            assert page.get_by_role('button',name='Tägliche Zusammenfassung',exact=True).get_attribute('aria-pressed')=='true'
            page.locator('.notification-menu summary').click()
            page.get_by_role('link',name='Bearbeiten',exact=True).click()
            assert page.locator('#rich-editor').inner_text()==multiline
            page.locator('#rich-editor').press('ControlOrMeta+End')
            page.locator('#rich-editor').press('Enter')
            page.locator('#rich-editor').press_sequentially('Sechste Zeile')
            edited=page.locator('#rich-editor').inner_text()
            page.get_by_role('button',name=re.compile('Änderungen speichern')).click()
            page.wait_for_url(topic_url)
            assert page.locator('.prose').inner_text()==edited
            page.get_by_role('link',name='Antwort schreiben').click()
            page.locator('#rich-editor').fill('Eine gute Idee. Ich freue mich auf den Austausch!')
            page.locator('#rich-editor').press('End')
            for line in ['Zweite Antwortzeile','','Nach einer Leerzeile']:
                page.locator('#rich-editor').press('Enter')
                if line:
                    page.locator('#rich-editor').press_sequentially(line)
            reply=page.locator('#rich-editor').inner_text()
            page.get_by_role('button',name=re.compile('Antwort veröffentlichen')).click()
            page.wait_for_url(topic_url)
            assert page.locator('.post').count()==2
            assert page.locator('.prose').nth(1).inner_text()==reply
            page.goto(base)
            assert page.locator('.topic-row').count()==3
            page.screenshot(path=str(output/'desktop.png'),full_page=True)
            for system_mode, opposite_mode in [('light','dark'),('dark','light')]:
                page.emulate_media(color_scheme=system_mode)
                assert page.locator('html').get_attribute('data-theme') is None
                assert page.evaluate('getComputedStyle(document.documentElement).colorScheme')==system_mode
                page.locator('#theme-toggle').click()
                assert page.locator('html').get_attribute('data-theme')==opposite_mode
                page.reload()
                assert page.locator('html').get_attribute('data-theme')==opposite_mode
                if opposite_mode=='dark':
                    page.screenshot(path=str(output/'dark.png'),full_page=True)
                page.locator('#theme-toggle').click()
                assert page.locator('html').get_attribute('data-theme')==system_mode
                page.locator('#theme-toggle').click()
                assert page.locator('html').get_attribute('data-theme') is None
            page.emulate_media(color_scheme='light')
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(output/'mobile.png'),full_page=True)
            for path in ['/',topic_url.removeprefix(base),'/topics/new','/admin','/admin/users','/settings']:
                page.goto(base+path)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),path
            page.goto(topic_url)
            page.locator('.notification-menu summary').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('.notification-dropdown').bounding_box()['x']>=0
            page.screenshot(path=str(output/'mobile-notifications.png'),full_page=True)
            page.locator('.notification-menu summary').click()
            page.screenshot(path=str(output/'mobile-topic.png'),full_page=True)
            page.goto(base+'/admin')
            page.locator('.admin-nav summary').click()
            assert not page.locator('.admin-nav').get_attribute('open')
            page.goto(base)
            page.get_by_role('button',name='EN',exact=True).click()
            assert page.locator('html').get_attribute('lang')=='en'
            assert page.get_by_role('heading',name='Good conversations start here.').is_visible()
            page.get_by_role('button',name='DE',exact=True).click()
            page.goto(base+'/admin/api')
            page.get_by_label('Name',exact=True).fill('Browser integration')
            page.get_by_role('button',name='Schlüssel generieren',exact=True).click()
            api_key=page.get_by_label('API-Schlüssel',exact=True).input_value()
            assert api_key.startswith('vorum_')
            assert page.get_by_role('link',name='API-Anleitung herunterladen').is_visible()
            page.goto(base+'/admin/api')
            assert page.get_by_label('API-Schlüssel',exact=True).count()==0
            page.goto(base+'/admin/appearance')
            intro_texts={
                'Kurzzeile (Deutsch)':('DEINE COMMUNITY','UNSER FORUM'),
                'Überschrift (Deutsch)':('Gute Gespräche beginnen hier.','Willkommen im Forum'),
                'Beschreibung (Deutsch)':('Teile Ideen, stelle Fragen und bleib im Austausch.','Hier tauschen wir uns aus.'),
                'Kurzzeile (Englisch)':('YOUR COMMUNITY','OUR FORUM'),
                'Überschrift (Englisch)':('Good conversations start here.','Welcome to the forum'),
                'Beschreibung (Englisch)':('Share ideas, ask questions, and stay connected.','Connect with our community.'),
            }
            for label,(default,custom) in intro_texts.items():
                assert page.get_by_label(label,exact=True).input_value()==default
                page.get_by_label(label,exact=True).fill(custom)
            page.get_by_label('Farbschema',exact=True).select_option('forest')
            page.get_by_role('button',name='Änderungen speichern',exact=True).click()
            page.screenshot(path=str(output/'admin-appearance.png'),full_page=True)
            page.goto(base+'/admin/settings')
            assert page.get_by_label('Zeitzone des Forums',exact=True).input_value()=='UTC'
            page.get_by_label('Zeitzone des Forums',exact=True).select_option('Europe/Berlin')
            page.get_by_label('Registrierung erlaubt',exact=True).uncheck()
            page.get_by_label('Login erlaubt',exact=True).uncheck()
            page.get_by_label('AGB-Text',exact=True).fill('Unsere Bedingungen\nBitte freundlich bleiben.')
            page.get_by_role('button',name='Änderungen speichern',exact=True).click()
            assert page.get_by_label('Zeitzone des Forums',exact=True).input_value()=='Europe/Berlin'
            page.reload()
            assert page.get_by_label('Zeitzone des Forums',exact=True).input_value()=='Europe/Berlin'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not page.get_by_label('Login erlaubt',exact=True).is_checked()
            page.screenshot(path=str(output/'admin-settings.png'),full_page=True)
            page.get_by_role('link',name='Mail →',exact=True).click()
            page.wait_for_url('**/admin/settings/mail')
            assert page.get_by_label('Versandzeit',exact=True).input_value()=='16:00'
            assert page.get_by_label('Zeitzone',exact=True).input_value()=='Europe/Berlin'
            assert page.get_by_label('Wöchentlicher Versand',exact=True).input_value()=='5'
            assert page.get_by_label('Empfänger',exact=True).input_value()=='alex@example.org'
            page.get_by_label('Zeitzone',exact=True).select_option('Atlantic/Canary')
            page.get_by_label('SMTP-Server',exact=True).fill('smtp.example.org')
            page.get_by_label('Mail-Absender',exact=True).fill('forum@example.org')
            page.get_by_role('button',name='Änderungen speichern',exact=True).click()
            assert page.get_by_label('Zeitzone',exact=True).input_value()=='Atlantic/Canary'
            page.get_by_role('button',name='Testmail versenden',exact=True).click()
            assert page.get_by_text('Testmail wurde versendet.',exact=True).is_visible()
            assert app.extensions['outbox'][-1]['to']=='alex@example.org'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/'admin-mail.png'),full_page=True)
            page.goto(base+'/admin/appearance')
            for label,(_,custom) in intro_texts.items():
                assert page.get_by_label(label,exact=True).input_value()==custom
            page.get_by_role('link',name='Logo →',exact=True).click()
            image=io.BytesIO()
            Image.new('RGBA',(400,200),'#23734c').save(image,'PNG')
            page.get_by_label('Bild auswählen',exact=True).set_input_files({'name':'logo.png','mimeType':'image/png','buffer':image.getvalue()})
            page.get_by_role('button',name='Logo hochladen',exact=True).click()
            assert page.get_by_alt_text('Aktuelles Foren-Logo').is_visible()
            assert page.locator('.forum-logo').evaluate('(img) => img.complete && img.naturalWidth > 0')
            icon=page.locator('link[rel="icon"]').get_attribute('href')
            assert page.request.get(base+icon).status==200
            page.screenshot(path=str(output/'admin-logo.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/'admin-logo-mobile.png'),full_page=True)
            page.once('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='Logo entfernen',exact=True).click()
            assert page.locator('.forum-logo').count()==0
            assert page.locator('link[rel="icon"]').count()==0
            page.set_viewport_size({'width':1440,'height':1000})
            page.goto(base)
            assert page.locator('.hero h1').inner_text()=='Willkommen im Forum'
            assert page.locator('.hero .eyebrow').inner_text()=='UNSER FORUM'
            assert page.locator('.hero > div:first-child > p').inner_text()=='Hier tauschen wir uns aus.'
            page.get_by_role('button',name='EN',exact=True).click()
            assert page.locator('.hero h1').inner_text()=='Welcome to the forum'
            assert page.locator('.hero .eyebrow').inner_text()=='OUR FORUM'
            assert page.locator('.hero > div:first-child > p').inner_text()=='Connect with our community.'
            page.get_by_role('button',name='DE',exact=True).click()

            payload={'external_id':'browser:001','email':'browser-api@example.org','email_verified':True,
                     'username':'Vorschlag','username_suggestion':True,
                     'avatar_url':'https://images.example.org/avatar.svg','avatar_suggestion':True}
            response=page.request.post(base+'/api/v1/users/login',data=payload,headers={'Authorization':'Bearer '+api_key})
            assert response.status==201,response.text()
            login_url=response.json()['login_url']
            external_context=browser.new_context(viewport={'width':390,'height':844},locale='de-DE')
            external_context.route('https://images.example.org/**',lambda route:route.fulfill(
                status=200,content_type='image/svg+xml',
                body='<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect width="128" height="128" rx="24" fill="#0077b6"/><circle cx="64" cy="48" r="20" fill="#caf0f8"/><path d="M24 112a40 40 0 0 1 80 0" fill="#caf0f8"/></svg>'))
            external=external_context.new_page()
            external.goto(login_url)
            assert external.get_by_label('Benutzername',exact=True).input_value()=='Vorschlag'
            external.wait_for_function("document.querySelector('.suggested-avatar').complete && document.querySelector('.suggested-avatar').naturalWidth > 0")
            external.get_by_label('Benutzername',exact=True).fill('Mein Name')
            external.screenshot(path=str(output/'api-profile.png'),full_page=True)
            external.get_by_role('button',name='Profil bestätigen und einloggen',exact=True).click()
            external.wait_for_url(base+'/')
            external.goto(base+'/settings')
            assert external.get_by_role('link',name='Avatar ↗').is_visible()
            assert external.locator('a[href="/settings/email"]').count()==0
            assert external.locator('a[href="/settings/password"]').count()==0
            external.get_by_role('link',name='Avatar ↗').click()
            external.locator('.avatar img').last.wait_for(state='visible')
            external.wait_for_function("Array.from(document.querySelectorAll('.avatar img')).every(image => image.complete && image.naturalWidth > 0)")
            assert external.evaluate('document.documentElement.scrollWidth <= innerWidth')
            external_context.close()
            page.goto(base+'/admin/api')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/'admin-api.png'),full_page=True)
            page.once('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='Entfernen',exact=True).click()
            assert page.get_by_text('Noch keine API-Schlüssel.',exact=True).is_visible()
            assert not errors,errors
            browser.close()
        print('Browser smoke passed: setup, superadmin forum switching, dropdowns, topics, rich text, replies, mobile layouts, themes, language, appearance, logo upload/removal, favicon, API keys, auth settings, external login. Screenshots:',output)
    finally:
        server.shutdown()
