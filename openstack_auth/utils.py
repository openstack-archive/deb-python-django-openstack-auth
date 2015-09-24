# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import functools
import logging

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import middleware
from django.contrib.auth import models
from django.utils import decorators
from django.utils import timezone
from keystoneclient.auth.identity import v2 as v2_auth
from keystoneclient.auth.identity import v3 as v3_auth
from keystoneclient.auth import token_endpoint
from keystoneclient import session
from keystoneclient.v2_0 import client as client_v2
from keystoneclient.v3 import client as client_v3
from six.moves.urllib import parse as urlparse


LOG = logging.getLogger(__name__)

_PROJECT_CACHE = {}

_TOKEN_TIMEOUT_MARGIN = getattr(settings, 'TOKEN_TIMEOUT_MARGIN', 0)

"""
We need the request object to get the user, so we'll slightly modify the
existing django.contrib.auth.get_user method. To do so we update the
auth middleware to point to our overridden method.

Calling the "patch_middleware_get_user" method somewhere like our urls.py
file takes care of hooking it in appropriately.
"""


def middleware_get_user(request):
    if not hasattr(request, '_cached_user'):
        request._cached_user = get_user(request)
    return request._cached_user


def get_user(request):
    try:
        user_id = request.session[auth.SESSION_KEY]
        backend_path = request.session[auth.BACKEND_SESSION_KEY]
        backend = auth.load_backend(backend_path)
        backend.request = request
        user = backend.get_user(user_id) or models.AnonymousUser()
    except KeyError:
        user = models.AnonymousUser()
    return user


def patch_middleware_get_user():
    middleware.get_user = middleware_get_user
    auth.get_user = get_user


""" End Monkey-Patching. """


def is_token_valid(token, margin=None):
    """Timezone-aware checking of the auth token's expiration timestamp.

    Returns ``True`` if the token has not yet expired, otherwise ``False``.

    :param token: The openstack_auth.user.Token instance to check

    :param margin:
       A time margin in seconds to subtract from the real token's validity.
       An example usage is that the token can be valid once the middleware
       passed, and invalid (timed-out) during a view rendering and this
       generates authorization errors during the view rendering.
       A default margin can be set by the TOKEN_TIMEOUT_MARGIN in the
       django settings.
    """
    expiration = token.expires
    # In case we get an unparseable expiration timestamp, return False
    # so you can't have a "forever" token just by breaking the expires param.
    if expiration is None:
        return False
    if margin is None:
        margin = getattr(settings, 'TOKEN_TIMEOUT_MARGIN', 0)
    expiration = expiration - datetime.timedelta(seconds=margin)
    if settings.USE_TZ and timezone.is_naive(expiration):
        # Presumes that the Keystone is using UTC.
        expiration = timezone.make_aware(expiration, timezone.utc)
    return expiration > timezone.now()


# From django.contrib.auth.views
# Added in Django 1.4.3, 1.5b2
# Vendored here for compatibility with old Django versions.
def is_safe_url(url, host=None):
    """Return ``True`` if the url is a safe redirection.

    The safe redirection means that it doesn't point to a different host.
    Always returns ``False`` on an empty url.
    """
    if not url:
        return False
    netloc = urlparse.urlparse(url)[1]
    return not netloc or netloc == host


def memoize_by_keyword_arg(cache, kw_keys):
    """Memoize a function using the list of keyword argument name as its key.

    Wrap a function so that results for any keyword argument tuple are stored
    in 'cache'. Note that the keyword args to the function must be usable as
    dictionary keys.

    :param cache: Dictionary object to store the results.
    :param kw_keys: List of keyword arguments names. The values are used
                    for generating the key in the cache.
    """
    def _decorator(func):
        @functools.wraps(func, assigned=decorators.available_attrs(func))
        def wrapper(*args, **kwargs):
            mem_args = [kwargs[key] for key in kw_keys if key in kwargs]
            mem_args = '__'.join(str(mem_arg) for mem_arg in mem_args)
            if not mem_args:
                return func(*args, **kwargs)
            if mem_args in cache:
                return cache[mem_args]
            result = func(*args, **kwargs)
            cache[mem_args] = result
            return result
        return wrapper
    return _decorator


