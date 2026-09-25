// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title Escrow - 案件ごとの「お金の預かり箱」
/// @notice 発注者が案件予算を預け、発注者の承認（release）または
///         Human Jury の多数決結果を受けた arbiter（resolve）によってのみ資金が動く。
///         期限の到来や AI の判断では資金は動かない。
contract Escrow {
    using SafeERC20 for IERC20;

    enum Status {
        None,
        Funded,
        Released,
        Resolved
    }

    struct Case {
        address client;
        address token;
        uint256 amount;
        Status status;
    }

    address public immutable arbiter;
    mapping(bytes32 => Case) public cases;

    event Deposited(bytes32 indexed caseId, address indexed client, address token, uint256 amount);
    event Released(bytes32 indexed caseId, address[] recipients, uint256[] amounts);
    event Resolved(bytes32 indexed caseId, address[] recipients, uint256[] amounts);

    error AlreadyFunded();
    error NotFunded();
    error NotClient();
    error NotArbiter();
    error ZeroAmount();
    error LengthMismatch();
    error SumMismatch();

    constructor(address arbiter_) {
        arbiter = arbiter_;
    }

    /// @notice 発注者が案件分の資金を預ける（事前に token.approve が必要）
    function deposit(bytes32 caseId, address token, uint256 amount) external {
        if (amount == 0) revert ZeroAmount();
        Case storage c = cases[caseId];
        if (c.status != Status.None) revert AlreadyFunded();

        c.client = msg.sender;
        c.token = token;
        c.amount = amount;
        c.status = Status.Funded;

        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        emit Deposited(caseId, msg.sender, token, amount);
    }

    /// @notice 発注者が検収を承認し、配分どおりに支払う
    function release(bytes32 caseId, address[] calldata recipients, uint256[] calldata amounts) external {
        Case storage c = cases[caseId];
        if (c.status != Status.Funded) revert NotFunded();
        if (msg.sender != c.client) revert NotClient();

        c.status = Status.Released;
        _distribute(c, recipients, amounts);
        emit Released(caseId, recipients, amounts);
    }

    /// @notice Human Jury の多数決結果を arbiter が反映する（支払い・返金・分割清算）
    function resolve(bytes32 caseId, address[] calldata recipients, uint256[] calldata amounts) external {
        if (msg.sender != arbiter) revert NotArbiter();
        Case storage c = cases[caseId];
        if (c.status != Status.Funded) revert NotFunded();

        c.status = Status.Resolved;
        _distribute(c, recipients, amounts);
        emit Resolved(caseId, recipients, amounts);
    }

    function getCase(bytes32 caseId) external view returns (Case memory) {
        return cases[caseId];
    }

    function _distribute(Case storage c, address[] calldata recipients, uint256[] calldata amounts) internal {
        if (recipients.length != amounts.length) revert LengthMismatch();
        uint256 total;
        for (uint256 i = 0; i < amounts.length; i++) {
            total += amounts[i];
        }
        if (total != c.amount) revert SumMismatch();

        IERC20 token = IERC20(c.token);
        for (uint256 i = 0; i < recipients.length; i++) {
            if (amounts[i] > 0) token.safeTransfer(recipients[i], amounts[i]);
        }
    }
}
