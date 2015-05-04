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
import uuid

from django.utils import datetime_safe
from keystoneclient import access
from keystoneclient import service_catalog
from keystoneclient.v3 import domains
from keystoneclient.v3 import projects
from keystoneclient.v3 import roles
from keystoneclient.v3 import users
import requests


class TestDataContainer(object):
    """Arbitrary holder for test data in an object-oriented fashion."""
    pass


class TestResponse(requests.Response):
    """Class used to wrap requests.Response.

    It also provides some convenience to initialize with a dict.
    """

    def __init__(self, data):
        self._text = None
        super(TestResponse, self)
        if isinstance(data, dict):
            self.status_code = data.get('status_code', 200)
            self.headers = data.get('headers', None)
            # Fake the text attribute to streamline Response creation
            self._text = data.get('text', None)
        else:
            self.status_code = data

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    @property
    def text(self):
        return self._text


def generate_test_data():
    '''Builds a set of test_data data as returned by Keystone V2.'''
    test_data = TestDataContainer()

    keystone_service = {
        'type': 'identity',
        'id': uuid.uuid4().hex,
        'endpoints': [
            {
                'url': 'http://admin.localhost:35357/v3',
                'region': 'RegionOne',
                'interface': 'admin',
                'id': uuid.uuid4().hex,
            },
            {
                'url': 'http://internal.localhost:5000/v3',
                'region': 'RegionOne',
                'interface': 'internal',
                'id': uuid.uuid4().hex
            },
            {
                'url': 'http://public.localhost:5000/v3',
                'region': 'RegionOne',
                'interface': 'public',
                'id': uuid.uuid4().hex
            }
        ]
    }

    # Domains
    domain_dict = {'id': uuid.uuid4().hex,
                   'name': 'domain',
                   'description': '',
                   'enabled': True}
    test_data.domain = domains.Domain(domains.DomainManager(None),
                                      domain_dict, loaded=True)

    # Users
    user_dict = {'id': uuid.uuid4().hex,
                 'name': 'gabriel',
                 'email': 'gabriel@example.com',
                 'password': 'swordfish',
                 'domain_id': domain_dict['id'],
                 'token': '',
                 'enabled': True}
    test_data.user = users.User(users.UserManager(None),
                                user_dict, loaded=True)

    # Projects
    project_dict_1 = {'id': uuid.uuid4().hex,
                      'name': 'tenant_one',
                      'description': '',
                      'domain_id': domain_dict['id'],
                      'enabled': True}
    project_dict_2 = {'id': uuid.uuid4().hex,
                      'name': 'tenant_two',
                      'description': '',
                      'domain_id': domain_dict['id'],
                      'enabled': False}
    test_data.project_one = projects.Project(projects.ProjectManager(None),
                                             project_dict_1,
                                             loaded=True)
    test_data.project_two = projects.Project(projects.ProjectManager(None),
                                             project_dict_2,
                                             loaded=True)

    # Roles
    role_dict = {'id': uuid.uuid4().hex,
                 'name': 'Member'}
    test_data.role = roles.Role(roles.RoleManager, role_dict)

    nova_service = {
        'type': 'compute',
        'id': uuid.uuid4().hex,
        'endpoints': [
            {
                'url': ('http://nova-admin.localhost:8774/v2.0/%s'
                        % (project_dict_1['id'])),
                'region': 'RegionOne',
                'interface': 'admin',
                'id': uuid.uuid4().hex,
            },
            {
                'url': ('http://nova-internal.localhost:8774/v2.0/%s'
                        % (project_dict_1['id'])),
                'region': 'RegionOne',
                'interface': 'internal',
                'id': uuid.uuid4().hex
            },
            {
                'url': ('http://nova-public.localhost:8774/v2.0/%s'
                        % (project_dict_1['id'])),
                'region': 'RegionOne',
                'interface': 'public',
                'id': uuid.uuid4().hex
            },
            {
                'url': ('http://nova2-admin.localhost:8774/v2.0/%s'
                        % (project_dict_1['id'])),
                'region': 'RegionTwo',
                'interface': 'admin',
                'id': uuid.uuid4().hex,
            },
            {
                'url': ('http://nova2-internal.localhost:8774/v2.0/%s'
                        % (project_dict_1['id'])),
                'region': 'RegionTwo',
                'interface': 'internal',
                'id': uuid.uuid4().hex
            },
            {
                'url': ('http://nova2-public.localhost:8774/v2.0/%s'
                        % (project_dict_1['id'])),
                'region': 'RegionTwo',
                'interface': 'public',
                'id': uuid.uuid4().hex
            }
        ]
    }

    # Tokens
    tomorrow = datetime_safe.datetime.now() + datetime.timedelta(days=1)
    expiration = datetime_safe.datetime.isoformat(tomorrow)
    auth_token = uuid.uuid4().hex
    auth_response_headers = {
        'X-Subject-Token': auth_token
    }

    auth_response = TestResponse({
        "headers": auth_response_headers
    })

    scoped_token_dict = {
        'token': {
            'methods': ['password'],
            'expires_at': expiration,
            'project': {
                'id': project_dict_1['id'],
                'name': project_dict_1['name'],
                'domain': {
                    'id': domain_dict['id'],
                    'name': domain_dict['name']
                }
            },
            'user': {
                'id': user_dict['id'],
                'name': user_dict['name'],
                'domain': {
                    'id': domain_dict['id'],
                    'name': domain_dict['name']
                }
            },
            'roles': [role_dict],
            'catalog': [keystone_service, nova_service]
        }
    }

    test_data.scoped_access_info = access.AccessInfo.factory(
        resp=auth_response,
        body=scoped_token_dict
    )

    unscoped_token_dict = {
        'token': {
            'methods': ['password'],
            'expires_at': expiration,
            'user': {
                'id': user_dict['id'],
                'name': user_dict['name'],
                'domain': {
                    'id': domain_dict['id'],
                    'name': domain_dict['name']
                }
            },
            'catalog': [keystone_service]
        }
    }

    test_data.unscoped_access_info = access.AccessInfo.factory(
        resp=auth_response,
        body=unscoped_token_dict
    )

    # Service Catalog
    test_data.service_catalog = service_catalog.ServiceCatalog.factory({
        'methods': ['password'],
        'user': {},
        'catalog': [keystone_service, nova_service],
    }, token=auth_token)

    # federated user
    federated_scoped_token_dict = {
        'token': {
            'methods': ['password'],
            'expires_at': expiration,
            'project': {
                'id': project_dict_1['id'],
                'name': project_dict_1['name'],
                'domain': {
                    'id': domain_dict['id'],
                    'name': domain_dict['name']
                }
            },
            'user': {
                'id': user_dict['id'],
                'name': user_dict['name'],
                'domain': {
                    'id': domain_dict['id'],
                    'name': domain_dict['name']
                },
                'OS-FEDERATION': {
                    'identity_provider': 'ACME',
                    'protocol': 'OIDC',
                    'groups': [
                        {'id': uuid.uuid4().hex},
                        {'id': uuid.uuid4().hex}
                    ]
                }
            },
            'roles': [role_dict],
            'catalog': [keystone_service, nova_service]
        }
    }

    test_data.federated_scoped_access_info = access.AccessInfo.factory(
        resp=auth_response,
        body=federated_scoped_token_dict
    )

    federated_unscoped_token_dict = {
        'token': {
            'methods': ['password'],
            'expires_at': expiration,
            'user': {
                'id': user_dict['id'],
                'name': user_dict['name'],
                'domain': {
                    'id': domain_dict['id'],
                    'name': domain_dict['name']
                },
                'OS-FEDERATION': {
                    'identity_provider': 'ACME',
                    'protocol': 'OIDC',
                    'groups': [
                        {'id': uuid.uuid4().hex},
                        {'id': uuid.uuid4().hex}
                    ]
                }
            },
            'catalog': [keystone_service]
        }
    }

    test_data.federated_unscoped_access_info = access.AccessInfo.factory(
        resp=auth_response,
        body=federated_unscoped_token_dict
    )

    return test_data
