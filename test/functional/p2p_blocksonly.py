#!/usr/bin/env python3
# Copyright (c) 2019-2020 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test p2p blocksonly mode & block-relay-only connections."""

from test_framework.blocktools import create_transaction
from test_framework.messages import msg_tx
from test_framework.p2p import P2PInterface
from test_framework.test_framework import BGLTestFramework
from test_framework.util import assert_equal


class P2PBlocksOnly(BGLTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.extra_args = [["-blocksonly"]]

    def skip_test_if_missing_module(self):
        self.skip_if_no_wallet()

    def run_test(self):
        block_relay_peer = self.nodes[0].add_p2p_connection(P2PInterface())

        input_txid = self.nodes[0].getblock(self.nodes[0].getblockhash(1), 2)['tx'][0]['txid']
        tx = create_transaction(self.nodes[0], input_txid, self.nodes[0].getnewaddress(), amount=(50 - 0.001))
        txid = tx.rehash()
        tx_hex = tx.serialize().hex()

        assert_equal(self.nodes[0].getnetworkinfo()['localrelay'], False)
        with self.nodes[0].assert_debug_log(['transaction sent in violation of protocol peer=0']):
            block_relay_peer.send_message(msg_tx(tx))
            block_relay_peer.wait_for_disconnect()
            assert_equal(self.nodes[0].getmempoolinfo()['size'], 0)

        self.nodes[0].add_p2p_connection(P2PInterface())
        tx, txid, tx_hex = self.check_p2p_tx_violation()

        self.log.info('Check that txs from rpc are not rejected and relayed to other peers')
        tx_relay_peer = self.nodes[0].add_p2p_connection(P2PInterface())
        assert_equal(self.nodes[0].getpeerinfo()[0]['relaytxes'], True)

        assert_equal(self.nodes[0].testmempoolaccept([tx_hex])[0]['allowed'], True)
        with self.nodes[0].assert_debug_log(['received getdata for: wtx {} peer=1'.format(txid)]):
            self.nodes[0].sendrawtransaction(tx_hex)
            tx_relay_peer.wait_for_tx(txid)
            assert_equal(self.nodes[0].getmempoolinfo()['size'], 1)

        self.log.info("Restarting node 0 with relay permission and blocksonly")
        self.restart_node(0, ["-persistmempool=0", "-whitelist=relay@127.0.0.1", "-blocksonly"])
        assert_equal(self.nodes[0].getrawmempool(), [])
        first_peer = self.nodes[0].add_p2p_connection(P2PInterface())
        second_peer = self.nodes[0].add_p2p_connection(P2PInterface())
        peer_1_info = self.nodes[0].getpeerinfo()[0]
        assert_equal(peer_1_info['permissions'], ['relay'])
        peer_2_info = self.nodes[0].getpeerinfo()[1]
        assert_equal(peer_2_info['permissions'], ['relay'])
        assert_equal(self.nodes[0].testmempoolaccept([tx_hex])[0]['allowed'], True)

        self.log.info('Check that the tx from first_peer with relay-permission is relayed to others (ie.second_peer)')
        with self.nodes[0].assert_debug_log(["received getdata"]):
            # Note that normally, first_peer would never send us transactions since we're a blocksonly node.
            # By activating blocksonly, we explicitly tell our peers that they should not send us transactions,
            # and BGL Core respects that choice and will not send transactions.
            # But if, for some reason, first_peer decides to relay transactions to us anyway, we should relay them to
            # second_peer since we gave relay permission to first_peer.
            # See https://github.com/bitcoin/bitcoin/issues/19943 for details.
            first_peer.send_message(msg_tx(tx))
            self.log.info('Check that the peer with relay-permission is still connected after sending the transaction')
            assert_equal(first_peer.is_connected, True)
            second_peer.wait_for_tx(txid)
            assert_equal(self.nodes[0].getmempoolinfo()['size'], 1)
        self.log.info("Relay-permission peer's transaction is accepted and relayed")

    def check_p2p_tx_violation(self):
        self.log.info('Check that txs from P2P are rejected and result in disconnect')

        input_txid = self.nodes[0].getblock(self.nodes[0].getblockhash(1), 2)['tx'][0]['txid']
        tx = create_transaction(self.nodes[0], input_txid, self.nodes[0].getnewaddress(), amount=(50 - 0.001))
        txid = tx.rehash()
        tx_hex = tx.serialize().hex()

        with self.nodes[0].assert_debug_log(['transaction sent in violation of protocol peer=0']):
            self.nodes[0].p2ps[0].send_message(msg_tx(tx))
            self.nodes[0].p2ps[0].wait_for_disconnect()
            assert_equal(self.nodes[0].getmempoolinfo()['size'], 0)

        # Remove the disconnected peer
        del self.nodes[0].p2ps[0]

        return tx, txid, tx_hex

if __name__ == '__main__':
    P2PBlocksOnly().main()
