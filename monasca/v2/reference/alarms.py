# Copyright 2014 Hewlett-Packard
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json
import re

import falcon
from oslo.config import cfg

from monasca.api.alarms_api_v2 import AlarmsV2API
from monasca.common.repositories import exceptions
from monasca.common import resource_api
from monasca.openstack.common import log
from monasca.v2.reference.alarming import Alarming
from monasca.v2.reference import helpers
from monasca.v2.reference.resource import resource_try_catch_block


LOG = log.getLogger(__name__)


class Alarms(AlarmsV2API, Alarming):

    def __init__(self, global_conf):

        try:

            super(Alarms, self).__init__(global_conf)

            self._region = cfg.CONF.region

            self._default_authorized_roles = (
                cfg.CONF.security.default_authorized_roles)
            self._delegate_authorized_roles = (
                cfg.CONF.security.delegate_authorized_roles)
            self._post_metrics_authorized_roles = (
                cfg.CONF.security.default_authorized_roles +
                cfg.CONF.security.agent_authorized_roles)

            self._alarms_repo = resource_api.init_driver(
                'monasca.repositories', cfg.CONF.repositories.alarms_driver)

            self._metrics_repo = resource_api.init_driver(
                'monasca.repositories', cfg.CONF.repositories.metrics_driver)

        except Exception as ex:
            LOG.exception(ex)
            raise exceptions.RepositoryException(ex)

    @resource_api.Restify('/v2.0/alarms/{id}', method='put')
    def do_put_alarms(self, req, res, id):

        helpers.validate_authorization(req, self._default_authorized_roles)

        result = ''

        res.body = json.dumps(result, ensure_ascii=False).encode('utf8')
        res.status = falcon.HTTP_200
        res.status = '501 Not Implemented'

    @resource_api.Restify('/v2.0/alarms/{id}', method='patch')
    def do_patch_alarms(self, req, res, id):

        helpers.validate_authorization(req, self._default_authorized_roles)

        result = ''
        res.body = json.dumps(result, ensure_ascii=False).encode('utf8')
        res.status = falcon.HTTP_200
        res.status = '501 Not Implemented'

    @resource_api.Restify('/v2.0/alarms/{id}', method='delete')
    def do_delete_alarms(self, req, res, id):

        helpers.validate_authorization(req, self._default_authorized_roles)

        tenant_id = helpers.get_tenant_id(req)

        self._alarm_delete(tenant_id, id)

        res.status = falcon.HTTP_204

    @resource_api.Restify('/v2.0/alarms', method='get')
    def do_get_alarms(self, req, res):

        helpers.validate_authorization(req, self._default_authorized_roles)
        tenant_id = helpers.get_tenant_id(req)

        query_parms = falcon.uri.parse_query_string(req.query_string)

        result = self._alarm_list(req.uri, tenant_id, query_parms)

        res.body = json.dumps(result, ensure_ascii=False).encode('utf8')
        res.status = falcon.HTTP_200

    @resource_api.Restify('/v2.0/alarms/{id}', method='get')
    def do_get_alarm_by_id(self, req, res, id):

        # Necessary because falcon interprets 'state-history' as an
        # alarm id, and this url masks '/v2.0/alarms/state-history'.
        if id.lower() == 'state-history':
            return self.do_get_alarms_state_history(req, res)

        helpers.validate_authorization(req, self._default_authorized_roles)
        tenant_id = helpers.get_tenant_id(req)

        result = self._alarm_show(req.uri, tenant_id, id)

        res.body = json.dumps(result, ensure_ascii=False).encode('utf8')
        res.status = falcon.HTTP_200

    @resource_api.Restify('/v2.0/alarms/state-history', method='get')
    def do_get_alarms_state_history(self, req, res):

        helpers.validate_authorization(req, self._default_authorized_roles)
        tenant_id = helpers.get_tenant_id(req)
        start_timestamp = helpers.get_query_starttime_timestamp(req, False)
        end_timestamp = helpers.get_query_endtime_timestamp(req, False)
        query_parms = falcon.uri.parse_query_string(req.query_string)

        result = self._alarm_history_list(tenant_id, start_timestamp,
                                          end_timestamp, query_parms)

        res.body = json.dumps(result, ensure_ascii=False).encode('utf8')
        res.status = falcon.HTTP_200

    @resource_api.Restify('/v2.0/alarms/{id}/state-history', method='get')
    def do_get_alarm_state_history(self, req, res, id):

        helpers.validate_authorization(req, self._default_authorized_roles)
        tenant_id = helpers.get_tenant_id(req)

        result = self._alarm_history(tenant_id, [id])

        res.body = json.dumps(result, ensure_ascii=False).encode('utf8')
        res.status = falcon.HTTP_200

    @resource_try_catch_block
    def _alarm_history_list(self, tenant_id, start_timestamp,
                            end_timestamp, query_parms):

        # get_alarms expects 'metric_dimensions' for dimensions key.
        if 'dimensions' in query_parms:
            new_query_parms = {'metric_dimensions': query_parms['dimensions']}
        else:
            new_query_parms = {}

        alarm_rows = self._alarms_repo.get_alarms(tenant_id, new_query_parms)
        alarm_id_list = [alarm_row['alarm_id'] for alarm_row in alarm_rows]

        return self._metrics_repo.alarm_history(tenant_id, alarm_id_list,
                                                start_timestamp, end_timestamp)

    @resource_try_catch_block
    def _alarm_history(self, tenant_id, alarm_id):

        return self._metrics_repo.alarm_history(tenant_id, alarm_id)

    @resource_try_catch_block
    def _alarm_delete(self, tenant_id, id):

        alarm_metric_rows = self._alarms_repo.get_alarm_metrics(id)
        sub_alarm_rows = self._alarms_repo.get_sub_alarms(tenant_id, id)

        self._alarms_repo.delete_alarm(tenant_id, id)

        # alarm_definition_id is the same for all rows.
        alarm_definition_id = sub_alarm_rows[0]['alarm_definition_id']

        self._send_alarm_deleted_event(tenant_id, alarm_definition_id,
                                       alarm_metric_rows, sub_alarm_rows)

    @resource_try_catch_block
    def _alarm_show(self, req_uri, tenant_id, id):

        alarm_rows = self._alarms_repo.get_alarm(tenant_id, id)

        first_row = True
        for alarm_row in alarm_rows:
            if first_row:
                ad = {u'id': alarm_row['alarm_definition_id'],
                      u'name': alarm_row['alarm_definition_name'],
                      u'severity': alarm_row['severity'], }
                helpers.add_links_to_resource(ad,
                                              re.sub('alarms',
                                                     'alarm-definitions',
                                                     req_uri),
                                              rel=None)

                metrics = []
                alarm = {u'id': alarm_row['alarm_id'], u'metrics': metrics,
                         u'state': alarm_row['state'],
                         u'alarm_definition': ad}
                helpers.add_links_to_resource(alarm, req_uri)

                first_row = False

            dimensions = {}
            metric = {u'name': alarm_row['metric_name'],
                      u'dimensions': dimensions}

            if alarm_row['metric_dimensions']:
                for dimension in alarm_row['metric_dimensions'].split(','):
                    parsed_dimension = dimension.split('=')
                    dimensions[parsed_dimension[0]] = parsed_dimension[1]

            metrics.append(metric)

        return alarm

    @resource_try_catch_block
    def _alarm_list(self, req_uri, tenant_id, query_parms):

        alarm_rows = self._alarms_repo.get_alarms(tenant_id, query_parms)

        result = []

        if not alarm_rows:
            return result

        # Forward declaration
        alarm = {}
        prev_alarm_id = None
        for alarm_row in alarm_rows:
            if prev_alarm_id != alarm_row['alarm_id']:
                if prev_alarm_id is not None:
                    result.append(alarm)

                ad = {u'id': alarm_row['alarm_definition_id'],
                      u'name': alarm_row['alarm_definition_name'],
                      u'severity': alarm_row['severity'], }
                helpers.add_links_to_resource(ad,
                                              re.sub('alarms',
                                                     'alarm-definitions',
                                                     req_uri),
                                              rel=None)

                metrics = []
                alarm = {u'id': alarm_row['alarm_id'], u'metrics': metrics,
                         u'state': alarm_row['state'],
                         u'alarm_definition': ad}
                helpers.add_links_to_resource(alarm, req_uri)

                prev_alarm_id = alarm_row['alarm_id']

            dimensions = {}
            metric = {u'name': alarm_row['metric_name'],
                      u'dimensions': dimensions}

            if alarm_row['metric_dimensions']:
                for dimension in alarm_row['metric_dimensions'].split(','):
                    parsed_dimension = dimension.split('=')
                    dimensions[parsed_dimension[0]] = parsed_dimension[1]

            metrics.append(metric)

        result.append(alarm)

        return result
