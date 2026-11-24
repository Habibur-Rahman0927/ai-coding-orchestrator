"""Shared non-secret provider preferences for CLI and dashboard."""
import json


def initialize(store):
    with store.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS dashboard_settings '
                           '(key TEXT PRIMARY KEY, value TEXT NOT NULL)')


def setting(store, key, default=None):
    initialize(store)
    with store.connect() as connection:
        row = connection.execute('SELECT value FROM dashboard_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default


def save_setting(store, key, value):
    initialize(store)
    with store.connect() as connection:
        connection.execute('INSERT OR REPLACE INTO dashboard_settings(key,value) VALUES(?,?)',
                           (key, json.dumps(value)))


def provider_config(store):
    return setting(store, 'providers', {})


def registry_for(store):
    from .providers import ProviderRegistry
    from .credentials import CredentialManager
    credentials = CredentialManager(store)
    return ProviderRegistry(config=provider_config(store), credential_resolver=credentials.resolve, credential_status=credentials.status)
