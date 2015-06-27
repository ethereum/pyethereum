import rlp
import ethereum.utils as utils
import sys

DEATH_ROW_OFFSET = 2**62
ZERO_ENCODED = utils.encode_int(0)
ONE_ENCODED = utils.encode_int(1)


class RefcountDB(object):
    def __init__(self, db):
        self.db = db
        self.journal = []
        self.death_row = []
        self.kv = self.db.kv
        self.ttl = 5000

    # Increase the reference count associated with a key
    def inc_refcount(self, k, v):
        try:
            node_object = rlp.decode(self.db.get('r:'+k))
            refcount = utils.decode_int(node_object[0])
            self.journal.append([node_object[0], k])
            if refcount >= DEATH_ROW_OFFSET:
                refcount = 0
            new_refcount = utils.encode_int(refcount + 1)
            self.db.put('r:'+k, rlp.encode([new_refcount, node_object[1]]))
        except:
            self.db.put('r:'+k, rlp.encode([ONE_ENCODED, v]))
            self.journal.append([ZERO_ENCODED, k])

    put = inc_refcount

    # Decrease the reference count associated with a key
    def dec_refcount(self, k):
        try:
            node_object = rlp.decode(self.db.get('r:'+k))
            refcount = utils.decode_int(node_object[0])
            self.journal.append([node_object[0], k])
            new_refcount = utils.encode_int(refcount - 1)
            self.db.put('r:'+k, rlp.encode([new_refcount, node_object[1]]))
            if new_refcount == ZERO_ENCODED:
                self.death_row.append(k)
        except:
            pass

    delete = dec_refcount

    # Get the value associated with a key
    def get(self, k):
        return rlp.decode(self.db.get('r:'+k))[1]

    # Kill nodes that are eligible to be killed, and remove the associated
    # deathrow record. Also delete old journals.
    def cleanup(self, epoch):
        try:
            death_row_node = self.db.get('deathrow:'+str(epoch))
        except:
            death_row_node = rlp.encode([])
        death_row_nodes = rlp.decode(death_row_node)
        pruned = 0
        for nodekey in death_row_nodes:
            try:
                refcount, val = rlp.decode(self.db.get('r:'+nodekey))
                if utils.decode_int(refcount) == DEATH_ROW_OFFSET + epoch:
                    self.db.delete('r:'+nodekey)
                    pruned += 1
            except:
                pass
        sys.stderr.write('%d nodes successfully pruned\n' % pruned)
        # Delete the deathrow after processing it
        try:
            self.db.delete('deathrow:'+str(epoch))
        except:
            pass
        # Delete journals that are too old
        try:
            self.db.delete('journal:'+str(epoch - self.ttl))
        except:
            pass

    # Commit changes to the journal and death row to the database
    def commit_refcount_changes(self, epoch):
        # Save death row nodes
        timeout_epoch = epoch + self.ttl
        try:
            death_row_nodes = rlp.decode(self.db.get('deathrow:'+str(timeout_epoch)))
        except:
            death_row_nodes = []
        for nodekey in self.nodes_for_death_row:
            refcount, val = rlp.decode(self.db.get('node:'+nodekey))
            if refcount == ZERO_ENCODED:
                new_refcount = utils.encode_int(DEATH_ROW_OFFSET + timeout_epoch)
                self.db.put('node:'+nodekey, rlp.encode([new_refcount, val]))
        if len(self.nodes_for_death_row) > 0:
            sys.stderr.write('%d nodes marked for pruning during block %d\n' %
                             (len(self.nodes_for_death_row), timeout_epoch))
        death_row_nodes.extend(self.nodes_for_death_row)
        self.nodes_for_death_row = []
        self.db.put('deathrow:'+str(timeout_epoch),
                    rlp.encode(death_row_nodes))
        # Save journal
        try:
            journal = rlp.decode(self.db.get('journal:'+str(epoch)))
        except:
            journal = []
        journal.extend(self.journal)
        self.journal = []
        self.db.put('journal:'+str(epoch), rlp.encode(journal))

    # Revert changes made during an epoch
    def revert_changes(self, epoch):
        timeout_epoch = epoch + self.ttl
        # Delete death row additions
        try:
            self.db.delete('deathrow:'+str(timeout_epoch))
        except:
            pass
        # Revert journal changes
        try:
            journal = rlp.decode(self.db.get('journal:'+str(epoch)))
            for new_refcount, hashkey in journal[::-1]:
                node_object = rlp.decode(self.db.get('r:'+hashkey))
                self.db.put('r:'+hashkey,
                            rlp.encode([new_refcount, node_object[1]]))
        except:
            pass
