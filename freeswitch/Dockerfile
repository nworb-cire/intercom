FROM safarov/freeswitch@sha256:b31c743f4c911a19687c61e3214968f2a24f93f9d3d667cc26284192e158ffc6

# Seed the full vanilla tree during the image build. The upstream entrypoint
# otherwise seeds it on first boot and overwrites files copied below.
RUN mkdir -p /etc/freeswitch \
 && cp -a /usr/share/freeswitch/conf/vanilla/. /etc/freeswitch/ \
 && rm -rf /etc/freeswitch/sip_profiles/* \
 && sed -i '/mod_signalwire/d;/mod_verto/d;/mod_rtc/d' /etc/freeswitch/autoload_configs/modules.conf.xml

COPY conference.conf.xml /etc/freeswitch/autoload_configs/conference.conf.xml
COPY event_socket.conf.xml.template /opt/intercom/event_socket.conf.xml.template
COPY intercom.xml /etc/freeswitch/dialplan/public/00_intercom.xml
COPY intercom-sip.xml /etc/freeswitch/sip_profiles/intercom.xml
COPY switch.conf.xml /etc/freeswitch/autoload_configs/switch.conf.xml
COPY docker-entrypoint-intercom.sh /docker-entrypoint-intercom.sh

ENTRYPOINT ["/docker-entrypoint-intercom.sh"]
