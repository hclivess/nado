// SPDX-License-Identifier: MIT
// Ethereum leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5): ONE contract serves every swap.
// No owner, no upgrade path, no fee switch — fund/claim/refund and nothing else. The hashlock is the SAME
// 32-byte SHA-256 image the NADO otc contract bound at post; claiming publishes the preimage in calldata,
// which is what lets the other chain settle. ERC-20 swaps are this same shape with transferFrom/transfer.
pragma solidity ^0.8.26;

contract HtlcEth {
    struct Lock { address claimant; address refundee; uint256 amount; bytes32 H; uint256 deadline; }
    mapping(bytes32 => Lock) public locks;   // key: keccak256(H, claimant, refundee, deadline)

    event Funded(bytes32 indexed key, address indexed claimant, address indexed refundee,
                 uint256 amount, bytes32 H, uint256 deadline);
    event Claimed(bytes32 indexed key, bytes32 s);
    event Refunded(bytes32 indexed key);

    function fund(address claimant, bytes32 H, uint256 deadline) external payable returns (bytes32 key) {
        require(msg.value > 0 && claimant != address(0) && deadline > block.timestamp, "bad lock");
        key = keccak256(abi.encode(H, claimant, msg.sender, deadline));
        require(locks[key].amount == 0, "exists");
        locks[key] = Lock(claimant, msg.sender, msg.value, H, deadline);
        emit Funded(key, claimant, msg.sender, msg.value, H, deadline);
    }

    // claim: reveal s with SHA256(s) == H, strictly before the deadline (the refund window never overlaps).
    function claim(bytes32 key, bytes32 s) external {
        Lock memory L = locks[key];
        require(L.amount > 0, "no lock");
        require(sha256(abi.encodePacked(s)) == L.H, "bad preimage");
        require(block.timestamp < L.deadline, "expired");
        delete locks[key];
        emit Claimed(key, s);
        (bool ok, ) = L.claimant.call{value: L.amount}("");
        require(ok, "pay failed");
    }

    // refund: anyone may trigger it at/after the deadline; funds only ever return to the refundee.
    function refund(bytes32 key) external {
        Lock memory L = locks[key];
        require(L.amount > 0, "no lock");
        require(block.timestamp >= L.deadline, "not yet");
        delete locks[key];
        emit Refunded(key);
        (bool ok, ) = L.refundee.call{value: L.amount}("");
        require(ok, "pay failed");
    }
}
