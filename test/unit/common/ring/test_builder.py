# Copyright (c) 2010-2012 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
import operator
import os
import unittest
import cPickle as pickle
from collections import defaultdict
from shutil import rmtree

from swift.common import exceptions
from swift.common import ring
from swift.common.ring.builder import MAX_BALANCE


class TestRingBuilder(unittest.TestCase):

    def setUp(self):
        self.testdir = os.path.join(os.path.dirname(__file__),
                                    'ring_builder')
        rmtree(self.testdir, ignore_errors=1)
        os.mkdir(self.testdir)

    def tearDown(self):
        rmtree(self.testdir, ignore_errors=1)

    def test_init(self):
        rb = ring.RingBuilder(8, 3, 1)
        self.assertEquals(rb.part_power, 8)
        self.assertEquals(rb.replicas, 3)
        self.assertEquals(rb.min_part_hours, 1)
        self.assertEquals(rb.parts, 2 ** 8)
        self.assertEquals(rb.devs, [])
        self.assertEquals(rb.devs_changed, False)
        self.assertEquals(rb.version, 0)

    def test_overlarge_part_powers(self):
        ring.RingBuilder(32, 3, 1)  # passes by not crashing
        self.assertRaises(ValueError, ring.RingBuilder, 33, 3, 1)

    def test_insufficient_replicas(self):
        ring.RingBuilder(8, 1.0, 1)  # passes by not crashing
        self.assertRaises(ValueError, ring.RingBuilder, 8, 0.999, 1)

    def test_negative_min_part_hours(self):
        ring.RingBuilder(8, 3, 0)  # passes by not crashing
        self.assertRaises(ValueError, ring.RingBuilder, 8, 3, -1)

    def test_get_ring(self):
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10004, 'device': 'sda1'})
        rb.remove_dev(1)
        rb.rebalance()
        r = rb.get_ring()
        self.assert_(isinstance(r, ring.RingData))
        r2 = rb.get_ring()
        self.assert_(r is r2)
        rb.rebalance()
        r3 = rb.get_ring()
        self.assert_(r3 is not r2)
        r4 = rb.get_ring()
        self.assert_(r3 is r4)

    def test_rebalance_with_seed(self):
        devs = [(0, 10000), (1, 10001), (2, 10002), (1, 10003)]
        ring_builders = []
        for n in range(3):
            rb = ring.RingBuilder(8, 3, 1)
            for idx, (zone, port) in enumerate(devs):
                rb.add_dev({'id': idx, 'region': 0, 'zone': zone, 'weight': 1,
                            'ip': '127.0.0.1', 'port': port, 'device': 'sda1'})
            ring_builders.append(rb)

        rb0 = ring_builders[0]
        rb1 = ring_builders[1]
        rb2 = ring_builders[2]

        r0 = rb0.get_ring()
        self.assertTrue(rb0.get_ring() is r0)

        rb0.rebalance()  # NO SEED
        rb1.rebalance(seed=10)
        rb2.rebalance(seed=10)

        r1 = rb1.get_ring()
        r2 = rb2.get_ring()

        self.assertFalse(rb0.get_ring() is r0)
        self.assertNotEquals(r0.to_dict(), r1.to_dict())
        self.assertEquals(r1.to_dict(), r2.to_dict())

    def test_set_replicas(self):
        rb = ring.RingBuilder(8, 3.2, 1)
        rb.devs_changed = False
        rb.set_replicas(3.25)
        self.assertTrue(rb.devs_changed)

        rb.devs_changed = False
        rb.set_replicas(3.2500001)
        self.assertFalse(rb.devs_changed)

    def test_add_dev(self):
        rb = ring.RingBuilder(8, 3, 1)
        dev = {'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
               'ip': '127.0.0.1', 'port': 10000}
        dev_id = rb.add_dev(dev)
        self.assertRaises(exceptions.DuplicateDeviceError, rb.add_dev, dev)
        self.assertEqual(dev_id, 0)
        rb = ring.RingBuilder(8, 3, 1)
        #test add new dev with no id
        dev_id = rb.add_dev({'zone': 0, 'region': 1, 'weight': 1,
                             'ip': '127.0.0.1', 'port': 6000})
        self.assertEquals(rb.devs[0]['id'], 0)
        self.assertEqual(dev_id, 0)
        #test add another dev with no id
        dev_id = rb.add_dev({'zone': 3, 'region': 2, 'weight': 1,
                             'ip': '127.0.0.1', 'port': 6000})
        self.assertEquals(rb.devs[1]['id'], 1)
        self.assertEqual(dev_id, 1)

    def test_set_dev_weight(self):
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 0.5,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 0.5,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10003, 'device': 'sda1'})
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 128, 1: 128, 2: 256, 3: 256})
        rb.set_dev_weight(0, 0.75)
        rb.set_dev_weight(1, 0.25)
        rb.pretend_min_part_hours_passed()
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 192, 1: 64, 2: 256, 3: 256})

    def test_remove_dev(self):
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 3, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10003, 'device': 'sda1'})
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 192, 1: 192, 2: 192, 3: 192})
        rb.remove_dev(1)
        rb.pretend_min_part_hours_passed()
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 256, 2: 256, 3: 256})

    def test_remove_a_lot(self):
        rb = ring.RingBuilder(3, 3, 1)
        rb.add_dev({'id': 0, 'device': 'd0', 'ip': '10.0.0.1',
                    'port': 6002, 'weight': 1000.0, 'region': 0, 'zone': 1})
        rb.add_dev({'id': 1, 'device': 'd1', 'ip': '10.0.0.2',
                    'port': 6002, 'weight': 1000.0, 'region': 0, 'zone': 2})
        rb.add_dev({'id': 2, 'device': 'd2', 'ip': '10.0.0.3',
                    'port': 6002, 'weight': 1000.0, 'region': 0, 'zone': 3})
        rb.add_dev({'id': 3, 'device': 'd3', 'ip': '10.0.0.1',
                    'port': 6002, 'weight': 1000.0, 'region': 0, 'zone': 1})
        rb.add_dev({'id': 4, 'device': 'd4', 'ip': '10.0.0.2',
                    'port': 6002, 'weight': 1000.0, 'region': 0, 'zone': 2})
        rb.add_dev({'id': 5, 'device': 'd5', 'ip': '10.0.0.3',
                    'port': 6002, 'weight': 1000.0, 'region': 0, 'zone': 3})
        rb.rebalance()
        rb.validate()

        # this has to put more than 1/3 of the partitions in the
        # cluster on removed devices in order to ensure that at least
        # one partition has multiple replicas that need to move.
        #
        # (for an N-replica ring, it's more than 1/N of the
        # partitions, of course)
        rb.remove_dev(3)
        rb.remove_dev(4)
        rb.remove_dev(5)

        rb.rebalance()
        rb.validate()

    def test_shuffled_gather(self):
        if self._shuffled_gather_helper() and \
                self._shuffled_gather_helper():
                raise AssertionError('It is highly likely the ring is no '
                                     'longer shuffling the set of partitions '
                                     'to reassign on a rebalance.')

    def _shuffled_gather_helper(self):
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.rebalance()
        rb.add_dev({'id': 3, 'region': 0, 'zone': 3, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10003, 'device': 'sda1'})
        rb.pretend_min_part_hours_passed()
        parts = rb._gather_reassign_parts()
        max_run = 0
        run = 0
        last_part = 0
        for part, _ in parts:
            if part > last_part:
                run += 1
            else:
                if run > max_run:
                    max_run = run
                run = 0
            last_part = part
        if run > max_run:
            max_run = run
        return max_run > len(parts) / 2

    def test_multitier_partial(self):
        # Multitier test, nothing full
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda'})
        rb.add_dev({'id': 1, 'region': 1, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb'})
        rb.add_dev({'id': 2, 'region': 2, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc'})
        rb.add_dev({'id': 3, 'region': 3, 'zone': 3, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdd'})

        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            counts = defaultdict(lambda: defaultdict(int))
            for replica in xrange(rb.replicas):
                dev = rb.devs[rb._replica2part2dev[replica][part]]
                counts['region'][dev['region']] += 1
                counts['zone'][dev['zone']] += 1

            if any(c > 1 for c in counts['region'].values()):
                raise AssertionError(
                    "Partition %d not evenly region-distributed (got %r)" %
                    (part, counts['region']))
            if any(c > 1 for c in counts['zone'].values()):
                raise AssertionError(
                    "Partition %d not evenly zone-distributed (got %r)" %
                    (part, counts['zone']))

        # Multitier test, zones full, nodes not full
        rb = ring.RingBuilder(8, 6, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc'})

        rb.add_dev({'id': 3, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdd'})
        rb.add_dev({'id': 4, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sde'})
        rb.add_dev({'id': 5, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdf'})

        rb.add_dev({'id': 6, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sdg'})
        rb.add_dev({'id': 7, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sdh'})
        rb.add_dev({'id': 8, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sdi'})

        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            counts = defaultdict(lambda: defaultdict(int))
            for replica in xrange(rb.replicas):
                dev = rb.devs[rb._replica2part2dev[replica][part]]
                counts['zone'][dev['zone']] += 1
                counts['dev_id'][dev['id']] += 1
            if counts['zone'] != {0: 2, 1: 2, 2: 2}:
                raise AssertionError(
                    "Partition %d not evenly distributed (got %r)" %
                    (part, counts['zone']))
            for dev_id, replica_count in counts['dev_id'].iteritems():
                if replica_count > 1:
                    raise AssertionError(
                        "Partition %d is on device %d more than once (%r)" %
                        (part, dev_id, counts['dev_id']))

    def test_multitier_full(self):
        # Multitier test, #replicas == #devs
        rb = ring.RingBuilder(8, 6, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb'})

        rb.add_dev({'id': 2, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdd'})

        rb.add_dev({'id': 4, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sde'})
        rb.add_dev({'id': 5, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdf'})

        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            counts = defaultdict(lambda: defaultdict(int))
            for replica in xrange(rb.replicas):
                dev = rb.devs[rb._replica2part2dev[replica][part]]
                counts['zone'][dev['zone']] += 1
                counts['dev_id'][dev['id']] += 1
            if counts['zone'] != {0: 2, 1: 2, 2: 2}:
                raise AssertionError(
                    "Partition %d not evenly distributed (got %r)" %
                    (part, counts['zone']))
            for dev_id, replica_count in counts['dev_id'].iteritems():
                if replica_count != 1:
                    raise AssertionError(
                        "Partition %d is on device %d %d times, not 1 (%r)" %
                        (part, dev_id, replica_count, counts['dev_id']))

    def test_multitier_overfull(self):
        # Multitier test, #replicas > #devs + 2 (to prove even distribution)
        rb = ring.RingBuilder(8, 8, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb'})

        rb.add_dev({'id': 2, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdd'})

        rb.add_dev({'id': 4, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sde'})
        rb.add_dev({'id': 5, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdf'})

        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            counts = defaultdict(lambda: defaultdict(int))
            for replica in xrange(rb.replicas):
                dev = rb.devs[rb._replica2part2dev[replica][part]]
                counts['zone'][dev['zone']] += 1
                counts['dev_id'][dev['id']] += 1

            self.assertEquals(8, sum(counts['zone'].values()))
            for zone, replica_count in counts['zone'].iteritems():
                if replica_count not in (2, 3):
                    raise AssertionError(
                        "Partition %d not evenly distributed (got %r)" %
                        (part, counts['zone']))
            for dev_id, replica_count in counts['dev_id'].iteritems():
                if replica_count not in (1, 2):
                    raise AssertionError(
                        "Partition %d is on device %d %d times, "
                        "not 1 or 2 (%r)" %
                        (part, dev_id, replica_count, counts['dev_id']))

    def test_multitier_expansion_more_devices(self):
        rb = ring.RingBuilder(8, 6, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc'})

        rb.rebalance()
        rb.validate()

        rb.add_dev({'id': 3, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdd'})
        rb.add_dev({'id': 4, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sde'})
        rb.add_dev({'id': 5, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdf'})

        for _ in xrange(5):
            rb.pretend_min_part_hours_passed()
            rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            counts = dict(zone=defaultdict(int),
                          dev_id=defaultdict(int))
            for replica in xrange(rb.replicas):
                dev = rb.devs[rb._replica2part2dev[replica][part]]
                counts['zone'][dev['zone']] += 1
                counts['dev_id'][dev['id']] += 1

            self.assertEquals({0: 2, 1: 2, 2: 2}, dict(counts['zone']))
            self.assertEquals({0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
                              dict(counts['dev_id']))

    def test_multitier_part_moves_with_0_min_part_hours(self):
        rb = ring.RingBuilder(8, 3, 0)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.rebalance()
        rb.validate()

        # min_part_hours is 0, so we're clear to move 2 replicas to
        # new devs
        rb.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc1'})
        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            devs = set()
            for replica in xrange(rb.replicas):
                devs.add(rb._replica2part2dev[replica][part])

            if len(devs) != 3:
                raise AssertionError(
                    "Partition %d not on 3 devs (got %r)" % (part, devs))

    def test_multitier_part_moves_with_positive_min_part_hours(self):
        rb = ring.RingBuilder(8, 3, 99)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.rebalance()
        rb.validate()

        # min_part_hours is >0, so we'll only be able to move 1
        # replica to a new home
        rb.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdc1'})
        rb.pretend_min_part_hours_passed()
        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            devs = set()
            for replica in xrange(rb.replicas):
                devs.add(rb._replica2part2dev[replica][part])

            if len(devs) != 2:
                raise AssertionError(
                    "Partition %d not on 2 devs (got %r)" % (part, devs))

    def test_multitier_dont_move_too_many_replicas(self):
        rb = ring.RingBuilder(8, 3, 0)
        # there'll be at least one replica in z0 and z1
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb1'})
        rb.rebalance()
        rb.validate()

        # only 1 replica should move
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdd1'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 3, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sde1'})
        rb.add_dev({'id': 4, 'region': 0, 'zone': 4, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdf1'})
        rb.rebalance()
        rb.validate()

        for part in xrange(rb.parts):
            zones = set()
            for replica in xrange(rb.replicas):
                zones.add(rb.devs[rb._replica2part2dev[replica][part]]['zone'])

            if len(zones) != 3:
                raise AssertionError(
                    "Partition %d not in 3 zones (got %r)" % (part, zones))
            if 0 not in zones or 1 not in zones:
                raise AssertionError(
                    "Partition %d not in zones 0 and 1 (got %r)" %
                    (part, zones))

    def test_rerebalance(self):
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 256, 1: 256, 2: 256})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 3, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10003, 'device': 'sda1'})
        rb.pretend_min_part_hours_passed()
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 192, 1: 192, 2: 192, 3: 192})
        rb.set_dev_weight(3, 100)
        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts[3], 256)

    def test_add_rebalance_add_rebalance_delete_rebalance(self):
        # Test for https://bugs.launchpad.net/swift/+bug/845952
        # min_part of 0 to allow for rapid rebalancing
        rb = ring.RingBuilder(8, 3, 0)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})

        rb.rebalance()

        rb.add_dev({'id': 3, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10003, 'device': 'sda1'})
        rb.add_dev({'id': 4, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10004, 'device': 'sda1'})
        rb.add_dev({'id': 5, 'region': 0, 'zone': 2, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10005, 'device': 'sda1'})

        rb.rebalance()

        rb.remove_dev(1)

        rb.rebalance()

    def test_set_replicas_increase(self):
        rb = ring.RingBuilder(8, 2, 0)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.rebalance()
        rb.validate()

        rb.replicas = 2.1
        rb.rebalance()
        rb.validate()

        self.assertEqual([len(p2d) for p2d in rb._replica2part2dev],
                         [256, 256, 25])

        rb.replicas = 2.2
        rb.rebalance()
        rb.validate()
        self.assertEqual([len(p2d) for p2d in rb._replica2part2dev],
                         [256, 256, 51])

    def test_set_replicas_decrease(self):
        rb = ring.RingBuilder(4, 5, 0)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.rebalance()
        rb.validate()

        rb.replicas = 4.9
        rb.rebalance()
        print repr(rb._replica2part2dev)
        print repr(rb.devs)
        rb.validate()

        self.assertEqual([len(p2d) for p2d in rb._replica2part2dev],
                         [16, 16, 16, 16, 14])

        # cross a couple of integer thresholds (4 and 3)
        rb.replicas = 2.5
        rb.rebalance()
        rb.validate()

        self.assertEqual([len(p2d) for p2d in rb._replica2part2dev],
                         [16, 16, 8])

    def test_fractional_replicas_rebalance(self):
        rb = ring.RingBuilder(8, 2.5, 0)
        rb.add_dev({'id': 0, 'region': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.rebalance()  # passes by not crashing
        rb.validate()   # also passes by not crashing
        self.assertEqual([len(p2d) for p2d in rb._replica2part2dev],
                         [256, 256, 128])

    def test_load(self):
        rb = ring.RingBuilder(8, 3, 1)
        devs = [{'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                 'ip': '127.0.0.0', 'port': 10000, 'device': 'sda1',
                 'meta': 'meta0'},
                {'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                 'ip': '127.0.0.1', 'port': 10001, 'device': 'sdb1',
                 'meta': 'meta1'},
                {'id': 2, 'region': 0, 'zone': 2, 'weight': 2,
                 'ip': '127.0.0.2', 'port': 10002, 'device': 'sdc1',
                 'meta': 'meta2'},
                {'id': 3, 'region': 0, 'zone': 3, 'weight': 2,
                 'ip': '127.0.0.3', 'port': 10003, 'device': 'sdd1'}]
        for d in devs:
            rb.add_dev(d)
        rb.rebalance()

        real_pickle = pickle.load
        try:
            #test a legit builder
            fake_pickle = mock.Mock(return_value=rb)
            fake_open = mock.Mock(return_value=None)
            pickle.load = fake_pickle
            builder = ring.RingBuilder.load('fake.builder', open=fake_open)
            self.assertEquals(fake_pickle.call_count, 1)
            fake_open.assert_has_calls([mock.call('fake.builder', 'rb')])
            self.assertEquals(builder, rb)
            fake_pickle.reset_mock()
            fake_open.reset_mock()

            #test old style builder
            fake_pickle.return_value = rb.to_dict()
            pickle.load = fake_pickle
            builder = ring.RingBuilder.load('fake.builder', open=fake_open)
            fake_open.assert_has_calls([mock.call('fake.builder', 'rb')])
            self.assertEquals(builder.devs, rb.devs)
            fake_pickle.reset_mock()
            fake_open.reset_mock()

            #test old devs but no meta
            no_meta_builder = rb
            for dev in no_meta_builder.devs:
                del(dev['meta'])
            fake_pickle.return_value = no_meta_builder
            pickle.load = fake_pickle
            builder = ring.RingBuilder.load('fake.builder', open=fake_open)
            fake_open.assert_has_calls([mock.call('fake.builder', 'rb')])
            self.assertEquals(builder.devs, rb.devs)
            fake_pickle.reset_mock()
        finally:
            pickle.load = real_pickle

    def test_save_load(self):
        rb = ring.RingBuilder(8, 3, 1)
        devs = [{'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                 'ip': '127.0.0.0', 'port': 10000,
                 'replication_ip': '127.0.0.0', 'replication_port': 10000,
                 'device': 'sda1', 'meta': 'meta0'},
                {'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                 'ip': '127.0.0.1', 'port': 10001,
                 'replication_ip': '127.0.0.1', 'replication_port': 10001,
                 'device': 'sdb1', 'meta': 'meta1'},
                {'id': 2, 'region': 0, 'zone': 2, 'weight': 2,
                 'ip': '127.0.0.2', 'port': 10002,
                 'replication_ip': '127.0.0.2', 'replication_port': 10002,
                 'device': 'sdc1', 'meta': 'meta2'},
                {'id': 3, 'region': 0, 'zone': 3, 'weight': 2,
                 'ip': '127.0.0.3', 'port': 10003,
                 'replication_ip': '127.0.0.3', 'replication_port': 10003,
                 'device': 'sdd1', 'meta': ''}]
        for d in devs:
            rb.add_dev(d)
        rb.rebalance()
        builder_file = os.path.join(self.testdir, 'test_save.builder')
        rb.save(builder_file)
        loaded_rb = ring.RingBuilder.load(builder_file)
        self.maxDiff = None
        self.assertEquals(loaded_rb.to_dict(), rb.to_dict())

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('swift.common.ring.builder.pickle.dump', autospec=True)
    def test_save(self, mock_pickle_dump, mock_open):
        mock_open.return_value = mock_fh = mock.MagicMock()
        rb = ring.RingBuilder(8, 3, 1)
        devs = [{'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                 'ip': '127.0.0.0', 'port': 10000, 'device': 'sda1',
                 'meta': 'meta0'},
                {'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                 'ip': '127.0.0.1', 'port': 10001, 'device': 'sdb1',
                 'meta': 'meta1'},
                {'id': 2, 'region': 0, 'zone': 2, 'weight': 2,
                 'ip': '127.0.0.2', 'port': 10002, 'device': 'sdc1',
                 'meta': 'meta2'},
                {'id': 3, 'region': 0, 'zone': 3, 'weight': 2,
                 'ip': '127.0.0.3', 'port': 10003, 'device': 'sdd1'}]
        for d in devs:
            rb.add_dev(d)
        rb.rebalance()
        rb.save('some.builder')
        mock_open.assert_called_once_with('some.builder', 'wb')
        mock_pickle_dump.assert_called_once_with(rb.to_dict(),
                                                 mock_fh.__enter__(),
                                                 protocol=2)

    def test_search_devs(self):
        rb = ring.RingBuilder(8, 3, 1)
        devs = [{'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                 'ip': '127.0.0.0', 'port': 10000, 'device': 'sda1',
                 'meta': 'meta0'},
                {'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                 'ip': '127.0.0.1', 'port': 10001, 'device': 'sdb1',
                 'meta': 'meta1'},
                {'id': 2, 'region': 1, 'zone': 2, 'weight': 2,
                 'ip': '127.0.0.2', 'port': 10002, 'device': 'sdc1',
                 'meta': 'meta2'},
                {'id': 3, 'region': 1, 'zone': 3, 'weight': 2,
                 'ip': '127.0.0.3', 'port': 10003, 'device': 'sdd1',
                 'meta': 'meta3'},
                {'id': 4, 'region': 2, 'zone': 4, 'weight': 1,
                 'ip': '127.0.0.4', 'port': 10004, 'device': 'sde1',
                 'meta': 'meta4', 'replication_ip': '127.0.0.10',
                 'replication_port': 20000},
                {'id': 5, 'region': 2, 'zone': 5, 'weight': 2,
                 'ip': '127.0.0.5', 'port': 10005, 'device': 'sdf1',
                 'meta': 'meta5', 'replication_ip': '127.0.0.11',
                 'replication_port': 20001},
                {'id': 6, 'region': 2, 'zone': 6, 'weight': 2,
                 'ip': '127.0.0.6', 'port': 10006, 'device': 'sdg1',
                 'meta': 'meta6', 'replication_ip': '127.0.0.12',
                 'replication_port': 20002}]
        for d in devs:
            rb.add_dev(d)
        rb.rebalance()
        res = rb.search_devs({'region': 0})
        self.assertEquals(res, [devs[0], devs[1]])
        res = rb.search_devs({'region': 1})
        self.assertEquals(res, [devs[2], devs[3]])
        res = rb.search_devs({'region': 1, 'zone': 2})
        self.assertEquals(res, [devs[2]])
        res = rb.search_devs({'id': 1})
        self.assertEquals(res, [devs[1]])
        res = rb.search_devs({'zone': 1})
        self.assertEquals(res, [devs[1]])
        res = rb.search_devs({'ip': '127.0.0.1'})
        self.assertEquals(res, [devs[1]])
        res = rb.search_devs({'ip': '127.0.0.1', 'port': 10001})
        self.assertEquals(res, [devs[1]])
        res = rb.search_devs({'port': 10001})
        self.assertEquals(res, [devs[1]])
        res = rb.search_devs({'replication_ip': '127.0.0.10'})
        self.assertEquals(res, [devs[4]])
        res = rb.search_devs({'replication_ip': '127.0.0.10',
                              'replication_port': 20000})
        self.assertEquals(res, [devs[4]])
        res = rb.search_devs({'replication_port': 20000})
        self.assertEquals(res, [devs[4]])
        res = rb.search_devs({'device': 'sdb1'})
        self.assertEquals(res, [devs[1]])
        res = rb.search_devs({'meta': 'meta1'})
        self.assertEquals(res, [devs[1]])

    def test_validate(self):
        rb = ring.RingBuilder(8, 3, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 2, 'region': 0, 'zone': 2, 'weight': 2,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.add_dev({'id': 3, 'region': 0, 'zone': 3, 'weight': 2,
                    'ip': '127.0.0.1', 'port': 10003, 'device': 'sda1'})

        # Degenerate case: devices added but not rebalanced yet
        self.assertRaises(exceptions.RingValidationError, rb.validate)

        rb.rebalance()
        r = rb.get_ring()
        counts = {}
        for part2dev_id in r._replica2part2dev_id:
            for dev_id in part2dev_id:
                counts[dev_id] = counts.get(dev_id, 0) + 1
        self.assertEquals(counts, {0: 128, 1: 128, 2: 256, 3: 256})

        dev_usage, worst = rb.validate()
        self.assert_(dev_usage is None)
        self.assert_(worst is None)

        dev_usage, worst = rb.validate(stats=True)
        self.assertEquals(list(dev_usage), [128, 128, 256, 256])
        self.assertEquals(int(worst), 0)

        rb.set_dev_weight(2, 0)
        rb.rebalance()
        self.assertEquals(rb.validate(stats=True)[1], MAX_BALANCE)

        # Test not all partitions doubly accounted for
        rb.devs[1]['parts'] -= 1
        self.assertRaises(exceptions.RingValidationError, rb.validate)
        rb.devs[1]['parts'] += 1

        # Test non-numeric port
        rb.devs[1]['port'] = '10001'
        self.assertRaises(exceptions.RingValidationError, rb.validate)
        rb.devs[1]['port'] = 10001

        # Test partition on nonexistent device
        rb.pretend_min_part_hours_passed()
        orig_dev_id = rb._replica2part2dev[0][0]
        rb._replica2part2dev[0][0] = len(rb.devs)
        self.assertRaises(exceptions.RingValidationError, rb.validate)
        rb._replica2part2dev[0][0] = orig_dev_id

        # Tests that validate can handle 'holes' in .devs
        rb.remove_dev(2)
        rb.pretend_min_part_hours_passed()
        rb.rebalance()
        rb.validate(stats=True)

        # Test partition assigned to a hole
        if rb.devs[2]:
            rb.remove_dev(2)
        rb.pretend_min_part_hours_passed()
        orig_dev_id = rb._replica2part2dev[0][0]
        rb._replica2part2dev[0][0] = 2
        self.assertRaises(exceptions.RingValidationError, rb.validate)
        rb._replica2part2dev[0][0] = orig_dev_id

        # Validate that zero weight devices with no partitions don't count on
        # the 'worst' value.
        self.assertNotEquals(rb.validate(stats=True)[1], MAX_BALANCE)
        rb.add_dev({'id': 4, 'region': 0, 'zone': 0, 'weight': 0,
                    'ip': '127.0.0.1', 'port': 10004, 'device': 'sda1'})
        rb.pretend_min_part_hours_passed()
        rb.rebalance()
        self.assertNotEquals(rb.validate(stats=True)[1], MAX_BALANCE)

    def test_get_part_devices(self):
        rb = ring.RingBuilder(8, 3, 1)
        self.assertEqual(rb.get_part_devices(0), [])

        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.rebalance()

        part_devs = sorted(rb.get_part_devices(0),
                           key=operator.itemgetter('id'))
        self.assertEqual(part_devs, [rb.devs[0], rb.devs[1]])

    def test_get_part_devices_partial_replicas(self):
        rb = ring.RingBuilder(8, 2.5, 1)
        rb.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 1, 'region': 0, 'zone': 1, 'weight': 1,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.rebalance()

        # note: partition 255 will only have 2 replicas
        part_devs = sorted(rb.get_part_devices(255),
                           key=operator.itemgetter('id'))
        self.assertEqual(part_devs, [rb.devs[0], rb.devs[1]])


if __name__ == '__main__':
    unittest.main()
