// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {Escrow} from "../src/Escrow.sol";
import {MockUSDC} from "../src/MockUSDC.sol";

contract EscrowTest is Test {
    Escrow escrow;
    MockUSDC usdc;

    address ops = makeAddr("ops");
    address client = makeAddr("client");
    uint256 devKey = 0xA11CE;
    uint256 finKey = 0xB0B;
    address dev;
    address fin;
    address agent = makeAddr("agent");
    address worker = makeAddr("worker");
    address stranger = makeAddr("stranger");

    bytes32 constant CASE = keccak256("case-1");
    bytes32 constant T1 = keccak256("task-1");
    bytes32 constant T2 = keccak256("task-2");
    bytes32 constant H1 = keccak256("deliverable-1");

    function setUp() public {
        dev = vm.addr(devKey);
        fin = vm.addr(finKey);
        usdc = new MockUSDC();
        escrow = new Escrow(ops);
        usdc.mint(client, 1_000e6);
        vm.prank(client);
        usdc.approve(address(escrow), type(uint256).max);
        address[] memory approvers = new address[](2);
        approvers[0] = dev;
        approvers[1] = fin;
        vm.prank(client);
        escrow.openCase(CASE, address(usdc), approvers, 2);
    }

    function _sig(uint256 key, bytes32 taskId, bytes32 h, address payee) internal view returns (bytes memory) {
        bytes32 digest = escrow.approvalDigest(CASE, taskId, h, payee);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    /// vm.prank は次の外部呼び出し（approvalDigest）で消費されるため、署名を先に作ってから ops で呼ぶ
    function _approveAs(uint256 key, address approver, bytes32 taskId, bytes32 h, address payee) internal {
        bytes memory sig = _sig(key, taskId, h, payee);
        vm.prank(ops);
        escrow.approve(CASE, taskId, h, payee, approver, sig);
    }

    function _approveExpectRevert(uint256 key, address approver, bytes32 taskId, bytes32 h, address payee, bytes4 err) internal {
        bytes memory sig = _sig(key, taskId, h, payee);
        vm.prank(ops);
        vm.expectRevert(err);
        escrow.approve(CASE, taskId, h, payee, approver, sig);
    }

    function _fundAndSubmit() internal {
        vm.startPrank(ops);
        escrow.fundTask(CASE, T1, 100e6);
        escrow.submit(CASE, T1, H1, agent);
        vm.stopPrank();
    }

    function test_openCase_rejectsBadApprovers() public {
        address[] memory a = new address[](1);
        a[0] = dev;
        vm.prank(client);
        vm.expectRevert(Escrow.BadApprovers.selector);
        escrow.openCase(keccak256("x"), address(usdc), a, 2);
    }

    function test_fundTask_pullsFromClient_onlyOps() public {
        vm.prank(stranger);
        vm.expectRevert(Escrow.NotOps.selector);
        escrow.fundTask(CASE, T1, 100e6);
        vm.prank(ops);
        escrow.fundTask(CASE, T1, 100e6);
        assertEq(usdc.balanceOf(address(escrow)), 100e6);
        assertEq(uint256(escrow.getTask(CASE, T1).status), uint256(Escrow.TaskStatus.Funded));
    }

    function test_autoPay_whenThresholdReached() public {
        _fundAndSubmit();
        _approveAs(devKey, dev, T1, H1, agent);
        assertEq(usdc.balanceOf(agent), 0); // 1/2 -> 保留（FR-013）
        assertEq(uint256(escrow.getTask(CASE, T1).status), uint256(Escrow.TaskStatus.Submitted));
        _approveAs(finKey, fin, T1, H1, agent);
        assertEq(usdc.balanceOf(agent), 100e6); // 2/2 -> 自動支払い（FR-012）
        assertEq(uint256(escrow.getTask(CASE, T1).status), uint256(Escrow.TaskStatus.Paid));
    }

    function test_approve_rejectsForgedOrWrongSigner() public {
        _fundAndSubmit();
        // ops が dev の承認を偽造（fin の鍵で署名）
        _approveExpectRevert(finKey, dev, T1, H1, agent, Escrow.NotApprover.selector);
        // 承認者でない者の署名
        _approveExpectRevert(0xC0DE, stranger, T1, H1, agent, Escrow.NotApprover.selector);
    }

    function test_approve_rejectsHashOrPayeeMismatch() public {
        _fundAndSubmit();
        _approveExpectRevert(devKey, dev, T1, keccak256("other"), agent, Escrow.HashMismatch.selector);
        _approveExpectRevert(devKey, dev, T1, H1, stranger, Escrow.HashMismatch.selector);
    }

    function test_resubmit_invalidatesApprovals() public {
        _fundAndSubmit();
        _approveAs(devKey, dev, T1, H1, agent);
        bytes32 h2 = keccak256("deliverable-2");
        vm.prank(ops);
        escrow.submit(CASE, T1, h2, agent);
        assertEq(escrow.getTask(CASE, T1).approvalCount, 0);
        // 古いハッシュへの承認は使えない
        _approveExpectRevert(finKey, fin, T1, H1, agent, Escrow.HashMismatch.selector);
    }

    function test_approve_rejectsDouble() public {
        _fundAndSubmit();
        _approveAs(devKey, dev, T1, H1, agent);
        _approveExpectRevert(devKey, dev, T1, H1, agent, Escrow.AlreadyApproved.selector);
    }

    function test_dispute_and_resolve_split() public {
        _fundAndSubmit();
        vm.prank(ops);
        escrow.dispute(CASE, T1);
        vm.prank(ops);
        vm.expectRevert(Escrow.SumMismatch.selector);
        escrow.resolve(CASE, T1, 50e6, 40e6);
        vm.prank(ops);
        escrow.resolve(CASE, T1, 40e6, 60e6);
        assertEq(usdc.balanceOf(agent), 40e6);
        assertEq(usdc.balanceOf(client), 1_000e6 - 100e6 + 60e6);
        assertEq(uint256(escrow.getTask(CASE, T1).status), uint256(Escrow.TaskStatus.Resolved));
    }

    function test_noPaymentPathWithoutApprovals() public {
        _fundAndSubmit();
        // Funded/Submitted のまま資金を動かす関数は存在しない: resolve は Disputed でのみ
        vm.prank(ops);
        vm.expectRevert(Escrow.BadStatus.selector);
        escrow.resolve(CASE, T1, 100e6, 0);
        assertEq(usdc.balanceOf(address(escrow)), 100e6);
    }

    function test_humanTaskPayeeIsWorker() public {
        vm.startPrank(ops);
        escrow.fundTask(CASE, T2, 30e6);
        escrow.submit(CASE, T2, keccak256("photo"), worker);
        vm.stopPrank();
        _approveAs(devKey, dev, T2, keccak256("photo"), worker);
        _approveAs(finKey, fin, T2, keccak256("photo"), worker);
        assertEq(usdc.balanceOf(worker), 30e6);
    }
}