def remove_project_cache(token):
    _PROJECT_CACHE.pop(token, None)


# Helper for figuring out keystone version
# Implementation will change when API version discovery is available
def get_keystone_version():
    return getattr(settings, 'OPENSTACK_API_VERSIONS', {}).get('identity', 2.0)


def get_session():
    insecure = getattr(settings, 'OPENSTACK_SSL_NO_VERIFY', False)
    verify = getattr(settings, 'OPENSTACK_SSL_CACERT', True)

    if insecure:
        verify = False

    return session.Session(verify=verify)


def get_keystone_client():
    if get_keystone_version() < 3:
        return client_v2
    else:
        return client_v3


def is_websso_enabled():
    """Websso is supported in Keystone version 3."""
    websso_enabled = getattr(settings, 'WEBSSO_ENABLED', False)
    keystonev3_plus = (get_keystone_version() >= 3)
    return websso_enabled and keystonev3_plus


def build_absolute_uri(request, relative_url):
    """Ensure absolute_uri are relative to WEBROOT."""
    webroot = getattr(settings, 'WEBROOT', '')
    if webroot.endswith("/") and relative_url.startswith("/"):
        webroot = webroot[:-1]

    return request.build_absolute_uri(webroot + relative_url)


def get_websso_url(request, auth_url, websso_auth):
    """Return the keystone endpoint for initiating WebSSO.

    Generate the keystone WebSSO endpoint that will redirect the user
    to the login page of the federated identity provider.

    Based on the authentication type selected by the user in the login
    form, it will construct the keystone WebSSO endpoint.

    :param request: Django http request object.
    :type request: django.http.HttpRequest
    :param auth_url: Keystone endpoint configured in the horizon setting.
                     The value is derived from:
                     - OPENSTACK_KEYSTONE_URL
                     - AVAILABLE_REGIONS
    :type auth_url: string
    :param websso_auth: Authentication type selected by the user from the
                        login form. The value is derived from the horizon
                        setting WEBSSO_CHOICES.
    :type websso_auth: string

    Example of horizon WebSSO setting::
        WEBSSO_CHOICES = (
            ("credentials", "Keystone Credentials"),
            ("oidc", "OpenID Connect"),
            ("saml2", "Security Assertion Markup Language"),
            ("acme_oidc", "ACME - OpenID Connect"),
            ("acme_saml2", "ACME - SAML2")
        )

        WEBSSO_IDP_MAPPING = {
            "acme_oidc": ("acme", "oidc"),
            "acme_saml2": ("acme", "saml2")
            }
        }

    The value of websso_auth will be looked up in the WEBSSO_IDP_MAPPING
    dictionary, if a match is found it will return a IdP specific WebSSO
    endpoint using the values found in the mapping.

    The value in WEBSSO_IDP_MAPPING is expected to be a tuple formatted as
    (<idp_id>, <protocol_id>). Using the values found, a IdP/protocol
    specific URL will be constructed:
        /auth/OS-FEDERATION/identity_providers/<idp_id>
        /protocols/<protocol_id>/websso

    If no value is found from the WEBSSO_IDP_MAPPING dictionary, it will
    treat the value as the global WebSSO protocol <protocol_id> and
    construct the WebSSO URL by:
        /auth/OS-FEDERATION/websso/<protocol_id>

    :returns: Keystone WebSSO endpoint.
    :rtype: string

    """
    origin = build_absolute_uri(request, '/auth/websso/')
    idp_mapping = getattr(settings, 'WEBSSO_IDP_MAPPING', {})
    idp_id, protocol_id = idp_mapping.get(websso_auth,
                                          (None, websso_auth))

    if idp_id:
        # Use the IDP specific WebSSO endpoint
        url = ('%s/auth/OS-FEDERATION/identity_providers/%s'
               '/protocols/%s/websso?origin=%s' %
               (auth_url, idp_id, protocol_id, origin))
    else:
        # If no IDP mapping found for the identifier,
        # perform WebSSO by protocol.
        url = ('%s/auth/OS-FEDERATION/websso/%s?origin=%s' %
               (auth_url, protocol_id, origin))

    return url


