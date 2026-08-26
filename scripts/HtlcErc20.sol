// SPDX-License-Identifier: MIT
// ERC-20 leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5). Same shape as HtlcEth — fund / claim /
// refund under one SHA-256 hashlock and a deadline — but the escrow is a token, so the money moves with
// transferFrom/transfer instead of msg.value. No owner, no upgrade path, no fee switch.
//
// Two things a token contract can do that plain ETH cannot, both handled here:
//   * NON-STANDARD RETURNS. Some widely-used tokens (USDT among them) return nothing from transfer /
//     transferFrom instead of a bool. A bare IERC20 call would revert on them, so every move goes through
//     _call(), which accepts "no return data" and only rejects an explicit false.
//   * FEE-ON-TRANSFER / REBASING. The amount that arrives can be less than the amount sent, so fund()
//     escrows the MEASURED balance delta, never the requested figure. Escrowing the requested amount would
//     leave the contract short and make the last claimant of that token unpayable.
// A token whose transfer re-enters is contained by check-effects-interactions plus an explicit guard: the
// lock is deleted before any external call, so a re-entering claim/refund finds nothing to take.
pragma solidity ^0.8.26;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address who) external view returns (uint256);
}

contract HtlcErc20 {
    struct Lock { address token; address claimant; address refundee; uint256 amount; bytes32 H; uint256 deadline; }
    mapping(bytes32 => Lock) public locks;   // key: keccak256(abi.encode(token, H, claimant, refundee, deadline))

    uint256 private _entered;                // reentrancy guard: token code is arbitrary and runs on transfer

    event Funded(bytes32 indexed key, address indexed token, address indexed claimant,
                 address refundee, uint256 amount, bytes32 H, uint256 deadline);
    event Claimed(bytes32 indexed key, bytes32 s);
    event Refunded(bytes32 indexed key);

    modifier lock_() {
        require(_entered == 0, "reentrant");
        _entered = 1; _;
        _entered = 0;
    }

    function lockKey(address token, bytes32 H, address claimant, address refundee, uint256 deadline)
        public pure returns (bytes32)
    {
        return keccak256(abi.encode(token, H, claimant, refundee, deadline));
    }

    // Approve this contract for `amount` of `token` first, then fund. The ESCROWED figure is what actually
    // arrived, so a fee-on-transfer token escrows (and later pays out) its post-fee amount.
    function fund(address token, address claimant, bytes32 H, uint256 deadline, uint256 amount)
        external lock_ returns (bytes32 key)
    {
        require(amount > 0 && token != address(0) && claimant != address(0), "bad lock");
        require(deadline > block.timestamp, "deadline in the past");
        key = lockKey(token, H, claimant, msg.sender, deadline);
        require(locks[key].amount == 0, "exists");
        uint256 before = IERC20(token).balanceOf(address(this));
        _call(token, abi.encodeWithSelector(IERC20.transferFrom.selector, msg.sender, address(this), amount));
        uint256 got = IERC20(token).balanceOf(address(this)) - before;
        require(got > 0, "nothing received");
        locks[key] = Lock(token, claimant, msg.sender, got, H, deadline);
        emit Funded(key, token, claimant, msg.sender, got, H, deadline);
    }

    // Reveal s with SHA256(s) == H, strictly before the deadline. s becomes public calldata — that is what
    // lets the other chain settle.
    function claim(bytes32 key, bytes32 s) external lock_ {
        Lock memory L = locks[key];
        require(L.amount > 0, "no lock");
        require(sha256(abi.encodePacked(s)) == L.H, "bad preimage");
        require(block.timestamp < L.deadline, "expired");
        delete locks[key];
        emit Claimed(key, s);
        _call(L.token, abi.encodeWithSelector(IERC20.transfer.selector, L.claimant, L.amount));
    }

    // Anyone may trigger a refund at/after the deadline; the tokens only ever return to the funder.
    function refund(bytes32 key) external lock_ {
        Lock memory L = locks[key];
        require(L.amount > 0, "no lock");
        require(block.timestamp >= L.deadline, "not yet");
        delete locks[key];
        emit Refunded(key);
        _call(L.token, abi.encodeWithSelector(IERC20.transfer.selector, L.refundee, L.amount));
    }

    // A token move that tolerates a missing return value but never a false one.
    function _call(address token, bytes memory data) private {
        (bool ok, bytes memory ret) = token.call(data);
        require(ok && (ret.length == 0 || abi.decode(ret, (bool))), "token transfer failed");
    }
}
