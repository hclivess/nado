# NADO

## Installation

```
python -m pip install pip --upgrade
git clone https://github.com/hclivess/nado
cd nado
python -m pip install -r requirements.txt
python nado.py
```

After installation, go to your browser and announce your peer to one of the nodes like this:
[http://207.180.218.90:9173/announce_peer?ip=89.176.130.244](http://207.180.218.90:9173/announce_peer?ip=89.176.130.244) but put your own IP as the argument after ```ip=```


## What is NADO?

Nado is just another blockchain written from scratch with a highly experimental consensus algorithm, which is supposed
to provide effortless mining for all participants with a public IP address. Nado is not a classic proof-of-work
blockchain like Bitcoin. Unlike most other crypto, its focus is on accessibility to rewards for everyone. It has a fully
elastic reward mechanism, rewarding users only when transactions are happening on the chain.

## Why is NADO?

NADO is a take on one of the newer trends, where users do not use graphics cards or specialized hardware for mining, nor
do they have to own a large portion of tokens in order to be rewarded. It is inspired by IDENA and NYZO, while
attempting to bring the barrier of entry even lower than those two by not requiring solving of puzzles or highly
efficient machines for users to remain in a reward distribution cycle.

## What does NADO do differently?

In NADO, every user generates new blocks at the same time. This is possible because users are not rewarded for mining
blocks but for keeping the network running. After generating a block and receiving a reward, chances of receiving more
block rewards are temporarily lowered based on the public IP address. Every IP address can only have one block
generating node. While this excludes users without public addresses, it prevents node spamming to a degree.

## Sounds interesting, can you elaborate?

There are multiple cycles for every block. It starts with accepting peers and transactions directly. In the second
stage, transactions and peers are stored in a buffer for the following block so that transactions can stabilize across
the network. NADO prefers decentralization over efficiency, which means it exposes consensus more than the invidual
node, which makes it more resilient regarding SPOF but less efficient.

## But is there a premise?

The premise of NADO is that users stop being interested in decentralized value distributing projects because it becomes
progressively more difficult for them to join them or remain as time goes on.

- With PoW, the problem is in the arms race.
- With PoS, the problem is in the rising price.
- With PoD, the problem is in the increasing number of cycle participants.

## Proof of what?

Every node in the NADO ecosystem keeps track of what opinions other nodes have by sharing state checksums for current
block producer pools, transaction pools, peer pools and block hash pools. Participants add credibility over time to
those who share their opinions on what the state of the network is.

## What about security?

There are no guarantees for security of NADO, mainly because of its highly experimental character. Compared to more
excluding networks like Bitcoin, security will always be lower as the main focus is on lowering the entry level for new
users to make mining as inclusive as possible.

## How many decimals are there and what are the units called?

1 NADO can be split into 1,000,000,000 units.

## Where can I learn more?

www.nado.live