def has_in_url_path(url, sub):
    """Test if the `sub` string is in the `url` path."""
    scheme, netloc, path, query, fragment = urlparse.urlsplit(url)
    return sub in path


def url_path_replace(url, old, new, count=None):
    """Return a copy of url with replaced path.

    Return a copy of url with all occurrences of old replaced by new in the url
    path.  If the optional argument count is given, only the first count
    occurrences are replaced.
    """
    args = []
    scheme, netloc, path, query, fragment = urlparse.urlsplit(url)
    if count is not None:
        args.append(count)
    return urlparse.urlunsplit((
        scheme, netloc, path.replace(old, new, *args), query, fragment))


def fix_auth_url_version(auth_url):
    """Fix up the auth url if an invalid version prefix was given.

    People still give a v2 auth_url even when they specify that they want v3
    authentication. Fix the URL to say v3. This should be smarter and take the
    base, unversioned URL and discovery.
    """
    if get_keystone_version() >= 3:
        if has_in_url_path(auth_url, "/v2.0"):
            LOG.warning("The settings.py file points to a v2.0 keystone "
                        "endpoint, but v3 is specified as the API version "
                        "to use. Using v3 endpoint for authentication.")
            auth_url = url_path_replace(auth_url, "/v2.0", "/v3", 1)

    return auth_url


def get_token_auth_plugin(auth_url, token, project_id=None):
    if get_keystone_version() >= 3:
        return v3_auth.Token(auth_url=auth_url,
                             token=token,
                             project_id=project_id,
                             reauthenticate=False)

    else:
        return v2_auth.Token(auth_url=auth_url,
                             token=token,
                             tenant_id=project_id,
                             reauthenticate=False)


@memoize_by_keyword_arg(_PROJECT_CACHE, ('token', ))
def get_project_list(*args, **kwargs):
    is_federated = kwargs.get('is_federated', False)
    sess = kwargs.get('session') or get_session()
    auth_url = fix_auth_url_version(kwargs['auth_url'])
    auth = token_endpoint.Token(auth_url, kwargs['token'])
    client = get_keystone_client().Client(session=sess, auth=auth)

    if get_keystone_version() < 3:
        projects = client.tenants.list()
    elif is_federated:
        projects = client.federation.projects.list()
    else:
        projects = client.projects.list(user=kwargs.get('user_id'))

    projects.sort(key=lambda project: project.name.lower())
    return projects


def default_services_region(service_catalog, request=None):
    """Returns the first endpoint region for first non-identity service.

    Extracted from the service catalog.
    """
    if service_catalog:
        available_regions = [get_endpoint_region(endpoint) for service
                             in service_catalog for endpoint
                             in service.get('endpoints', [])
                             if (service.get('type') is not None
                                 and service.get('type') != 'identity')]
        if not available_regions:
            # this is very likely an incomplete keystone setup
            LOG.warning('No regions could be found excluding identity.')
            available_regions = [get_endpoint_region(endpoint) for service
                                 in service_catalog for endpoint
                                 in service.get('endpoints', [])]

            if not available_regions:
                # if there are no region setup for any service endpoint,
                # this is a critical problem and it's not clear how this occurs
                LOG.error('No regions can be found in the service catalog.')
                return None

        selected_region = None
        if request:
            selected_region = request.COOKIES.get('services_region',
                                                  available_regions[0])
        if selected_region not in available_regions:
            selected_region = available_regions[0]
        return selected_region
    return None


def set_response_cookie(response, cookie_name, cookie_value):
    """Common function for setting the cookie in the response.

    Provides a common policy of setting cookies for last used project
    and region, can be reused in other locations.

    This method will set the cookie to expire in 365 days.
    """
    now = timezone.now()
    expire_date = now + datetime.timedelta(days=365)
    response.set_cookie(cookie_name, cookie_value, expires=expire_date)


def get_endpoint_region(endpoint):
    """Common function for getting the region from endpoint.

    In Keystone V3, region has been deprecated in favor of
    region_id.

    This method provides a way to get region that works for both
    Keystone V2 and V3.
    """
    return endpoint.get('region_id') or endpoint.get('region')
