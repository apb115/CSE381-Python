""" Components.py """

import random
import collections      # provides 'deque': double-ended queue
import inspect
import networkx as nx
import math
import numpy as np

from . import Globals
from . import Priority
from . import Utils
from . import PacketGenerator


class Channel:
    """ Model a connection between two nodes """

    def __init__(self, env, delay, conn_out, conn_in):
        self.env = env
        self.delay = delay
        self.conn_out = conn_out
        self.conn_in = conn_in

    def latency(self, pkt):
        """ Latency for putting packet onto the wire """
        yield self.env.timeout(self.delay)

        self.conn_out.put(pkt)

    def put(self, pkt):
        """ Puts the packet 'pkt' onto the wire """
        self.env.process(self.latency(pkt))

    def get(self):
        """ Retrieves packet from the connection """
        return self.conn_in.get()


class Node:
    """ Model a network node """

    def __init__(self, env, M, node_name, verbose):

        self.env = env  # SimPy environment
        self.name = node_name  # must be unique
        self.type = M.G.nodes[node_name][Globals.NODE_TYPE_KWD]
        if int(node_name) in range(25,29):
            self.quantum = 1
        # priority here?
        self.pkt_rate = M.G.nodes[node_name][Globals.NODE_PKT_RATE_KWD]
        self.proc_delay = M.G.nodes[node_name][Globals.NODE_PROC_DELAY_KWD]
        self.queue_check = M.G.nodes[node_name][Globals.NODE_QUEUE_CHECK_KWD]
        self.queue_cutoff = M.G.nodes[node_name][Globals.NODE_QUEUE_CUTOFF_KWD]

        # precomputed table of shortest paths
        self.path_G = M.shortest_paths
        self.nodes = nx.nodes(M.G)

        self.conns = {}
        self.verbose = verbose

        # processing queue and queue length monitor
        self.proc_queue = collections.deque()
        self.queue_mon = collections.deque()

        # packets persistent storage
        self.generated = collections.deque()
        self.received = collections.deque()
        self.forwarded = collections.deque()
        self.discarded = collections.deque()

        # counters for sent/received packets (key=node name)
        self.pkt_sent = {}
        self.pkt_recv = {}

        # dt interval for incoming queue monitoring
        self.queue_monitor_deltat = Globals.QUEUE_MONITOR_DELTAT

    def add_conn(self, c, conn):
        """ Add a connection from this node to the node 'c' """

        self.conns[c] = conn
        self.pkt_sent[c] = 0
        self.pkt_recv[c] = 0

    def if_up(self):
        """ Activates interfaces- this sets up SimPy processes """

        # start receiving processes on all receiving connections
        for c in self.conns:
            self.env.process(self.if_recv(c))

        # activate packet generator, packet forwarding, queue monitoring
        self.env.process(self.pkt_gen_process())
        self.env.process(self.forward_process())
        self.env.process(self.queue_monitor())

    def if_recv(self, c):
        """ Node receive interface from node 'c' """

        # the connection from 'self.name' to 'c'
        conn = self.conns[c]

        while True:

            # pick up any incoming packets
            pkt = yield conn.get()

            # increment the counter for this sending node
            self.pkt_recv[c] += 1

            # put the packet in the processing queue
            self.proc_queue.append(pkt)

            # report as per verbose level
            if self.verbose >= Globals.VERB_LO:
                Utils.report(self.env.now, self.name, pkt, self.proc_queue, inspect.currentframe().f_code.co_name, self.verbose)

    def forward_process(self):
        """ Node packet forwarding process """
        # run until 500 time units
        # yield by quantum
        # update cpu burst by subtracting 1
        # append left (IF CPU BURST is bigger than quantum do this
        # yield by cpu burst second time (condition)
        # save original CPU BURST to excel files
        # always increment number of rounds
        while True:
            # if packet burst less than quantum
            #     yield
            # verbose ???????
            #  incrmement num of rounds
            # else
            # go to another round
            # update time by amount of quantum
            # decrease the quantum by cpu burst
            # send the packet back

            # if there are any packets in the processing queue
            if len(self.proc_queue) > 0:

                # get the first packet from the queue
                pkt = self.proc_queue.pop()
                # pkt[Globals.CPU_UPDATE] -= self.proc_delay

                # get the destination node
                dest_node = pkt[Globals.DEST_NODE]


                # if the destination node is this current node
                if self.name == dest_node:
                    if float(pkt[Globals.CPU_UPDATE]) >= self.quantum:
                        yield self.env.timeout(self.quantum)
                        pkt[Globals.NO_ROUNDS] += 1
                        pkt[Globals.CPU_UPDATE] -= self.quantum
                        self.proc_queue.appendleft(pkt)
                    else:
                        yield self.env.timeout(pkt[Globals.CPU_UPDATE])
                        pkt[Globals.NO_ROUNDS] += 1

                        # incur packet processing time
                        # yield self.env.timeout(random.expovariate(self.proc_delay))

                        # set the destination arrival time of the packet
                        pkt[Globals.DEST_TIME_STAMP] = self.env.now

                        data = Globals.DICTIONARY[pkt[Globals.ID]]
                        p_size = data[0]
                        time = data[2]
                        counter = data[1]
                        counter += 1

                        if (counter == p_size):
                            Globals.DICTIONARY[pkt[Globals.ID]] = [p_size, counter, pkt[Globals.DEST_TIME_STAMP] - time]
                        else:
                            Globals.DICTIONARY[pkt[Globals.ID]] = [p_size, counter, time]

                        # packet terminates here - put it in the received queue
                        self.received.append([self.env.now, pkt])


                        print(f'A packet has been successfully processed at server {self.name}')

                        if self.verbose >= Globals.VERB_LO:
                            Utils.report(self.env.now, self.name, pkt, self.proc_queue,
                                         inspect.currentframe().f_code.co_name + '_get',
                                         self.verbose)

                # if the destination is some other node, forward this packet then
                else:

                    print(f'A packet has been scheduled on the server {dest_node}\n')

                    # incur packet processing time
                    yield self.env.timeout(random.expovariate(self.proc_delay))  # no scheduling delay needed

                    # increment the packet hop counter
                    pkt[Globals.NO_HOPS] += 1

                    # get next-hop node along the shortest path
                    hop_node = self.path_G[(self.name, dest_node)]

                    # register the next-hop node with the packet
                    pkt[Globals.HOP_NODE] = hop_node

                    # forward packet to the next-hop node
                    self.send_to_node(pkt, hop_node)

                    # count this packet as sent to 'hop_node'
                    self.pkt_sent[hop_node] += 1

                    # register forwarded packets in the forward queue
                    self.forwarded.append([self.env.now, pkt])

                    # report as per verbose level
                    if self.verbose >= Globals.VERB_LO:
                        Utils.report(self.env.now, self.name, pkt, self.proc_queue, inspect.currentframe().f_code.co_name + '_fwd',
                                     self.verbose)


            # if there are no packets in the processing queue
            else:

                #  incur queue check delay
                yield self.env.timeout(self.queue_check)

    def send_to_node(self, pkt, next_node):
        """ Sends packet to the destination node """

        # get the connection to the destination node
        conn = self.conns[next_node]
        conn.put(pkt)  # put the packet onto the connection

        # report as per verbose level
        if self.verbose > Globals.VERB_NO:
            Utils.report(self.env.now, self.name, pkt, self.proc_queue, inspect.currentframe().f_code.co_name, self.verbose)

    def pkt_gen_process(self):
        """ Process that generates networks packets """

        # Determine list of user nodes 1 - 20
        if int(self.name) in range(1, 21):

            while True:

                # find the arrival time of packets
                pkt_gen_deltat = PacketGenerator.run(self.pkt_rate)

                # incur packet processing time
                yield self.env.timeout(pkt_gen_deltat)

                # Randomly find the packet types and save it in 'pkt_type' XXXXXXXXXXXXX
                id = Utils.gen_id()
                p_size = np.random.geometric(p=0.5)

                # Specify the server (dest_node) on which the packet should be scheduled and save it in 'dest_node'
                dest_node = str(random.randrange(25, 29, 1))

                if p_size == 1:
                    pkttype = "process"
                    pkt = self.make_pkt(pkttype, dest_node)
                    Globals.DICTIONARY[pkt[Globals.ID]] = [p_size, 0, pkt[Globals.TIME_STAMP]]
                    self.proc_queue.appendleft(pkt)
                    # Report generated packets in the generated queue
                    self.generated.appendleft([self.env.now, pkt])

                    if self.verbose > Globals.VERB_NO:
                        Utils.report(self.env.now, self.name, pkt, self.proc_queue,
                                     inspect.currentframe().f_code.co_name, self.verbose)
                else:
                    pkttype = "thread"
                    id = Utils.gen_id()
                    pkt = self.make_pkt(pkttype, dest_node)
                    Globals.DICTIONARY[pkt[Globals.ID]] = [p_size, 0, pkt[Globals.TIME_STAMP]]
                    i = 0
                    while i < p_size:
                        destination = str(random.randrange(25, 29, 1))
                        pktthread = self.make_pkt(pkttype, destination)
                        pktthread[Globals.ID] = id
                        self.proc_queue.appendleft(pktthread)
                        self.generated.appendleft([self.env.now, pktthread])
                        i +=1

    def make_pkt(self, pkt_type, dest_node):
        """ Creates a network packet """
        pkt = {
            Globals.TIME_STAMP: self.env.now,
            Globals.ID: Utils.gen_id(),
            Globals.TYPE: pkt_type,
            Globals.CPU_BURST: random.expovariate(self.proc_delay),
            Globals.SOURCE: self.name,
            Globals.DEST_NODE: dest_node,
            Globals.HOP_NODE: Globals.NONE,
            Globals.DEST_TIME_STAMP: -1.0,
            Globals.NO_ROUNDS: 0,
            Globals.NO_HOPS: 0
        }
        pkt[Globals.CPU_UPDATE] = pkt[Globals.CPU_BURST]
        return pkt

    def discard_packet(self, pkt, msg):
        """ Discards the packet (puts the packet into the node packet sink) """

        # place this packet in the node sink
        self.discarded.append([self.env.now, pkt])

    def queue_monitor(self):
        """ Queue monitor process """

        while True:
            # add to queue monitor time now and queue_length
            self.queue_mon.append([self.env.now, len(self.proc_queue)])

            # incur monitor queue delay  [queue_check = 0.001]
            yield self.env.timeout(self.queue_monitor_deltat)
