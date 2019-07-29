#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os, errno, socket, re
import glob
import time
import sys

from ConfigParser import ConfigParser
from argparse import ArgumentParser
from prometheus_client import start_http_server, Counter

METRICS_DIR = '/var/run/gluster/metrics/'

P_OPS_TOTAL = Counter('glusterfs_ops_total', 'operations per translator', ['volume','translator', 'operation'])
P_FOP_TOTAL = Counter('glusterfs_fop_total', 'total operations', ['volume','translator'])
P_MD_CACHE_STATUS = Counter('glusterfs_md_cache_status', 'md=cache hit and miss statistics', ['volume', 'operation', 'status'])
P_MD_CACHE_LOOKUP = Counter('glusterfs_md_cache_lookup', 'md-cache lookups statistics', ['volume', 'lookup'])
P_MD_CACHE_INVALIDATIONS_RECEIVED = Counter('glusterfs_md_cache_invalidations_received', 'md-cache invalidations received', ['volume', 'operation'])

# Available metrics and respective metrics collection functions
AVAILABLE_METRICS = [
    "local_io",
]

def to_strlist(value):
    value = value.strip()
    if value == "":
        return []

    value = value.split(",")
    return [v.strip() for v in value]


def to_int(value):
    return int(value)


# Typecast to desired type after reading from conf file
TYPECAST_MAP = {
    "enabled_metrics": to_strlist,
    "interval": to_int
}

# Section name in Conf file
CONF_SECT = "settings"


# Default Config when config file is not passed
DEFAULT_CONFIG = {
    "interval": 15,
    "enabled_metrics": AVAILABLE_METRICS,
}


class Config(object):
    def __init__(self, config_file=None):
        self.config_file = config_file
        self.conf = None
        self.load()
        self.prev_mtime = None

    def get(self, name, default_value=None):
        if self.config_file is None:
            return DEFAULT_CONFIG.get(name, default_value)

        if self.conf is None:
            return default_value

        if self.conf.has_option(CONF_SECT, name):
            val = self.conf.get(CONF_SECT, name)
            typecast_func = TYPECAST_MAP.get(name, None)
            if typecast_func is not None:
                return typecast_func(val)

            return val
        else:
            return default_value

    def load(self):
        if self.config_file is None:
            return

        self.conf = ConfigParser()
        with open(self.config_file) as f:
            self.conf.readfp(f)

        # Store mtime of conf file for future comparison
        self.prev_mtime = os.lstat(self.config_file).st_mtime

    def reload(self):
        if self.config_file is None:
            return False

        st_mtime = os.lstat(self.config_file).st_mtime
        if self.prev_mtime is None or st_mtime > self.prev_mtime:
            self.load()
            return True

        return False

def increment_prometheus_counter(counter, new_value):
    current_value = counter._value.get()
    increase = new_value - current_value
    counter.inc(increase)

def delete_gluster_dump_files():
    for gfile in glob.glob("%s/gmetrics.*" % METRICS_DIR):
        os.remove(gfile)

