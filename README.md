### gmetrics-exporter

Prometheus exporter for GlusterFS metrics from [/var/run/gluster/metrics/](https://docs.gluster.org/en/latest/release-notes/4.0.0/#2-monitoring-support).

Inspired and based on [amarts/glustermetrics](https://github.com/amarts/glustermetrics).

And looking forward to https://github.com/gluster/gluster-prometheus/issues/25 be resolved.

# Installation Process

On GlusterFS machines:
- python
- pip install prometheus_client

Run the exporter:

```
# python gmetrics-exporter.py
```

# Configurations
To customize the gmetrics-exporter, create a config file and override the settings

        [settings]
        interval=10
        enabled_metrics=local_i0

And call `gmetrics-exporter.py` using,

```
# python gmetrics.py -c /root/gmetrics-exporter.conf
```

Configuration change will be detected automatically by `gmetrics-exporter.py`, config
file can be edited as required.

The only one option for `enabled_metrics` available at the moment:

```
    "local_io"
```
