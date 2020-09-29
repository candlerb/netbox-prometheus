FROM debian:bullseye-slim

RUN apt-get update && apt-get -y install supervisor nginx python3-pip procps

COPY netbox_prometheus.py /netbox_prometheus.py
COPY requirements.txt /requirements.txt

ADD conf/default.conf /etc/nginx/sites-enabled/default
ADD poll.sh /

COPY conf/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN pip3 install -r /requirements.txt \
	&& chmod +x /netbox_prometheus.py \
	&& mkdir -p /etc/prometheus/targets.d /var/www/html/metrics \
	&& chmod +x /poll.sh

EXPOSE 80
CMD ["/usr/bin/supervisord"]