def local_io_metrics():

    os.system ("pgrep glusterfs | xargs kill -USR2")

    # Idea is to provide a second for application to dump metrics
    time.sleep(1)

    timestamp = time.time()
    metric_group_label = "io"

    for gfile in glob.glob("%s/gmetrics.*" % METRICS_DIR):
        all_metrics = {}
        with open(gfile) as f:
            proc_id = "(null)"
            for line in f:
                # Handle comments
                if "# glusterd" in line:
                    break

                if "### BrickName: " in line:
                    proc_id = line.split(":")[1].strip()
                    continue

                if "(null)" == proc_id and "### MountName: " in line:
                    proc_id = line.split(":")[1].strip()
                    continue

                if "#" == line[0]:
                    # trying to get volume name
                    volume_match = re.search("(?<=\#\ debug\/io-stats\.).*(?=\.total\.num_types\ .*)", line)
                    if volume_match:
                        volume_name = volume_match.group()
                    continue

                data = line.split(" ")
                if len(data) < 2:
                    break

                key = data[0].strip()
                value = data[1].strip()
                all_metrics[key] = str(value)

        # Remove the file, so there won't be a repeat
        os.remove(gfile)

        # let's find all needed metrics with regular expressions
        for k in all_metrics:
            # gl1-client-3.total.GETXATTR.count
            r = re.search(volume_name + "\-([a-zA-Z0-9\-]+)\.total\.([a-zA-Z0-9\-]+)\.count", k)
            if r:
                translator = r.group(1)
                operation = r.group(2)
                increment_prometheus_counter(P_OPS_TOTAL.labels(volume_name, translator, operation), int(all_metrics[k]))
                continue

            # meta-autoload.total.READDIRP.count
            r = re.search("([a-zA-Z0-9\-]+)\.total\.([a-zA-Z0-9\-]+)\.count", k)
            if r:
                translator = r.group(1)
                operation = r.group(2)
                increment_prometheus_counter(P_OPS_TOTAL.labels(volume_name, translator, operation), int(all_metrics[k]))
                continue

            # gl1-client-4.total.fop-count
            r = re.search(volume_name + "\-([a-zA-Z0-9\-]+)\.total\.fop\-count", k)
            if r:
                translator = r.group(1)
                increment_prometheus_counter(P_FOP_TOTAL.labels(volume_name, translator), int(all_metrics[k]))
                continue

            # meta-autoload.total.fop-count
            r = re.search("([a-zA-Z0-9\-]+)\.total\.fop\-count", k)
            if r:
                translator = r.group(1)
                increment_prometheus_counter(P_FOP_TOTAL.labels(volume_name, translator), int(all_metrics[k]))
                continue

            # gl1-md-cache.xattr_cache_miss_count
            r = re.search(volume_name + "\-md\-cache\.([a-zA-Z0-9\_]+)_cache_([a-zA-Z_]+)_count", k)
            if r:
                operation = r.group(1)
                status = r.group(2)
                increment_prometheus_counter(P_MD_CACHE_STATUS.labels(volume_name, operation, status), int(all_metrics[k]))
                continue

            # gl1-md-cache.negative_lookup_count
            r = re.search(volume_name + "\-md\-cache\.([a-zA-Z0-9\_]+_lookup)_count", k)
            if r:
                lookup_type = r.group(1)
                increment_prometheus_counter(P_MD_CACHE_LOOKUP.labels(volume_name, lookup_type), int(all_metrics[k]))
                continue

            # gl1-md-cache.xattr_cache_invalidations_received
            r = re.search(volume_name + "\-md\-cache\.([a-zA-Z0-9\_]+)_cache_invalidations_received", k)
            if r:
                operation = r.group(1)
                increment_prometheus_counter(P_MD_CACHE_INVALIDATIONS_RECEIVED.labels(volume_name, operation), int(all_metrics[k]))
                continue

            # everything else is skipped


def main():
    # Arguments Handling
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--config-file", help="Config File")
    parser.add_argument("--exporter-port",
                        help="Exporter port",
                        default=9622,
                        type=int)
    parser.add_argument("--exporter-addr",
                        help="Address the exporter will bind on",
                        default="0.0.0.0")
    args = parser.parse_args()

    # Load Config File
    conf = Config(args.config_file)

    enabled_metrics = conf.get("enabled_metrics")
    # If enabled_metrics list is empty enable all metrics
    if not enabled_metrics:
        enabled_metrics = AVAILABLE_METRICS

    # Create the metrics dir in which all the metrics would be dumped
    try:
        os.mkdir(METRICS_DIR)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    delete_gluster_dump_files()

    start_http_server(args.exporter_port, args.exporter_addr)

    # Metrics collection Loop
    while True:
        # Reloads only if config file is modified
        if conf.reload():
            print "Reloaded Config file"
            # If Config is reloaded, get enabled metrics list again
            enabled_metrics = conf.get("enabled_metrics")
            # If enabled_metrics list is empty enable all metrics
            if not enabled_metrics:
                enabled_metrics = AVAILABLE_METRICS

        # TODO: Not yet Parallel to collect different metrics
        for m in enabled_metrics:
            metrics_func = globals().get(m + "_metrics", None)
            if metrics_func is not None:
                metrics_func()

        # Sleep till next collection interval
        time.sleep(conf.get("interval", 15))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print "Exiting.."
        delete_gluster_dump_files()
        sys.exit(1)
