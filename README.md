<p align="center">
  <a href="https://nado.live"><img src="graphics/bauhaus.png" /></a>
</p>

<p align="center">
    <a href="https://discord.gg/6aEBWTvcTV"><img src="graphics/discord.png" /></a>
    &emsp;
    <a href="https://twitter.com/nadodigital"><img src="graphics/twitter.png" /></a>

</p>

## Notice
NADO mainnet is released.

## Installation
### Linux

#### Direct installation one-liner
```
sysctl -w fs.file-max=65535 && sudo apt-get update && sudo add-apt-repository ppa:deadsnakes/ppa -y && sudo apt-get install python3.10 python3.10-distutils git screen curl -y && curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.10 && sudo ufw allow 9173 && git clone https://github.com/hclivess/nado && cd nado && python3.10 -m pip install -r requirements.txt && screen -dmS nado python3.10 nado.py
```

#### Virtual environment installation

```
sysctl -w fs.file-max=65535
screen -S nado
sudo apt-get update
sudo apt-get install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
apt-get install python3.10-dev python3.10-venv
python3.10 -m venv nado_venv
source nado_venv/bin/activate
pip install --upgrade pip
git clone https://github.com/hclivess/nado
cd nado
pip install -r requirements.txt
```

To go back to your screen, use `screen -r nado` 
To update your NADO installation, use 

```
git reset --hard origin/main
git pull origin main
```

from the directory where you have it installed.

### Windows

