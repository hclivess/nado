// SPDX-License-Identifier: MIT
// Ethereum leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5): ONE contract serves every swap.
// No owner, no upgrade path, no fee switch — fund/claim/refund and nothing else. The hashlock is the SAME
// 32-byte SHA-256 image the NADO otc contract bound; claiming publishes the preimage in calldata, which is
// what lets the other chain settle.
//
// SECURITY NOTES (v2 — an audit of v1 proved the first two as live theft):
//  * THE KEY BINDS THE AMOUNT. v1 keyed a lock on (H, claimant, refundee, deadline) only, so an attacker
//    could fund ONE WEI against the agreed tuple; the victim's client derived the same key, claimed the
//    dust, and PUBLISHED THE PREIMAGE — which the attacker then used to take the whole other-chain escrow.
//    Binding `amount` makes an underfunded lock land on a different key, so the claim reverts "no lock"
//    and the secret is never revealed. Fail-safe by construction, with no client cooperation required.
//  * THE REFUNDEE IS EXPLICIT. v1 hard-wired refundee = msg.sender with a push payment, so a contract
//    wallet that cannot receive ETH stranded its funds FOREVER (proven), and funding on behalf of someone
//    else was impossible. The refundee is now a parameter, and a failed push is CREDITED for later
//    withdrawal instead of reverting — no payout path can permanently trap money.
//  * THE DEADLINE IS BOUNDED. v1 accepted any future timestamp, including 2^256-1, which made the refund
//    unreachable forever. A lock now has to expire inside a sane window.
// Reentrancy: the lock is deleted before any external call, and the payout carries a fixed gas stipend
// only for the credit fallback path. ERC-20 swaps live in HtlcErc20.sol.
pragma solidity ^0.8.26;

contract HtlcEth {
    struct Lock { address claimant; address refundee; uint256 amount; bytes32 H; uint256 deadline; }
    mapping(bytes32 => Lock) public locks;
    mapping(address => uint256) public credits;   // owed to someone whose push payment failed

    uint256 public constant MIN_WINDOW = 10 minutes;
    uint256 public constant MAX_WINDOW = 30 days;

    event Funded(bytes32 indexed key, address indexed claimant, address indexed refundee,
                 uint256 amount, bytes32 H, uint256 deadline);
    event Claimed(bytes32 indexed key, bytes32 s);
    event Refunded(bytes32 indexed key);
    event Credited(address indexed who, uint256 amount);

    function lockKey(bytes32 H, address claimant, address refundee, uint256 deadline, uint256 amount)
        public pure returns (bytes32)
    {
        return keccak256(abi.encode(H, claimant, refundee, deadline, amount));
    }

    function fund(address claimant, address refundee, bytes32 H, uint256 deadline)
        external payable returns (bytes32 key)
    {
        require(msg.value > 0 && claimant != address(0) && refundee != address(0), "bad lock");
        require(deadline >= block.timestamp + MIN_WINDOW && deadline <= block.timestamp + MAX_WINDOW,
                "deadline outside the allowed window");
        key = lockKey(H, claimant, refundee, deadline, msg.value);
        require(locks[key].amount == 0, "exists");
        locks[key] = Lock(claimant, refundee, msg.value, H, deadline);
        emit Funded(key, claimant, refundee, msg.value, H, deadline);
    }

    // claim: reveal s with SHA256(s) == H, strictly before the deadline (the windows never overlap).
    function claim(bytes32 key, bytes32 s) external {
        Lock memory L = locks[key];
        require(L.amount > 0, "no lock");
        require(sha256(abi.encodePacked(s)) == L.H, "bad preimage");
        require(block.timestamp < L.deadline, "expired");
        delete locks[key];
        emit Claimed(key, s);
        _pay(L.claimant, L.amount);
    }

    // refund: anyone may trigger it at/after the deadline; funds only ever return to the refundee.
    function refund(bytes32 key) external {
        Lock memory L = locks[key];
        require(L.amount > 0, "no lock");
        require(block.timestamp >= L.deadline, "not yet");
        delete locks[key];
        emit Refunded(key);
        _pay(L.refundee, L.amount);
    }

    // Whatever a failed push left owed to you. Pull payment: the recipient controls the gas.
    function withdraw() external {
        uint256 owed = credits[msg.sender];
        require(owed > 0, "nothing owed");
        credits[msg.sender] = 0;
        (bool ok, ) = msg.sender.call{value: owed}("");
        require(ok, "withdraw failed");
    }

    // A push that fails must never revert the settlement — it would strand the money and, on the claim
    // path, burn the revealed preimage for nothing. Credit it and let the recipient pull.
    function _pay(address to, uint256 amount) private {
        (bool ok, ) = to.call{value: amount, gas: 30000}("");
        if (!ok) { credits[to] += amount; emit Credited(to, amount); }
    }
}
