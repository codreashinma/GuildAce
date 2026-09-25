// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/// @title Escrow - タスク（工程）単位の契約・預託・検収・自動支払い
/// @notice アーキテクチャ設計書 ADR-001 / ADR-005 / ADR-006、CON-006、FR-012 / FR-013 / FR-019 に対応する。
///  - 資金の状態機械はこのコントラクトが正本。オフチェーン DB は投影のみ。
///  - 契約はタスク単位。預託も「その工程分だけ」を作業前に行う。
///  - 成果物はハッシュだけを記録し、承認は (成果物ハッシュ, 支払先) に紐づく。差し替えると承認は無効になる。
///  - 必要数の承認がそろった時点で、このコントラクトが自動で支払う。オフチェーンから送金を指示する経路は無い。
///  - 承認者の署名（EIP-712）を運用ウォレット（ops = チェーン連携ワーカー）が中継する。ops は承認を偽造できない。
///  - 紛争時は保留し、Jury の裁定を arbiter（ops）が resolve として反映する。
contract Escrow is EIP712 {
    using SafeERC20 for IERC20;

    enum TaskStatus {
        None,
        Funded,
        Submitted,
        Paid,
        Disputed,
        Resolved
    }

    struct CaseInfo {
        address client;
        address token;
        address[] approvers;
        uint8 threshold;
    }

    struct TaskInfo {
        uint256 amount;
        address payee;
        bytes32 deliverableHash;
        uint8 approvalCount;
        TaskStatus status;
    }

    bytes32 public constant APPROVAL_TYPEHASH =
        keccak256("Approval(bytes32 caseId,bytes32 taskId,bytes32 deliverableHash,address payee)");

    address public immutable ops; // チェーン連携ワーカー（預託の要求・提出と承認の中継・裁定の反映）

    mapping(bytes32 => CaseInfo) internal _cases;
    mapping(bytes32 => mapping(bytes32 => TaskInfo)) internal _tasks;
    mapping(bytes32 => mapping(bytes32 => mapping(address => bytes32))) public approvedHash; // 承認者が承認したハッシュ

    event CaseOpened(bytes32 indexed caseId, address indexed client, address token, address[] approvers, uint8 threshold);
    event TaskFunded(bytes32 indexed caseId, bytes32 indexed taskId, uint256 amount);
    event Submitted(bytes32 indexed caseId, bytes32 indexed taskId, bytes32 deliverableHash, address payee);
    event Approved(bytes32 indexed caseId, bytes32 indexed taskId, address indexed approver, bytes32 deliverableHash, uint8 approvalCount);
    event Paid(bytes32 indexed caseId, bytes32 indexed taskId, address indexed payee, uint256 amount);
    event Disputed(bytes32 indexed caseId, bytes32 indexed taskId);
    event Resolved(bytes32 indexed caseId, bytes32 indexed taskId, uint256 paid, uint256 refunded);

    error NotOps();
    error NotClient();
    error CaseExists();
    error CaseNotFound();
    error BadApprovers();
    error TaskExists();
    error BadStatus();
    error ZeroAmount();
    error NotApprover();
    error AlreadyApproved();
    error HashMismatch();
    error SumMismatch();
    error ZeroPayee();

    constructor(address ops_) EIP712("ChoiceEscrow", "1") {
        ops = ops_;
    }

    modifier onlyOps() {
        if (msg.sender != ops) revert NotOps();
        _;
    }

    // ------------------------------------------------------------------ case

    /// @notice 発注者が案件を開く。承認者と必要承認数をここで固定する（名前ではなく権限で承認できる者を決める）。
    function openCase(bytes32 caseId, address token, address[] calldata approvers, uint8 threshold) external {
        if (_cases[caseId].client != address(0)) revert CaseExists();
        if (approvers.length == 0 || threshold == 0 || threshold > approvers.length) revert BadApprovers();
        _cases[caseId] = CaseInfo({client: msg.sender, token: token, approvers: approvers, threshold: threshold});
        emit CaseOpened(caseId, msg.sender, token, approvers, threshold);
    }

    // ------------------------------------------------------------------ task

    /// @notice 工程分の資金を預ける（ops が発注者の allowance から引き落とす。発注者が openCase で許可した案件にのみ使える）
    function fundTask(bytes32 caseId, bytes32 taskId, uint256 amount) external onlyOps {
        CaseInfo storage c = _cases[caseId];
        if (c.client == address(0)) revert CaseNotFound();
        if (amount == 0) revert ZeroAmount();
        TaskInfo storage t = _tasks[caseId][taskId];
        if (t.status != TaskStatus.None) revert TaskExists();
        t.amount = amount;
        t.status = TaskStatus.Funded;
        IERC20(c.token).safeTransferFrom(c.client, address(this), amount);
        emit TaskFunded(caseId, taskId, amount);
    }

    /// @notice 成果物の提出（ハッシュ）と支払先の確定。再提出すると承認はリセットされる（差し替え前の承認は使えない）。
    function submit(bytes32 caseId, bytes32 taskId, bytes32 deliverableHash, address payee) external onlyOps {
        TaskInfo storage t = _tasks[caseId][taskId];
        if (t.status != TaskStatus.Funded && t.status != TaskStatus.Submitted) revert BadStatus();
        if (payee == address(0)) revert ZeroPayee();
        t.deliverableHash = deliverableHash;
        t.payee = payee;
        t.approvalCount = 0;
        t.status = TaskStatus.Submitted;
        emit Submitted(caseId, taskId, deliverableHash, payee);
    }

    /// @notice 承認者の EIP-712 署名を ops が中継する。必要数がそろった時点で自動的に支払う（FR-012）。
    function approve(bytes32 caseId, bytes32 taskId, bytes32 deliverableHash, address payee, address approver, bytes calldata signature)
        external
        onlyOps
    {
        CaseInfo storage c = _cases[caseId];
        TaskInfo storage t = _tasks[caseId][taskId];
        if (t.status != TaskStatus.Submitted) revert BadStatus();
        if (t.deliverableHash != deliverableHash || t.payee != payee) revert HashMismatch();
        if (!_isApprover(c, approver)) revert NotApprover();
        if (approvedHash[caseId][taskId][approver] == deliverableHash) revert AlreadyApproved();

        bytes32 digest = _hashTypedDataV4(keccak256(abi.encode(APPROVAL_TYPEHASH, caseId, taskId, deliverableHash, payee)));
        if (ECDSA.recover(digest, signature) != approver) revert NotApprover();

        approvedHash[caseId][taskId][approver] = deliverableHash;
        t.approvalCount += 1;
        emit Approved(caseId, taskId, approver, deliverableHash, t.approvalCount);

        if (t.approvalCount >= c.threshold) {
            t.status = TaskStatus.Paid;
            IERC20(c.token).safeTransfer(payee, t.amount);
            emit Paid(caseId, taskId, payee, t.amount);
        }
        // 条件未達なら何もしない = 保留（FR-013）
    }

    /// @notice 差し戻し。資金は保留のまま Jury の裁定を待つ。
    function dispute(bytes32 caseId, bytes32 taskId) external onlyOps {
        TaskInfo storage t = _tasks[caseId][taskId];
        if (t.status != TaskStatus.Funded && t.status != TaskStatus.Submitted) revert BadStatus();
        t.status = TaskStatus.Disputed;
        emit Disputed(caseId, taskId);
    }

    /// @notice Jury の裁定を反映する（支払い・返金・分割清算）。合計は預託額と一致しなければならない。
    function resolve(bytes32 caseId, bytes32 taskId, uint256 payAmount, uint256 refundAmount) external onlyOps {
        CaseInfo storage c = _cases[caseId];
        TaskInfo storage t = _tasks[caseId][taskId];
        if (t.status != TaskStatus.Disputed) revert BadStatus();
        if (payAmount + refundAmount != t.amount) revert SumMismatch();
        if (payAmount > 0 && t.payee == address(0)) revert ZeroPayee();
        t.status = TaskStatus.Resolved;
        if (payAmount > 0) IERC20(c.token).safeTransfer(t.payee, payAmount);
        if (refundAmount > 0) IERC20(c.token).safeTransfer(c.client, refundAmount);
        emit Resolved(caseId, taskId, payAmount, refundAmount);
    }

    // ------------------------------------------------------------------ views

    function getCase(bytes32 caseId) external view returns (CaseInfo memory) {
        return _cases[caseId];
    }

    function getTask(bytes32 caseId, bytes32 taskId) external view returns (TaskInfo memory) {
        return _tasks[caseId][taskId];
    }

    function approvalDigest(bytes32 caseId, bytes32 taskId, bytes32 deliverableHash, address payee) external view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(APPROVAL_TYPEHASH, caseId, taskId, deliverableHash, payee)));
    }

    function _isApprover(CaseInfo storage c, address a) internal view returns (bool) {
        for (uint256 i = 0; i < c.approvers.length; i++) {
            if (c.approvers[i] == a) return true;
        }
        return false;
    }
}
