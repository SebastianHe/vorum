PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS tenants (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 logo TEXT NOT NULL DEFAULT '',
 theme TEXT NOT NULL DEFAULT 'default', timezone TEXT NOT NULL DEFAULT 'UTC',
 intro_eyebrow_de TEXT NOT NULL DEFAULT 'DEINE COMMUNITY',
 intro_eyebrow_en TEXT NOT NULL DEFAULT 'YOUR COMMUNITY',
 intro_title_de TEXT NOT NULL DEFAULT 'Gute Gespräche beginnen hier.',
 intro_title_en TEXT NOT NULL DEFAULT 'Good conversations start here.',
 intro_description_de TEXT NOT NULL DEFAULT 'Teile Ideen, stelle Fragen und bleib im Austausch.',
 intro_description_en TEXT NOT NULL DEFAULT 'Share ideas, ask questions, and stay connected.',
 smtp_host TEXT NOT NULL DEFAULT '',
 smtp_port INTEGER NOT NULL DEFAULT 587, smtp_user TEXT NOT NULL DEFAULT '',
 smtp_password TEXT NOT NULL DEFAULT '', smtp_security TEXT NOT NULL DEFAULT 'starttls',
 mail_from TEXT NOT NULL DEFAULT '',
 registration_allowed INTEGER NOT NULL DEFAULT 1, registration_url TEXT NOT NULL DEFAULT '',
 registration_terms TEXT NOT NULL DEFAULT '', login_allowed INTEGER NOT NULL DEFAULT 1,
 login_url TEXT NOT NULL DEFAULT '',
 search_indexing_allowed INTEGER NOT NULL DEFAULT 1,
 guests_can_view_forum INTEGER NOT NULL DEFAULT 1,
 guests_can_view_topics INTEGER NOT NULL DEFAULT 1,
 digest_time TEXT NOT NULL DEFAULT '16:00', digest_timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
 digest_weekday INTEGER NOT NULL DEFAULT 5
);
CREATE TABLE IF NOT EXISTS hosts (hostname TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, tenant_id INTEGER REFERENCES tenants(id),
 username TEXT NOT NULL, email TEXT NOT NULL COLLATE NOCASE, password TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','moderator','admin','superadmin')),
 verified INTEGER NOT NULL DEFAULT 0, color INTEGER NOT NULL, avatar TEXT,
 pending_email TEXT, code_hash TEXT, registration_code TEXT, code_attempts INTEGER NOT NULL DEFAULT 0,
 code_until REAL, cooldown_until REAL, code_sent REAL, created_at TEXT NOT NULL,
 external_id TEXT, username_suggestion INTEGER NOT NULL DEFAULT 0,
 avatar_editable INTEGER NOT NULL DEFAULT 1, avatar_suggestion_url TEXT,
 profile_pending INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS user_local_email ON users(tenant_id,email) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_global_email ON users(email) WHERE tenant_id IS NULL;
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 slug TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(tenant_id,slug)
);
CREATE TABLE IF NOT EXISTS topics (
 id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 slug TEXT NOT NULL, title TEXT NOT NULL, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, username TEXT NOT NULL,
 created_at TEXT NOT NULL, activity TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1, UNIQUE(tenant_id,slug)
);
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, username TEXT NOT NULL,
 body TEXT NOT NULL, created_at TEXT NOT NULL, edited_at TEXT, editor_name TEXT
);
CREATE TABLE IF NOT EXISTS edits (
 id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 body TEXT NOT NULL, editor_name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS post_topic_created ON posts(topic_id,created_at);
CREATE TABLE IF NOT EXISTS attachments (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 filename TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE, size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reads (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE, revision INTEGER NOT NULL, visited_at TEXT,
 PRIMARY KEY(user_id, topic_id)
);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
 tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL,
 created_at TEXT NOT NULL, last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS api_login_tokens (
 token_hash TEXT PRIMARY KEY,
 tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
 expires_at REAL NOT NULL, avatar_preview BLOB
);
CREATE INDEX IF NOT EXISTS api_login_expiry ON api_login_tokens(expires_at);
CREATE TABLE IF NOT EXISTS forum_visits (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, visited_at TEXT NOT NULL,
 PRIMARY KEY(user_id,tenant_id)
);
CREATE TABLE IF NOT EXISTS forum_subscriptions (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 mode TEXT NOT NULL CHECK(mode IN ('all','topics','daily','weekly','none')),
 since TEXT NOT NULL, last_digest_at TEXT, language TEXT NOT NULL DEFAULT 'de', base_url TEXT NOT NULL,
 PRIMARY KEY(user_id,tenant_id)
);
CREATE TABLE IF NOT EXISTS topic_subscriptions (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
 mode TEXT NOT NULL CHECK(mode IN ('all','daily','weekly','none')),
 since TEXT NOT NULL, last_digest_at TEXT, language TEXT NOT NULL DEFAULT 'de', base_url TEXT NOT NULL,
 PRIMARY KEY(user_id,topic_id)
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 is_topic INTEGER NOT NULL DEFAULT 0, delivered_at TEXT,
 PRIMARY KEY(user_id,post_id)
);
CREATE INDEX IF NOT EXISTS pending_notifications ON notification_deliveries(post_id) WHERE delivered_at IS NULL;
