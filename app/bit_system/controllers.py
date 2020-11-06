from flask import Blueprint, request, render_template, flash, g, session, redirect, url_for
from .ipfs import *
from .main import *
from app.bit_system.models import Contracts

bit_system = Blueprint('bit', __name__, url_prefix="/process")

CONNECTED_NODE_ADDRESS="http://127.0.0.1:5000"

posts=[]
peers = set()
blockchain = Blockchain()

# Endpoint to add new peers to the network
@app.route('/register_node', methods=['POST'])
def register_new_peers():
    # The host address of the peer node.
    node_address = request.get_json()['node_address']
    if not node_address:
        return "Invalid data", 400

    # Add the node to the peer list
    peers.add(node_address)
    # Syncing the block chain with the newly created node.
    return get_chain()

@app.route('/register_with', methods=['POST'])
def register_with_existing_node():
    """
    Internally calls the `register_node` endpoint to
    register current node with the remote node specified in the
    request, and sync the blockchain as well with the remote node.
    """
    node_address = request.get_json()['node_address']
    if not node_address:
        return "Invalid data", 400
    
    data = {"node_address": request.host_url}
    headers = {"Content-Type": "application/json"}

    # Make a request to register with remote node and obtain information
    response = requests.post(node_address + "/process/register_node", data=json.dumps(data), headers=headers)

    if response.status_code == 200:
        global blockchain
        global peers
        # update chain and the peers
        chain_dump = response.json()['chain']
        blockchain = create_chain_from_dump(chain_dump)
        peers.update(response.json()['peers'])
        return "Registration succesful", 200
    else:
        # if something goes wrong, pass it on to the API Response
        return response.content, response.status_code

def create_chain_from_dump(chain_dump):
    blockchain = Blockchain()
    for idx, block_data in enumerate(chain_dump):
        block = Block(block_data['index'],
                    block_data['transactions'],
                    block_data['timestamp'],
                    block_data['previous_hash'])
        
        proof = block_data['hash']
        if idx > 0:
            added = blockchain.add_block(block, proof)
            if not added:
                raise Exception("The chain dump is tempered!!")
        else: # The block is a genesis block aka the first block, no verification is needed.
            blockchain.chain.append(block)
    return blockchain

def fetch_posts():
    """
    Function to fetch the chain from a blockchain node, parse the
    data, and store it locally.
    """
    get_chain_address = "{}/chain".format(CONNECTED_NODE_ADDRESS)
    response = requests.get(get_chain_address)
    if response.status_code == 200:
        content = []
        chain = json.loads(response.content)
        for block in chain["chain"]:
            for tx in block["transactions"]:
                tx["index"] = block["previous_hash"]
                content.append(tx)
    
    global posts
    posts = sorted(content, key = lambda k : k['timestamp'], reverse = True)

# endpoint to add a block mined by someone else to
# the node's chain. The node first verifies the block
# and then adds it to the chain.
@bit_system.route('/add_block', methods=['POST'])
def verify_and_add_block():
    block_data = request.get_json()
    block = Block(block_data["index"],
                  block_data["transactions"],
                  block_data["timestamp"],
                  block_data["previous_hash"])

    proof = block_data['hash']
    added = blockchain.add_block(block, proof)

    if not added:
        return "The block was discarded by the node", 400

    return "Block added to the chain", 201


def announce_new_block(block):
    """
    A function to announce to the network once a block has been mined.
    Other blocks can simply verify the proof of work and add it to their
    respective chains.
    """
    for peer in peers:
        url = "{}add_block".format(peer)
        requests.post(url, data=json.dumps(block.__dict__, sort_keys=True))

def consensus():
    """
    Our simple consensus algorithm. If a longer valid chain is
    found, our chain is replaced with it.
    """
    global blockchain

    longest_chain = None
    current_len = len(blockchain.chain)

    for node in peers:
        response = requests.get('{}/chain'.format(node))
        length = response.json()['length']
        chain = response.json()['chain']
        if length > current_len and blockchain.check_chain_validity(chain):
              # Longer valid chain found!
            current_len = length
            longest_chain = chain

    if longest_chain:
        blockchain = longest_chain
        return True

    return False



@bit_system.route('/mine', methods=['GET'])
def mine_unconfirmed_transactions():
    result = blockchain.mine()
    if not result:
        return "No transactions to mine"
    else:
        # Making sure we have the longest chain before announcing to the network
        chain_length = len(blockchain.chain)
        consensus()
        if chain_length == len(blockchain.chain):
            # announce the recently mined block to the network
            announce_new_block(blockchain.last_block)
        return "Block #{} is mined.".format(blockchain.last_block.index)




@bit_system.route('/post', methods=['POST'])
def publish():
    title = request.form.get('title')
    content = request.form.get('content')
    url = request.form.get('url')
    urlToImage = request.form.get('urlToImage')
    subject = request.form.get('subject')

    objString = '''
    {
        'title': {title},
        'subject': {subject},
        'content': {content},
        'url': {url},
        'urlToImage': {urlToImage},
    }
    '''.format(title=title, subject=subject, content=content, url=url, urlToImage=urlToImage)
    
    hash = upload_json(objString)
    

