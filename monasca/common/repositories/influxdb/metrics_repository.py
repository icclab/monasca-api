# -*- coding: utf8 -*-
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
import time
import urllib

from influxdb import client
from oslo.config import cfg

from monasca.common.repositories import constants
from monasca.common.repositories import exceptions
from monasca.common.repositories import metrics_repository
from monasca.openstack.common import log


LOG = log.getLogger(__name__)


class MetricsRepository(metrics_repository.MetricsRepository):

    def __init__(self):

        try:
            self.conf = cfg.CONF
            self.influxdb_client = client.InfluxDBClient(
                self.conf.influxdb.ip_address, self.conf.influxdb.port,
                self.conf.influxdb.user, self.conf.influxdb.password,
                self.conf.influxdb.database_name)

            # compile regex only once for efficiency
            self._serie_name_reqex = re.compile(
                '([^?&=]+)\?([^?&=]+)&([^?&=]+)(&[^?&=]+=[^?&=]+)*')
            self._serie_tenant_id_region_name_regex = re.compile(
                '[^?&=]+\?[^?&=]+&[^?&=]+')
            self._serie_name_dimension_regex = re.compile('&[^?&=]+=[^?&=]+')
            self._serie_name_dimension_parts_regex = re.compile(
                '&([^?&=]+)=([^?&=]+)')

        except Exception as ex:
            LOG.exception()
            raise exceptions.RepositoryException(ex)

    def _build_list_series_query(self, dimensions, name, tenant_id, region):

        from_clause = self._build_from_clause(dimensions, name, tenant_id,
                                              region)

        query = 'list series ' + from_clause

        return query

    def _build_select_query(self, dimensions, name, tenant_id,
                            region, start_timestamp, end_timestamp, offset):

        from_clause = self._build_from_clause(dimensions, name, tenant_id,
                                              region, start_timestamp,
                                              end_timestamp)

        offset_clause = self._build_offset_clause(offset)

        query = 'select * ' + from_clause + offset_clause

        return query

    def _build_statistics_query(self, dimensions, name, tenant_id,
                                region, start_timestamp, end_timestamp,
                                statistics, period):

        from_clause = self._build_from_clause(dimensions, name, tenant_id,
                                              region, start_timestamp,
                                              end_timestamp)

        statistics = [statistic.replace('avg', 'mean') for statistic in
                      statistics]
        statistics = [statistic + '(value)' for statistic in statistics]

        statistic_string = ",".join(statistics)

        query = 'select ' + statistic_string + ' ' + from_clause

        if period is None:
            period = str(300)

        query += " group by time(" + period + "s)"

        return query

    def _build_from_clause(self, dimensions, name, tenant_id, region,
                           start_timestamp=None, end_timestamp=None):

        from_clause = 'from /^'

        # tenant id
        from_clause += urllib.quote(tenant_id.encode('utf8'), safe='')

        # region
        from_clause += '\?' + urllib.quote(region.encode('utf8'), safe='')

        # name - optional
        if name:
            from_clause += '&' + urllib.quote(name.encode('utf8'), safe='')
            from_clause += '(&|$)'

        # dimensions - optional
        if dimensions:
            for dimension_name, dimension_value in iter(
                    sorted(dimensions.iteritems())):
                from_clause += '(.*&)*'
                from_clause += urllib.quote(dimension_name.encode('utf8'),
                                            safe='')
                from_clause += '='
                from_clause += urllib.quote(dimension_value.encode('utf8'),
                                            safe='')
                from_clause += '(&|$)'

        from_clause += '/'

        if start_timestamp is not None:
            # subtract 1 from timestamp to get >= semantics
            from_clause += " where time > " + str(start_timestamp - 1) + "s"
            if end_timestamp is not None:
                # add 1 to timestamp to get <= semantics
                from_clause += " and time < " + str(end_timestamp + 1) + "s"

        return from_clause

    def list_metrics(self, tenant_id, region, name, dimensions, offset):

        try:

            query = self._build_list_series_query(dimensions, name, tenant_id,
                                                  region)

            result = self.influxdb_client.query(query, 's')

            json_metric_list = self._decode_influxdb_serie_name_list(result,
                                                                     offset)

            return json_metric_list

        except Exception as ex:
            LOG.exception(ex)
            raise exceptions.RepositoryException(ex)

    def _decode_influxdb_serie_name_list(self, series_names, offset):

        """Example series_names from InfluxDB.

        [
          {
            "points": [
              [
                0,
                "tenant?useast&%E5%8D%83&dim1=%E5%8D%83&dim2=%E5%8D%83"
              ]
            ],
            "name": "list_series_result",
            "columns": [
              "time",
              "name"
            ]
          }
        ]


        :param series_names:
        :return:
        """

        json_metric_list = []
        serie_names_list_list = series_names[0]['points']
        for serie_name_list in serie_names_list_list:
            serie_name = serie_name_list[1]
            if offset is not None:
                if serie_name < urllib.unquote(offset):
                    continue
            metric = self._decode_influxdb_serie_name(serie_name)
            if metric is None:
                continue
            json_metric_list.append(metric)

            if offset is not None:
                if len(json_metric_list) >= constants.PAGE_LIMIT:
                    break

        return json_metric_list

    def _decode_influxdb_serie_name(self, serie_name):

        """Decodes a serie name from InfluxDB.

        The raw serie name is
        formed by url encoding the tenant id, region, name, and dimensions,
        and concatenating them into a quasi URL query string.

        urlencode(tenant)?urlencode(region)&urlencode(name)[&urlencode(
        dim_name)=urlencode(dim_value)]...


        :param serie_name:
        :return:
        """

        match = self._serie_name_reqex.match(serie_name)
        if match:

            # throw tenant_id (match.group(1) and region (match.group(2) away

            metric_name = (
                urllib.unquote_plus(match.group(3).encode(
                    'utf8')).decode('utf8'))

            metric = {u'name': metric_name,
                      u'id': urllib.quote(serie_name)}

            # only returns the last match. we need all dimensions.
            dimensions = match.group(4)
            if dimensions:
                # remove the name, tenant_id, and region; just
                # dimensions remain
                dimensions_part = self._serie_tenant_id_region_name_regex.sub(
                    '', serie_name)
                dimensions = {}
                dimension_list = self._serie_name_dimension_regex.findall(
                    dimensions_part)
                for dimension in dimension_list:
                    match = self._serie_name_dimension_parts_regex.match(
                        dimension)
                    dimension_name = urllib.unquote(
                        match.group(1).encode('utf8')).decode('utf8')
                    dimension_value = urllib.unquote(
                        match.group(2).encode('utf8')).decode('utf8')
                    dimensions[dimension_name] = dimension_value

                metric["dimensions"] = dimensions
        else:
            metric = None

        return metric

    def measurement_list(self, tenant_id, region, name, dimensions,
                         start_timestamp,
                         end_timestamp, offset):
        """Example result from InfluxDB.

        [
          {
            "points": [
              [
                1413230362,
                5369370001,
                99.99
              ]
            ],
            "name": "tenant?useast&%E5%8D%83&dim1=%E5%8D%83&dim2
            =%E5%8D%83",
            "columns": [
              "time",
              "sequence_number",
              "value"
            ]
          }
        ]

        After url decoding the result would look like this. In this example
        the name, dim1 value, and dim2 value were non-ascii chars.

        [
          {
            "points": [
              [
                1413230362,
                5369370001,
                99.99
              ]
            ],
            "name": "tenant?useast&千&dim1=千&dim2=千",
            "columns": [
              "time",
              "sequence_number",
              "value"
            ]
          }
        ]

        :param tenant_id:
        :param name:
        :param dimensions:
        :return:
        """

        json_measurement_list = []

        try:
            query = self._build_select_query(dimensions, name, tenant_id,
                                             region, start_timestamp,
                                             end_timestamp, offset)

            try:
                result = self.influxdb_client.query(query, 's')
            except client.InfluxDBClientError as ex:
                # check for non-existent serie name.
                msg = "Couldn't look up columns"
                if ex.code == 400 and ex.content == (msg):
                    return json_measurement_list
                else:
                    raise ex

            for serie in result:

                metric = self._decode_influxdb_serie_name(serie['name'])

                if metric is None:
                    continue

                # Replace 'sequence_number' -> 'id' for column name
                columns = [column.replace('sequence_number', 'id') for column
                           in serie['columns']]
                # Replace 'time' -> 'timestamp' for column name
                columns = [column.replace('time', 'timestamp') for column in
                           columns]

                # format the utc date in the points
                fmtd_pts = [[time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                           time.gmtime(point[0])), point[1],
                             point[2]] for point in serie['points']]

                # Set the last point's time as the id. Used for next link.
                measurement = {u"name": metric['name'],
                               u"id": serie['points'][-1][0],
                               u"dimensions": metric['dimensions'],
                               u"columns": columns,
                               u"measurements": fmtd_pts}

                json_measurement_list.append(measurement)

            return json_measurement_list

        except Exception as ex:
            LOG.exception(ex)
            raise exceptions.RepositoryException(ex)

    def metrics_statistics(self, tenant_id, region, name, dimensions,
                           start_timestamp,
                           end_timestamp, statistics, period):

        json_statistics_list = []

        try:
            query = self._build_statistics_query(dimensions, name, tenant_id,
                                                 region,
                                                 start_timestamp,
                                                 end_timestamp, statistics,
                                                 period)

            try:
                result = self.influxdb_client.query(query, 's')
            except client.InfluxDBClientError as ex:
                # check for non-existent serie name.
                msg = "Couldn't look up columns"
                if ex.code == 400 and ex.content == (msg):
                    return json_statistics_list
                else:
                    raise ex

            for serie in result:

                metric = self._decode_influxdb_serie_name(serie['name'])

                if metric is None:
                    continue

                # Replace 'avg' -> 'mean' for column name
                columns = [column.replace('mean', 'avg') for column in
                           serie['columns']]
                # Replace 'time' -> 'timestamp' for column name
                columns = [column.replace('time', 'timestamp') for column in
                           columns]

                fmtd_pts_list_list = [[time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                     time.gmtime(pts_list[
                                                         0]))] + pts_list[1:]
                                      for pts_list in serie['points']]

                measurement = {"name": metric['name'],
                               "dimensions": metric['dimensions'],
                               "columns": columns,
                               "measurements": fmtd_pts_list_list}

                json_statistics_list.append(measurement)

            return json_statistics_list

        except Exception as ex:
            LOG.exception(ex)
            raise exceptions.RepositoryException(ex)

    def _build_offset_clause(self, offset):

        if offset is not None:

            # If offset is not empty.
            if offset:

                offset_clause = (
                    ' and time < {}s limit {}'.
                    format(offset, str(constants.PAGE_LIMIT)))
            else:

                offset_clause = ' limit {}'.format(str(
                    constants.PAGE_LIMIT))

        else:

            offset_clause = ''

        return offset_clause

    def alarm_history(self, tenant_id, alarm_id_list,
                      offset, start_timestamp=None,
                      end_timestamp=None):
        """Example result from Influxdb.

        [
            {
                "points": [
                    [
                        1415894490,
                        272140001,
                        "6ac10841-d02f-4f7d-a191-ae0a3d9a25f2",
                        "[{\"name\": \"cpu.system_perc\", \"dimensions\": {
                        \"hostname\": \"mini-mon\", \"component\":
                        \"monasca-agent\", \"service\": \"monitoring\"}},
                        {\"name\": \"load.avg_1_min\", \"dimensions\": {
                        \"hostname\": \"mini-mon\", \"component\":
                        \"monasca-agent\", \"service\": \"monitoring\"}}]",
                        "ALARM",
                        "OK",
                        "Thresholds were exceeded for the sub-alarms: [max(
                        load.avg_1_min{hostname=mini-mon}) > 0.0,
                        max(cpu.system_perc) > 0.0]",
                        "{}"
                    ],
                ],
                "name": "alarm_state_history",
                "columns": [
                    "time",
                    "sequence_number",
                    "alarm_id",
                    "metrics",
                    "new_state",
                    "old_state",
                    "reason",
                    "reason_data"
                ]
            }
        ]

        :param tenant_id:
        :param alarm_id:
        :return:
        """

        try:

            json_alarm_history_list = []

            if not alarm_id_list:
                return json_alarm_history_list

            for alarm_id in alarm_id_list:
                if '\'' in alarm_id or ';' in alarm_id:
                    raise Exception(
                        "Input from user contains single quote ['] or "
                        "semi-colon [;] characters[ {} ]".format(alarm_id))

            query = """
              select alarm_id, metrics, old_state, new_state,
                     reason, reason_data
              from alarm_state_history
              """

            where_clause = (
                " where tenant_id = '{}' ".format(tenant_id.encode('utf8')))

            alarm_id_where_clause_list = (
                [" alarm_id = '{}' ".format(id.encode('utf8'))
                    for id in alarm_id_list])

            alarm_id_where_clause = " or ".join(alarm_id_where_clause_list)

            where_clause += ' and (' + alarm_id_where_clause + ')'

            time_clause = ''
            if start_timestamp:
                # subtract 1 from timestamp to get >= semantics
                time_clause += " and time > " + str(start_timestamp - 1) + "s"
            if end_timestamp:
                # add 1 to timestamp to get <= semantics
                time_clause += " and time < " + str(end_timestamp + 1) + "s"

            offset_clause = self._build_offset_clause(offset)

            query += where_clause + time_clause + offset_clause

            try:
                result = self.influxdb_client.query(query, 's')
            except client.InfluxDBClientError as ex:
                # check for non-existent serie name. only happens
                # if alarm_state_history serie does not exist.
                msg = "Couldn't look up columns"
                if ex.code == 400 and ex.content == (msg):
                    return json_alarm_history_list
                else:
                    raise ex

            if not result:
                return json_alarm_history_list

            # There's only one serie, alarm_state_history.
            for point in result[0]['points']:
                alarm_point = {u'alarm_id': point[2],
                               u'metrics': json.loads(point[3]),
                               u'old_state': point[4], u'new_state': point[5],
                               u'reason': point[6], u'reason_data': point[7],
                               u'timestamp': time.strftime(
                                   "%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime(point[0])),
                               u'id': point[0]}

                json_alarm_history_list.append(alarm_point)

            return json_alarm_history_list

        except Exception as ex:
            LOG.exception(ex)
            raise exceptions.RepositoryException(ex)