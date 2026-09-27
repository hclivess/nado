// SPDX-License-Identifier: MIT
// Hostile and ordinary ERC-20s for tests/test_htlc_erc20.mjs, which compiles this file with solc into a temp dir on
// every run. (The compiled tokens used to live in /tmp/erc20t/out, built once by hand; the sources were never
// committed, so the test failed on every host that lacked that directory.) Each deploys with 1e24 units to msg.sender.
pragma solidity ^0.8.26;

// Standard: returns true, moves exactly what it is asked to.
contract Good {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    constructor() { balanceOf[msg.sender] = 1e24; }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external returns (bool) { _move(msg.sender, to, a); return true; }
    function transferFrom(address f, address to, uint256 a) external returns (bool) {
        require(allowance[f][msg.sender] >= a, "allowance"); allowance[f][msg.sender] -= a; _move(f, to, a); return true;
    }
    function _move(address f, address to, uint256 a) internal { require(balanceOf[f] >= a, "balance"); balanceOf[f] -= a; balanceOf[to] += a; }
}

// USDT-style: transfer and transferFrom return NOTHING, so a caller that demands `bool true` would reject it.
contract NoReturn {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    constructor() { balanceOf[msg.sender] = 1e24; }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external { _move(msg.sender, to, a); }
    function transferFrom(address f, address to, uint256 a) external {
        require(allowance[f][msg.sender] >= a, "allowance"); allowance[f][msg.sender] -= a; _move(f, to, a);
    }
    function _move(address f, address to, uint256 a) internal { require(balanceOf[f] >= a, "balance"); balanceOf[f] -= a; balanceOf[to] += a; }
}

// Fee-on-transfer: 10% of every transfer is burned, so the recipient gets 90% — an escrow must record what ARRIVED.
contract FeeOnTransfer {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    constructor() { balanceOf[msg.sender] = 1e24; }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external returns (bool) { _move(msg.sender, to, a); return true; }
    function transferFrom(address f, address to, uint256 a) external returns (bool) {
        require(allowance[f][msg.sender] >= a, "allowance"); allowance[f][msg.sender] -= a; _move(f, to, a); return true;
    }
    function _move(address f, address to, uint256 a) internal {
        require(balanceOf[f] >= a, "balance"); balanceOf[f] -= a; balanceOf[to] += a - a / 10;
    }
}

// Re-entering: during its first transferFrom it calls back into the HTLC. `tried` records the attempt; `reverted_` is
// set ONLY if the nested call failed with the guard's own reason ("reentrant") — a nested call that failed for any
// other reason (e.g. "no lock") would not prove the guard, so it does not count.
contract Evil {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    address public htlc;
    uint256 public tried;
    uint256 public reverted_;
    constructor() { balanceOf[msg.sender] = 1e24; }
    function setHtlc(address h) external { htlc = h; }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external returns (bool) { _move(msg.sender, to, a); return true; }
    function transferFrom(address f, address to, uint256 a) external returns (bool) {
        require(allowance[f][msg.sender] >= a, "allowance"); allowance[f][msg.sender] -= a;
        if (htlc != address(0) && tried == 0) {
            tried = 1;
            (bool ok, bytes memory ret) = htlc.call(abi.encodeWithSignature("claim(bytes32,bytes32)", bytes32(0), bytes32(0)));
            if (!ok && keccak256(ret) == keccak256(abi.encodeWithSignature("Error(string)", "reentrant"))) reverted_ = 1;
        }
        _move(f, to, a); return true;
    }
    function _move(address f, address to, uint256 a) internal { require(balanceOf[f] >= a, "balance"); balanceOf[f] -= a; balanceOf[to] += a; }
}
