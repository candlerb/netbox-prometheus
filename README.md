# Netbox Prometheus configuration generator

This script generates targets files for prometheus from devices and VMs in
the Netbox database.  Example:

```
# Auto-generated from Netbox, do not edit as your changes will be overwritten!
- labels:
    module: if_mib_secret
    netbox_type: device
  targets:
  - sw1/192.168.1.2
  - sw2/192.168.1.3
- labels:
    module: mikrotik_secret
    netbox_type: device
  targets:
  - gw/192.168.1.1
```

It writes separate files for each type of target: `node_targets.yml`,
`snmp_targets.yml`, `windows_targets.yml`.

It also generates synthetic metrics which can be used for
[machine role queries](https://www.robustperception.io/how-to-have-labels-for-machine-roles)
and to add extra labels to alerts:

```
netbox_meta{instance="gw",netbox_type="device",rack="r1",site="dc",tags_prom_snmp="1",role="router"} 1
netbox_meta{instance="sw1",netbox_type="device",rack="r1",site="dc1",tags_prom_snmp="1",role="core-switch"} 1
netbox_meta{instance="sw2",netbox_type="device",rack="r2",site="dc1",tags_prom_snmp="1",role="core-switch"} 1
```

# Installation

Normally you would install script this on your prometheus server, so that it
can write the targets files directly.

Copy the python source file to your prometheus server, e.g. as
`/usr/local/bin/netbox_prometheus.py`

## Dependencies

```
apt-get install python3-pip
pip3 install pynetbox
```

## Netbox Configuration

### API token

In Netbox, create an API token with write disabled.

Inside the python source file, set API_URL and API_TOKEN to be able to
communicate with Netbox REST API.

### Tags

In your Netbox instance:

* Add tag "prometheus" onto each of the site(s) where you have things to to poll (*)
* Add tag "prom_node" to each Linux device/VM that you want to poll
* Add tag "prom_windows" to each Windows device/VM that you want to poll
* Add tag "prom_snmp" to each network device that you want to poll
* Ensure that each device or VM that you want to poll has status "Active",
  and either has a primary IP address assigned, or its name is resolvable

Note: the script *requires* all those tags to exist, even if there are no
devices with them, because the Netbox API gives an error if you try to query
non-existent tags.

Therefore if you don't need `prom_windows` or `prom_snmp`, you still need to
create an unused tag in Netbox (prior to v2.9.0 you had to add it to a
device then remove it again), or else comment out the relevant lines in the
script.

(*) To scrape Virtual Machines, the *cluster* must be associated with a
site, and that site must have the label "prometheus".  Site Groups are
currently not tested, but you can adjust the filter yourself if you wish.

### SNMP configuration

If you have any SNMP devices to poll, then you need to create a new custom
field as follows:

* Type: Selection (or Multiple Selection)
* Name: `snmp_module`
* Label: `SNMP Module`
* Content Types: `DCIM > device` and `Virtualization > virtual machine`
* Choices: list of SNMP modules as required, e.g. `if_mib,apcups,synology`
  (these refer to modules in your snmp_exporter `snmp.yml`)

Then select one or more of these choices on each device or VM that you wish
to poll, as well as setting the `prom_snmp` tag.

(The tag is required to minimise the data returned in the API query; Netbox
does not yet have
[custom field filters](https://github.com/netbox-community/netbox/issues/6615)
such as `cf_snmp_module__empty=0`)

## Script setup

### Create the output directories

```
mkdir -p /etc/prometheus/targets.d
mkdir -p /var/www/html/metrics
```

If you want the output to go somewhere else, then modify the
relevant constants in the script.

### Run the script

Run the script, check for no errors, and that it creates output files in the
given directories.

### Add cronjob

Create `/etc/cron.d/netbox_prometheus` to keep the files up-to-date:

```
*/5 * * * * /usr/local/bin/netbox_prometheus.py
```

Prometheus `file_sd` automatically detects files which change, and doesn't
need to be reloaded.

## Prometheus scrape configuration

### Targets

This script can output targets of the following forms:

```
- foo               # name only
- x.x.x.x           # IPv4 address only
- foo/x.x.x.x       # name and IPv4 address
- [dead:beef::]     # IPv6 address only
- foo/[dead:beef::] # name and IPv6 address
```

The IP addresses come from the "primary" IP address defined in Netbox, and
the name from the device/VM name.  This approach allows you to have
[meaningful instance labels](https://www.robustperception.io/controlling-the-instance-label)
like `{instance="foo"}` whilst using IP addresses for targets, avoiding
the need for DNS resolution.

To use these target files, you will need some relabelling configuration.

Node Exporter:

```
  - job_name: node
    scrape_interval: 1m
    file_sd_configs:
      - files:
        - /etc/prometheus/targets.d/node_targets.yml
    metrics_path: /metrics
    relabel_configs:
      # When __address__ consists of just a name or IP address,
      # copy it to the "instance" label.  Doing this explicitly
      # keeps the port number out of the instance label.
      - source_labels: [__address__]
        regex: '([^/]+)'
        target_label: instance

      # When __address__ is of the form "name/address", extract
      # name to "instance" label and address to "__address__"
      - source_labels: [__address__]
        regex: '(.+)/(.+)'
        target_label: instance
        replacement: '${1}'
      - source_labels: [__address__]
        regex: '(.+)/(.+)'
        target_label: __address__
        replacement: '${2}'

      # Append port number to __address__ so that scrape gets
      # sent to the right port
      - source_labels: [__address__]
        target_label: __address__
        replacement: '${1}:9100'
```

Windows exporter is similar (just change the job_name, the filename, and the
replacement port number to 9182).

SNMP exporter is slightly trickier because the target parameter
cannot contain square brackets around IPv6 addresses.

```
  - job_name: snmp
    scrape_interval: 1m
    file_sd_configs:
      - files:
        - /etc/prometheus/targets.d/snmp_targets.yml
    metrics_path: /snmp
    relabel_configs:
      # When __address__ consists of just a name or IP address,
      # copy it to both the "instance" label (visible to user)
      # and "__param_target" (where snmp_exporter sends SNMP)
      - source_labels: [__address__]
        regex: '([^/]+)'
        target_label: instance
      - source_labels: [__address__]
        regex: '([^/]+)'
        target_label: __param_target

      # When __address__ is of the form "name/address", extract
      # name to "instance" label and address to "__param_target"
      - source_labels: [__address__]
        regex: '(.+)/(.+)'
        target_label: instance
        replacement: '${1}'
      - source_labels: [__address__]
        regex: '(.+)/(.+)'
        target_label: __param_target
        replacement: '${2}'

      # If __param_target is enclosed by square brackets, remove them
      - source_labels: [__param_target]
        regex: '\[(.+)\]'
        target_label: __param_target
        replacement: '${1}'

      # Copy "module" label to "__param_module" so that snmp_exporter
      # receives it as part of the scrape URL
      - source_labels: [module]
        target_label: __param_module

      # Send the actual scrape to SNMP exporter
      - target_label: __address__
        replacement: 127.0.0.1:9116
```

Reload prometheus config and check there are no errors:

```
killall -HUP prometheus
journalctl -eu prometheus
```

See also:

* https://www.robustperception.io/controlling-the-instance-label
* https://www.robustperception.io/target-labels-are-for-life-not-just-for-christmas/
* https://www.robustperception.io/reloading-prometheus-configuration

### Metadata

In order to use the metadata metrics, you'll need to expose them using http
(`apt-get install apache2`) and add a scrape job:

```
  # Pick up netbox_meta metrics exported from netbox database
  - job_name: netbox
    metrics_path: /metrics/netbox
    scrape_interval: 5m
    honor_labels: true
    static_configs:
      - targets:
        - 127.0.0.1:80
```

You can then use queries and alerting rules with extra labels from Netbox, e.g.

```
# Filter based on Netbox attributes
(up == 1) * on (instance) group_left netbox_meta{role="core-switch"}

# Add extra labels from Netbox
(up == 1) * on (instance) group_left(tenant,role,site,rack,cluster) netbox_meta
```

You can modify the python code to add extra labels, e.g. "platform".

See also:

* [How to have labels for machine roles](https://www.robustperception.io/how-to-have-labels-for-machine-roles)
* [Exposing the software version to prometheus](https://www.robustperception.io/exposing-the-software-version-to-prometheus)
* [Many-to-one and one-to-one vector matches](https://prometheus.io/docs/prometheus/latest/querying/operators/#many-to-one-and-one-to-many-vector-matches)

# Complex deployments

## Multiple prometheus instances

You might have multiple prometheus instances.  Say prometheus1 should poll
sites A, B and C, while prometheus2 polls sites A (for redundancy), D and E.

You can control this with the SITE_TAG setting.  On the two prometheus
instances run the same script, but one configured with

```
SITE_TAG = "prometheus1"
```

and the other with

```
SITE_TAG = "prometheus2"
```

Then in Netbox, tag sites A, B and C with "prometheus1", and sites A, D and
E with "prometheus2".  The correct targets will be generated for each
prometheus instance.
