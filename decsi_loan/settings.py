# loan_system/settings.py

import os
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

DEBUG = os.getenv('DEBUG', 'False') == 'False'

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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

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

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]



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


LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Committee notifications (optional email; in-app always created)
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@decsi.local')
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'

# Document OCR (Tesseract language packs: eng, amh, or eng+amh)
DOCUMENT_OCR_LANG = os.getenv('DOCUMENT_OCR_LANG', 'eng+amh')

# Core banking / party customer lookup (Sheet 1 intake)
DECSI_BASE_URL = os.getenv('DECSI_BASE_URL', '').rstrip('/')
DECSI_CUSTOMER_TIMEOUT = int(os.getenv('DECSI_CUSTOMER_TIMEOUT', '8'))
DECSI_CUSTOMER_FORCE_MOCK = os.getenv('DECSI_CUSTOMER_FORCE_MOCK', '').lower() in ('1', 'true', 'yes')
DECSI_CUSTOMER_FALLBACK_MOCK = os.getenv('DECSI_CUSTOMER_FALLBACK_MOCK', 'True').lower() in ('1', 'true', 'yes')

# HTTPS reverse proxy for tablet field visits (see docker-compose.https.yml)
if os.getenv('USE_HTTPS_PROXY', '') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

_csrf_trusted = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
if _csrf_trusted:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_trusted.split(',') if o.strip()]
