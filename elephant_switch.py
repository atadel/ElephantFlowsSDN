# simple_switch.py
from ryu.base import app_manager
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import dpid as dpid_lib
from ryu.lib import stplib
from ryu.lib import hub
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import udp
from ryu.controller import ofp_event
from ryu.app import simple_switch_13


class SimpleSwitch13(simple_switch_13.SimpleSwitch13):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'stplib': stplib.Stp}

    STATS_INTERVAL_SEC = 5
    ELEPHANT_DURATION_THRESHOLD_SEC = 30
    ELEPHANT_RATE_THRESHOLD_BPS = 5_000_000  # 5 Mbps

    # Porty zgodne z Twoim generatorem (UDP)
    PORT_RANGE_MOUSE_UDP = range(5000, 5010)
    PORT_RANGE_ELEPHANT_UDP = range(6000, 6010)

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.stp = kwargs['stplib']

        # datapaths do odpytywania statystyk
        self.datapaths = {}

        # (dpid, flow_key) -> last_byte_count
        self._last_bytes = {}

        # (dpid, flow_key) -> 'mouse' / 'elephant'
        self._flow_class = {}

        # (dpid, flow_key) -> current_out_port 
        self._flow_out_port = {}

        # STP config
        config = {
            dpid_lib.str_to_dpid('0000000000000001'): {'bridge': {'priority': 0x8000}},
            dpid_lib.str_to_dpid('0000000000000002'): {'bridge': {'priority': 0x9000}},
            dpid_lib.str_to_dpid('0000000000000003'): {'bridge': {'priority': 0xa000}},
            dpid_lib.str_to_dpid('0000000000000004'): {'bridge': {'priority': 0xb000}},
            dpid_lib.str_to_dpid('0000000000000005'): {'bridge': {'priority': 0xc000}},
        }
        self.stp.set_config(config)

        # IP hosta -> switch brzegowy
        self.host_edge = {
            "10.0.0.1": "s1",
            "10.0.0.2": "s1",
            "10.0.0.3": "s2",
            "10.0.0.4": "s2",
            "10.0.0.5": "s3",
            "10.0.0.6": "s3",
        }

        # (dpid, out_port) -> nazwa sąsiada (core / edge)
        self.port_to_switch = {
            # s1
            (1, 3): "s4",
            (1, 4): "s5",

            # s2
            (2, 3): "s4",
            (2, 4): "s5",

            # s3
            (3, 3): "s4",
            (3, 4): "s5",

            # s4
            (4, 1): "s1",
            (4, 2): "s2",
            (4, 3): "s3",

            # s5
            (5, 1): "s1",
            (5, 2): "s2",
            (5, 3): "s3",
        }

        # Wątek okresowego odpytywania statystyk
        self.monitor_thread = hub.spawn(self._monitor)

        self.logger.info("Controller started. Flow monitor every %ss.", self.STATS_INTERVAL_SEC)

    # --------- Monitorowanie flow stats (co 5s) ----------

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_flow_stats(dp)
            hub.sleep(self.STATS_INTERVAL_SEC)

    def _request_flow_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath, 0, ofproto.OFPTT_ALL,
                                        ofproto.OFPP_ANY, ofproto.OFPG_ANY,
                                        0, 0, parser.OFPMatch())
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if dp.id not in self.datapaths:
                self.datapaths[dp.id] = dp
                self.logger.info("Datapath registered: dpid=%s", dpid_lib.dpid_to_str(dp.id))
        elif ev.state == DEAD_DISPATCHER:
            if dp.id in self.datapaths:
                del self.datapaths[dp.id]
                self.logger.info("Datapath unregistered: dpid=%s", dpid_lib.dpid_to_str(dp.id))

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id

        for stat in ev.msg.body:
            m = stat.match
            if 'eth_type' not in m or m.get('eth_type') != 0x0800:
                continue
            if m.get('ip_proto') != 17:
                continue
            if 'ipv4_src' not in m or 'ipv4_dst' not in m:
                continue
            if 'udp_src' not in m or 'udp_dst' not in m:
                continue

            flow_key = self._flow_key_from_match(m)

            byte_count = stat.byte_count
            duration = float(stat.duration_sec) + float(stat.duration_nsec) / 1e9

            last = self._last_bytes.get((dpid, flow_key), None)
            if last is None:
                self._last_bytes[(dpid, flow_key)] = byte_count
                continue

            delta_bytes = max(0, byte_count - last)
            self._last_bytes[(dpid, flow_key)] = byte_count

            rate_bps = (delta_bytes * 8.0) / float(self.STATS_INTERVAL_SEC)

            is_elephant = (duration > self.ELEPHANT_DURATION_THRESHOLD_SEC and
                           rate_bps > self.ELEPHANT_RATE_THRESHOLD_BPS)

            prev_class = self._flow_class.get((dpid, flow_key), None)
            new_class = 'elephant' if is_elephant else 'mouse'

            if prev_class != new_class:
                self._flow_class[(dpid, flow_key)] = new_class
                self.logger.info(
                    "CLASSIFY dpid=%s flow=%s duration=%.1fs rate=%.2fMbps => %s",
                    dpid_lib.dpid_to_str(dpid),
                    self._flow_key_to_str(flow_key),
                    duration,
                    rate_bps / 1e6,
                    new_class.upper()
                )

            # Reroutuj TYLKO w momencie zmiany klasy na ELEPHANT
            if prev_class != 'elephant' and is_elephant:
                self._reroute_elephant(dp, m, flow_key)

    # --------- Reroute Elephant ----------

    def _reroute_elephant(self, datapath, match, flow_key):
        dpid = datapath.id
        parser = datapath.ofproto_parser

        current_out = self._flow_out_port.get((dpid, flow_key), None)
        alt_out = self._pick_alternate_out_port(datapath, current_out)

        if alt_out is None or (current_out is not None and alt_out == current_out):
            return

        if current_out == alt_out:
            return

        self._delete_flow_strict(datapath, match, priority=10)

        actions = [parser.OFPActionOutput(alt_out)]
        self.add_flow(datapath, 10, match, actions)

        self._flow_out_port[(dpid, flow_key)] = alt_out

        # zapisz nowy port
        self._flow_out_port[(dpid, flow_key)] = alt_out

        if current_out != alt_out:

            src_ip, dst_ip, _, _ = flow_key

            old_core = self.port_to_switch.get((dpid, current_out), "UNKNOWN")
            new_core = self.port_to_switch.get((dpid, alt_out), "UNKNOWN")

            old_path = self._pretty_path(src_ip, dst_ip, old_core)
            new_path = self._pretty_path(src_ip, dst_ip, new_core)

            if "UNKNOWN" in old_path or "UNKNOWN" in new_path:
                return

            if old_core == new_core:
                return

            src_edge = self.host_edge.get(src_ip)
            dst_edge = self.host_edge.get(dst_ip)

            if src_edge == old_core or dst_edge == old_core:
                return

            if src_edge == new_core or dst_edge == new_core:
                return

            self.logger.info(
                "PATH CHANGE (ELEPHANT) dpid=%s flow=%s",
                dpid_lib.dpid_to_str(dpid),
                self._flow_key_to_str(flow_key),
            )
            self.logger.info("OLD PATH: %s", old_path)
            self.logger.info("NEW PATH: %s", new_path)


    def _delete_flow_strict(self, datapath, match, priority):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            priority=priority,
            match=match
        )
        datapath.send_msg(mod)

    def _pick_alternate_out_port(self, datapath, current_out_port):
        """
        Wybieraj TYLKO uplinki do spine: porty 3 i 4
        """
        dpid = datapath.id

        spine_ports = [3, 4]

        # jeśli nie znamy obecnego, weź 3
        if current_out_port is None:
            return spine_ports[0]

        # przełącz 3 <-> 4
        if current_out_port == 3:
            return 4
        if current_out_port == 4:
            return 3

        return 3

    # --------- PacketIn ----------

    @set_ev_cls(stplib.EventPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        ip4 = pkt.get_protocol(ipv4.ipv4)
        udpp = pkt.get_protocol(udp.udp)

        if ip4 and udpp:
            match = parser.OFPMatch(
                eth_type=0x0800,
                ip_proto=17,
                ipv4_src=ip4.src,
                ipv4_dst=ip4.dst,
                udp_src=udpp.src_port,
                udp_dst=udpp.dst_port
            )

            if dst in self.mac_to_port[dpid]:
                out_port = self.mac_to_port[dpid][dst]
            else:
                out_port = ofproto.OFPP_FLOOD

            actions = [parser.OFPActionOutput(out_port)]

            if out_port != ofproto.OFPP_FLOOD:
                self.add_flow(datapath, 10, match, actions)
                flow_key = self._flow_key_from_match(match)
                if (dpid, flow_key) not in self._flow_out_port:
                    self._flow_out_port[(dpid, flow_key)] = out_port

            data = None
            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                data = msg.data
            out = parser.OFPPacketOut(datapath=datapath,
                                      buffer_id=msg.buffer_id,
                                      in_port=in_port,
                                      actions=actions,
                                      data=data)
            datapath.send_msg(out)
            return

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    # --------- STP ----------

    def delete_flow(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        if datapath.id not in self.mac_to_port:
            return
        for dst in list(self.mac_to_port[datapath.id].keys()):
            match = parser.OFPMatch(eth_dst=dst)
            mod = parser.OFPFlowMod(
                datapath,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                priority=1,
                match=match)
            datapath.send_msg(mod)

    @set_ev_cls(stplib.EventTopologyChange, MAIN_DISPATCHER)
    def _topology_change_handler(self, ev):
        dp = ev.dp
        if dp.id in self.mac_to_port:
            self.delete_flow(dp)
            del self.mac_to_port[dp.id]

    @set_ev_cls(stplib.EventPortStateChange, MAIN_DISPATCHER)
    def _port_state_change_handler(self, ev):
        pass

    # --------- Helpers ----------

    def _flow_key_from_match(self, match):
        return (match.get('ipv4_src'),
                match.get('ipv4_dst'),
                match.get('udp_src'),
                match.get('udp_dst'))

    def _flow_key_to_str(self, flow_key):
        s_ip, d_ip, s_p, d_p = flow_key
        return f"{s_ip}:{s_p} -> {d_ip}:{d_p}"

    def _pretty_path(self, src_ip, dst_ip, core_name):
        src_edge = self.host_edge.get(src_ip)
        dst_edge = self.host_edge.get(dst_ip)

        if not src_edge or not dst_edge:
            return f"{src_ip} -> ??? -> {dst_ip}"

        return f"{src_ip} -> {src_edge} -> {core_name} -> {dst_edge} -> {dst_ip}"
