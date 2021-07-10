#!/usr/bin/python3
import os
import pynetbox
import re
import sys
import yaml

CLASS_MAP = {
    "Devices": "device",
    "VirtualMachines": "vm",
}

class ConfigBuilder:
    def __init__(self, nb, filter={}):
        self.nb = nb
        self.filter = filter
        self.metrics = {}   #  {(instance, kind) => {label=>value}}  # static metadata
        self.targets = {}   #  {filename => (labels) => [target]}    # targets to be scraped

    def add_target(self, item, filename, labels={}):
        if not item.name:
            print("Unnamed item %r" % item, file=sys.stderr)
            return
        kind = CLASS_MAP.get(item.__class__.__name__, item.__class__.__name__)

        # add to prometheus scraping target
        target_key = tuple([("netbox_type",kind)] + sorted(labels.items()))
        self.targets.setdefault(filename, {})
        tf = self.targets[filename]
        tf.setdefault(target_key, [])
        tt = tf[target_key]

        if item.primary_ip:
            addr = re.sub(r'/\d+$', '', item.primary_ip.address)
            if ":" in addr:
                addr = "[" + addr + "]"
            tt.append(item.name + "/" + addr)
        else:
            tt.append(item.name)

        # add netbox_meta metric (label with role, site etc)
        metric_key = (item.name, kind)
        self.metrics.setdefault(metric_key, {})
        tenant = getattr(item, "tenant", None)
        if tenant:
            self.metrics[metric_key]["tenant"] = tenant.slug
        role = getattr(item, "device_role", getattr(item, "role", None))
        if role:
            self.metrics[metric_key]["role"] = role.slug
        site = getattr(item, "site", None)
        if site:
            self.metrics[metric_key]["site"] = site.slug
        rack = getattr(item, "rack", None)
        if rack:
            self.metrics[metric_key]["rack"] = rack.name # rack has no slug
        cluster = getattr(item, "cluster", None)
        if cluster:
            self.metrics[metric_key]["cluster"] = cluster.name # cluster has no slug
        for tag in item.tags:
            self.metrics[metric_key]["tags_"+str(tag)] = "1"

    def add_targets(self, items, filename, labels={}):
        """Add a target once"""
        for item in items:
            self.add_target(item, filename, labels)

    def add_targets_ctx(self, items, filename, context_var, param_name):
        """Add a target for each value in a given context_var"""
        for item in items:
            cv = item.config_context.get(context_var, [])
            if not cv:
                print("Item %r: missing or empty %s" % (item, context_var))
            else:
                if not isinstance(cv, list):
                    cv = [cv]
                for mod in cv:
                    self.add_target(item, filename, {param_name: mod})

    def build(self):
        """
        Here you assemble the netbox things you wish to query and which files to add them to.
        Add queries for the different types of object to be polled.
        """
        self.add_targets(self.nb.dcim.devices.filter(tag="prom_node", **self.filter), "node_targets.yml")
        self.add_targets(self.nb.virtualization.virtual_machines.filter(tag="prom_node", **self.filter), "node_targets.yml")
        self.add_targets_ctx(self.nb.dcim.devices.filter(tag="prom_snmp", **self.filter), "snmp_targets.yml", "snmp_mibs", "module")
        # Not bothering with VMs for SNMP
        self.add_targets(self.nb.dcim.devices.filter(tag="prom_windows", **self.filter), "windows_targets.yml")
        self.add_targets(self.nb.virtualization.virtual_machines.filter(tag="prom_windows", **self.filter), "windows_targets.yml")
        # TODO: blackbox_targets: should this be on Device/VM or on IPAddress object?

    def replace_file(self, filename, content):
        try:
            with open(filename) as f:
                oldconf = f.read()
            if oldconf == content:
                return
        except FileNotFoundError:
            pass
        with open(filename+".new", "w") as f:
            f.write(content)
        os.rename(filename+".new", filename)

    def gen_target_file(self, data):
        """ data is a dict of (labels) => [target]
        Sort it so that it's repeatable
        """
        content = []
        for labels, targets in sorted(data.items()):
            content.append({"labels": dict(labels), "targets": sorted(targets)})
        return "# Auto-generated from Netbox, do not edit as your changes will be overwritten!\n" + yaml.dump(content, default_flow_style=False)

    def write_targets(self, dir):
        for filename, data in self.targets.items():
            self.replace_file(dir+"/"+filename, self.gen_target_file(data))

    def write_metrics(self, filename):
        content = ""
        for (instance, kind), labels in sorted(self.metrics.items()):
            content += "netbox_meta{instance=\"%s\",netbox_type=\"%s\"" % (instance, kind)
            for k, v in labels.items():
                content += ",%s=\"%s\"" % (re.sub(r'[^a-zA-Z0-9_]', '_', k), re.sub(r'"', r'\\"', v))
            content += "} 1\n"
        self.replace_file(filename, content)

if __name__ == "__main__":
    API_URL = os.getenv('NETBOX_URL', "https://netbox.example.net")
    API_TOKEN = os.getenv('API_TOKEN', "XXXXXXXX")
    SITE_TAG = "prometheus"  # we will poll devices in all sites with this tag
    DIR = "/etc/prometheus/targets.d"
    METRICS = "/var/www/html/metrics/netbox"
    # Uncomment when testing:
    #DIR = "/tmp"
    #METRICS = "/tmp/netbox.prom"

    nb = pynetbox.api(API_URL, token=API_TOKEN)
    # Wether or not to validate the TLS certificate of API_URL
    nb.http_session.verify = True

    builder = ConfigBuilder(
        nb=nb,
        filter={
            "site_id": [s.id for s in nb.dcim.sites.filter(tag=SITE_TAG)],
            # This changed in 2.7: https://github.com/netbox-community/netbox/issues/3569
            "status": "active",  # "status": 1,
        },
    )
    builder.build()
    builder.write_targets(DIR)
    builder.write_metrics(METRICS)
