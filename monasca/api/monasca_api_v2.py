# Copyright 2013 IBM Corp
#
# Author: Tong Li <litong01@us.ibm.com>
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

from monasca.common import resource_api
from monasca.openstack.common import log


LOG = log.getLogger(__name__)


class V2API(object):
    def __init__(self, global_conf):
        LOG.debug('initializing V2API!')
        self.global_conf = global_conf

    @resource_api.Restify('/v2.0/metrics', method='get')
    def do_get_metrics(self, req, res):
        res.status = '501 Not Implemented'

    @resource_api.Restify('/v2.0/metrics/', method='post')
    def do_post_metrics(self, req, res):
        res.status = '501 Not Implemented'

    @resource_api.Restify('/{version_id}', method='get')
    def do_get_version(self, req, res, version_id):
        res.status = '501 Not Implemented'

    @resource_api.Restify('/v2.0/metrics/measurements', method='get')
    def do_get_measurements(self, req, res):
        res.status = '501 Not Implemented'

    @resource_api.Restify('/v2.0/metrics/statistics', method='get')
    def do_get_statistics(self, req, res):
        res.status = '501 Not Implemented'
