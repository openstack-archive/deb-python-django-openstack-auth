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

from django.conf.urls import url

from openstack_auth import utils
from openstack_auth import views

utils.patch_middleware_get_user()


urlpatterns = [
    url(r"^login/$", views.login, name='login'),
    url(r"^logout/$", views.logout, name='logout'),
    url(r'^switch/(?P<tenant_id>[^/]+)/$', views.switch,
        name='switch_tenants'),
    url(r'^switch_services_region/(?P<region_name>[^/]+)/$',
        views.switch_region,
        name='switch_services_region')
]

if utils.is_websso_enabled():
    urlpatterns.append(url(r"^websso/$", views.websso, name='websso'))
