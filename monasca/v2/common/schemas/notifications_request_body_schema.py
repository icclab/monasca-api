# Copyright 2014 Hewlett-Packard
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from voluptuous import Schema
from voluptuous import Optional, Required, Any, All, Length
from monasca.openstack.common import log
from monasca.v2.common.schemas import exceptions

LOG = log.getLogger(__name__)

notification_schema = {
    Required('name'): Schema(All(Any(str, unicode), Length(max=250))),
    Required('type'): Schema(Any("EMAIL", "email")),
    Required('address'): Schema(All(Any(str, unicode), Length(max=100)))
}

request_body_schema = Schema(Any(notification_schema))


def validate(msg):
    try:
        request_body_schema(msg)
    except Exception as ex:
        LOG.debug(ex)
        raise exceptions.ValidationException(str(ex))
