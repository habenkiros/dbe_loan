# loan_system/settings.py

import os
import sys
from pathlib import Path
import environ
import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
from datetime import timedelta

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')


def _env_bool(name, default=False):
    """Parse a truthy/falsey environment flag. Missing/blank uses *default*."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == '':
        return bool(default)
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


DEBUG = _env_bool('DEBUG', default=False)
TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'


def _https_allow_any_host():
    """Field HTTPS overlay: accept whatever LAN IP DHCP assigned (not a baked Host)."""
    if os.getenv('USE_HTTPS_PROXY', '') != '1':
        return False
    return os.getenv('HTTPS_ALLOW_ANY_HOST', '1').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


_allowed = os.getenv('ALLOWED_HOSTS', '*').strip()
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(',') if h.strip()] if _allowed else ['*']
if _https_allow_any_host():
    ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'loans',
    'collateral',
    'partners',
    'applicant_portal',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # On-prem product license (Ed25519); blocks app when missing/expired past grace
    'loans.license_middleware.LicenseEnforcementMiddleware',
    # After apps URLs: bare staff paths (/manage_users/ …) → /hub/…
    'loans.legacy_hub_redirect.StaffHubLegacyRedirectMiddleware',
    'loans.middleware.DelegationPrincipalLockoutMiddleware',
]

# --- On-prem license (Seqela-signed; see docs/deployment/) ---
LICENSE_KEY = os.getenv('LICENSE_KEY', '').strip()
LICENSE_KEY_FILE = os.getenv('LICENSE_KEY_FILE', '').strip()
LICENSE_GRACE_DAYS = int(os.getenv('LICENSE_GRACE_DAYS', '7') or 7)
# LICENSE_ENFORCE: unset = enforce when DEBUG=False; set true/false to override
LICENSE_ENFORCE = os.getenv('LICENSE_ENFORCE', '').strip()

ROOT_URLCONF = 'decsi_loan.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'loans.context_processors.loan_notifications',
                'loans.context_processors.staff_delegations',
                'loans.context_processors.agent_assistant',
                'loans.context_processors.staff_nav',
                'loans.context_processors.product_license',
                'loans.context_processors.institution_branding',
                'collateral.context_processors.gebeta_maps',
                'applicant_portal.context_processors.portal_notices',
            ],
        },
    },
]

WSGI_APPLICATION = 'decsi_loan.wsgi.application'

# Custom User Model
AUTH_USER_MODEL = 'loans.CustomUser'

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

# Database configuration for PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'decsiloandb'),
        'USER': os.getenv('DB_USER', 'decsiloandbuser'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'decsiloandbpassword'),
        'HOST': 'db',
        'PORT': '5432',
    }
}
# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

PASSWORD_MIN_LENGTH = int(os.getenv('PASSWORD_MIN_LENGTH', '10') or '10')

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': PASSWORD_MIN_LENGTH},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Browser hardening (always on; not gated on DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
# JS clients must read csrftoken for AJAX
CSRF_COOKIE_HTTPONLY = False



# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static", BASE_DIR / "presentation"]
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (collateral building images)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# settings.py

# STATIC_URL = '/static/'

# # Add this if you don't already have it
# STATICFILES_DIRS = [
#     os.path.join(BASE_DIR, "static"),
# ]

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


LOGIN_URL = '/hub/login/'
LOGIN_REDIRECT_URL = '/hub/'
LOGOUT_REDIRECT_URL = '/hub/login/'

# This instance: Development Bank of Ethiopia (not DECSI production).
INSTITUTION_NAME = os.getenv('INSTITUTION_NAME', 'Development Bank of Ethiopia').strip() or 'Development Bank of Ethiopia'
INSTITUTION_SHORT = os.getenv('INSTITUTION_SHORT', 'DBE').strip() or 'DBE'
PRODUCT_NAME = os.getenv('PRODUCT_NAME', 'Credit Intelligence').strip() or 'Credit Intelligence'

# Auth hardening (read from .env — see .env.example)
LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv('LOGIN_MAX_FAILED_ATTEMPTS', '5') or '5')
LOGIN_LOCKOUT_MINUTES = int(os.getenv('LOGIN_LOCKOUT_MINUTES', '15') or '15')
MFA_REQUIRED = os.getenv('MFA_REQUIRED', 'False').strip().lower() in ('1', 'true', 'yes', 'on')
# Re-auth (password, + TOTP if enrolled) before committee vote / return
COMMITTEE_STEPUP_REQUIRED = os.getenv('COMMITTEE_STEPUP_REQUIRED', 'True').strip().lower() in (
    '1', 'true', 'yes', 'on',
)
_mfa_issuer = os.getenv('MFA_TOTP_ISSUER', '').strip()
MFA_TOTP_ISSUER = _mfa_issuer or f'{INSTITUTION_SHORT} {PRODUCT_NAME}'
SESSION_IDLE_TIMEOUT = int(os.getenv('SESSION_IDLE_TIMEOUT', '1800') or '1800')
SESSION_IDLE_WARNING_SECONDS = int(os.getenv('SESSION_IDLE_WARNING_SECONDS', '120') or '120')
_session_age = os.getenv('SESSION_COOKIE_AGE', '').strip()
if _session_age.isdigit():
    SESSION_COOKIE_AGE = int(_session_age)
SESSION_EXPIRE_AT_BROWSER_CLOSE = os.getenv(
    'SESSION_EXPIRE_AT_BROWSER_CLOSE', 'True'
).strip().lower() in ('1', 'true', 'yes', 'on')

# Chapa payments (digital apply processing fee)
# Get test keys from https://dashboard.chapa.co — leave blank to use mock checkout in dev.
CHAPA_SECRET_KEY = os.getenv('CHAPA_SECRET_KEY', '').strip()
CHAPA_PUBLIC_KEY = os.getenv('CHAPA_PUBLIC_KEY', '').strip()
CHAPA_CURRENCY = os.getenv('CHAPA_CURRENCY', 'ETB').strip() or 'ETB'
# Force mock checkout even if secret key is set (tests / local demos)
CHAPA_FORCE_MOCK = os.getenv('CHAPA_FORCE_MOCK', '').lower() in ('1', 'true', 'yes')

# Optional SMS gateway for applicant OTP / status (POST JSON: to, message)
APPLICANT_SMS_URL = os.getenv('APPLICANT_SMS_URL', '').strip()
APPLICANT_SMS_API_KEY = os.getenv('APPLICANT_SMS_API_KEY', '').strip()

# Committee notifications (optional email; in-app always created)
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@dbe.local')
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@dbe.local')
# After Chapa marks fee paid, create LoanRequest + branch queue when docs are complete.
DECSI_AUTO_QUEUE_ON_PAID = os.getenv('DECSI_AUTO_QUEUE_ON_PAID', 'True').lower() in ('1', 'true', 'yes')

# Document OCR (Tesseract language packs: eng, amh, or eng+amh)
DOCUMENT_OCR_LANG = os.getenv('DOCUMENT_OCR_LANG', 'eng+amh')
DOCUMENT_OCR_MATCH_MIN_SCORE = int(os.getenv('DOCUMENT_OCR_MATCH_MIN_SCORE', '60') or '60')
DOCUMENT_NEAR_DUP_SCAN_LIMIT = int(os.getenv('DOCUMENT_NEAR_DUP_SCAN_LIMIT', '800') or '800')
# Optional LLM assist for bank-statement plausibility (per-type enable_llm_check)
DOCUMENT_LLM_PROVIDER = os.getenv('DOCUMENT_LLM_PROVIDER', 'openai').strip().lower() or 'openai'
OPENAI_DOCUMENT_MODEL = os.getenv('OPENAI_DOCUMENT_MODEL', 'gpt-4o-mini').strip() or 'gpt-4o-mini'
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_DOCUMENT_MODEL = os.getenv('GEMINI_DOCUMENT_MODEL', 'gemini-1.5-flash').strip() or 'gemini-1.5-flash'
# Optional HTTP webhook for document identity verify (else DECSI party / mock)
EXTERNAL_ID_VERIFY_URL = os.getenv('EXTERNAL_ID_VERIFY_URL', '').strip()

# Applicant KYC identity rails (Fayda FAN / TIN). off | mock | http
IDENTITY_VERIFY_PROVIDER = os.getenv('IDENTITY_VERIFY_PROVIDER', 'mock').strip().lower()
IDENTITY_VERIFY_FORCE_MOCK = os.getenv('IDENTITY_VERIFY_FORCE_MOCK', '').lower() in ('1', 'true', 'yes')
FAYDA_VERIFY_URL = os.getenv('FAYDA_VERIFY_URL', '').strip()
TIN_VERIFY_URL = os.getenv('TIN_VERIFY_URL', '').strip()
IDENTITY_VERIFY_TIMEOUT = int(os.getenv('IDENTITY_VERIFY_TIMEOUT', '8'))

# Face / liveness adapter (off | mock | http). Stores score + vendor ref only.
BIOMETRIC_PROVIDER = os.getenv('BIOMETRIC_PROVIDER', 'mock').strip().lower()
BIOMETRIC_VERIFY_URL = os.getenv('BIOMETRIC_VERIFY_URL', '').strip()
BIOMETRIC_VERIFY_TIMEOUT = int(os.getenv('BIOMETRIC_VERIFY_TIMEOUT', '8'))
BIOMETRIC_SEND_IMAGE = os.getenv('BIOMETRIC_SEND_IMAGE', '').lower() in ('1', 'true', 'yes')
BIOMETRIC_MATCH_MIN = int(os.getenv('BIOMETRIC_MATCH_MIN', '70'))

# Core banking / party customer lookup (Sheet 1 intake).
# BANK_CBS_* is the DBE name; DECSI_* remains an alias for the live factory.
BANK_CBS_BASE_URL = os.getenv('BANK_CBS_BASE_URL', '').rstrip('/')
DECSI_BASE_URL = BANK_CBS_BASE_URL or os.getenv('DECSI_BASE_URL', '').rstrip('/')
DECSI_CUSTOMER_TIMEOUT = int(os.getenv('DECSI_CUSTOMER_TIMEOUT', '8'))
DECSI_CUSTOMER_FORCE_MOCK = os.getenv('DECSI_CUSTOMER_FORCE_MOCK', '').lower() in ('1', 'true', 'yes')
# Silent mock fallback after live failure:
# - explicit True/False from env wins
# - otherwise: allow fallback only when no DECSI_BASE_URL (pure demo); refuse silent fallback when live URL is set
_fallback_raw = os.getenv('DECSI_CUSTOMER_FALLBACK_MOCK', '').strip().lower()
if _fallback_raw in ('1', 'true', 'yes'):
    DECSI_CUSTOMER_FALLBACK_MOCK = True
elif _fallback_raw in ('0', 'false', 'no'):
    DECSI_CUSTOMER_FALLBACK_MOCK = False
else:
    DECSI_CUSTOMER_FALLBACK_MOCK = not bool(DECSI_BASE_URL)
DECSI_CUSTOMER_DETAIL_PATH = os.getenv(
    'DECSI_CUSTOMER_DETAIL_PATH',
    '/getCusByCusNo/api/v1.0.0/party/custid/{cid}/custdets',
)
DECSI_TRANSACTIONS_PATH = os.getenv(
    'DECSI_TRANSACTIONS_PATH',
    '/getCusByCusNo/api/v1.0.0/party/custid/{cid}/transactions',
)

# CBS / Temenos — outstanding + disbursement booking (PortfolioLedgerAdapter)
# auto = use DecsiCbsLedgerAdapter when mock ledger or DECSI_BASE_URL enabled
DECSI_LEDGER_ADAPTER = os.getenv('DECSI_LEDGER_ADAPTER', 'auto').strip().lower()  # auto|cbs|stub
DECSI_CBS_ENABLED = os.getenv('DECSI_CBS_ENABLED', 'True').lower() in ('1', 'true', 'yes')
# When True (default), mock outstanding/booking works offline without DECSI_BASE_URL
DECSI_CBS_USE_MOCK_LEDGER = os.getenv('DECSI_CBS_USE_MOCK_LEDGER', 'True').lower() in ('1', 'true', 'yes')
DECSI_CBS_FORCE_MOCK = os.getenv('DECSI_CBS_FORCE_MOCK', '').lower() in ('1', 'true', 'yes')
DECSI_CBS_TIMEOUT = int(os.getenv('DECSI_CBS_TIMEOUT', os.getenv('DECSI_CUSTOMER_TIMEOUT', '8')))
DECSI_CBS_API_KEY = (os.getenv('BANK_CBS_API_KEY') or os.getenv('DECSI_CBS_API_KEY') or '').strip()
DECSI_OUTSTANDING_PATH = os.getenv(
    'DECSI_OUTSTANDING_PATH',
    '/getCusByCusNo/api/v1.0.0/party/custid/{cid}/outstanding',
)
DECSI_DISBURSE_PATH = os.getenv(
    'DECSI_DISBURSE_PATH',
    '/loanDisburse/api/v1.0.0/loans/disburse',
)
# When True, officer "Mark disbursed" books in CBS first (required success)
DECSI_CBS_BOOK_ON_DISBURSE = os.getenv('DECSI_CBS_BOOK_ON_DISBURSE', 'True').lower() in ('1', 'true', 'yes')

# Sanctions / PEP name screening → Fraud/AML compliance desk
# mock = built-in demo watchlist; http = POST JSON to vendor URL; off = disabled
SANCTIONS_PROVIDER = os.getenv('SANCTIONS_PROVIDER', 'mock').strip().lower()
SANCTIONS_FORCE_MOCK = os.getenv('SANCTIONS_FORCE_MOCK', '').lower() in ('1', 'true', 'yes')
SANCTIONS_HTTP_URL = os.getenv('SANCTIONS_HTTP_URL', '').rstrip('/')
SANCTIONS_HTTP_PATH = os.getenv('SANCTIONS_HTTP_PATH', '/screen').strip()
SANCTIONS_HTTP_API_KEY = os.getenv('SANCTIONS_HTTP_API_KEY', '').strip()
SANCTIONS_HTTP_TIMEOUT = int(os.getenv('SANCTIONS_HTTP_TIMEOUT', '8'))
SANCTIONS_HTTP_FALLBACK_MOCK = os.getenv('SANCTIONS_HTTP_FALLBACK_MOCK', 'True').lower() in (
    '1', 'true', 'yes',
)
# Comma-separated extra demo names that always hit (offline UAT)
SANCTIONS_DEMO_EXTRA_NAMES = os.getenv('SANCTIONS_DEMO_EXTRA_NAMES', '')
SANCTIONS_KEEP_RAW = os.getenv('SANCTIONS_KEEP_RAW', '').lower() in ('1', 'true', 'yes')

# Gebeta Maps — Ethiopia-local geocoding + map tiles (MapLibre / Gebeta styles)
# Docs: https://docs.gebeta.app/docs · JS tiles: https://github.com/AfriGebeta/gebeta-tiles-js
GEBETA_MAPS_API_KEY = os.getenv('GEBETA_MAPS_API_KEY', '').strip()
GEBETA_MAPS_GEOCODE_URL = os.getenv(
    'GEBETA_MAPS_GEOCODE_URL',
    'https://mapapi.gebeta.app/api/v1/route/geocoding',
).rstrip('/')
GEBETA_MAPS_TIMEOUT = int(os.getenv('GEBETA_MAPS_TIMEOUT', '8'))
# auto = Gebeta when key set, else Nominatim; force with gebeta|nominatim
GEBETA_MAPS_GEOCODE_PROVIDER = os.getenv('GEBETA_MAPS_GEOCODE_PROVIDER', 'auto').strip().lower()
# auto = Gebeta tiles when key set, else Leaflet/OSM; force with gebeta|leaflet_osm
GEBETA_MAPS_TILES_PROVIDER = os.getenv('GEBETA_MAPS_TILES_PROVIDER', 'auto').strip().lower()
GEBETA_MAPS_STYLE_STANDARD = os.getenv(
    'GEBETA_MAPS_STYLE_STANDARD',
    'https://tiles.gebeta.app/styles/standard/style.json',
)
GEBETA_MAPS_STYLE_SATELLITE = os.getenv(
    'GEBETA_MAPS_STYLE_SATELLITE',
    'https://tiles.gebeta.app/styles/raster/raster.json',
)
GEBETA_MAPS_STYLE_TERRAIN = os.getenv(
    'GEBETA_MAPS_STYLE_TERRAIN',
    'https://tiles.gebeta.app/styles/standard/terrain/terrain.json',
)

# HTTPS reverse proxy for tablet field visits (see docker-compose.https.yml)
if os.getenv('USE_HTTPS_PROXY', '') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    # Default off: Secure cookies break login on http://LAN:8000 and are often
    # dropped by mobile browsers on self-signed https://LAN:8443.
    # Set HTTPS_SECURE_COOKIES=1 only with a trusted/public TLS cert.
    _secure_cookies = os.getenv('HTTPS_SECURE_COOKIES', '0') == '1'
    SESSION_COOKIE_SECURE = _secure_cookies
    CSRF_COOKIE_SECURE = _secure_cookies

_csrf_trusted = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
_csrf_origins = [o.strip() for o in _csrf_trusted.split(',') if o.strip()] if _csrf_trusted else []
# Field HTTPS: do not pin CSRF to a single LAN IP. Same-origin POSTs use the
# request Host (whatever DHCP assigned). Localhost is listed for laptop tests.
_site_url = os.getenv('SITE_URL', '').strip().rstrip('/')
if _site_url.startswith(('https://', 'http://')) and _site_url not in _csrf_origins:
    _csrf_origins.append(_site_url)
if os.getenv('USE_HTTPS_PROXY', '') == '1':
    for _base in ('https://localhost:8443', 'https://127.0.0.1:8443'):
        if _base not in _csrf_origins:
            _csrf_origins.append(_base)
if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = _csrf_origins

# ---------------------------------------------------------------------------
# Agentic Assist chatbot (OpenAI tool-calling; stub without key)
# ---------------------------------------------------------------------------
# Recommendation: OpenAI GPT-4o-mini — strong function calling, low cost.
# Azure OpenAI: set OPENAI_BASE_URL to the deployment URL and OPENAI_API_VERSION.
AGENT_LLM_PROVIDER = os.getenv('AGENT_LLM_PROVIDER', 'auto').strip().lower()  # auto|openai|stub
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini').strip() or 'gpt-4o-mini'
OPENAI_API_VERSION = os.getenv('OPENAI_API_VERSION', '').strip()  # Azure only, e.g. 2024-08-01-preview
AGENT_LLM_TIMEOUT = int(os.getenv('AGENT_LLM_TIMEOUT', '60') or '60')

# Credit Intelligence operational alert thresholds (days)
CI_AGING_APPRAISAL_DAYS = int(os.getenv('CI_AGING_APPRAISAL_DAYS', '7') or '7')
COMMITTEE_PEND_DUE_DAYS = int(os.getenv('COMMITTEE_PEND_DUE_DAYS', '5') or '5')
CI_COMMITTEE_SLA_DAYS = int(os.getenv('CI_COMMITTEE_SLA_DAYS', '5') or '5')