There is a [release page in GitHub](https://github.com/hclivess/nado/releases), which is periodically updated when major changes occur. 
The easiest way to run NADO for Windows users is to use the `nado.exe` binary from there.

It is also possible to install [Python on Windows](https://www.python.org/downloads/) and run NADO directly. Command line instructions:

#### Direct installation
First [download](https://github.com/hclivess/nado/archive/refs/heads/main.zip) the master branch from GitHub and extract the archive.
Run the command line as Administrator and enter the following commands:
```
python -m pip install -r requirements.txt
```

### To run NADO, execute the following command: `python3.10 nado.py`

After installation, go to your browser and announce your peer to one of the nodes like this:
http://127.0.0.1:9173/announce_peer?ip=207.180.203.132. For this,
you should have [port 9173 open](https://www.google.com/search?q=port+forwarding+guide) so the node is accessible from the internet if you want to receive rewards. After this step, synchronization should start shortly. 

## Wallet
You can download the [official NADO wallet here](https://github.com/hclivess/nado-microwallet) or on the [release page of NADO](https://github.com/hclivess/nado/releases).

## Remote access

After running the node, you can access it at http://127.0.0.1:9173 from where all API calls used by the node itself are accessible. Here are some examples:
- http://127.0.0.1:9173/get_account?address=ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29

## Private key storage
In previous versions, private key was stored in the folder where NADO is installed, under `private` directory, specifically in the `keys.dat` file. With the latest version,
this file is stored in user's home directory, `/~/nado/private/keys.dat` in Linux and `C:\Users\[username]\nado\private` in Windows. 

## Is there anything unique?

Yes. No mining, minting, block production happens in every node at once, based on the deterministic principles of the
blockchain. This is possible because block production is separated from the consensual layer. This removes all the selfish
miner incentives, which cause issues like transaction exclusion in traditional PoW systems.

## What is NADO?

<p align="center">
  <img src="graphics/overview.png" />
</p>

NADO is short for Tornado. It is just another blockchain written from scratch with a highly experimental consensus algorithm, 
which was created to provide effortless mining for all participants with a public IP address. NADO is not a classic proof-of-work
blockchain like Bitcoin. Unlike most other crypto, its focus is on accessibility to rewards for everyone. It has a fully
elastic reward mechanism, rewarding users only when transactions are happening on the chain. Users can burn their share
of tokens in order to increase their chances of winning more rewards in the future.

## What's the reason for NADO?

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
the network. NADO prefers decentralization to efficiency, which means it exposes consensus more than the individual
node, which makes it more resilient regarding SPOF but less efficient.

## But is there a premise?

The premise of NADO is that users stop being interested in decentralized value distributing projects because it becomes
progressively more difficult for them to join them or remain as time goes on.
The main reason for users to leave is not the lack of adoption, but the mismatch between adoption, 
distribution and inflation. Distribution is the single one most important aspect of a cryptocurrency project as proven 
in the success of NANO, where no single entity was capable of obtaining a high amount of tokens through monopolizing 
token distribution. 

- Constant rewards are counterproductive: Users will keep running their nodes even though they are not receiving rewards
in a particular moment because there is no block reward for a particular block because network activity is low. Fighting
inflation is more important than hoping for users to not stop running nodes.

- Elastic distribution was one of the key promises of Vertcoin, one of the most popular cryptocurrencies 
of 2014. NADO puts these promises into practice. 

- Litecoin was created as a Bitcoin with fair distribution. None of the projects mentioned above put large 
effort into marketing and were extremely popular nonetheless.

- Barrier of entry is directly correlated to fairness of distribution. This is an idea on which Steve Jobs built his
entire business. Removal of hassles in Apple operating systems and simplicity of their mobile devices led to widespread 
adoption simply because there were no hurdles to adoption.

- Interestingly enough, some of the most successful "cryptocurrency projects" where pyramid schemes that had zero technology
in them: Bitcoinnect and Onecoin. All users had to do there was to go on a website and click a button to invest
money into something that did not exist. Why did they do it? Because it was easy.

- Combining great and accessible technology with perfect distribution and effective marketing is the key to successful adoption. 

## Why not only use the existing projects?

- With PoW, the problem is in the arms race.
- With PoS, the problem is in the rising price.
- With PoD, the problem is in the increasing difficulty to re-join mesh with more participants.

## Proof of what?

Every node in the NADO ecosystem keeps track of what opinions other nodes have by sharing state checksums for current
block producer pools, transaction pools, peer pools and block hash pools. Participants add credibility over time to
those who share their opinions on what the state of the network is. The security principle is that any
attacker needs to be connected to the network for a longer time than the legitimate nodes and postpone the attack until
their network participation duration is longer than that of other nodes - to perform a 51% attack. If the legitimate nodes
stay in the network longer than the attackers, it is impossible to attack.

## Burn-to-Bribe system and governance
In the beginning, all users have the same chance at receiving a reward every block. If they succeed, they are issued
both tokens and a penalty. This penalty lowers chance of further finding rewards in relation to users who have not been 
rewarded yet, but it can be negated by burning a portion of the coins they generated or obtained otherwise. 

The model is set up in 1:100 ratio, which means that 1 portion of burn negates 100 portions of penalty. Both penalty and burn 
are counted from the smallest unit of NADO, so the lowest penalty resolution is 0.0000000001 and the lowest burn/bribe 
resolution is 0.0000000100.

To prevent monopolization of reward distribution, the burn bonus is in effect only to the level of default value for the
account, which means that any account can at best have a bonus of an entirely fresh address.

This system was created as an additional measure against inflation 
after implementation of elastic distribution and burned tokens are used for governance purposes.

To burn your NADO, send it to the following address: `burn`


## What about security?

There are no guarantees for security of NADO, mainly because of its highly experimental character. Compared to more
excluding networks like Bitcoin, security will always be lower as the main focus is on lowering the entry level for new
users to make mining as inclusive as possible.

## How many decimals are there and what are the units called?

1 NADO can be split into 1,000,000,000 units.

## Got some sci-fi tech mumbo jumbo?
- Cryptography: Edwards-curve Digital Signature Algorithm (Ed25519)
- Link hashing: BLAKE2b
- Block capacity: Capped at 250KB per minute
- Block reward: Between 0 and 5 depending on network usage
- Transaction throughput: 7 raw transactions per second
- Proof of Fidelity with aspects of majority and diversity
- noSQL MessagePack file-based atomized database system
- Optional MessagePack formatting in API
- Shared mining protocol
- Periodic intervals to enforce consensus stabilization
- Burn-to-Bribe deflationary incentive and governance
- The logo is a vortexed version of the Impossible Toroidal Polyhedron

## Where can I learn more?

www.nado.live

## For developers
### Design philosophy

When implementing new functionalities to NADO, existing routines/loops should be used instead of instant invocation of functions.
Every function should have its place in the particular routine, which is responsible for it. If such routine does not exist, create it.

Standard development rules apply. Functions should be as small and as independent as possible, responsible for small tasks
after which they are named. Assignment of returns is preferred to object fungibility passed as arguments.

Synchronous loops are not allowed for multiple targets, always use the existing compounder. If you require a specific new
compounder function, feel free to add it.

### How to contribute

To contribute, you first have to fork this repository here on GitHub. After that, you make changes to your fork.
When you are done, you can ask for a merge request to have your changes to the code accepted to the repository.